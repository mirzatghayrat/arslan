"""Replay-safe tool whitelist (S2 E3 — hermetic replay).

An evolution replay must run a spawn on a task WITHOUT touching real state, so the
model may only see tools that are read-only or fully sandboxed and produce nothing
persistent that a live turn would. This is an explicit ALLOW-list, not an MCP
deny-list: everything not named here is dropped — every MCP tool (side effects on a
real server), `create_skill` (writes a candidate row), the interactive `ask_user_choice`,
and any future tool default to unsafe until proven hermetic.

Why exactly these six:
  - web_search / web_extract   : read-only web fetches (no writes)
  - render_chart               : returns a chart spec/artifact in-memory (no disk write)
  - render_deck                : builds the .pptx in-memory and returns it base64 (the deck
                                 executor never writes disk; only the WS layer offers it as a
                                 download, and replay's on_event is a no-op)
  - run_python                 : the code sandbox (ephemeral scrubbed tmpdir, no network)
  - read_skill                 : reads an equipped skill's own body (read-only)

MCP tools are identified structurally by NOT being in this set (their keys are
`mcp_<sid>__<name>` and carry a non-NULL Tool.external_name); the whitelist needs no
prefix check — an MCP key simply is not a member.
"""
from __future__ import annotations

# Builtin tools safe to expose to the model inside a hermetic replay.
REPLAY_SAFE_BUILTINS: frozenset[str] = frozenset({
    "web_search",
    "web_extract",
    "render_chart",
    "render_deck",
    "run_python",
    "read_skill",
})


def is_replay_safe(key: str | None) -> bool:
    """True iff `key` is a builtin tool safe to run in a hermetic replay."""
    return key in REPLAY_SAFE_BUILTINS


def filter_replay_tools(wired: list[dict]) -> list[dict]:
    """Narrow a resolved wired-tool list to the replay-safe builtins, dropping every
    MCP tool and any non-hermetic builtin. Order preserved; input never mutated."""
    return [t for t in wired if t.get("key") in REPLAY_SAFE_BUILTINS]
