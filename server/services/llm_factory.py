"""Build an LLMAdapter from stored user settings (shared by chat + orchestrator)."""
from __future__ import annotations

from arslan.llm.adapter import LLMAdapter
from server.db import session as db_session
from server.services import settings_service


async def build_adapter() -> LLMAdapter:
    """Construct an LLMAdapter from persisted settings (provider/model/base_url + key)."""
    async with db_session.AsyncSessionLocal() as db:
        cfg = await settings_service.get_settings(db)
        api_key = await settings_service.get_decrypted_api_key(db)
    provider = cfg.get("llm_provider") or "openai"
    model = cfg.get("llm_model") or "gpt-4o"
    base_url = cfg.get("llm_base_url") or ""
    return LLMAdapter(provider, model, api_key=api_key, base_url=base_url)
