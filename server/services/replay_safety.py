"""Replay-safe tool whitelist (S2 E3 — hermetic replay). DELETE-BY: v0.1.64, with C7c-3b.

An evolution replay must run a spawn on a task WITHOUT touching real state, so the
model may only see tools that are read-only or fully sandboxed and produce nothing
persistent that a live turn would. This is an explicit ALLOW-list, not an MCP
deny-list: everything not named here is dropped — every MCP tool (side effects on a
real server), `create_skill` (asks to save a skill), the interactive `ask_user_choice`,
and any future tool default to unsafe until proven hermetic.

Why exactly these five:
  - web_search / web_extract   : read-only web fetches (no writes)
  - render_chart               : returns a chart spec/artifact in-memory (no disk write)
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
# under one of these must be hermetic. The throat backstop (tool_loop._dispatch_tool)
# reads this set; so did the expert dispatcher's structural rule until C7b-4 deleted it.
#   "evolution-replay"  — was replay_run.REPLAY_CONVERSATION_ID, the sentinel every
#                         eval/replay path used. Those paths went in C7b-1/C7b-2
#                         (v0.1.63), so no live path dispatches under it today; the
#                         seal stays for old rows and any future eval path.
#   "evolution-eval"    — RESERVED, not in use: no dispatch path under server/ or
#                         arslan/ passes this id (it appears in this module and in the
#                         tests that pin the set). It stays so a future eval path can
#                         adopt it already-sealed; do not read its presence as evidence
#                         that something dispatches under it.
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
    assertion derive hermeticity from THIS predicate.

    🔴 Besides meaning "synthetic traffic", a True here makes `tool_loop._dispatch_tool`
    refuse every non-REPLAY_SAFE_BUILTINS tool. Never add a real or background
    conversation id to `_HERMETIC_CONVERSATION_IDS`: it would seal that work's own
    writes. (The separate "never learn from it" predicate, should_not_curate, went with
    its only caller, distill_service, in C8-4, v0.1.63.)
    """
    return conversation_id in _HERMETIC_CONVERSATION_IDS


#: 0.1.63 K4b: a live run has no allowance of its own any more (it was 25); a web read is one tool
#: call under the run's limits (K4a), and K4a's tool-call limit and dollar cap bound a web-heavy turn.
#: What stays is the eval/replay allowance below. The tools it covers: capping web_extract alone
#: would be bypassed by alternating with web_search, so they share ONE allowance.
_FETCH_TOOLS = frozenset({"web_search", "web_extract"})


#: FU-2b. The eval/replay allowance, and it is deliberately NOT per dispatch.
#:
#: The gate dispatches roughly `pairs x 2 arms x (epochs*lr_budget + 1)` times —
#: a few hundred for one candidate. Giving each of those its own 25 would be a
#: cap in name only: 25 x 224 is not a bound, it is a multiplier with a label.
#: So the allowance spans the whole attempt, and it is smaller than the live one
#: because an evaluation is not supposed to be doing research — a candidate that
#: needs fifty pages is a candidate worth refusing.
HERMETIC_FETCH_BUDGET = 50      # DELETE-BY: v0.1.64, with C7c-3b.

#: Spent-so-far per hermetic sentinel. Module state rather than a threaded
#: parameter because every dispatch in an attempt already shares one sentinel
#: conversation id, and threading a budget object through the evaluator would
#: mean changing every layer between here and the watcher for a counter.
#:
#: If two spawns are evaluated at once they SHARE this allowance. That is the
#: conservative direction for a spend gate and is left deliberately: a shared
#: budget can only refuse earlier than a per-attempt one, never later.
#:
#: 🔴 That last sentence was FALSE, and the sharing was never why. The RESET
#: was: the watcher cleared the counter at the top of EVERY attempt, and
#: `_running_spawns` allows one attempt per SPAWN, not one overall. Attempt B
#: starting refunded attempt A mid-flight — 90 spent against a cap of 50 from a
#: single overlap, N x 50 for N overlaps, i.e. the gate loosened exactly when
#: evolution activity and therefore spend was highest.
#:
#: Passing the sentinel to the reset does NOT fix it, which is worth writing
#: down because it is the obvious fix and it is empty: every hermetic dispatch
#: shares the one id, so popping that key and clearing the dict are the same
#: operation. What restores the promise is refcounting the attempts in flight —
#: a fresh allowance when the first one starts, and nothing but sharing after.
#: Covered by tests/server/test_hermetic_budget_refund.py.
_hermetic_fetches: dict[str, int] = {}


