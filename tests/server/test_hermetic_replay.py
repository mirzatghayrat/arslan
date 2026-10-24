"""S2 E3 — hermetic replay: a spawn runs on a task WITHOUT polluting real state.

Each test monkeypatches the adapter to a deterministic stub. The invariants:
  - replay writes NO brain_usage (vs a live dispatch which DOES)
  - replay writes NO ConversationEvent (the honesty guard still RUNS — correction applied)
  - the model sees NO MCP tool in replay (builtins kept)
  - replay creates a kind='replay', status='replayed' Run with output + steps, no scoring
  - two arms sharing an ambient + prompts differing by one line → prompts differ by that line
  - is_replayable is False iff the original trace used a non-replay-safe (MCP) tool
"""
from __future__ import annotations



from server.services.replay_safety import REPLAY_SAFE_BUILTINS, filter_replay_tools



# ---------------------------------------------------------------------------
# Deterministic adapters
# ---------------------------------------------------------------------------
class _StreamAdapter:
    """Zero-tool path stub: chat_stream yields fixed chunks."""

    def __init__(self, chunks):
        self._chunks = list(chunks)

    async def chat_stream(self, system, user, history=None, tools=None, temperature=0.7):
        for c in self._chunks:
            yield c

    async def chat(self, system, user, history=None, tools=None, temperature=0.7):
        from arslan.models import LLMResponse
        return LLMResponse(content="".join(self._chunks), tool_calls=[], usage={})


class _LLMResp:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class _NativeAdapter:
    """Equipped path stub: records every chat() call (incl. the tools schema it saw)."""

    def __init__(self, replies):
        self._it = iter(replies)
        self.calls: list[dict] = []

    async def chat(self, system, user, history=None, tools=None, temperature=0.7):
        self.calls.append({"system": system, "tools": tools})
        return next(self._it)


# ---------------------------------------------------------------------------
# DB fixtures
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 1. no brain_usage
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 2. no ConversationEvent (guard still runs)
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 3. no MCP tools visible to the model
# ---------------------------------------------------------------------------
def test_filter_replay_tools_unit():
    wired = [
        {"key": "web_search"}, {"key": "render_chart"},
        {"key": "mcp_9__do"}, {"key": "create_skill"}, {"key": "ask_user_choice"},
    ]
    kept = {t["key"] for t in filter_replay_tools(wired)}
    assert kept == {"web_search", "render_chart"}
    assert "mcp_9__do" not in REPLAY_SAFE_BUILTINS


# ---------------------------------------------------------------------------
# 4. replay creates a replay Run, no scoring
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 5. two-arm symmetry
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 6. is_replayable
# ---------------------------------------------------------------------------
