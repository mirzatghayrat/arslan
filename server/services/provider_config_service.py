"""CRUD for multi-key BYOK provider configs. One row is always is_primary."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from arslan.llm import routing
from arslan.llm.catalog import capabilities_for
from server import crypto
from server.db.models import ProviderConfig
from server.services.settings_service import _looks_masked, mask_secret


def _safe(enc: str) -> str:
    try:
        return crypto.decrypt(enc)
    except Exception:  # noqa: BLE001 - undecryptable key treated as unset for display
        return ""


def _to_public(row: ProviderConfig) -> dict:
    return {
        "id": row.id, "label": row.label, "provider": row.provider, "model": row.model,
        "base_url": row.base_url or "", "is_primary": bool(row.is_primary),
        "api_key": mask_secret(_safe(row.api_key)),
    }


async def list_configs(session: AsyncSession) -> list[dict]:
    rows = (await session.execute(select(ProviderConfig).order_by(ProviderConfig.id))).scalars().all()
    return [_to_public(r) for r in rows]


async def list_for_routing(session: AsyncSession) -> list[dict]:
    rows = (await session.execute(select(ProviderConfig).order_by(ProviderConfig.id))).scalars().all()
    return [{"id": r.id, "provider": r.provider, "model": r.model,
             "base_url": r.base_url or "", "is_primary": bool(r.is_primary)} for r in rows]


async def add_config(session: AsyncSession, *, label: str, provider: str, model: str,
                     base_url: str, api_key: str) -> dict:
    first = (await session.execute(select(ProviderConfig).limit(1))).scalar_one_or_none() is None
    row = ProviderConfig(label=label, provider=provider, model=model, base_url=base_url or None,
                         api_key=crypto.encrypt(api_key), is_primary=first)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _to_public(row)


async def update_config(session: AsyncSession, config_id: int, *, label: str | None = None,
                        provider: str | None = None, model: str | None = None,
                        base_url: str | None = None, api_key: str | None = None) -> dict | None:
    row = await session.get(ProviderConfig, config_id)
    if row is None:
        return None
    if label is not None:
        row.label = label
    if provider is not None:
        row.provider = provider
    if model is not None:
        row.model = model
    if base_url is not None:
        row.base_url = base_url or None
    if api_key and not _looks_masked(api_key):
        row.api_key = crypto.encrypt(api_key)
    await session.commit()
    await session.refresh(row)
    return _to_public(row)


async def set_primary(session: AsyncSession, config_id: int) -> None:
    rows = (await session.execute(select(ProviderConfig))).scalars().all()
    for r in rows:
        r.is_primary = (r.id == config_id)
    await session.commit()


async def delete_config(session: AsyncSession, config_id: int) -> bool:
    """Delete a provider config.  Returns False (and does NOT delete) if it is the only row.

    The caller should translate False → HTTP 400.  Returns True on success.
    Returns True (no-op) when config_id does not exist (already gone).
    """
    row = await session.get(ProviderConfig, config_id)
    if row is None:
        return True  # already absent — nothing to do
    # Guard: refuse to delete the last remaining config
    count_result = await session.execute(select(ProviderConfig))
    all_rows = count_result.scalars().all()
    if len(all_rows) <= 1:
        return False
    was_primary = row.is_primary
    await session.delete(row)
    await session.commit()
    if was_primary:
        survivor = (await session.execute(
            select(ProviderConfig).order_by(ProviderConfig.id).limit(1))).scalar_one_or_none()
        if survivor is not None:
            survivor.is_primary = True
            await session.commit()
    return True


async def get_primary(session: AsyncSession) -> ProviderConfig | None:
    row = (await session.execute(
        select(ProviderConfig).where(ProviderConfig.is_primary.is_(True)).limit(1))).scalar_one_or_none()
    if row is not None:
        return row
    return (await session.execute(
        select(ProviderConfig).order_by(ProviderConfig.id).limit(1))).scalar_one_or_none()


async def get_decrypted_key(session: AsyncSession, config_id: int) -> str:
    row = await session.get(ProviderConfig, config_id)
    return _safe(row.api_key) if row else ""


async def suggest_primary(session: AsyncSession, language: str | None) -> dict | None:
    configs = await list_for_routing(session)
    pick = routing.suggest_primary(configs, language)
    if pick is None:
        return None
    caps = capabilities_for(pick["provider"])
    rationale = (f"Best all-round quality among your keys "
                 f"(reasoning {caps['reasoning']}/10, tool-calling {caps['tool_calling']}/10).")
    return {"id": pick["id"], "provider": pick["provider"], "rationale": rationale}
