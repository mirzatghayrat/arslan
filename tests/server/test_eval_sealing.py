# tests/server/test_eval_sealing.py
import json

from server.services import replay_safety
from server.services.replay_run import REPLAY_CONVERSATION_ID
from server.orchestrator import tool_loop


def test_is_hermetic_context_matches_both_eval_sentinels():
    # Both eval sentinels are hermetic; a real conversation id and None are not.
    assert replay_safety.is_hermetic_context("evolution-eval") is True
    assert replay_safety.is_hermetic_context("evolution-replay") is True
    assert replay_safety.is_hermetic_context(REPLAY_CONVERSATION_ID) is True  # == "evolution-replay"
    assert replay_safety.is_hermetic_context("conv_abc123") is False
    assert replay_safety.is_hermetic_context(None) is False


def test_hermetic_set_covers_the_evaluator_sentinel_literal():
    # evaluator.py + evolution_loop._val_outputs dispatch under "evolution-eval";
    # pin that literal is a member so a rename can't silently un-seal them.
    assert "evolution-eval" in replay_safety._HERMETIC_CONVERSATION_IDS


async def test_throat_refuses_nonsafe_tool_in_hermetic_context_even_if_resolver_leaks():
    """The backstop is independent of resolve_tools: even if resolve_tools LEAKS an MCP
    key into the live set (simulating a forgotten upstream filter), a hermetic
    conversation_id must make _dispatch_tool refuse it without executing."""
    executed = []

    async def leaky_resolve():
        # Deliberately leak a side-effecting MCP tool into the live set.
        return [{"key": "mcp_1__send_message"}, {"key": "web_search"}]

    # Monkeypatch resolve_executor so we can detect if execution is (wrongly) reached.
    import server.orchestrator.tool_loop as tl

    async def fake_resolve_executor(key):
        executed.append(key)
        class _E:
            async def execute(self, args):
                executed.append(("EXECUTED", key))
                return {"ok": True}
        return _E()

    orig = tl.resolve_executor
    tl.resolve_executor = fake_resolve_executor
    try:
        emitted = []
        out = await tool_loop._dispatch_tool(
            "mcp_1__send_message", {"to": "x"},
            json.dumps({"tool": "mcp_1__send_message", "args": {}}),
            resolve_tools=leaky_resolve, emit=lambda e: emitted.append(e),
            tool_timeout_s=5, tool_trace=[], convo=[{"role": "user", "content": "hi"}],
            conversation_id="evolution-eval")
    finally:
        tl.resolve_executor = orig

    assert out["ok"] is False
    assert "hermetic" in (out.get("error") or "").lower()
    assert ("EXECUTED", "mcp_1__send_message") not in executed  # never executed


async def test_throat_allows_safe_tool_in_hermetic_context():
    """A read-only builtin (web_search) is NOT blocked by the backstop in a hermetic
    context — it still resolves + executes normally."""
    import server.orchestrator.tool_loop as tl

    async def resolve():
        return [{"key": "web_search"}]

    async def fake_resolve_executor(key):
        class _E:
            async def execute(self, args):
                return {"ok": True, "results": []}
        return _E()

    orig = tl.resolve_executor
    tl.resolve_executor = fake_resolve_executor
    try:
        out = await tool_loop._dispatch_tool(
            "web_search", {"query": "x"},
            json.dumps({"tool": "web_search", "args": {"query": "x"}}),
            resolve_tools=resolve, emit=lambda e: None,
            tool_timeout_s=5, tool_trace=[], convo=[{"role": "user", "content": "hi"}],
            conversation_id="evolution-eval")
    finally:
        tl.resolve_executor = orig
    assert out.get("ok") is True
