"""Pure key derivation: no configuration, filesystem, or global salt state."""
import base64
import hashlib

from cryptography.fernet import Fernet, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

PBKDF2_ITERATIONS = 600_000


def keyring(secret: str, salt: bytes | None) -> MultiFernet:
    legacy = Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest()))
    if salt is None:
        return MultiFernet([legacy])
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                     iterations=PBKDF2_ITERATIONS)
    primary = Fernet(base64.urlsafe_b64encode(kdf.derive(secret.encode("utf-8"))))
    return MultiFernet([primary, legacy])
