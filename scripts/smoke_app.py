"""Smoke-harness ASGI app: the REAL production app with exactly ONE seam patched.

`server.services.llm_factory.build_adapter` is replaced with a deterministic,
network-free mock BEFORE `server.main` is imported — every consumer module does
`from server.services.llm_factory import build_adapter` at import time, so the
patch must land first (this file's import order is load-bearing).

Everything else is the true production path: uvicorn boot, the migration chain in
main.py's lifespan, the /ws/arslan WebSocket, the router, persistence.

Run (scripts/smoke_main_link.py does this for you):
    ARSLAN_DATA_DIR=<tmp> .venv/bin/python -m uvicorn scripts.smoke_app:app --port <p>
"""
from __future__ import annotations

import os

# --- 1. patch the adapter factory BEFORE any server module imports it ---------
from server.services import llm_factory  # noqa: E402  (only import that may precede the patch)

SMOKE_REPLY = "SMOKE_REPLY_OK — deterministic answer from the smoke adapter."
ROUTER_JSON = '{"action": "answer", "reason": "smoke: deterministic answer turn"}'


class _SmokeAdapter:
    """Mirrors tests/server/conftest.MockAdapter's surface (chat + chat_stream).

    role="router" gets valid router JSON → a clean persisted "answer" decision;
    every other role gets plain text (JSON-parsing side consumers like
    storage-intent/titler fail-open by design — the main link is what we assert).
    """

    def __init__(self, role: str | None):
        self._role = role

    async def chat(self, system, user, history=None, tools=None, temperature=0.7):  # noqa: ANN001
        from arslan.models import LLMResponse
        if os.environ.get("ARSLAN_SMOKE_VALIDATION") == "1":
            self._broken_fixture = getattr(self, "_broken_fixture", False) or "UI_BROKEN_FILE" in str(user)
            if self._broken_fixture:
                return LLMResponse(content="[Synthetic missing file](/api/v1/runs/999/artifacts/run_999_missing.pdf)",
                                   tool_calls=[], usage={})
        if os.environ.get("ARSLAN_SMOKE_COLLABORATION") == "1":
            if "temporary collaborator on one bounded subtask" in system:
                return LLMResponse(content='{"result":"已核对合成参考材料，未访问真实账号或外部服务。","remaining_work":[]}',
                                   tool_calls=[], usage={})
            if ("UI_WORKER_CHECK" in str(user) and tools and
                    any(item.get("function", {}).get("name") == "delegate_work" for item in tools)):
                return LLMResponse(content="", usage={}, tool_calls=[{
                    "id": "synthetic-collaboration", "type": "function", "function": {
                        "name": "delegate_work", "arguments": {"jobs": [
                            {"method": "research", "objective": "核对合成资料的事实", "context": "合成资料：两份说明均已提供。"},
                            {"method": "product-design", "objective": "核对合成界面的可读性", "context": "合成设计说明：正文与按钮需清晰。"},
                        ]}}}])
        content = ROUTER_JSON if self._role == "router" else SMOKE_REPLY
        return LLMResponse(content=content, tool_calls=[], usage={})

    async def chat_stream(self, system, user, history=None, tools=None, temperature=0.7):  # noqa: ANN001
        yield ROUTER_JSON if self._role == "router" else SMOKE_REPLY


async def _smoke_build_adapter(role: str | None = None):
    return _SmokeAdapter(role)


llm_factory.build_adapter = _smoke_build_adapter

# --- 2. only now import the real app (consumers bind the patched factory) -----
from server.main import create_app  # noqa: E402

app = create_app()
