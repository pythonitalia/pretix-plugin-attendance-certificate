from io import BytesIO

import pytest
from django.core.cache import cache
from django_scopes import scopes_disabled

from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign.validation import validate_pdf_signature
from pyhanko.keys import load_certs_from_pemder_data
from pyhanko_certvalidator import ValidationContext

from pretix_attendance_certificate import signing
from pretix_attendance_certificate.models import OrganizerSigningCertificate
from pretix_attendance_certificate.render import render_certificate


@pytest.fixture(scope="module")
def keypair():
    return signing.generate_self_signed("Test Org", "Test e.V.", valid_days=30)


@pytest.fixture
def signing_cfg(event, keypair):
    with scopes_disabled():
        return OrganizerSigningCertificate.objects.create(
            organizer=event.organizer,
            certificate_pem=keypair[0],
            private_key_pem=keypair[1],
        )


@pytest.fixture
def simple_pdf():
    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    page = canvas.Canvas(buffer)
    page.drawString(100, 700, "certificate")
    page.save()
    return buffer.getvalue()


def _validate(pdf_bytes, certificate_pem):
    reader = PdfFileReader(BytesIO(pdf_bytes))
    assert len(reader.embedded_signatures) == 1
    sig = reader.embedded_signatures[0]
    trust = ValidationContext(
        trust_roots=list(load_certs_from_pemder_data(certificate_pem.encode()))
    )
    return validate_pdf_signature(sig, trust)


@pytest.mark.django_db
def test_certificate_is_unsigned_without_configuration(event, pos, layout):
    with scopes_disabled():
        pdf = render_certificate(position=pos, event=event, layout=layout).read()
    assert PdfFileReader(BytesIO(pdf)).embedded_signatures == []


@pytest.mark.django_db
def test_certificate_is_signed_and_valid(event, pos, layout, signing_cfg, keypair):
    with scopes_disabled():
        pdf = render_certificate(position=pos, event=event, layout=layout).read()
    status = _validate(pdf, keypair[0])
    assert status.intact and status.valid and status.trusted


@pytest.mark.django_db
def test_modified_pdf_fails_validation(event, pos, layout, signing_cfg, keypair):
    with scopes_disabled():
        pdf = render_certificate(position=pos, event=event, layout=layout).read()
    # Change a byte inside the signed range without breaking the structure.
    marker = b"/Producer"
    assert marker in pdf
    tampered = pdf.replace(marker, b"/Producar", 1)
    status = _validate(tampered, keypair[0])
    assert not status.intact


@pytest.mark.django_db
def test_disabled_signing_is_skipped(event, pos, layout, signing_cfg):
    signing_cfg.enabled = False
    signing_cfg.save()
    with scopes_disabled():
        pdf = render_certificate(position=pos, event=event, layout=layout).read()
    assert PdfFileReader(BytesIO(pdf)).embedded_signatures == []


def test_pkcs12_roundtrip(keypair):
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.serialization import pkcs12

    cert = x509.load_pem_x509_certificate(keypair[0].encode())
    key = serialization.load_pem_private_key(keypair[1].encode(), None)
    data = pkcs12.serialize_key_and_certificates(
        b"x", key, cert, None, serialization.BestAvailableEncryption(b"secret")
    )
    cert_pem, key_pem, chain = signing.load_pkcs12(data, "secret")
    assert chain == ""
    signing.check_pair(cert_pem, key_pem)
    with pytest.raises(signing.InvalidCertificate):
        signing.load_pkcs12(data, "wrong")


def test_mismatching_pair_is_rejected(keypair):
    other = signing.generate_self_signed("Other")
    with pytest.raises(signing.InvalidCertificate):
        signing.check_pair(keypair[0], other[1])


def _url(event, name="organizer.signing"):
    from django.urls import reverse

    return reverse(
        "plugins:pretix_attendance_certificate:" + name,
        kwargs={"organizer": event.organizer.slug},
    )


