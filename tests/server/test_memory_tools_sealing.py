"""brain-P2 Task 3 — hermetic sealing for recall/remember.

Decision point 2 (plan): recall/remember must NOT enter replay_safety.REPLAY_SAFE_BUILTINS
— an evolution eval/replay run must never read or write the real Second Brain. Mirrors the
throat pattern in tests/server/test_eval_sealing.py (manual resolve_executor swap-and-restore
+ an executed[] spy) for both tools.
"""
from __future__ import annotations

import json

from server.orchestrator import tool_loop
from server.services import replay_safety


def test_recall_not_in_replay_safe_builtins():
    assert "recall" not in replay_safety.REPLAY_SAFE_BUILTINS


def test_remember_not_in_replay_safe_builtins():
    assert "remember" not in replay_safety.REPLAY_SAFE_BUILTINS


async def _throat_refuses(tool_key: str, args: dict) -> None:
    """Shared assertion: in a hermetic context, the throat refuses `tool_key` before
    the executor is ever reached — identical shape to test_eval_sealing.py's
    test_throat_refuses_nonsafe_tool_in_hermetic_context_even_if_resolver_leaks."""
    executed = []

    async def leaky_resolve():
        # Simulate a forgotten upstream filter: the tool IS in the live set.
        return [{"key": tool_key}]

    async def fake_resolve_executor(key):
        executed.append(key)

        class _E:
            async def execute(self, args):
                executed.append(("EXECUTED", key))
                return {"ok": True}
        return _E()

    orig = tool_loop.resolve_executor
    tool_loop.resolve_executor = fake_resolve_executor
    try:
        out = await tool_loop._dispatch_tool(
            tool_key, args, json.dumps({"tool": tool_key, "args": args}),
            resolve_tools=leaky_resolve, emit=lambda e: None,
            tool_timeout_s=5, tool_trace=[], convo=[{"role": "user", "content": "hi"}],
            conversation_id="evolution-eval")
    finally:
        tool_loop.resolve_executor = orig

    assert out["ok"] is False
    assert "unavailable" in (out.get("error") or "").lower()
    assert ("EXECUTED", tool_key) not in executed   # never executed


async def test_throat_refuses_recall_in_hermetic_context():
    await _throat_refuses("recall", {"query": "anything"})


async def test_throat_refuses_remember_in_hermetic_context():
    await _throat_refuses("remember", {"kind": "fact", "action": "append", "content": "x"})


async def test_throat_refuses_remember_even_under_evolution_replay_sentinel():
    """Both hermetic sentinels (evolution-eval AND evolution-replay) must seal remember —
    not just the eval one."""
    executed = []

    async def leaky_resolve():
        return [{"key": "remember"}]

    async def fake_resolve_executor(key):
        executed.append(key)

        class _E:
            async def execute(self, args):
                executed.append(("EXECUTED", key))
                return {"ok": True}
        return _E()

    orig = tool_loop.resolve_executor
    tool_loop.resolve_executor = fake_resolve_executor
    try:
        out = await tool_loop._dispatch_tool(
            "remember", {"kind": "fact", "action": "append", "content": "x"},
            json.dumps({"tool": "remember", "args": {}}),
            resolve_tools=leaky_resolve, emit=lambda e: None,
            tool_timeout_s=5, tool_trace=[], convo=[{"role": "user", "content": "hi"}],
            conversation_id="evolution-replay")
    finally:
        tool_loop.resolve_executor = orig

    assert out["ok"] is False
    assert ("EXECUTED", "remember") not in executed
