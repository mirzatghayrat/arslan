"""Symmetric encryption for secrets at rest (Fernet)."""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet

from server import config


def _derive_key() -> bytes:
    """Derive a urlsafe-base64 32-byte Fernet key from ARSLAN_SECRET_KEY.

    Falls back to a fixed dev key when unset (local-only; never for production).
    Reads ``config.settings`` at call time so reloading ``server.config`` in
    tests takes effect without reloading this module.
    """
    raw = config.settings.secret_key or "arslan-insecure-dev-key"
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _fernet() -> Fernet:
    return Fernet(_derive_key())


def encrypt(plaintext: str) -> str:
    """Encrypt a string, returning a urlsafe token."""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(token: str) -> str:
    """Decrypt a token produced by encrypt()."""
    return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