@pytest.mark.django_db
def test_generate_via_ui_then_certificates_are_signed(
    organizer_client, event, pos, layout
):
    response = organizer_client.post(
        _url(event),
        {
            "action": "generate",
            "generate-common_name": "Test e.V.",
            "generate-organization": "",
            "generate-valid_years": "2",
        },
    )
    assert response.status_code == 302
    with scopes_disabled():
        cfg = OrganizerSigningCertificate.objects.get(organizer=event.organizer)
        assert cfg.enabled
        pdf = render_certificate(position=pos, event=event, layout=layout).read()
    assert _validate(pdf, cfg.certificate_pem).valid
    assert "Test e.V." in organizer_client.get(_url(event)).content.decode()


@pytest.mark.django_db
def test_public_certificate_download_never_contains_the_key(
    organizer_client, event, signing_cfg
):
    response = organizer_client.get(_url(event, "organizer.signing.certificate"))
    body = response.content.decode()
    assert response.status_code == 200
    assert "BEGIN CERTIFICATE" in body and "PRIVATE KEY" not in body


@pytest.mark.django_db
def test_import_via_ui(organizer_client, event, keypair):
    from django.core.files.uploadedfile import SimpleUploadedFile
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.serialization import pkcs12

    p12 = pkcs12.serialize_key_and_certificates(
        b"x",
        serialization.load_pem_private_key(keypair[1].encode(), None),
        x509.load_pem_x509_certificate(keypair[0].encode()),
        None,
        serialization.BestAvailableEncryption(b"secret"),
    )
    bad = organizer_client.post(
        _url(event),
        {"action": "import", "import-pkcs12": SimpleUploadedFile("a.p12", p12),
         "import-password": "wrong"},
    )
    assert bad.status_code == 200
    with scopes_disabled():
        assert not OrganizerSigningCertificate.objects.exists()
    good = organizer_client.post(
        _url(event),
        {"action": "import", "import-pkcs12": SimpleUploadedFile("a.p12", p12),
         "import-password": "secret"},
    )
    assert good.status_code == 302
    with scopes_disabled():
        assert OrganizerSigningCertificate.objects.get().certificate_pem == keypair[0]


@pytest.mark.django_db
def test_delete_stops_signing(organizer_client, event, signing_cfg):
    organizer_client.post(_url(event), {"action": "delete"})
    with scopes_disabled():
        assert not OrganizerSigningCertificate.objects.exists()


@pytest.mark.django_db
def test_signing_page_requires_organizer_permission(client, event):
    from pretix.base.models import Team, User

    with scopes_disabled():
        user = User.objects.create_user("noperm@dummy.dummy", "noperm")
        Team.objects.create(organizer=event.organizer).members.add(user)
    client.force_login(user)
    assert client.get(_url(event)).status_code != 200
    assert client.post(_url(event), {"action": "delete"}).status_code != 200


def _ca_chain_p12():
    """Root CA -> leaf, returned as .p12 bytes with the root included."""
    import datetime

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID

    now = datetime.datetime.now(datetime.timezone.utc)

    def make(cn, issuer_name, issuer_key, ca):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(issuer_name or name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=30))
            .add_extension(x509.BasicConstraints(ca=ca, path_length=0 if ca else None), True)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=not ca,
                    content_commitment=not ca,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=ca,
                    crl_sign=ca,
                    encipher_only=False,
                    decipher_only=False,
                ),
                True,
            )
            .sign(issuer_key or key, hashes.SHA256())
        )
        return key, cert

    root_key, root = make("Test Root CA", None, None, True)
    leaf_key, leaf = make("Test Leaf", root.subject, root_key, False)
    return pkcs12.serialize_key_and_certificates(
        b"x", leaf_key, leaf, [root], serialization.NoEncryption()
    ), root


def test_pkcs12_chain_is_kept():
    data, root = _ca_chain_p12()
    cert_pem, _key, chain = signing.load_pkcs12(data)
    assert cert_pem.count("BEGIN CERTIFICATE") == 1
    assert chain.count("BEGIN CERTIFICATE") == 1
    assert "Test Root CA" in signing.chain_info(chain)[0].subject


