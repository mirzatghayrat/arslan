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

# E1 continuation registry (in-memory until the E2 `runs.continuation` column lands):
# an auto-continue re-dispatch marks its Run here so the judge can score completion
# against THIS round's incremental goal instead of the full original request.
# Process-local by design — a restart loses the marks, which E2 fixes by persisting
# the flag on the Run row. Entries are tiny (one int per run) and never removed
# within a process lifetime so reaper/rescore re-judging still sees them.
_continuation_run_ids: set[int] = set()


def is_continuation(run_id: int) -> bool:
    """True when this run was recorded as an auto-continue (continuation) round."""
    return run_id in _continuation_run_ids


class RunRecorder:
    def __init__(self, run_id: int, started_at: datetime, route_ms: int | None,
                 spawn_name: str | None = None, continuation: bool = False) -> None:
        self.run_id = run_id
        self.started_at = started_at
        self.route_ms = route_ms
        self.spawn_name = spawn_name
        self.continuation = continuation
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
            )
            db.add(run)
            await db.commit()
            await db.refresh(run)
            run_id = run.id
        if continuation:
            _continuation_run_ids.add(run_id)
        return cls(run_id, started, route_ms, spawn_name, continuation)

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
                        injected_kb_sources: list | None = None) -> int:
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
                run.status = "recorded"
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
        try:
            # task_tokens was already read (usage_sink.total()) and persisted above, BEFORE
            # scheduling. The judge task inherits this context's bucket via create_task, but
            # nothing re-reads it for this run, so its tokens never affect task_tokens.
            schedule_scoring(self.run_id)
        except Exception as exc:  # noqa: BLE001 — scoring is best-effort
            logger.warning("schedule_scoring failed (non-fatal): %s", exc)
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
