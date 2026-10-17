"""Digital signatures (PAdES) for rendered certificates of attendance.

The organizer stores one certificate + private key. Every PDF produced by
render_certificate() is signed with it, so a PDF reader can show that the file
really comes from the organizer and was not modified afterwards.

With a self-signed certificate readers will say "identity unknown" until the
public certificate (downloadable on the signing settings page) is added to the
reader's trusted certificates - that's expected and the integrity check
("document has not been modified since it was signed") works regardless.
"""

import asyncio
import datetime
import hashlib
import logging
import socket
import time
from dataclasses import dataclass
from io import BytesIO
from urllib.parse import urlparse

import requests
from asn1crypto import tsp
from django.conf import settings
from django.core.cache import cache
from django.utils.translation import gettext as _

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from pyhanko.keys import load_certs_from_pemder_data, load_private_key_from_pemder_data
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.sign import fields, signers
from pyhanko.sign.timestamps import TimestampRequestError, TimeStamper
from pyhanko_certvalidator.registry import SimpleCertificateStore

from pretix.helpers.ssrf import should_block_access

from pretix_attendance_certificate.models import (
    OrganizerSigningCertificate,
    TimestampMode,
)

logger = logging.getLogger(__name__)

TSA_TIMEOUT = 5  # seconds per request
TSA_ATTEMPTS = 2  # tries per certificate before giving up
TSA_RETRY_PAUSE = 1  # seconds between tries
# After a failed run the authority counts as down for this long, so a bulk
# send doesn't wait for timeouts on every single PDF.
TSA_COOLDOWN = 60
# Fallback for installations without a shared cache (see _tsa_is_down).
_tsa_down_until = {}


class InvalidCertificate(ValueError):
    pass


class TimestampError(Exception):
    """The timestamp authority could not be reached or answered badly."""


@dataclass
class CertificateInfo:
    subject: str
    not_before: datetime.datetime
    not_after: datetime.datetime
    fingerprint: str

    @property
    def expired(self):
        return self.not_after < datetime.datetime.now(datetime.timezone.utc)


def _pem_private_key(key):
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def _pem_certificate(cert):
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def generate_self_signed(common_name, organization="", valid_days=5 * 365):
    """Returns (certificate_pem, private_key_pem) of a new self-signed
    certificate that is usable for document signing."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    attributes = [x509.NameAttribute(NameOID.COMMON_NAME, common_name)]
    if organization:
        attributes.append(x509.NameAttribute(NameOID.ORGANIZATION_NAME, organization))
    name = x509.Name(attributes)
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=valid_days))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=True,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    return _pem_certificate(cert), _pem_private_key(key)


def load_pkcs12(data, password=None):
    """Returns (certificate_pem, private_key_pem, chain_pem) from a .p12/.pfx
    file. chain_pem holds the file's further certificates (CA chain), if any."""
    try:
        key, cert, extra = pkcs12.load_key_and_certificates(
            data, password.encode() if password else None
        )
    except (ValueError, TypeError) as e:
        raise InvalidCertificate(str(e))
    if key is None or cert is None:
        raise InvalidCertificate("The file does not contain a key and a certificate.")
    chain = "".join(_pem_certificate(c) for c in extra or [] if c != cert)
    return _pem_certificate(cert), _pem_private_key(key), chain


def certificate_info(certificate_pem):
    cert = x509.load_pem_x509_certificate(certificate_pem.encode())
    return CertificateInfo(
        subject=cert.subject.rfc4514_string(),
        not_before=cert.not_valid_before_utc,
        not_after=cert.not_valid_after_utc,
        fingerprint=cert.fingerprint(hashes.SHA256()).hex(":").upper(),
    )


def check_pair(certificate_pem, private_key_pem):
    """Raises InvalidCertificate unless key and certificate belong together
    and the pair can sign."""
    try:
        cert = x509.load_pem_x509_certificate(certificate_pem.encode())
        key = serialization.load_pem_private_key(private_key_pem.encode(), None)
    except (ValueError, TypeError) as e:
        raise InvalidCertificate(str(e))
    public = serialization.PublicFormat.SubjectPublicKeyInfo
    encoding = serialization.Encoding.DER
    if cert.public_key().public_bytes(encoding, public) != key.public_key().public_bytes(
        encoding, public
    ):
        raise InvalidCertificate("The private key does not match the certificate.")


def chain_info(chain_pem):
    return [
        certificate_info(pem)
        for pem in _split_pem(chain_pem)
    ]


def _split_pem(pem):
    marker = "-----END CERTIFICATE-----"
    return [part + marker for part in pem.split(marker) if part.strip()]


def _signer(signing: OrganizerSigningCertificate):
    # The CA chain is embedded in the signature, so a reader can build the path
    # to the root. (It still only trusts a root the recipient has imported.)
    chain = (
        list(load_certs_from_pemder_data(signing.chain_pem.encode()))
        if signing.chain_pem
        else []
    )
    return signers.SimpleSigner(
        signing_cert=next(
            iter(load_certs_from_pemder_data(signing.certificate_pem.encode()))
        ),
        signing_key=load_private_key_from_pemder_data(
            signing.private_key_pem.encode(), passphrase=None
        ),
        cert_registry=SimpleCertificateStore.from_certs(chain),
    )