@pytest.mark.django_db
def test_ca_chain_is_embedded_in_signed_pdf(event, pos, layout):
    from cryptography.hazmat.primitives import serialization

    data, root = _ca_chain_p12()
    cert_pem, key_pem, chain = signing.load_pkcs12(data)
    with scopes_disabled():
        OrganizerSigningCertificate.objects.create(
            organizer=event.organizer,
            certificate_pem=cert_pem,
            private_key_pem=key_pem,
            chain_pem=chain,
        )
        pdf = render_certificate(position=pos, event=event, layout=layout).read()
    sig = PdfFileReader(BytesIO(pdf)).embedded_signatures[0]
    names = sorted(
        c.native["tbs_certificate"]["subject"]["common_name"]
        for c in sig.signed_data["certificates"]
    )
    assert names == ["Test Leaf", "Test Root CA"]
    # ...and with the root as trust anchor the whole chain validates.
    root_pem = root.public_bytes(serialization.Encoding.PEM).decode()
    status = _validate(pdf, root_pem)
    assert status.intact and status.valid and status.trusted


@pytest.mark.django_db
def test_import_via_ui_stores_chain(organizer_client, event):
    from django.core.files.uploadedfile import SimpleUploadedFile

    data, _root = _ca_chain_p12()
    response = organizer_client.post(
        _url(event),
        {"action": "import", "import-pkcs12": SimpleUploadedFile("a.p12", data)},
    )
    assert response.status_code == 302
    with scopes_disabled():
        cfg = OrganizerSigningCertificate.objects.get()
    assert cfg.chain_pem.count("BEGIN CERTIFICATE") == 1
    assert "Test Root CA" in organizer_client.get(_url(event)).content.decode()


# ---------------------------------------------------------------- timestamps

TSA_URL = "https://tsa.example.org/tsr"


@pytest.fixture(autouse=True)
def fast_tsa(monkeypatch):
    """No real sleeping, and a clean "TSA is down" memory between tests."""
    monkeypatch.setattr(signing.time, "sleep", lambda s: None)
    signing._tsa_down_until.clear()


@pytest.fixture(scope="module")
def tsa():
    """A fake time stamping authority (certificate + key)."""
    import datetime

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
    from pyhanko.keys import load_private_key_from_pemder_data

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Fake TSA")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=30))
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.TIME_STAMPING]), True
        )
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return (
        next(iter(load_certs_from_pemder_data(cert_pem))),
        load_private_key_from_pemder_data(key_pem, None),
    )


class FakeTSA(signing.RequestsTimeStamper):
    """Real RequestsTimeStamper, but the HTTP POST is answered locally."""

    def __init__(self, tsa, fail_times=0):
        super().__init__(TSA_URL)
        from pyhanko.sign.timestamps import DummyTimeStamper

        self.dummy = DummyTimeStamper(*tsa)
        self.fail_times = fail_times
        self.calls = 0

    def _post(self, data):
        import asyncio

        from asn1crypto import tsp

        self.calls += 1
        if self.calls <= self.fail_times:
            raise ConnectionError("tsa down")
        req = tsp.TimeStampReq.load(data)
        return asyncio.run(self.dummy.async_request_tsa_response(req)).dump()


def _signing(event, keypair, mode, url=TSA_URL):
    with scopes_disabled():
        return OrganizerSigningCertificate.objects.create(
            organizer=event.organizer,
            certificate_pem=keypair[0],
            private_key_pem=keypair[1],
            timestamp_mode=mode,
            timestamp_url=url,
        )


def _has_timestamp(pdf):
    sig = PdfFileReader(BytesIO(pdf)).embedded_signatures[0]
    unsigned = sig.signed_data["signer_infos"][0]["unsigned_attrs"]
    if not unsigned.native:
        return False
    return any(a["type"].native == "signature_time_stamp_token" for a in unsigned)


