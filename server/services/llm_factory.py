"""Build an LLMAdapter from stored provider configs (shared by chat + orchestrator)."""
from __future__ import annotations

from arslan.llm.adapter import LLMAdapter
from arslan.llm.presets import expand_preset
from server.db import session as db_session
from server.services import provider_config_service, settings_service


async def build_adapter(role: str | None = None) -> LLMAdapter:
    """Construct an LLMAdapter for *role*.

    Phase A: always uses the primary config. The legacy flat-settings path is the
    fallback when no provider_configs exist yet (fresh install before first save).
    Phase B replaces the `chosen = primary` line with the routing engine.
    """
    async with db_session.AsyncSessionLocal() as db:
        configs = await provider_config_service.list_for_routing(db)
        if not configs:
            return await _legacy_build_adapter(db)
        primary = next((c for c in configs if c["is_primary"]), configs[0])
        chosen = primary  # Phase B: routing.select(role, strategy, configs, language)
        key = await provider_config_service.get_decrypted_key(db, chosen["id"])
    provider, model, base_url = expand_preset(chosen["provider"], chosen["model"], chosen["base_url"] or "")
    return LLMAdapter(provider, model or "gpt-4o", api_key=key, base_url=base_url)


async def _legacy_build_adapter(db) -> LLMAdapter:  # noqa: ANN001
    cfg = await settings_service.get_settings(db)
    api_key = await settings_service.get_decrypted_api_key(db)
    provider = cfg.get("llm_provider") or "openai"
    model = cfg.get("llm_model") or ""
    base_url = cfg.get("llm_base_url") or ""
    provider, model, base_url = expand_preset(provider, model, base_url)
    return LLMAdapter(provider, model or "gpt-4o", api_key=api_key, base_url=base_url)
