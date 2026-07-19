"""Hermetic-replay atoms the paired ReplayGate (S2 E4) is built from.

- snapshot_ambient : capture a pair's shared ambient (facts + KB injection) ONCE, so the
  two arms are byte-identical outside the target-prompt diff even if the DB shifts between
  them (spec §E3 / audit #16).
- run_arm          : run ONE arm as a hermetic replay (dispatch(replay=True)), returning
  its replay run_id + output + step evidence (E1). The Tier-1 suffix is appended AFTER the
  prompt override for BOTH arms (dispatcher.build_spawn_system), so a candidate and a
  baseline built from the same ambient differ ONLY by their prompt text.
- is_replayable    : a run is replayable iff every tool it actually called is replay-safe;
  a run that used an MCP / side-effect tool is excluded from the corpus.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy import select

from server.db.models import RunStep
from server.orchestrator import dispatcher
from server.services import trace_evidence
from server.services.replay_safety import REPLAY_SAFE_BUILTINS

# Synthetic conversation id for hermetic replays — never a real user conversation, so
# nothing a replay might (in a bug) log lands in a user's timeline.
REPLAY_CONVERSATION_ID = "evolution-replay"


async def snapshot_ambient(db, *, spawn_id: int, conversation_id: str,
                           task: str = "") -> dict:
    """Capture the ambient prompt components (facts + KB injection) for a pair ONCE.

    Returned dict {facts, kb_block, kb_sources} is passed as `ambient=` to run_arm's two
    arms so both see byte-identical context. Retrieval records NO brain_usage (hermetic).
    `db`/`conversation_id` are accepted for caller-session symmetry with E4; retrieval and
    facts open their own sessions. `task` scopes the KB snapshot (a pair is one task)."""
    from server.orchestrator import memory
    from server.services import knowledge

    facts = await memory.facts_text()
    kb_block = ""
    kb_sources = None
    try:
        kb = await knowledge.retrieve_scoped(
            task or "", spawn_id=spawn_id, used_ref=None, record_usage=False)
        kb_block = knowledge.knowledge_block(kb)
        kb_sources = [src for src, _ in kb] or None
    except Exception:  # noqa: BLE001 — a KB miss must not break a replay pair
        pass
    return {"facts": facts, "kb_block": kb_block, "kb_sources": kb_sources}


# ── run-id collection (evolution cost attribution) ─────────────────────────────────
#
# Replay dispatches are already fully accounted on their Run rows, but nothing said WHICH
# attempt caused which row. The obvious join — (spawn_id, time window) — is wrong here:
# skill_forge.evaluate_candidate calls run_gate for the same spawn, producing replays with
# the same spawn_id AND the same sentinel conversation_id, and it is not covered by the
# watcher's per-spawn concurrency guard. Its spend would be silently absorbed.
#
# So attribution is by IDENTITY: a caller opens a collection and every run_arm on that
# TASK notes its run_id into it. Task-local, mirroring usage_sink.collecting(), so a
# concurrent skill_forge run in another task cannot leak in no matter how they interleave.
_collected_run_ids: ContextVar[list[int] | None] = ContextVar(
    "replay_collected_run_ids", default=None)


@contextmanager
def collect_run_ids():
    """Gather the run_id of every replay dispatched on this task inside the block."""
    bucket: list[int] = []
    token = _collected_run_ids.set(bucket)
    try:
        yield bucket
    finally:
        _collected_run_ids.reset(token)


def _note_run_id(run_id: int) -> None:
    """Record a replay run_id if a collection is active; a free no-op otherwise."""
    bucket = _collected_run_ids.get()
    if bucket is not None:
        bucket.append(run_id)


async def run_arm(db, *, spawn_id: int, task: str, system_prompt: str,
                  ambient: dict, conversation_id: str = REPLAY_CONVERSATION_ID) -> dict:
    """Run ONE replay arm on `task` under the full prompt override `system_prompt`, sharing
    the pre-captured `ambient` with its pair partner. Returns {run_id, output, evidence}.
    `db` is accepted for E4 session symmetry; dispatch manages its own sessions."""
    out = await dispatcher.dispatch(
        conversation_id, spawn_id=spawn_id, task_brief=task,
        system_prompt_override=system_prompt, replay=True, ambient=ambient)
    run_id = out["run_id"]
    _note_run_id(run_id)
    evidence = await trace_evidence.build_evidence(run_id)
    return {"run_id": run_id, "output": out.get("full_output", ""), "evidence": evidence}


async def is_replayable(db, run_id: int) -> bool:
    """True iff every tool_call in the original run used a replay-safe builtin. A run that
    invoked an MCP / side-effecting tool is NOT hermetically replayable → excluded from the
    corpus (the exclusion count/ratio is surfaced on the promotion card, spec §E3/#11)."""
    steps = (await db.execute(
        select(RunStep).where(RunStep.run_id == run_id, RunStep.kind == "tool_call")
    )).scalars().all()
    for s in steps:
        ref = s.ref if isinstance(s.ref, dict) else {}
        tool = ref.get("tool")
        if tool and tool not in REPLAY_SAFE_BUILTINS:
            return False
    return True
