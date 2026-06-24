"""LLM judgment: does the user want to persist the attached material, and to whom?"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from server.orchestrator.json_protocol import parse_json_object
from server.services.llm_factory import build_adapter
from server.services.prompts.storage_intent import STORAGE_INTENT_SYSTEM

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StorageIntent:
    store: bool
    target: str | None


async def classify(message: str, attachment_names: list[str], spawn_names: list[str]) -> StorageIntent:
    """Conservative: any error / unparseable / uncertain → store=False."""
    user = (
        f"User message: {message}\n"
        f"Attached: {', '.join(attachment_names) or '(none)'}\n"
        f"Available spawns: {', '.join(spawn_names) or '(none)'}"
    )
    try:
        adapter = await build_adapter(role="judgment")
        resp = await adapter.chat(system=STORAGE_INTENT_SYSTEM, user=user)
        parsed = parse_json_object(resp.content or "") or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("storage_intent classify failed (defaulting to no-store): %s", exc)
        return StorageIntent(store=False, target=None)
    store = bool(parsed.get("store"))
    target = parsed.get("target")
    if not isinstance(target, str) or not target.strip():
        target = None
    return StorageIntent(store=store, target=target)