@pytest.mark.django_db
def test_timestamp_is_embedded(event, keypair, tsa, monkeypatch, simple_pdf):
    cfg = _signing(event, keypair, "required")
    fake = FakeTSA(tsa)
    monkeypatch.setattr(signing, "_timestamper", lambda s: fake)
    assert _has_timestamp(signing.sign_pdf(simple_pdf, cfg))
    # pyHanko asks once with a dummy digest to size the signature, then for real
    assert fake.calls == 2
    # the size estimate is cached: further PDFs cost exactly one request each
    assert _has_timestamp(signing.sign_pdf(simple_pdf, cfg))
    assert fake.calls == 3


@pytest.mark.django_db
def test_one_client_is_reused_per_url(event, keypair):
    cfg = _signing_obj(keypair, "optional")
    signing._timestampers.clear()
    assert signing._timestamper(cfg) is signing._timestamper(cfg)


def _signing_obj(keypair, mode):
    return OrganizerSigningCertificate(
        certificate_pem=keypair[0], private_key_pem=keypair[1],
        timestamp_mode=mode, timestamp_url=TSA_URL,
    )


@pytest.mark.django_db
def test_off_never_contacts_the_tsa(event, keypair, monkeypatch, simple_pdf):
    cfg = _signing(event, keypair, "off")
    monkeypatch.setattr(
        signing, "RequestsTimeStamper", lambda *a, **k: pytest.fail("contacted")
    )
    assert not _has_timestamp(signing.sign_pdf(simple_pdf, cfg))


@pytest.mark.django_db
def test_one_failed_try_is_retried(event, keypair, tsa, monkeypatch, simple_pdf):
    cfg = _signing(event, keypair, "required")
    fake = FakeTSA(tsa, fail_times=1)
    monkeypatch.setattr(signing, "_timestamper", lambda s: fake)
    assert _has_timestamp(signing.sign_pdf(simple_pdf, cfg))
    assert fake.calls == 3  # failed, then dummy + real


@pytest.mark.django_db
def test_optional_falls_back_to_unstamped_and_warns(
    event, keypair, tsa, monkeypatch, simple_pdf, caplog
):
    cfg = _signing(event, keypair, "optional")
    fake = FakeTSA(tsa, fail_times=99)
    monkeypatch.setattr(signing, "_timestamper", lambda s: fake)
    with caplog.at_level("WARNING"):
        pdf = signing.sign_pdf(simple_pdf, cfg)
    assert len(PdfFileReader(BytesIO(pdf)).embedded_signatures) == 1
    assert not _has_timestamp(pdf)
    assert "Signing without timestamp" in caplog.text
    assert fake.calls == signing.TSA_ATTEMPTS


@pytest.mark.django_db
def test_required_fails_when_tsa_is_down(event, keypair, tsa, monkeypatch, simple_pdf):
    cfg = _signing(event, keypair, "required")
    monkeypatch.setattr(signing, "_timestamper", lambda s: FakeTSA(tsa, fail_times=99))
    with pytest.raises(signing.TimestampError):
        signing.sign_pdf(simple_pdf, cfg)


@pytest.mark.django_db
def test_down_tsa_is_skipped_for_a_while(event, keypair, tsa, monkeypatch, simple_pdf):
    """After a failed run, further PDFs don't each wait for timeouts."""
    cfg = _signing(event, keypair, "optional")
    fake = FakeTSA(tsa, fail_times=99)
    monkeypatch.setattr(signing, "_timestamper", lambda s: fake)
    signing.sign_pdf(simple_pdf, cfg)
    calls_after_first = fake.calls
    signing.sign_pdf(simple_pdf, cfg)
    signing.sign_pdf(simple_pdf, cfg)
    assert fake.calls == calls_after_first
    # ...and the authority is tried again once the cool-down is over.
    signing._tsa_down_until.clear()
    fake.fail_times = 0
    assert _has_timestamp(signing.sign_pdf(simple_pdf, cfg))


