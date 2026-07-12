"""Build an LLMAdapter from stored provider configs (shared by chat + orchestrator)."""
from __future__ import annotations

from arslan.llm.adapter import LLMAdapter
from arslan.llm.presets import expand_preset
from arslan.llm import routing
from server.db import session as db_session
from server.services import provider_config_service, settings_service


def _require_model(model: str, config_provider: str) -> str:
    """Fail loudly on a blank model instead of the old `or "gpt-4o"` poison
    fallback, which silently sent requests for a model most providers don't
    serve (opaque 404s at chat time)."""
    if not model or not model.strip():
        raise ValueError(
            f"provider '{config_provider}' 没有配置模型 — 请在 Settings 里选择或输入 model id"
        )
    return model


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
        cfg = await settings_service.get_settings(db)
        strategy = cfg.get("llm_strategy") or "single"
        language = cfg.get("language") or None
        chosen = routing.select(role, strategy, configs, language) or next(
            (c for c in configs if c["is_primary"]), configs[0])
        key = await provider_config_service.get_decrypted_key(db, chosen["id"])
    provider, model, base_url = expand_preset(chosen["provider"], chosen["model"], chosen["base_url"] or "")
    return LLMAdapter(provider, _require_model(model, chosen["provider"]), api_key=key,
                      base_url=base_url, report_provider=chosen["provider"])


async def build_synthesis_adapter() -> LLMAdapter | None:
    """Optional dedicated adapter for the tool-loop's forced-step SYNTHESIS call (turning gathered
    findings into the finished answer). Returns the stronger model ONLY when a dedicated synthesis
    config is set (settings `synthesis_config_id` → a provider_config id); otherwise None, so the
    caller keeps its normal adapter. Lets the tool loop stay on a fast model (DeepSeek) while the
    synthesis step uses a stronger one (e.g. Gemini) — without disturbing the default."""
    async with db_session.AsyncSessionLocal() as db:
        cfg = await settings_service.get_settings(db)
        sid = str(cfg.get("synthesis_config_id") or "").strip()
        if not sid:
            return None
        for c in await provider_config_service.list_configs(db):
            if str(c.get("id")) == sid:
                key = await provider_config_service.get_decrypted_key(db, c["id"])
                provider, model, base_url = expand_preset(
                    c["provider"], c["model"], c.get("base_url") or "")
                return LLMAdapter(provider, _require_model(model, c["provider"]), api_key=key,
                                  base_url=base_url, report_provider=c["provider"])
    return None


async def _legacy_build_adapter(db) -> LLMAdapter:  # noqa: ANN001
    cfg = await settings_service.get_settings(db)
    api_key = await settings_service.get_decrypted_api_key(db)
    config_provider = cfg.get("llm_provider") or "openai"
    model = cfg.get("llm_model") or ""
    base_url = cfg.get("llm_base_url") or ""
    provider, model, base_url = expand_preset(config_provider, model, base_url)
    return LLMAdapter(provider, _require_model(model, config_provider), api_key=api_key,
                      base_url=base_url, report_provider=config_provider)
