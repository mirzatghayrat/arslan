"""<agent_status>: what the host knows right now, at the end of every request (0.1.50 P2 S1).

Rules in a system prompt fade over a long task; a short block of CURRENT,
concrete facts at the very end of the context is what steers the next step
(the book's experiments; Claude Code's system reminders and Codex's plan echo
work the same way). So, per request:

- facts only: the writable workspace, files saved this turn, the model's own
  plan, work done so far, and the step notes that used to be appended to the
  system prompt (forced step, wrap-up, research scope, compaction);
- rendered for this request and never stored: history does not pile up stale
  copies, the next step gets a fresh one;
- the system prompt stays byte-identical for the whole turn, so the provider's
  prefix cache holds (before 0.1.50 a note appended mid-turn changed the system
  prompt and invalidated the whole cached prefix from then on);
- appended to the LAST message already in the request (the user turn or the
  newest tool result), never sent as a new user message. DeepSeek's thinking
  template drops the reasoning of assistant messages that come before the
  latest user message, so a status user turn on every step would discard the
  in-turn reasoning the native protocol passes back. (The S10 probe only showed
  that the API accepts such shapes, not what the template keeps.)
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

OPEN = '<agent_status note="host facts for this step, not from the user">'
CLOSE = "</agent_status>"
MAX_SAVED = 10
_WRITERS = ("write_file", "edit_file", "run_command")
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".cache"}


def home_relative(path: Path | str) -> str:
    """`~/Arslan` rather than `/Users/<name>/Arslan`: the account name is not
    needed to write a file, so it does not go to the model provider."""
    p, home = str(path), str(Path.home())
    return "~" + p[len(home):] if p == home or p.startswith(home + os.sep) else p


def saved_by_tools(tool_trace: list[dict]) -> list[str]:
    """Workspace-relative paths written by write_file/edit_file this turn, oldest first."""
    seen: list[str] = []
    for item in tool_trace:
        result = item.get("result") or {}
        if item.get("tool") in ("write_file", "edit_file") and result.get("ok") is True:
            path = result.get("path")
            if isinstance(path, str) and path:
                if path in seen:
                    seen.remove(path)
                seen.append(path)
    return seen


def recent_files(root: Path, since: float, *, max_entries: int = 4000, max_depth: int = 3) -> list[str]:
    """Files under `root` modified at/after `since` (covers run_command saves).
    Bounded: a big chosen workspace (a repo) must not turn every step into a
    full walk. Hidden and dependency folders are skipped. Newest last."""
    found: list[tuple[float, str]] = []
    budget = max_entries
    stack = [(root, 0)]
    while stack and budget > 0:
        folder, depth = stack.pop()
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for entry in entries:
            budget -= 1
            if budget <= 0:
                break
            if entry.name.startswith("."):
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    if depth + 1 < max_depth and entry.name not in _SKIP_DIRS:
                        stack.append((Path(entry.path), depth + 1))
                elif entry.is_file(follow_symlinks=False):
                    mtime = entry.stat(follow_symlinks=False).st_mtime
                    if mtime >= since:
                        found.append((mtime, os.path.relpath(entry.path, root)))
            except OSError:
                continue
    return [rel for _, rel in sorted(found)]


def owned_outputs(tool_trace: list[dict], root: Path | None, since: float) -> list[str]:
    """What this turn saved: write tool results, plus files a successful
    run_command left in the workspace. The newest MAX_SAVED, oldest first."""
    names = saved_by_tools(tool_trace)
    ran_command = any(item.get("tool") == "run_command" and (item.get("result") or {}).get("ok")
                      for item in tool_trace)
    if root is not None and ran_command:
        names += [n for n in recent_files(root, since) if n not in names]
    return names[-MAX_SAVED:]


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" + ("" if n == 1 else "s")


def render(*, workspace: str | None, writers: list[str], own_folder: bool, saved: list[str],
           plan: str, tool_calls: int, model_calls: int, wrap_up_at: int | None,
           notes: list[str]) -> str:
    """The block, or "" when there is nothing to say."""
    lines: list[str] = []
    if workspace and writers:
        tools = ", ".join(w for w in _WRITERS if w in writers)
        lines.append(f"Workspace: {workspace} — " + (
            f"your own folder: create and edit files here without asking ({tools})." if own_folder else
            f"you can create and edit files here ({tools}); the user approves writes once per session."))
    if saved:
        lines.append("Saved this turn: " + ", ".join(saved))
    if plan:
        lines.append(f"Plan (your list): {plan}")
    if tool_calls or model_calls:
        limit = f" (wrap-up at {wrap_up_at})" if wrap_up_at else ""
        lines.append(f"Work so far: {_count(tool_calls, 'tool call')}{limit}, {_count(model_calls, 'model call')}.")
    lines += [note.strip() for note in notes if note and note.strip()]
    return f"{OPEN}\n" + "\n".join(lines) + f"\n{CLOSE}" if lines else ""


def attach(messages: list[dict], status: str) -> list[dict]:
    """A copy of `messages` with `status` at the end of the last message.

    Never mutates the caller's dicts (the trajectory keeps no status). Text
    content gets the block appended; a multimodal user turn (a list of parts)
    gets one more text part. Only a last message with neither (never produced
    by run_native) falls back to a separate user message."""
    if not status or not messages:
        return messages
    last = messages[-1]
    content = last.get("content")
    if isinstance(content, str):
        return [*messages[:-1], {**last, "content": f"{content}\n\n{status}" if content else status}]
    if isinstance(content, list):
        return [*messages[:-1], {**last, "content": [*content, {"type": "text", "text": status}]}]
    return [*messages, {"role": "user", "content": status}]


def now() -> float:
    return time.time()


_ECHO = re.compile(r"<agent_status\b[^>]*>.*?</agent_status>\s*", re.S)


def strip_echo(text: str) -> str:
    """A model that copies the block into its reply must not show the user host
    bookkeeping; the rest of the reply is kept."""
    return _ECHO.sub("", text).strip() if text and "<agent_status" in text else text
