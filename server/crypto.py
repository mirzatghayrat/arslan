"""Symmetric encryption for secrets at rest (Fernet).

Key derivation (S1 OSS-safety hardening)
----------------------------------------
The Fernet key is derived from ``ARSLAN_SECRET_KEY``.

* When a real key is set (including the dev/test flow's ``dev-secret-key``), the key
  is stretched with **PBKDF2-HMAC-SHA256** over a per-install random salt generated
  once and persisted to ``<data_dir>/crypto_salt``. This replaces the old, unsalted
  ``SHA256(secret_key)`` derivation.

* When ``ARSLAN_SECRET_KEY`` is unset, the module falls back to the PUBLIC constant
  ``arslan-insecure-dev-key`` — a value that ships in the open-source repo. In that
  state any stored secret is effectively plaintext to anyone with the database file,
  so :func:`encrypt` **fails closed**: it refuses to write NEW secrets and raises
  :class:`InsecureSecretStoreError` unless ``ARSLAN_ALLOW_INSECURE_SECRETS`` opts in.
  READS are never blocked, so already-stored data is not bricked.

Backward compatibility
-----------------------
:func:`decrypt` uses ``MultiFernet([new_pbkdf2_key, legacy_sha256_key])``: it tries
the new PBKDF2 key first and falls back to the legacy bare-SHA256 key, so ciphertext
written under the old scheme still decrypts. New writes always use the PBKDF2 key.
"""
from __future__ import annotations

import base64
import functools
import hashlib
import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from server import config

logger = logging.getLogger(__name__)

# PUBLIC dev fallback — this literal ships in the open-source repo. When it is the
# active derivation input (ARSLAN_SECRET_KEY unset), stored secrets are readable by
# anyone with the source, so writes fail closed (see :func:`encrypt`).
_DEV_FALLBACK_SECRET = "arslan-insecure-dev-key"

# PBKDF2 work factor — the OWASP-2023 floor for PBKDF2-HMAC-SHA256. The derived key
# is cached per (secret, salt), so this cost is paid once per process, not per call.
_PBKDF2_ITERATIONS = 600_000
_SALT_FILENAME = "crypto_salt"
_SALT_LEN = 16
# Deterministic fallback salt, used ONLY when <data_dir> cannot be read/written, so
# derivation stays stable across restarts (weaker than a random per-install salt, but
# it never breaks decrypt). A random persisted salt is preferred and used when possible.
_FALLBACK_SALT = hashlib.sha256(b"arslan-crypto-salt-v1").digest()[:_SALT_LEN]

_TRUTHY = {"1", "true", "yes", "on"}


class InsecureSecretStoreError(RuntimeError):
    """Raised when a NEW secret would be encrypted under the PUBLIC dev fallback key.

    The API layer maps this to a clean 4xx (see ``server.main.create_app``) so the
    caller gets actionable guidance instead of an opaque 500.
    """


def _active_secret() -> str:
    """The effective derivation input: the configured key, or the public fallback.

    Strips first so it agrees with :func:`is_insecure_default` (which also strips): a
    whitespace-only ``ARSLAN_SECRET_KEY`` is treated as UNSET → derives from the public
    ``_DEV_FALLBACK_SECRET`` and reads as insecure, rather than silently deriving a real
    key from the literal whitespace while the fail-closed guard claims "public key"."""
    return (config.settings.secret_key or "").strip() or _DEV_FALLBACK_SECRET


def is_insecure_default() -> bool:
    """True when ``ARSLAN_SECRET_KEY`` is unset/empty → the PUBLIC fallback is active.

    False for ANY real key — including the dev/test flow's ``dev-secret-key``, which is
    a real (non-public-constant) value and must keep the dev flow fully functional.
    """
    return not (config.settings.secret_key or "").strip()


def insecure_writes_allowed() -> bool:
    """Escape hatch: ``ARSLAN_ALLOW_INSECURE_SECRETS`` re-permits writes under the
    public key for a bare no-key local run. Default OFF; every such write is logged."""
    return os.environ.get("ARSLAN_ALLOW_INSECURE_SECRETS", "").strip().lower() in _TRUTHY


def _salt_path() -> Path:
    return Path(config.settings.data_dir) / _SALT_FILENAME


def _load_or_create_salt() -> bytes:
    """Return the per-install PBKDF2 salt, generating + persisting it on first use.

    Falls back to a fixed deterministic salt when ``<data_dir>`` is not readable or
    writable, so key derivation remains stable across restarts either way.
    """
    path = _salt_path()
    try:
        if path.exists():
            data = path.read_bytes()
            if len(data) >= _SALT_LEN:
                return data
    except OSError:
        return _FALLBACK_SALT
    salt = os.urandom(_SALT_LEN)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(salt)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return salt
    except OSError:
        return _FALLBACK_SALT


@functools.lru_cache(maxsize=16)
def _build_multifernet(secret: str, salt: bytes) -> MultiFernet:
    """Build a MultiFernet with the new PBKDF2 key first, legacy SHA256 key second.

    Cached by (secret, salt) so the expensive PBKDF2 derivation runs once per process
    per distinct key. A config reload that changes the secret yields a new cache key.
    """
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                     iterations=_PBKDF2_ITERATIONS)
    new_key = base64.urlsafe_b64encode(kdf.derive(secret.encode("utf-8")))
    legacy_key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return MultiFernet([Fernet(new_key), Fernet(legacy_key)])


def _fernet() -> MultiFernet:
    return _build_multifernet(_active_secret(), _load_or_create_salt())


def encrypt(plaintext: str) -> str:
    """Encrypt a string, returning a urlsafe token.

    FAILS CLOSED under the public dev fallback key: raises
    :class:`InsecureSecretStoreError` unless ``ARSLAN_ALLOW_INSECURE_SECRETS`` is set,
    because the default key is public and offers no real protection.
    """
    if is_insecure_default():
        if not insecure_writes_allowed():
            raise InsecureSecretStoreError(
                "Set ARSLAN_SECRET_KEY to store API keys securely — the default "
                "encryption key is public and offers no protection. See README. "
                "(For local testing only, set ARSLAN_ALLOW_INSECURE_SECRETS=1 to override.)"
            )
        logger.warning(
            "crypto: writing a secret under the PUBLIC dev fallback key "
            "(ARSLAN_ALLOW_INSECURE_SECRETS is set). Stored secrets are effectively "
            "plaintext to anyone with the database file — set ARSLAN_SECRET_KEY for "
            "real protection."
        )
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(token: str) -> str:
    """Decrypt a token produced by :func:`encrypt` (new PBKDF2 or legacy SHA256 scheme)."""
    return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