class RequestsTimeStamper(TimeStamper):
    """RFC 3161 client on top of ``requests``. pretix guards its urllib3 /
    requests traffic against requests to internal networks (SSRF); pyHanko's
    own aiohttp client would bypass that."""

    def __init__(self, url, timeout=TSA_TIMEOUT):
        self.url = url
        self.timeout = timeout
        super().__init__()

    def _post(self, data: bytes) -> bytes:
        response = requests.post(
            self.url,
            data=data,
            headers={
                "Content-Type": "application/timestamp-query",
                "Accept": "application/timestamp-reply",
            },
            timeout=self.timeout,
            allow_redirects=False,
        )
        response.raise_for_status()
        if response.headers.get("Content-Type") != "application/timestamp-reply":
            raise TimestampRequestError("Timestamp server response is malformed.")
        return response.content

    async def async_request_tsa_response(self, req):
        data = await asyncio.to_thread(self._post, req.dump())
        return tsp.TimeStampResp.load(data)

    async def async_timestamp(self, message_digest, md_algorithm):
        # Whatever goes wrong on the authority's side (network, HTTP, garbage
        # in the answer, a refusal) surfaces as one error type, so signing
        # problems of our own are never mistaken for an unreachable TSA.
        try:
            return await super().async_timestamp(message_digest, md_algorithm)
        except TimestampRequestError:
            raise
        except Exception as e:
            raise TimestampRequestError("Timestamp service failed") from e


def validate_timestamp_url(url):
    """Raises ValueError for anything but a public http(s) address."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(_("Only http(s) addresses are allowed."))
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or 443)
    except OSError:
        raise ValueError(_("The host name could not be resolved."))
    for info in infos:
        if should_block_access(info[4])[0]:
            raise ValueError(_("Addresses in internal networks are not allowed."))


_timestampers = {}


def _timestamper(signing: OrganizerSigningCertificate):
    if signing.timestamp_mode == TimestampMode.OFF or not signing.timestamp_url:
        return None
    # One client per URL: pyHanko sizes the signature with a dummy timestamp
    # request that it caches per client, so reusing the client means only the
    # first PDF of a process costs this extra request.
    url = signing.timestamp_url
    if url not in _timestampers:
        _timestampers[url] = RequestsTimeStamper(url)
    return _timestampers[url]


def _sign(pdf, signing, timestamper):
    writer = IncrementalPdfFileWriter(BytesIO(pdf))
    metadata = signers.PdfSignatureMetadata(
        field_name="Signature1",
        reason=signing.reason or None,
        subfilter=fields.SigSeedSubFilter.PADES,
    )
    pdf_signer = signers.PdfSigner(
        metadata, signer=_signer(signing), timestamper=timestamper
    )
    return pdf_signer.sign_pdf(writer).read()


def _tsa_down_key(url):
    return "attendance_certificate_tsa_down_" + hashlib.sha256(url.encode()).hexdigest()


def _tsa_is_down(url):
    # With a real cache (redis/memcached) all web and worker processes share the
    # cool-down; otherwise it is remembered per process.
    if settings.REAL_CACHE_USED:
        return cache.get(_tsa_down_key(url)) is not None
    return time.monotonic() < _tsa_down_until.get(url, 0)


def _mark_tsa_down(url):
    if settings.REAL_CACHE_USED:
        cache.set(_tsa_down_key(url), True, TSA_COOLDOWN)
    else:
        _tsa_down_until[url] = time.monotonic() + TSA_COOLDOWN


def _mark_tsa_up(url):
    if settings.REAL_CACHE_USED:
        cache.delete(_tsa_down_key(url))
    else:
        _tsa_down_until.pop(url, None)


def sign_pdf(pdf: bytes, signing: OrganizerSigningCertificate) -> bytes:
    """Returns pdf with an invisible PAdES signature added (with a trusted
    timestamp if configured; see OrganizerSigningCertificate.timestamp_mode
    for what happens when the authority fails)."""
    timestamper = _timestamper(signing)
    if timestamper is None:
        return _sign(pdf, signing, None)

    url = signing.timestamp_url
    error = None
    if _tsa_is_down(url):
        error = TimestampRequestError("Timestamp server was unreachable just now")
    else:
        for attempt in range(TSA_ATTEMPTS):
            try:
                signed = _sign(pdf, signing, timestamper)
                _mark_tsa_up(url)
                return signed
            except TimestampRequestError as e:
                error = e
                if attempt + 1 < TSA_ATTEMPTS:
                    time.sleep(TSA_RETRY_PAUSE)
        _mark_tsa_down(url)

    if signing.timestamp_mode == TimestampMode.REQUIRED:
        raise TimestampError(
            "Could not get a trusted timestamp from {}: {}".format(url, error)
        ) from error
    logger.warning(
        "Signing without timestamp, timestamp server %s failed: %s", url, error
    )
    return _sign(pdf, signing, None)


def signing_for(organizer):
    """The organizer's active signing configuration, or None."""
    return OrganizerSigningCertificate.objects.filter(
        organizer=organizer, enabled=True
    ).first()
