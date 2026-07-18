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

🔴 DEBT (brain-P2 decision point 2, follow-up recorded Task 6 — not yet actioned):
`recall` (server.registry.memory_executors.RecallExecutor) is deliberately EXCLUDED
here even though it is read-only, because a replay run must reproduce EXACTLY what
the live turn saw. This round hardened `recall`'s sensitive-fact filter to be
fail-closed on the LIVE path (host sees sensitive facts; spawn/no-caller never do —
see RecallExecutor's docstring), but that filter's behavior has NOT been separately
verified against the REPLAY path (a hermetic replay reconstructs its own caller
context; nothing today asserts replay's sensitive-exclusion is byte-for-byte
identical to live's). The PREREQUISITE for ever reconsidering `recall` here is:
prove replay-path sensitive-exclusion == live-path sensitive-exclusion, with a test
that exercises both paths side by side — not just live. Do not add `recall` to this
set until that verification exists; `remember` (a write tool) must never join this
set regardless.
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


# Synthetic conversation ids used ONLY by evolution eval/replay dispatch. A dispatch
# under one of these must be hermetic — the single source of truth both the structural
# rule (dispatcher.dispatch) and the throat backstop (tool_loop._dispatch_tool) read,
# so the two layers can never drift on "is this an eval context".
#   "evolution-eval"    — evaluator.evaluate / evolution_loop._val_outputs
#   "evolution-replay"  — replay_run.REPLAY_CONVERSATION_ID (run_arm / replay_gate / synthetic_corpus)
#
# 🔴 DRIFT RULE (do not violate): this frozenset is the ONE registry of eval/replay
# sentinel ids. Any NEW eval/replay dispatch path MUST reuse a sentinel from here (or add
# its id to this set) — never hand-write a fresh eval conversation id at a call site. A
# hand-written id that isn't a member here would silently ESCAPE sealing (the whole hole
# this change closes). Adjacent-but-live ids (e.g. the scheduler's "scheduled-{task_id}")
# must NOT be added — they are real work and must run real tools.
_HERMETIC_CONVERSATION_IDS: frozenset[str] = frozenset({"evolution-eval", "evolution-replay"})


def is_hermetic_context(conversation_id: str | None) -> bool:
    """True iff `conversation_id` is an evolution eval/replay sentinel (never a real
    user conversation). Both the structural hermetic rule and the fail-closed throat
    assertion derive hermeticity from THIS predicate."""
    return conversation_id in _HERMETIC_CONVERSATION_IDS
