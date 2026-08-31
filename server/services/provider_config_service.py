"""CRUD for multi-key BYOK provider configs. One row is always is_primary."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from arslan.llm import routing
from arslan.llm.catalog import capabilities_for
from server import crypto
from server.db.models import ProviderConfig
from server.services.secret_state import secret_state
from server.services.settings_service import _looks_masked, mask_secret


def _safe(enc: str) -> str:
    try:
        return crypto.decrypt(enc)
    except Exception:  # noqa: BLE001 - undecryptable key treated as unset for display
        return ""


#: The shared three-state predicate. This module implemented it FIRST, for the BYOK
#: provider rows; it now lives in server.services.secret_state so the settings-level
#: secrets use the same vocabulary instead of a second copy that could drift.
_key_status = secret_state


def _require_custom_base_url(provider: str, base_url: str) -> None:
    """P3: a "custom" config has no preset to fall back on — expand_preset
    passes it through verbatim, so a blank base_url would silently talk to
    api.openai.com (OpenAIProvider's default). Refuse it at the door.

    Raises ValueError; the API layer maps it to HTTP 422.
    """
    if provider == "custom" and not (base_url or "").strip():
        raise ValueError("custom provider 必须填写 base_url")


def _to_public(row: ProviderConfig) -> dict:
    return {
        "id": row.id, "label": row.label, "provider": row.provider, "model": row.model,
        "base_url": row.base_url or "", "is_primary": bool(row.is_primary),
        "api_key": mask_secret(_safe(row.api_key)),
        # Honest key state so the UI can distinguish "no key" from "stored but
        # undecryptable" (secret changed) instead of showing a misleading "requires key".
        "key_status": _key_status(row.api_key),
        # P4: last connectivity probe (null until the first probe)
        "last_health": row.last_health,
        "last_health_detail": row.last_health_detail,
        "last_health_at": row.last_health_at.isoformat() if row.last_health_at else None,
    }


async def count_undecryptable_keys(session: AsyncSession) -> int:
    """Count provider configs whose api_key is STORED but cannot be decrypted (encrypted
    under a now-changed ARSLAN_SECRET_KEY). A non-zero count means every affected BYOK key
    silently reads as empty. A boot canary reads this to warn the operator."""
    rows = (await session.execute(select(ProviderConfig))).scalars().all()
    return sum(1 for r in rows if _key_status(r.api_key) == "undecryptable")


async def list_configs(session: AsyncSession) -> list[dict]:
    rows = (await session.execute(select(ProviderConfig).order_by(ProviderConfig.id))).scalars().all()
    return [_to_public(r) for r in rows]


async def list_for_routing(session: AsyncSession) -> list[dict]:
    rows = (await session.execute(select(ProviderConfig).order_by(ProviderConfig.id))).scalars().all()
    # 🔴 healthy + key_state are here because routing cannot filter on what it cannot
    # see. Without them arslan.llm.routing.usable() is a no-op that looks like a
    # feature: a config whose key will not decrypt scores exactly as well as one that
    # works, gets chosen, and fails at the provider with a 401 that blames the
    # provider.
    return [{"id": r.id, "provider": r.provider, "model": r.model,
             "base_url": r.base_url or "", "is_primary": bool(r.is_primary),
             "healthy": _last_health_ok(r),
             "key_state": _key_status(r.api_key)} for r in rows]


#: The producer's vocabulary, mapped to the routing predicate. The ONLY writer of
#: ProviderConfig.last_health is record_test_verdict() below, which turns one
#: chat-test result into one of these two words — so these keys are not a
#: convention, they are that function's literals.
#:
#: 🔴 History, twice over. This first tested the column against ("ok","healthy",
#: "true","1") — words no producer ever wrote — so every probed config read as
#: healthy=False and routing filtered out the very configs the user had tested.
#: It was then pinned to the /models probe's three words. That probe is now gone:
#: it answered "did /models list anything", which for a public model-list endpoint
#: (OpenRouter's is public) returns 200 with no key at all — so a dead, capped or
#: region-blocked key still read as reachable. The question was never "does the
#: list endpoint answer", it is "can this LLM answer a message", so the chat test
#: is the only producer now. tests/server/test_health_vocabulary_reaches_routing.py
#: derives these keys from record_test_verdict's source and fails on any drift.
_HEALTH_OK: dict[str, bool] = {
    # A real chat round-trip came back. The only evidence that means anything.
    "ok": True,
    # The provider refused, or nothing came back. Unlike the old probe's
    # "reachable_no_list", this is not an ambiguous signal to fail open on: the
    # exact call the user's turn would make was made, and it did not work.
    # select() still keeps the primary regardless, so a transient failure at
    # launch cannot lock anyone out of their own default model.
    "failed": False,
}


def record_test_verdict(row, *, ok: bool, detail: str | None) -> None:
    """Persist one chat-test verdict on a config row. The ONLY writer of
    last_health / last_health_at / last_health_detail.

    ``detail`` is the human-readable reason from llm_errors (or None on success);
    it is stored rather than kept in frontend memory so that the reason a model
    is unusable survives a remount — "failed" with no reason is only marginally
    better than a green dot that lies.
    """
    row.last_health = "ok" if ok else "failed"
    row.last_health_at = datetime.utcnow()
    row.last_health_detail = detail


def _last_health_ok(row) -> bool | None:
    """Tri-state: True/False from the last probe, None when none has run.

    None is NOT False. "Never checked" and "checked and down" call for different
    behaviour, and collapsing them would make a fresh install look broken.

    An unrecognised state also reads None rather than False — if a fourth state ever
    reaches a build whose mapping predates it, "unknown" is the honest answer and the
    fail-open one. The drift guard makes that a red test, not a silent demotion.
    """
    value = getattr(row, "last_health", None)
    if value is None or value == "":
        return None
    return _HEALTH_OK.get(str(value))


async def add_config(session: AsyncSession, *, label: str, provider: str, model: str,
                     base_url: str, api_key: str) -> dict:
    _require_custom_base_url(provider, base_url)
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
    # P3: validate the EFFECTIVE (row ∘ patch) state BEFORE mutating anything,
    # so a rejected patch leaves the row untouched.
    effective_provider = provider if provider is not None else row.provider
    effective_base_url = base_url if base_url is not None else (row.base_url or "")
    _require_custom_base_url(effective_provider, effective_base_url)
    if label is not None:
        row.label = label
    if provider is not None:
        row.provider = provider
    if model is not None:
        row.model = model
    if base_url is not None:
        row.base_url = base_url or None
    key_changed = bool(api_key) and not _looks_masked(api_key)
    if key_changed:
        row.api_key = crypto.encrypt(api_key)
    # A verdict is about the exact configuration that produced it. Change the
    # provider, the model, where it points, or the key, and the stored "ok" is
    # vouching for something nobody has tried — the same class of lie as a green
    # dot from a public model list. Clear it back to "never tested"; the next
    # launch (or the Test button) refills it with something that means anything.
    # `label` is deliberately NOT in this set: renaming a row changes nothing
    # about whether it works.
    if (provider is not None or model is not None
            or base_url is not None or key_changed):
        row.last_health = None
        row.last_health_at = None
        row.last_health_detail = None
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
