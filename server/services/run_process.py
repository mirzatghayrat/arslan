"""What a reply did, folded and in plain words (0.1.58 §1).

Two views of one recorded Run, both built from what is already stored — the Run row and
its tool_call RunSteps (whose detail carries args_full / result_raw from run_trace, and
the narration Arslan said before the call):

* ``summary`` — the footer row under a reply: how many steps, how many did not work,
  how long, which model, what it used. Rides on every history row, so a reloaded
  conversation shows the same row as a live one.
* ``entries`` — the list that opens under it: narration and steps in order, each step
  with the few things a person wants to see (the query and the links, the file, the
  command and its first lines). Raw input/output is included only when the user turned
  on 设置 › 通用 › 显示技术细节; otherwise it is not sent at all.

The client draws the words (i18n); this module returns data, never sentences.
"""
from __future__ import annotations

import json
from typing import Any

#: Starting, checking and stopping background work is shown by the job card itself, so a
#: successful one is not a step of the reply (web/src/stores/arslanStore.ts JOB_TOOLS —
#: the guard test test_run_process.py keeps the two lists equal).
JOB_TOOLS = frozenset({"start_background_work", "background_status", "stop_background_work"})

LINK_LIMIT = 5          # web_search links shown
HEAD_LINES = 5          # command / script output lines shown (Codex: 5 + "+N lines")
TEXT_CAP = 600          # any one shown value
ARGS_SHOWN = 6          # key/value rows for a tool without its own view


def _load(raw: Any) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None          # capped at RUN_RAW_CAP mid-value: not parseable, fall back


def _short(value: Any, cap: int = TEXT_CAP) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    text = " ".join(text.split()) if "\n" not in text else text
    return text if len(text) <= cap else text[:cap] + "…"


def _head(text: Any) -> dict:
    lines = [ln for ln in str(text or "").splitlines()]
    while lines and not lines[-1].strip():
        lines.pop()
    return {"lines": [_short(ln, 300) for ln in lines[:HEAD_LINES]], "more": max(0, len(lines) - HEAD_LINES)}


def _args(step_detail: dict) -> dict:
    args = _load(step_detail.get("args_full"))
    if not isinstance(args, dict):
        args = _load(step_detail.get("args_summary"))
    return args if isinstance(args, dict) else {}


def _result(step_detail: dict) -> dict:
    result = _load(step_detail.get("result_raw"))
    return result if isinstance(result, dict) else {}


def _kv(args: dict) -> list[list[str]]:
    return [[str(k), _short(v, 200)] for k, v in list(args.items())[:ARGS_SHOWN]]


def plain(tool: str, args: dict, result: dict, *, ok: bool, summary: str = "") -> dict:
    """The step's own view: a `view` name the client knows how to draw, plus its data."""
    error = _short(result.get("error") or (summary if not ok else ""), 300) if not ok else None
    out: dict[str, Any]
    if tool == "web_search":
        links = [{"title": _short(r.get("title") or r.get("url") or "", 160), "url": r.get("url") or ""}
                 for r in (result.get("results") or []) if isinstance(r, dict) and r.get("url")][:LINK_LIMIT]
        out = {"view": "search", "query": _short(args.get("query") or "", 200),
               "count": len(result.get("results") or []), "links": links, "provider": result.get("provider")}
    elif tool == "web_extract":
        out = {"view": "page", "url": result.get("url") or args.get("url") or "",
               "title": _short(result.get("title") or "", 200), "chars": len(result.get("text") or "")}
    elif tool in ("read_file", "list_dir"):
        out = {"view": "file", "path": result.get("path") or args.get("path") or "",
               "entries": len(result.get("entries") or []) if tool == "list_dir" else None,
               "chars": len(result.get("content") or "") if tool == "read_file" else None}
    elif tool == "write_file":
        out = {"view": "write", "path": result.get("path") or args.get("path") or "", "bytes": result.get("bytes"),
               "artifact": result.get("artifact")}
    elif tool == "edit_file":
        out = {"view": "edit", "path": result.get("path") or args.get("path") or "",
               "old": _short(args.get("old") or "", TEXT_CAP), "new": _short(args.get("new") or "", TEXT_CAP),
               "artifact": result.get("artifact")}
    elif tool == "search_files":
        out = {"view": "find", "query": _short(args.get("query") or "", 200), "count": len(result.get("matches") or [])}
    elif tool in ("run_command", "ssh_run"):
        output = "\n".join(x for x in (result.get("stdout"), result.get("stderr"), result.get("output")) if x)
        out = {"view": "command", "command": _short(args.get("command") or "", TEXT_CAP),
               "exit_code": result.get("exit_code"), "head": _head(output)}
    elif tool == "run_python":
        out = {"view": "code", "head": _head(result.get("stdout") or result.get("output") or ""),
               "files": [a.get("title") or a.get("filename") for a in (result.get("artifacts") or []) if isinstance(a, dict)]}
    elif tool == "whats_new":
        out = {"view": "release", "version": result.get("version"),
               "releases": [r.get("version") for r in (result.get("releases") or []) if isinstance(r, dict)][:5]}
    elif tool in ("recall", "conversation_search"):
        out = {"view": "recall", "query": _short(args.get("query") or "", 200),
               "count": result.get("count") if isinstance(result.get("count"), int) else len(result.get("hits") or result.get("results") or [])}
    elif tool.startswith("mcp_"):
        out = {"view": "mcp", "args": _kv(args), "head": _head(_mcp_text(result))}
    else:
        out = {"view": "generic", "args": _kv(args), "head": _head(_generic_text(result, summary))}
    out["error"] = error
    return out


