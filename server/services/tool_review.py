"""What the iPhone's quick review shows of one tool call (mobile bridge §5.3 run.result).

Recorded with the run's steps (RunStep.detail["review"]) at the moment the tool
finishes, because that is the only place that sees both the full arguments and the
result: an edit's old and new text, a command's exit code and output. Bounded on
purpose — a few kilobytes per step — so a finished task can be reviewed from the
phone later without re-running anything, and the run table does not grow with
whole files (a written file's bytes are already kept as a run artifact).

Never sent to a window: the frame builders rebuild tool_call/tool_result from named
fields only, so this key stays between the tool loop and the run recorder.
"""
from __future__ import annotations

import re

SNIPPET_CHARS = 6000        # an edit's old / new text, each
HEAD_CHARS = 2400           # the start of a newly written file
TAIL_LINES = 60             # a command's output: the last lines
TAIL_CHARS = 6000
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")


def _text(value, limit: int) -> str:
    text = value if isinstance(value, str) else ""
    return text if len(text) <= limit else text[:limit] + "\n…"


def _tail(text: str) -> list[str]:
    clean = _ANSI.sub("", text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = clean.rstrip("\n").split("\n") if clean.strip() else []
    lines = lines[-TAIL_LINES:]
    while sum(len(line) + 1 for line in lines) > TAIL_CHARS and len(lines) > 1:
        lines.pop(0)
    return [line[:400] for line in lines]


def capture(tool: str, args: dict, result: dict) -> dict | None:
    """The review record for one finished tool call, or None for tools with nothing to show."""
    args = args if isinstance(args, dict) else {}
    result = result if isinstance(result, dict) else {}
    path = str(args.get("path") or "")[:500]
    if tool == "edit_file":
        return {"kind": "edit", "path": str(result.get("path") or path)[:500],
                "old": _text(args.get("old"), SNIPPET_CHARS), "new": _text(args.get("new"), SNIPPET_CHARS)}
    if tool == "write_file":
        content = args.get("content") if isinstance(args.get("content"), str) else ""
        artifact = result.get("artifact") if isinstance(result.get("artifact"), dict) else {}
        return {"kind": "write", "path": str(result.get("path") or path)[:500], "bytes": len(content.encode("utf-8")),
                "head": _text(content, HEAD_CHARS), "file_id": artifact.get("filename")}
    if tool == "run_command":
        from server.services import terminal_policy
        output = "\n".join(part for part in (result.get("stdout"), result.get("stderr")) if isinstance(part, str) and part)
        exit_code = result.get("exit_code")
        return {"kind": "command", "command": terminal_policy.as_shell(args.get("command"), args.get("argv"))[:1000],
                "exit": exit_code if isinstance(exit_code, int) else None, "lines": _tail(output)}
    if tool in ("web_extract", "browser_open"):
        return {"kind": "web", "url": str(args.get("url") or "")[:500]}
    if tool == "web_search":
        return {"kind": "search", "query": str(args.get("query") or args.get("q") or "")[:300]}
    if tool in ("read_file", "list_dir"):
        return {"kind": "read", "path": path}
    return None