#: How many hermetic attempts are in flight. The allowance is refreshed when
#: this goes 0 -> 1 and never while it is above zero, so concurrent attempts
#: SHARE one allowance (conservative, and what the comment above has always
#: claimed) instead of refunding each other (what actually happened).
_hermetic_attempts_inflight = 0


def begin_hermetic_attempt() -> None:
    """Claim the allowance for an attempt that is starting.

    Production callers use this instead of `reset_hermetic_fetch_budget`, which
    is unconditional and therefore unsafe while anything else is running.
    """
    global _hermetic_attempts_inflight
    if _hermetic_attempts_inflight == 0:
        _hermetic_fetches.clear()
    _hermetic_attempts_inflight += 1


def end_hermetic_attempt() -> None:
    """Release one in-flight claim. Must run even when the attempt raised."""
    global _hermetic_attempts_inflight
    _hermetic_attempts_inflight = max(0, _hermetic_attempts_inflight - 1)


def hermetic_attempts_inflight() -> int:
    """For tests and diagnostics; never a control-flow input."""
    return _hermetic_attempts_inflight


def reset_hermetic_fetch_budget(conversation_id: str | None = None) -> None:
    """Start a fresh allowance. Called by the watcher at the top of an attempt.

    Without this the counter would be process-lifetime and the first attempt
    after a restart would get the budget while every later one got nothing —
    a gate that tightens silently over uptime, which is worse than no gate
    because it looks like a broken feature rather than a limit."""
    if conversation_id is None:
        _hermetic_fetches.clear()
    else:
        _hermetic_fetches.pop(conversation_id, None)


def hermetic_fetches_used(conversation_id: str) -> int:
    """For tests and diagnostics; never a control-flow input."""
    return _hermetic_fetches.get(conversation_id, 0)


def _check_hermetic_fetch_budget(conversation_id: str | None) -> dict | None:
    key = conversation_id or "evolution"
    used = _hermetic_fetches.get(key, 0)
    if used >= HERMETIC_FETCH_BUDGET:
        return {"ok": False,
                "error": f"evaluation fetch budget reached ({HERMETIC_FETCH_BUDGET} "
                         "web_search/web_extract calls for this attempt) — judge the "
                         "candidate on what has already been gathered"}
    _hermetic_fetches[key] = used + 1
    return None


async def _check_fetch_budget(tool_key: str, *, conversation_id: str | None) -> dict | None:
    """None to proceed, or an explicit refusal dict once an eval/replay attempt has spent its allowance.

    🔴 SCOPE. A live run has no fetch allowance since 0.1.63 K4b: its reads count as tool calls.
    A hermetic eval/replay gets HERMETIC_FETCH_BUDGET for the WHOLE ATTEMPT, which is the only shape that
    bounds anything there: `web_search` and `web_extract` are both in
    REPLAY_SAFE_BUILTINS (sealing keeps read-only web and drops WRITE tools plus
    anything non-allowlisted), and the gate dispatches roughly
    `pairs x 2 arms x (epochs*lr_budget + 1)` times — so a per-dispatch cap would
    multiply rather than limit. This was registered as FU-2b and is now in.

    The refusal is EXPLICIT rather than a silent drop: a swallowed fetch looks to the
    model like a page with no content, and it will simply try the next URL.
    """
    if tool_key not in _FETCH_TOOLS:
        return None
    if is_hermetic_context(conversation_id):
        return _check_hermetic_fetch_budget(conversation_id)
    return None
