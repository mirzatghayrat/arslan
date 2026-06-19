"""Build an LLMAdapter from stored user settings (shared by chat + orchestrator)."""
from __future__ import annotations

from arslan.llm.adapter import LLMAdapter
from arslan.llm.presets import expand_preset
from server.db import session as db_session
from server.services import settings_service


async def build_adapter() -> LLMAdapter:
    """Construct an LLMAdapter from persisted settings (provider/model/base_url + key).

    A stored ``llm_provider`` that names a Tier-0 preset (e.g. ``"deepseek"``) is
    expanded to its OpenAI-compatible base_url + default model via ``expand_preset``,
    so the user only has to pick a name and supply a key.
    """
    async with db_session.AsyncSessionLocal() as db:
        cfg = await settings_service.get_settings(db)
        api_key = await settings_service.get_decrypted_api_key(db)
    provider = cfg.get("llm_provider") or "openai"
    model = cfg.get("llm_model") or ""
    base_url = cfg.get("llm_base_url") or ""
    # Expand the preset on the raw (possibly empty) model so the preset default
    # can fill it; only fall back to gpt-4o if nothing supplied a model.
    provider, model, base_url = expand_preset(provider, model, base_url)
    return LLMAdapter(provider, model or "gpt-4o", api_key=api_key, base_url=base_url)