@pytest.mark.django_db
def test_down_tsa_is_shared_through_the_cache(
    event, keypair, tsa, monkeypatch, simple_pdf, settings
):
    """With a real cache the cool-down is not kept per process."""
    settings.REAL_CACHE_USED = True
    settings.CACHES = {
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
    }
    cfg = _signing(event, keypair, "optional")
    fake = FakeTSA(tsa, fail_times=99)
    monkeypatch.setattr(signing, "_timestamper", lambda s: fake)
    signing.sign_pdf(simple_pdf, cfg)
    calls_after_first = fake.calls
    signing.sign_pdf(simple_pdf, cfg)
    assert fake.calls == calls_after_first
    assert not signing._tsa_down_until

    cache.delete(signing._tsa_down_key(cfg.timestamp_url))
    fake.fail_times = 0
    assert _has_timestamp(signing.sign_pdf(simple_pdf, cfg))
    assert cache.get(signing._tsa_down_key(cfg.timestamp_url)) is None


@pytest.mark.django_db
def test_signing_errors_are_not_blamed_on_the_tsa(
    event, keypair, tsa, monkeypatch, simple_pdf
):
    cfg = _signing(event, keypair, "optional")
    cfg.private_key_pem = "garbage"
    fake = FakeTSA(tsa)
    monkeypatch.setattr(signing, "_timestamper", lambda s: fake)
    with pytest.raises(Exception) as e:
        signing.sign_pdf(simple_pdf, cfg)
    assert not isinstance(e.value, signing.TimestampError)
    assert not signing._tsa_down_until


def test_http_client_rejects_wrong_content_type(monkeypatch):
    class Response:
        headers = {"Content-Type": "text/html"}
        content = b""

        def raise_for_status(self):
            pass

    monkeypatch.setattr(signing.requests, "post", lambda *a, **k: Response())
    from pyhanko.sign.timestamps import TimestampRequestError

    with pytest.raises(TimestampRequestError):
        signing.RequestsTimeStamper(TSA_URL)._post(b"x")


def test_http_client_does_not_follow_redirects(monkeypatch):
    seen = {}

    class Response:
        headers = {"Content-Type": "application/timestamp-reply"}
        content = b"ok"

        def raise_for_status(self):
            pass

    def post(*a, **k):
        seen.update(k)
        return Response()

    monkeypatch.setattr(signing.requests, "post", post)
    assert signing.RequestsTimeStamper(TSA_URL)._post(b"x") == b"ok"
    assert seen["allow_redirects"] is False and seen["timeout"] == signing.TSA_TIMEOUT


@pytest.mark.parametrize(
    "url, resolves_to, ok",
    [
        (TSA_URL, "93.184.216.34", True),
        ("http://tsa.example.org", "93.184.216.34", True),
        ("https://internal.example.org", "10.0.0.5", False),
        ("https://meta.example.org", "169.254.169.254", False),
        ("https://local.example.org", "127.0.0.1", False),
        ("ftp://tsa.example.org", "93.184.216.34", False),
    ],
)
def test_timestamp_url_validation(monkeypatch, url, resolves_to, ok):
    monkeypatch.setattr(
        signing.socket,
        "getaddrinfo",
        lambda host, port: [(2, 1, 6, "", (resolves_to, port))],
    )
    if ok:
        signing.validate_timestamp_url(url)
    else:
        with pytest.raises(ValueError):
            signing.validate_timestamp_url(url)


@pytest.mark.django_db
def test_settings_form_requires_url_unless_off(organizer_client, event, signing_cfg, monkeypatch):
    monkeypatch.setattr(
        signing.socket, "getaddrinfo",
        lambda host, port: [(2, 1, 6, "", ("93.184.216.34", port))],
    )
    base = {"action": "settings", "enabled": "on", "reason": "x"}
    missing = organizer_client.post(
        _url(event), {**base, "timestamp_mode": "required", "timestamp_url": ""}
    )
    assert missing.status_code == 200  # form re-rendered with an error
    with scopes_disabled():
        assert OrganizerSigningCertificate.objects.get().timestamp_mode == "off"
    saved = organizer_client.post(
        _url(event), {**base, "timestamp_mode": "optional", "timestamp_url": TSA_URL}
    )
    assert saved.status_code == 302
    with scopes_disabled():
        cfg = OrganizerSigningCertificate.objects.get()
    assert (cfg.timestamp_mode, cfg.timestamp_url) == ("optional", TSA_URL)
