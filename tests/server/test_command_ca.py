from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import padding

from server.services import command_ca


def test_ca_generates_and_signs_leaf(tmp_path):
    ca = command_ca.LocalCA(tmp_path / "ca")
    cert_pem, key_pem = ca.leaf_for("github.com")
    leaf = x509.load_pem_x509_certificate(cert_pem)
    # leaf is for github.com
    san = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "github.com" in san.get_values_for_type(x509.DNSName)
    # leaf is signed by the CA (verify signature with CA public key)
    ca_cert = x509.load_pem_x509_certificate((tmp_path / "ca" / "ca.crt").read_bytes())
    ca_cert.public_key().verify(
        leaf.signature, leaf.tbs_certificate_bytes,
        padding.PKCS1v15(), leaf.signature_hash_algorithm)  # raises if not signed by CA


def test_ca_is_cached(tmp_path):
    a = command_ca.LocalCA(tmp_path / "ca")
    b = command_ca.LocalCA(tmp_path / "ca")           # reuse existing CA on disk
    assert a.ca_cert_pem == b.ca_cert_pem
