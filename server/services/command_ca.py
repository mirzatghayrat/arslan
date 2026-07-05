"""Local CA for the shell network proxy's TLS MITM. Generates a self-signed CA once (cached on
disk, OUTSIDE the sandbox) and signs short-lived leaf certs for allowlisted hosts on demand, so
the proxy can terminate TLS and inject credentials. The CA private key never leaves the host."""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

_ONE_YEAR = _dt.timedelta(days=365)
# NOTE: cryptography needs aware datetimes; this module is the ONE place that legitimately calls
# datetime.now — it stamps certs. Fixed epoch is impossible (certs need real validity windows).


class LocalCA:
    def __init__(self, ca_dir: Path):
        self.dir = Path(ca_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._crt = self.dir / "ca.crt"
        self._key = self.dir / "ca.key"
        if not (self._crt.exists() and self._key.exists()):
            self._generate()
        self.ca_cert_pem = self._crt.read_bytes()
        self._ca_key = serialization.load_pem_private_key(self._key.read_bytes(), password=None)
        self._ca_cert = x509.load_pem_x509_certificate(self.ca_cert_pem)

    def _generate(self) -> None:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Arslan Shell Local CA")])
        now = _dt.datetime.now(_dt.timezone.utc)  # noqa: DTZ005 -- cert validity needs a real clock
        cert = (x509.CertificateBuilder()
                .subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now - _dt.timedelta(minutes=1)).not_valid_after(now + _ONE_YEAR)
                .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                .sign(key, hashes.SHA256()))
        self._key.write_bytes(key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()))
        self._crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        self._key.chmod(0o600)

    def leaf_for(self, host: str) -> tuple[bytes, bytes]:
        """Return (cert_pem, key_pem) for `host`, signed by the CA. New key per call."""
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = _dt.datetime.now(_dt.timezone.utc)  # noqa: DTZ005 -- cert validity needs a real clock
        cert = (x509.CertificateBuilder()
                .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)]))
                .issuer_name(self._ca_cert.subject).public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now - _dt.timedelta(minutes=1)).not_valid_after(now + _dt.timedelta(days=1))
                .add_extension(x509.SubjectAlternativeName([x509.DNSName(host)]), critical=False)
                .sign(self._ca_key, hashes.SHA256()))
        return (cert.public_bytes(serialization.Encoding.PEM),
                key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()))
