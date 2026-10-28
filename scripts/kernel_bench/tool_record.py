"""Which tools an entrant called in a run, read from the run's own record (T16, T17; v0.1.64 M64).

- Arslan: `<run>.frames.jsonl`, the driver's transcript of every frame it got. A `tool_call`
  frame's `tool` is the tool's name (server/ws/protocol.py; accept_0152.steps reads it the same
  way). A sub-session's own calls go to its own conversation, not into this transcript.
- Claude Code: its session transcript under the bench HOME,
  `<home>/.claude/projects/*/<session>.jsonl`; the `tool_use` blocks of each assistant entry name
  the tools. Entries marked `isSidechain` (a subagent's own work) are left out.
- Anyone else: None. The bench reads no tool record for them, so the runner records T16 and T17
  as unsupported for them (runner.TOOL_RECORD).

Not yet checked against a real run (M64 made no model calls): the Claude Code transcript's place
and shape (Claude Code 2.1.300, the pinned version), and the name Arslan's sub-session tool will have.
"""

from __future__ import annotations

import json
from pathlib import Path

# The sub-session tool: `start_sub_session` is the name the SUB card proposes (SUB3 fixes it);
# Claude Code's subagent tool is `Task` (renamed `Agent` in later versions).
# DELETE-BY: v0.1.64 when SUB3 merges: put the tool's real name here if it is not start_sub_session.
SUB_SESSION = {
    "arslan": frozenset({"start_sub_session"}),
    "arslan-legacy": frozenset({"start_sub_session"}),
    "claude-code": frozenset({"Task", "Agent"}),
}
# Other ways of handing work off: Arslan's helpers (SUB6 deletes delegate_work in v0.1.64).
DELEGATE = {"arslan": frozenset({"delegate_work"}), "arslan-legacy": frozenset({"delegate_work"})}
READS = frozenset(SUB_SESSION)


def _jsonl(path: Path):
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            yield row


def calls(who: str, run: str, ctx: dict) -> list[str] | None:
    """Tool names in call order; None when there is no record to read (not the same as no calls)."""
    if who in ("arslan", "arslan-legacy"):
        frames = Path(f"{str(run).rstrip('/')}.frames.jsonl")
        if not frames.is_file():
            return None
        return [str(f.get("tool")) for f in _jsonl(frames) if f.get("type") == "tool_call"]
    if who == "claude-code":
        session, home = ctx.get("session"), ctx.get("home")
        found = (
            sorted(Path(home).glob(f".claude/projects/*/{session}.jsonl"))
            if session and home
            else []
        )
        if not found:
            return None
        names = []
        for row in _jsonl(found[0]):
            content = (
                (row.get("message") or {}).get("content")
                if row.get("type") == "assistant"
                else None
            )
            if row.get("isSidechain") or not isinstance(content, list):
                continue
            names += [
                str(b.get("name"))
                for b in content
                if isinstance(b, dict) and b.get("type") == "tool_use"
            ]
        return names
    return None


def sub_sessions(who: str, names: list[str]) -> int:
    return sum(1 for n in names if n in SUB_SESSION.get(who, ()))


def handoffs(who: str, names: list[str]) -> int:
    """Sub-sessions opened plus work delegated any other way."""
    return sub_sessions(who, names) + sum(1 for n in names if n in DELEGATE.get(who, ()))
