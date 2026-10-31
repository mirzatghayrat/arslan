"""Per-turn full tool-call trace via a contextvar (mirrors usage_sink). Populated by the
tool loop, drained by RunRecorder.finalize into RunStep.detail — kept OUT of the WS stream
so full args/raw results never bloat client traffic."""
from __future__ import annotations

import json
from contextlib import contextmanager
from contextvars import ContextVar

from server.services.run_recorder import RUN_RAW_CAP

_trace: ContextVar[list[dict] | None] = ContextVar("run_trace", default=None)
# SBX-7: a sandbox denial of the command being run, waiting for that call's entry. A dict, so a note made in a
# task the call awaits (asyncio.wait_for copies the context) still reaches it.
_denial: ContextVar[dict | None] = ContextVar("run_denial", default=None)
DENIAL_CODES = frozenset({"eperm"})        # what SBX-3 detects so far; more after SBX-M
_prompt: ContextVar[dict | None] = ContextVar("run_prompt", default=None)
# v0.1.64 INB2: whether the run's turns took in anything off the "about you" allowlist (untrusted.known_local,
# #475 F2); None until a turn of the run ends.
_outside: ContextVar[dict | None] = ContextVar("run_outside", default=None)


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
    entry = {
        "tool": tool,
        "args_full": _cap(args_full),
        "result_raw": _cap(result_str),
        "ok": bool(ok),
        "error": (_cap(error) if error else None),
        "ms": ms,
    }
    # INB6: the files a read read, whole. result_raw is cut at RUN_RAW_CAP, which loses most of a search's matches.
    if isinstance(result, dict) and result.get("ok") and tool in ("read_file", "search_files"):
        found = [result.get("path")] if tool == "read_file" else [m.get("path") for m in result.get("matches") or ()]
        paths = list(dict.fromkeys(path for path in found if path))
        if paths:
            entry["paths"] = paths
    held = _denial.get()
    denial = held.pop("code", None) if held is not None else None
    if denial and tool == "run_command":
        entry["denial"] = denial                     # SBX-7: kept whole however long the output result_raw cuts
    buf.append(entry)


def note_denial(code: str) -> None:
    """SBX-7: the sandbox stopped the command being run. The code goes on that call's entry, and from there on
    the run step's `ref`. It never goes on the result, which the model and every other payload read (card
    §"The two numbers"). Kept when an approved re-run outside replaces the result."""
    held = _denial.get()
    if held is not None and code in DENIAL_CODES:
        held["code"] = code


def snapshot() -> list[dict]:
    return list(_trace.get() or [])


def extend(entries: list[dict]) -> None:
    """K9a: a call that ran next to others recorded into a list of its own; its entries join the turn's
    trace in the reply's order (parallel_reads.Batch.take)."""
    buf = _trace.get()
    if buf is not None:
        buf.extend(entries)


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


def record_outside(seen: bool) -> None:
    """A turn of this run ended (tool_loop.run_native): whether it took in anything off INB2's allowlist.
    Any turn that did makes the run's record yes."""
    holder = _outside.get()
    if holder is not None:
        holder["seen"] = bool(holder["seen"]) or bool(seen)


def outside() -> bool | None:
    """The run's record for `runs.read_outside`; None when no turn of the run ended (counts as yes)."""
    holder = _outside.get()
    return None if holder is None else holder["seen"]


@contextmanager
def collecting():
    buf: list[dict] = []
    prompt_bucket = {"system_prompt": None, "injected_kb": None, "injected_kb_sources": None}
    token = _trace.set(buf)
    ptoken = _prompt.set(prompt_bucket)
    otoken = _outside.set({"seen": None})
    dtoken = _denial.set({})
    try:
        yield buf
    finally:
        _trace.reset(token)
        _prompt.reset(ptoken)
        _outside.reset(otoken)
        _denial.reset(dtoken)
