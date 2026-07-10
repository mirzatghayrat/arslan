"""S1 OSS-safety: crypto fail-closed under the public dev key + hardened KDF.

Covers:
  * is_insecure_default() — True only when ARSLAN_SECRET_KEY is unset/empty; a real
    key (including the dev/test flow's ``dev-secret-key``) is False.
  * encrypt() refuses to write NEW secrets under the PUBLIC fallback key, raising
    InsecureSecretStoreError; the ARSLAN_ALLOW_INSECURE_SECRETS escape hatch re-permits it.
  * the API returns a clean 4xx (not 500) when a provider api_key would be written
    under the public key, and 200 with the escape hatch.
  * a real key round-trips through the new PBKDF2 KDF (and persists a per-install salt).
  * legacy bare-SHA256 ciphertext still decrypts (backward compatibility).
"""
from __future__ import annotations

import base64
import hashlib
import importlib
import os

import pytest
from cryptography.fernet import Fernet, InvalidToken

from server import config as _config_module
from server import crypto


@pytest.fixture
def reload_config():
    """Set crypto-relevant env, reload server.config, return the fresh settings.

    crypto reads ``config.settings`` at call time, so reloading the config module is
    enough to change the active secret. Env is saved/restored manually (NOT via
    monkeypatch) so the final reload happens AFTER restoration — otherwise config
    would be left in the insecure-default state and bleed into later tests.
    """
    _keys = ("ARSLAN_SECRET_KEY", "ARSLAN_ALLOW_INSECURE_SECRETS", "ARSLAN_DATA_DIR")
    saved = {k: os.environ.get(k) for k in _keys}

    def _set(name, value):
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = str(value)

    def _apply(*, secret_key=None, allow_insecure=None, data_dir=None):
        _set("ARSLAN_SECRET_KEY", secret_key)
        _set("ARSLAN_ALLOW_INSECURE_SECRETS", allow_insecure)
        if data_dir is not None:
            _set("ARSLAN_DATA_DIR", str(data_dir))
        importlib.reload(_config_module)
        return _config_module.settings

    yield _apply
    for k, v in saved.items():
        _set(k, v)
    importlib.reload(_config_module)


# --------------------------------------------------------------------------- #
# is_insecure_default()
# --------------------------------------------------------------------------- #
def test_is_insecure_default_true_when_unset(reload_config):
    reload_config(secret_key=None)
    assert crypto.is_insecure_default() is True


def test_is_insecure_default_false_for_dev_secret_key(reload_config):
    # The standard dev/test flow sets a REAL value — NOT the public fallback constant.
    reload_config(secret_key="dev-secret-key")
    assert crypto.is_insecure_default() is False


def test_is_insecure_default_false_for_real_key(reload_config):
    reload_config(secret_key="x" * 40)
    assert crypto.is_insecure_default() is False


# --------------------------------------------------------------------------- #
# FIX 4: whitespace-only secret is normalized consistently (unset == insecure).
# is_insecure_default() strips before testing, so a whitespace-only ARSLAN_SECRET_KEY
# reads as insecure; _active_secret() must ALSO strip so the DERIVED key is the
# dev-fallback key — not a key derived from the literal whitespace (which would fail
# closed citing "public key" while actually using a different, whitespace-derived key).
# --------------------------------------------------------------------------- #
def test_whitespace_secret_is_insecure_and_uses_dev_fallback(reload_config):
    reload_config(secret_key="   ")
    assert crypto.is_insecure_default() is True
    assert crypto._active_secret() == crypto._DEV_FALLBACK_SECRET


def test_whitespace_secret_derives_same_key_as_unset(reload_config, tmp_path):
    """A whitespace-only secret must derive the SAME key as the (unset) public fallback:
    a ciphertext written under "   " decrypts after the secret is unset, same salt."""
    reload_config(secret_key="   ", allow_insecure="1", data_dir=tmp_path)
    token = crypto.encrypt("sk-ws-derived")
    reload_config(secret_key=None, allow_insecure="1", data_dir=tmp_path)
    assert crypto.decrypt(token) == "sk-ws-derived"


# --------------------------------------------------------------------------- #
# encrypt() fail-closed + escape hatch (service/unit level)
# --------------------------------------------------------------------------- #
def test_encrypt_refuses_under_public_key(reload_config, tmp_path):
    reload_config(secret_key=None, data_dir=tmp_path)
    with pytest.raises(crypto.InsecureSecretStoreError) as exc:
        crypto.encrypt("sk-would-be-plaintext")
    assert "ARSLAN_SECRET_KEY" in str(exc.value)


