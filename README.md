# pretix-plugin-attendance-certificate

Plugin to create and send the certificate of attendance to attendees.

Used by https://pycon.it

## Requirements

pretix 2026.7.0 or newer and Python 3.11 or newer.

## Digital signature

Organizers can sign all certificates of attendance with a certificate of their
organization (PAdES signature, added with [pyHanko](https://github.com/MatthiasValvekens/pyHanko)).
Open *Certificate templates* in the organizer settings and choose
*Digital signature*; there you can create a self-signed certificate or import a
`.p12`/`.pfx` file.

With a self-signed certificate, PDF readers show the signer as unknown until the
public certificate (downloadable on the same page) is added to their trusted
certificates. Publish it together with its SHA-256 fingerprint, e.g. on your
website. Later modifications of a signed PDF are detected regardless.

CA certificates (e.g. the root) contained in an imported `.p12` are stored and
embedded in every signature. Readers still trust only a root the recipient has
imported themselves.

Optionally every signature gets a trusted timestamp (RFC 3161) from a timestamp
server of your choice, which keeps it verifiable after your certificate has
expired. Choose what happens if the server is unreachable: *if possible* signs
without a timestamp and logs a warning, *required* refuses to create the
certificate (a running mail send stops). A server that failed is skipped for
60 seconds, so a bulk send doesn't wait for timeouts on every PDF. This is
shared between all pretix processes if pretix has a cache configured (Redis or
memcached) and remembered per process otherwise.

The private key is stored unencrypted in the pretix database.