def _mcp_text(result: dict) -> str:
    content = result.get("content")
    if isinstance(content, list):
        parts = [c.get("text") for c in content if isinstance(c, dict) and isinstance(c.get("text"), str)]
        if parts:
            return "\n".join(parts)
    for key in ("text", "result", "summary"):
        if isinstance(result.get(key), str):
            return result[key]
    return ""


def _generic_text(result: dict, summary: str) -> str:
    for key in ("summary", "text", "body"):
        if isinstance(result.get(key), str) and result[key].strip():
            return result[key]
    return summary if summary and summary != "ok" else ""


def counts(tool_steps: list[tuple[str | None, bool]]) -> tuple[int, int]:
    """(steps, failed) as the footer shows them: a successful job tool is not a step."""
    shown = [(t, ok) for t, ok in tool_steps if not (t in JOB_TOOLS and ok)]
    return len(shown), sum(1 for _, ok in shown if not ok)


def entries(steps: list, *, raw: bool) -> list[dict]:
    """The opened list: narration and steps in order (RunStep rows of kind tool_call)."""
    out: list[dict] = []
    for s in steps:
        if s.kind != "tool_call":
            continue
        ref, detail = s.ref or {}, s.detail or {}
        tool, ok = ref.get("tool") or "", bool(ref.get("ok"))
        if tool in JOB_TOOLS and ok:
            continue
        if detail.get("narration"):
            out.append({"kind": "note", "text": detail["narration"]})
        entry = {"kind": "tool", "tool": tool, "ok": ok, "ms": s.duration_ms,
                 "args_summary": detail.get("args_summary") or "", "summary": detail.get("summary") or "",
                 "detail": plain(tool, _args(detail), _result(detail), ok=ok, summary=detail.get("summary") or "")}
        if raw:
            entry["raw"] = {"args": detail.get("args_full") or detail.get("args_summary") or "",
                            "result": detail.get("result_raw") or detail.get("summary") or ""}
        out.append(entry)
    return out


async def summaries(db, run_ids: list[int]) -> dict[int, dict]:
    """The footer row for each run, in one pass (history rows)."""
    from sqlalchemy import select
    from server.api.usage import item_usd
    from server.db.models import Run, RunStep
    ids = [i for i in {*run_ids} if isinstance(i, int)]
    if not ids:
        return {}
    runs = {r.id: r for r in (await db.execute(select(Run).where(Run.id.in_(ids)))).scalars()}
    per: dict[int, list[tuple[str | None, bool]]] = {}
    for run_id, ref in (await db.execute(select(RunStep.run_id, RunStep.ref).where(
            RunStep.run_id.in_(ids), RunStep.kind == "tool_call").order_by(RunStep.run_id, RunStep.seq))).all():
        per.setdefault(run_id, []).append(((ref or {}).get("tool"), bool((ref or {}).get("ok"))))
    out: dict[int, dict] = {}
    for run_id, run in runs.items():
        steps, failed = counts(per.get(run_id, []))
        usd = item_usd(run.model, run.tokens_in, run.tokens_out, bool(run.tokens_estimated), run.provider)
        out[run_id] = {
            "steps": steps, "failed": failed, "ms": run.total_ms,
            "usage": {"tokens_in": run.tokens_in, "tokens_out": run.tokens_out, "tokens_total": run.task_tokens or 0,
                      "estimated": bool(run.tokens_estimated), "usd": usd,
                      "models": [{"model": run.model, "provider": run.provider}] if run.model else []},
        }
    return out
