"""Read/write user settings, encrypting the API key and masking it on read."""
from __future__ import annotations

import logging

from cryptography.fernet import InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server import crypto
from server.db.models import Setting

logger = logging.getLogger(__name__)

# Plain (non-secret) keys returned verbatim.
_PLAIN_KEYS = ("llm_provider", "llm_model", "llm_base_url", "language")
# Secret key stored encrypted, returned masked.
_SECRET_KEY_NAME = "llm_api_key"


def mask_secret(value: str) -> str:
    """Mask a secret for display: keep a prefix hint and last 4 chars."""
    if not value:
        return ""
    if len(value) < 8:
        return "***"
    prefix = value[:3] if value.startswith("sk-") else value[:2]
    return f"{prefix}...{value[-4:]}"


def _safe_decrypt(enc: str) -> str:
    """Decrypt a stored secret, treating an undecryptable value as unset.

    If ARSLAN_SECRET_KEY changed since the value was encrypted, Fernet raises
    InvalidToken; we degrade gracefully so the settings endpoint stays usable
    and the user can re-enter the key.
    """
    try:
        return crypto.decrypt(enc)
    except InvalidToken:
        logger.warning("settings: stored API key could not be decrypted; treating as unset")
        return ""


async def _get_raw(session: AsyncSession, key: str) -> str | None:
    result = await session.execute(select(Setting).where(Setting.key == key))
    row = result.scalar_one_or_none()
    return row.value if row else None


async def _set_raw(session: AsyncSession, key: str, value: str) -> None:
    existing = await session.get(Setting, key)
    if existing:
        existing.value = value
    else:
        session.add(Setting(key=key, value=value))


async def update_settings(session: AsyncSession, data: dict[str, str]) -> None:
    """Persist provided settings. The API key is encrypted before storage."""
    for key in _PLAIN_KEYS:
        if key in data and data[key] is not None:
            await _set_raw(session, key, str(data[key]))
    if data.get(_SECRET_KEY_NAME):
        await _set_raw(session, _SECRET_KEY_NAME, crypto.encrypt(str(data[_SECRET_KEY_NAME])))
    await session.commit()


async def get_settings(session: AsyncSession) -> dict[str, str]:
    """Return settings for display; the API key is masked."""
    out: dict[str, str] = {}
    for key in _PLAIN_KEYS:
        val = await _get_raw(session, key)
        if val is not None:
            out[key] = val
    enc = await _get_raw(session, _SECRET_KEY_NAME)
    out[_SECRET_KEY_NAME] = mask_secret(_safe_decrypt(enc)) if enc else ""
    return out


async def get_decrypted_api_key(session: AsyncSession) -> str:
    """Return the plaintext API key for making LLM calls (never exposed via API)."""
    enc = await _get_raw(session, _SECRET_KEY_NAME)
    return _safe_decrypt(enc) if enc else ""