def test_encrypt_allowed_with_escape_hatch(reload_config, tmp_path):
    reload_config(secret_key=None, allow_insecure="1", data_dir=tmp_path)
    token = crypto.encrypt("sk-local-test")
    assert crypto.decrypt(token) == "sk-local-test"


def test_reads_still_work_under_public_key(reload_config, tmp_path):
    """Fail-closed is WRITE-only: already-stored ciphertext must still decrypt."""
    # Encrypt with the escape hatch on, then flip it off — the read must still work.
    reload_config(secret_key=None, allow_insecure="1", data_dir=tmp_path)
    token = crypto.encrypt("sk-stored-earlier")
    reload_config(secret_key=None, allow_insecure=None, data_dir=tmp_path)
    assert crypto.is_insecure_default() is True
    assert crypto.decrypt(token) == "sk-stored-earlier"


# --------------------------------------------------------------------------- #
# hardened KDF (real key) + backward-compat decrypt
# --------------------------------------------------------------------------- #
def test_real_key_roundtrip_and_salt_persisted(reload_config, tmp_path):
    reload_config(secret_key="a-real-strong-random-key-0123456789", data_dir=tmp_path)
    token = crypto.encrypt("sk-live-abcdef")
    assert crypto.decrypt(token) == "sk-live-abcdef"
    # A per-install salt is generated + persisted for the new PBKDF2 KDF.
    assert (tmp_path / "crypto_salt").exists()


def test_new_scheme_is_not_bare_sha256(reload_config, tmp_path):
    """The new ciphertext must NOT be decryptable by the old bare-SHA256 key —
    proving the KDF (PBKDF2 + salt) actually replaced SHA256 on the write path."""
    raw = "a-real-strong-random-key-0123456789"
    reload_config(secret_key=raw, data_dir=tmp_path)
    token = crypto.encrypt("sk-new-scheme")
    legacy_key = base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())
    with pytest.raises(InvalidToken):
        Fernet(legacy_key).decrypt(token.encode())


def test_legacy_sha256_ciphertext_still_decrypts(reload_config, tmp_path):
    """A ciphertext produced under the OLD bare-SHA256 scheme still decrypts after
    the KDF change (MultiFernet legacy fallback) — existing stored data is not bricked."""
    raw = "dev-secret-key"
    reload_config(secret_key=raw, data_dir=tmp_path)
    legacy_key = base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())
    legacy_token = Fernet(legacy_key).encrypt(b"sk-old-legacy-value").decode()
    assert crypto.decrypt(legacy_token) == "sk-old-legacy-value"


# --------------------------------------------------------------------------- #
# API surface: clean 4xx (not 500) on write under the public key
# --------------------------------------------------------------------------- #
async def _build_settings_client(tmp_path):
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    from server.db.models import Base
    from server.db.session import get_session
    from server.main import create_app

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'app.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _override_get_session():
        async with maker() as s:
            yield s

    app = create_app()
    app.dependency_overrides[get_session] = _override_get_session
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
    return engine, client


async def test_api_provider_config_write_returns_4xx_under_public_key(reload_config, tmp_path):
    reload_config(secret_key=None, data_dir=tmp_path)
    engine, client = await _build_settings_client(tmp_path)
    try:
        r = await client.post("/api/v1/settings/provider-configs", json={
            "label": "A", "provider": "deepseek", "model": "deepseek-chat",
            "base_url": "", "api_key": "sk-secret-would-leak"})
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
        assert "ARSLAN_SECRET_KEY" in r.json()["detail"]
    finally:
        await client.aclose()
        await engine.dispose()


async def test_api_provider_config_write_allowed_with_escape_hatch(reload_config, tmp_path):
    reload_config(secret_key=None, allow_insecure="1", data_dir=tmp_path)
    engine, client = await _build_settings_client(tmp_path)
    try:
        r = await client.post("/api/v1/settings/provider-configs", json={
            "label": "A", "provider": "deepseek", "model": "deepseek-chat",
            "base_url": "", "api_key": "sk-local-test-key"})
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
        assert "..." in r.json()["api_key"]
    finally:
        await client.aclose()
        await engine.dispose()
