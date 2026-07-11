"""Records one route→dispatch turn as a Run + ordered RunSteps.

A RunRecorder is created at the top of _dispatch_spawn; its tee() wraps the
EventSink so every emitted event is both forwarded live AND timestamped for
step derivation. finalize() persists steps, links the spawn-summary message,
and schedules async judge scoring.

Note: the escalation re-dispatch path emits its spawn_meta through this same
teed sink before finalize runs, so the dispatch step closes normally; finalize
is called once per turn by the orchestrator.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime

from arslan.llm import usage_sink
from server.db import session as db_session
from server.db.models import ArslanMessage, Run, RunStep

RUN_RAW_CAP = 2000   # per-tool args_full / result_raw truncation cap
RUN_ERR_CAP = 2000   # error_text truncation cap

logger = logging.getLogger(__name__)


def _default_schedule(run_id: int) -> None:
    """Fire-and-forget judge scoring (overridable in tests)."""
    from server.services import run_eval_service

    asyncio.create_task(run_eval_service.score(run_id))


# Module-level indirection so tests can stub scheduling.
schedule_scoring: Callable[[int], None] = _default_schedule

# E2: the `runs.continuation` column is now authoritative — start() persists the flag on the
# Run row and score() reads run.continuation directly (no extra query; the row is already loaded).
# This registry is retained only as a transitional in-memory mirror for any synchronous caller
# of is_continuation() (a run_id can be checked without a DB round-trip). start() keeps it in sync.
_continuation_run_ids: set[int] = set()


def is_continuation(run_id: int) -> bool:
    """True when this run was recorded as an auto-continue (continuation) round.

    Transitional sync shim. The authoritative source is the `runs.continuation` column,
    which score() reads directly; this mirror only exists for sync callers that hold a
    run_id but no DB session.
    """
    return run_id in _continuation_run_ids


class RunRecorder:
    def __init__(self, run_id: int, started_at: datetime, route_ms: int | None,
                 spawn_name: str | None = None, continuation: bool = False,
                 spawn_id: int | None = None) -> None:
        self.run_id = run_id
        self.started_at = started_at
        self.route_ms = route_ms
        self.spawn_name = spawn_name
        self.continuation = continuation
        self.spawn_id = spawn_id
        self._events: list[tuple[datetime, dict]] = []

    @classmethod
    async def start(
        cls,
        *,
        conversation_id: str,
        spawn_id: int | None,
        spawn_name: str | None,
        user_message: str,
        route_ms: int | None = None,
        continuation: bool = False,
        kind: str = "live",
    ) -> "RunRecorder":
        started = datetime.utcnow()
        async with db_session.AsyncSessionLocal() as db:
            run = Run(
                conversation_id=conversation_id,
                spawn_id=spawn_id,
                spawn_name=spawn_name,
                user_message=user_message or "",
                started_at=started,
                status="recording",
                task_tokens=0,
                # E2: this is the live path — quarantine old data via epoch, mark real turns
                # kind='live', and persist the continuation flag on the row (authoritative;
                # score() reads run.continuation directly). E3: kind='replay' marks a hermetic
                # evolution arm — epoch stays 1 but the terminal status ('replayed', set in
                # finalize) keeps it out of every scoring/reaper query.
                kind=kind,
                epoch=1,
                continuation=continuation,
            )
            db.add(run)
            await db.commit()
            await db.refresh(run)
            run_id = run.id
        if continuation:
            _continuation_run_ids.add(run_id)
        return cls(run_id, started, route_ms, spawn_name, continuation, spawn_id)

    def tee(self, emit: Callable[[dict], None]) -> Callable[[dict], None]:
        def _emit(ev: dict) -> None:
            self._events.append((datetime.utcnow(), ev))
            emit(ev)

        return _emit

    def _derive_steps(self, full_output: str) -> list[dict]:
        steps: list[dict] = []
        dispatch_start: datetime | None = None
        pending_tool: tuple[datetime, dict] | None = None
        pending_esc: tuple[datetime, dict] | None = None

        def add(kind, ref, detail, start, end, duration_ms=None):
            ms = duration_ms
            if ms is None:
                ms = int((end - start).total_seconds() * 1000) if start and end else None
            steps.append({
                "seq": len(steps), "kind": kind, "ref": ref, "detail": detail,
                "started_at": start, "ended_at": end, "duration_ms": ms,
            })

        for ts, ev in self._events:
            t = ev.get("type")
            if t == "routing":
                add("route", {"spawn_name": ev.get("spawn_name")}, {},
                    self.started_at, ts, duration_ms=self.route_ms)
            elif t == "stream_start" and ev.get("source") == "spawn":
                dispatch_start = ts
            elif t == "tool_call":
                pending_tool = (ts, ev)
            elif t == "tool_result" and pending_tool is not None:
                call_ts, call_ev = pending_tool
                add("tool_call",
                    {"tool": ev.get("tool"), "ok": bool(ev.get("ok"))},
                    {"args_summary": call_ev.get("args_summary", ""),
                     "summary": ev.get("summary", "")},
                    call_ts, ts)
                pending_tool = None
            elif t == "escalation":
                pending_esc = (ts, ev)
            elif t in ("escalation_resolved", "escalation_refused") and pending_esc is not None:
                esc_ts, esc_ev = pending_esc
                add("escalation",
                    {"kind": esc_ev.get("kind", "data"), "need": esc_ev.get("need", "")},
                    {"how": ev.get("how", ""), "detail": ev.get("detail", ""),
                     "why": ev.get("why", "")},
                    esc_ts, ts)
                pending_esc = None
            elif t == "spawn_meta" and dispatch_start is not None:
                add("dispatch",
                    {"spawn_name": ev.get("spawn_name") or self.spawn_name},
                    {"output_preview": (full_output or "")[:500]},
                    dispatch_start, ts)
                dispatch_start = None

        if pending_tool is not None:
            call_ts, call_ev = pending_tool
            last_ts = self._events[-1][0] if self._events else call_ts
            add("tool_call",
                {"tool": call_ev.get("tool"), "ok": False},
                {"args_summary": call_ev.get("args_summary", ""), "summary": ""},
                call_ts, last_ts)

        if pending_esc is not None:
            esc_ts, esc_ev = pending_esc
            last_ts = self._events[-1][0] if self._events else esc_ts
            add("escalation",
                {"kind": esc_ev.get("kind", "data"), "need": esc_ev.get("need", "")},
                {"how": "no_resolution", "detail": "", "why": ""},
                esc_ts, last_ts)

        # Normal path: finalize runs BEFORE spawn_meta is emitted, so spawn_meta is
        # usually absent here and the dispatch step is closed by the fallback below.
        if dispatch_start is not None:
            last_ts = self._events[-1][0] if self._events else dispatch_start
            add("dispatch", {"spawn_name": self.spawn_name},
                {"output_preview": (full_output or "")[:500]}, dispatch_start, last_ts)

        steps.sort(key=lambda s: (s["started_at"] or self.started_at, s["seq"]))
        for i, s in enumerate(steps):
            s["seq"] = i
        return steps

    async def finalize(self, *, summary_message_id: int | None, full_output: str,
                        model: str | None = None, provider: str | None = None,
                        tokens_in: int | None = None, tokens_out: int | None = None,
                        tokens_estimated: bool = False,
                        error_kind: str | None = None, error_text: str | None = None,
                        system_prompt: str | None = None, injected_kb: str | None = None,
                        injected_kb_sources: list | None = None,
                        replay: bool = False,
                        status_override: str | None = None) -> int:
        """Persist steps + run metadata and (for live runs only) schedule judge scoring.

        replay=True (S2 E3 hermetic replay): terminal status is 'replayed' (never
        'recorded'/'score_failed', so no scoring/reaper query ever matches it),
        kind='replay', the arm's output is stored in final_output for judge-comparison
        and trace, and schedule_scoring is NOT called — a replay is evaluated by the
        paired ReplayGate (E4), not the per-run judge."""
        ended = datetime.utcnow()
        steps = self._derive_steps(full_output)
        self._merge_tool_trace(steps)
        total_ms = int((ended - self.started_at).total_seconds() * 1000)
        tokens = usage_sink.total()
        async with db_session.AsyncSessionLocal() as db:
            run = await db.get(Run, self.run_id)
            if run is not None:
                run.ended_at = ended
                run.total_ms = total_ms
                run.task_tokens = tokens
                # E2: belt-and-suspenders — the live recorder always finalizes a live run at
                # epoch 1 and persists the continuation flag on the row (start() already set
                # them; re-affirm here so no live finalize path can leave the columns unset).
                # E3: a replay run finalizes to the quarantine terminal status + kind and
                # persists its output on the row for judge-comparison/trace.
                # S3-M1: status_override ("cancelled"/"interrupted") is a user/boot terminal
                # state — it bypasses scoring entirely, so such runs can never enter the
                # corpus (replay_set only collects status='scored').
                run.status = status_override or ("replayed" if replay else "recorded")
                run.kind = "replay" if replay else "live"
                run.epoch = 1
                run.continuation = self.continuation
                if replay:
                    run.final_output = full_output
                run.model = model
                run.provider = provider
                run.tokens_in = tokens_in
                run.tokens_out = tokens_out
                run.tokens_estimated = tokens_estimated
                run.error_kind = error_kind
                run.error_text = (error_text[:RUN_ERR_CAP] if error_text else None)
                run.system_prompt = system_prompt
                run.injected_kb = injected_kb
                run.injected_kb_sources = injected_kb_sources
                for s in steps:
                    db.add(RunStep(run_id=self.run_id, **s))
                if summary_message_id is not None:
                    msg = await db.get(ArslanMessage, summary_message_id)
                    if msg is not None:
                        msg.run_id = self.run_id
            await db.commit()
        if replay or status_override is not None:
            return self.run_id  # replay → paired gate; cancelled/interrupted → never scored
        try:
            # task_tokens was already read (usage_sink.total()) and persisted above, BEFORE
            # scheduling. The judge task inherits this context's bucket via create_task, but
            # nothing re-reads it for this run, so its tokens never affect task_tokens.
            schedule_scoring(self.run_id)
        except Exception as exc:  # noqa: BLE001 — scoring is best-effort
            logger.warning("schedule_scoring failed (non-fatal): %s", exc)
        # E5: nudge the evolution watcher that this spawn got fresh activity so a newly
        # eligible spawn doesn't wait for the next 5-min tick. No-op unless the watch loop
        # is running (the loop is the backstop); best-effort + non-blocking.
        try:
            if self.spawn_id is not None:
                from server.services import evolution_watcher

                evolution_watcher.notify_spawn(self.spawn_id)
        except Exception as exc:  # noqa: BLE001 — the ping is never fatal
            logger.warning("evolution notify failed (non-fatal): %s", exc)
        return self.run_id

    def _merge_tool_trace(self, steps: list[dict]) -> None:
        """Fold the per-turn full tool trace (run_trace) into the derived tool_call steps,
        pairing in order. Best-effort: extra/mismatched entries are ignored."""
        from server.orchestrator import run_trace

        trace = run_trace.snapshot()
        it = iter(trace)
        for s in steps:
            if s["kind"] != "tool_call":
                continue
            entry = next(it, None)
            if entry is None:
                continue
            s["detail"] = {**s["detail"], "args_full": entry["args_full"],
                            "result_raw": entry["result_raw"], "error": entry.get("error")}
            s["ref"] = {**s["ref"], "ok": entry["ok"]}
