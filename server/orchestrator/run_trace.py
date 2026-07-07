"""Per-turn full tool-call trace via a contextvar (mirrors usage_sink). Populated by the
tool loop, drained by RunRecorder.finalize into RunStep.detail — kept OUT of the WS stream
so full args/raw results never bloat client traffic."""
from __future__ import annotations

import json
from contextlib import contextmanager
from contextvars import ContextVar

from server.services.run_recorder import RUN_RAW_CAP

_trace: ContextVar[list[dict] | None] = ContextVar("run_trace", default=None)
_prompt: ContextVar[dict | None] = ContextVar("run_prompt", default=None)


def _cap(s: str) -> str:
    return s if len(s) <= RUN_RAW_CAP else s[:RUN_RAW_CAP]


def record(*, tool: str, args, result, ok: bool, error: str | None, ms: int | None) -> None:
    buf = _trace.get()
    if buf is None:
        return
    try:
        args_full = json.dumps(args, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        args_full = str(args)
    result_str = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
    buf.append({
        "tool": tool,
        "args_full": _cap(args_full),
        "result_raw": _cap(result_str),
        "ok": bool(ok),
        "error": (_cap(error) if error else None),
        "ms": ms,
    })


def snapshot() -> list[dict]:
    return list(_trace.get() or [])


def record_prompt(*, system_prompt: str | None, injected_kb: str | None = None,
                   injected_kb_sources: list | None = None) -> None:
    d = _prompt.get()
    if d is None:
        return
    d["system_prompt"] = system_prompt
    d["injected_kb"] = injected_kb
    d["injected_kb_sources"] = injected_kb_sources


def prompt() -> dict:
    d = _prompt.get()
    return dict(d) if d else {"system_prompt": None, "injected_kb": None, "injected_kb_sources": None}


@contextmanager
def collecting():
    buf: list[dict] = []
    prompt_bucket = {"system_prompt": None, "injected_kb": None, "injected_kb_sources": None}
    token = _trace.set(buf)
    ptoken = _prompt.set(prompt_bucket)
    try:
        yield buf
    finally:
        _trace.reset(token)
        _prompt.reset(ptoken)
