"""Symmetric encryption for secrets at rest (Fernet).

Key derivation (S1 OSS-safety hardening)
----------------------------------------
The Fernet key is derived from ``ARSLAN_SECRET_KEY``.

* When a real key is set (including the dev/test flow's ``dev-secret-key``), the key
  is stretched with **PBKDF2-HMAC-SHA256** over a per-install random salt that lives
  in the DATABASE, alongside the ciphertext it is half the key to (migration 0039).
  This replaces the old, unsalted ``SHA256(secret_key)`` derivation.

  The salt is installed once at boot by :func:`adopt_salt`
  (``server.services.crypto_boot`` resolves it). This module NEVER reads the
  filesystem for it and NEVER invents one: deriving without an installed salt raises
  :class:`CryptoNotInitializedError`. A fallback would be indistinguishable from
  working — a *stable* wrong key opens nothing, and anything written under it becomes
  unreadable the moment the real salt reappears. That is the original defect, not a
  safety net for it.

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
_SALT_LEN = 16
# 🔴 NO LONGER USED FOR DERIVATION, and deliberately still here.
#
# This constant was substituted, silently, whenever <data_dir> could not be read or
# written — the third of the three routes by which the salt came apart from the
# ciphertext. Its old docstring said derivation "remains stable across restarts either
# way", which was true and beside the point: a stable WRONG key decrypts nothing, and
# secrets written under it stop opening once the real salt returns.
#
# It is kept because some installs really did write ciphertext under it, and it is
# their only way back. It belongs to the RECOVERY keyring (candidate keys, gated,
# read-only) and must never be reachable from the write path again.
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


class CryptoNotInitializedError(RuntimeError):
    """Raised when a key is derived before boot installed the PBKDF2 salt.

    Loud on purpose. The alternative — guess a salt — is the defect this module was
    rewritten to remove: every guess produces a key that is stable and wrong, which
    looks like a working install right up until the real salt comes back and the
    secrets written in the meantime turn out to be unreadable.
    """


# Process-wide installed salt. Written once, at boot, by :func:`adopt_salt`; read on
# every derivation. Module state rather than a config field because the value lives in
# the database and ``config`` is built before any database exists.
_salt: bytes | None = None
_salt_source: str | None = None


def adopt_salt(salt: bytes, *, source: str) -> None:
    """Install the process-wide PBKDF2 salt. Called once per process, at boot.

    ``source`` records WHERE the salt came from, so a derivation that used anything
    other than the stored per-install value can be reported instead of shrugged at.
    A short salt is rejected rather than padded: padding would accept a truncated or
    poisoned value and pin the install to a key derived from garbage.
    """
    if not isinstance(salt, (bytes, bytearray)) or len(salt) < _SALT_LEN:
        raise ValueError(f"PBKDF2 salt must be at least {_SALT_LEN} bytes")
    global _salt, _salt_source
    _salt, _salt_source = bytes(salt), source


def current_salt() -> bytes:
    """The installed salt, or raise. Never a default."""
    if _salt is None:
        raise CryptoNotInitializedError(
            "the PBKDF2 salt has not been installed for this process; "
            "server.services.crypto_boot.resolve_and_adopt_salt must run at boot"
        )
    return _salt


def salt_provenance() -> str | None:
    """Where the installed salt came from, or None if none is installed."""
    return _salt_source


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


def primary_fernet() -> Fernet:
    """The current key ALONE — PBKDF2 over the installed salt, no fallback.

    Exposed because :class:`MultiFernet` reports only THAT some key worked, never
    WHICH one, and "which one" is the line between a migration and a gamble
    (server/services/crypto_boot.py). It is also the only honest way to verify a
    re-encryption: reading it back through the full keyring would pass on a value
    that is still legacy.
    """
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=current_salt(),
                     iterations=_PBKDF2_ITERATIONS)
    return Fernet(base64.urlsafe_b64encode(kdf.derive(_active_secret().encode("utf-8"))))


def legacy_fernet() -> Fernet:
    """The pre-d6d8afa8 key ALONE — bare SHA256, no salt.

    Needs no installed salt, which is what lets boot ask "can the current inputs open
    this?" before the salt is resolved.
    """
    digest = hashlib.sha256(_active_secret().encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _fernet() -> MultiFernet:
    return _build_multifernet(_active_secret(), current_salt())


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
