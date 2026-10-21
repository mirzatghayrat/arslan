"""0.1.63 K5: what this Mac is, in two lines, for the turn's reference block (K3's turn context).

- The macOS version, and which of a fixed list of command-line tools are on the user's login PATH.
- The working folder as counts only: folders and files at its top level, and files by type.

It never includes a file or folder name (⓪Plan, K5 plan Q2). Names can be private ("体检报告.pdf"), and
this rides every turn to the model without the user doing anything. When a task needs names the model
calls list_dir, which is a step the user sees.

It's cached per conversation and folder, so every turn of a conversation carries the same bytes. The
counts are as of the conversation's first turn; the folder's current state is a list_dir away.
"""
from __future__ import annotations

import asyncio
import logging
import os
import platform
import re
import shutil
from collections import Counter, OrderedDict
from pathlib import Path

logger = logging.getLogger(__name__)

#: Worth knowing up front; anything else, the model checks with `command -v` (How you work says so).
CLI_TOOLS = ("git", "gh", "python3", "uv", "node", "npm", "brew", "ffmpeg", "pandoc", "jq", "rg", "sqlite3",
             "docker", "curl")
#: File types named in the counts; the rest are summed as "other".
MAX_TYPES = 8
#: A folder with more entries than this is counted up to it, with a "+".
MAX_ENTRIES = 5_000
#: What counts as a file type. A longer "extension" is usually part of a name ("x.health-2026-report").
_TYPE = re.compile(r"[a-z0-9]{1,6}")
_CACHE_SIZE = 128
_cache: OrderedDict[tuple[str, str], str] = OrderedDict()


def _system() -> str:
    version = platform.mac_ver()[0]
    return f"macOS {version}" if version else platform.system()


def folder_counts(root: Path) -> str:
    """Top-level counts of `root`: folders, files, and files by type. Never a name; dot-entries skipped."""
    folders = files = 0
    types: Counter[str] = Counter()
    more = False
    try:
        with os.scandir(root) as entries:
            for seen, entry in enumerate(entries):
                if seen >= MAX_ENTRIES:
                    more = True
                    break
                if entry.name.startswith("."):
                    continue
                try:
                    if entry.is_dir(follow_symlinks=False):
                        folders += 1
                        continue
                except OSError:
                    continue
                files += 1
                kind = Path(entry.name).suffix[1:].lower()
                types[kind if _TYPE.fullmatch(kind) else "other"] += 1
    except OSError:
        return "not readable"
    plus = "+" if more else ""
    counts = f"{folders}{plus} folders, {files}{plus} files"
    named = sorted(((n, kind) for kind, n in types.items() if kind != "other"), key=lambda p: (-p[0], p[1]))
    rest = types.get("other", 0) + sum(n for n, _ in named[MAX_TYPES:])
    parts = [f"{kind} {n}" for n, kind in named[:MAX_TYPES]] + ([f"other {rest}"] if rest else [])
    return f"{counts} (files by type: {', '.join(parts)})" if parts else counts


def describe(workspace: Path | None, *, path: str) -> str:
    """The snapshot's text, starting with a blank line as the other pieces of the turn's block do."""
    from server.orchestrator import agent_status
    tools = [tool for tool in CLI_TOOLS if shutil.which(tool, path=path)]
    lines = [f"This Mac: {_system()}; command-line tools found: {', '.join(tools) or 'none of the usual ones'}."]
    if workspace is not None:
        lines.append(f"Working folder {agent_status.home_relative(workspace)}: {folder_counts(workspace)}.")
    return "\n\n" + "\n".join(lines)


async def _workspace() -> Path | None:
    from server.db import session as db_session
    from server.services import settings_service
    async with db_session.AsyncSessionLocal() as db:
        return await settings_service.workspace_dir(db)


async def for_turn(conversation_id: str | None) -> str:
    """The snapshot for this conversation's turn: cached, so every turn carries the same bytes. "" when it
    can't be built: it's context, and never fails a turn."""
    try:
        workspace = await _workspace()
        key = (conversation_id or "", str(workspace))
        if conversation_id and key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
        from server.mcp.spawn_env import merged_path
        text = await asyncio.to_thread(lambda: describe(workspace, path=merged_path()))
    except Exception:  # noqa: BLE001 — the snapshot is context: without it the turn goes on
        logger.warning("environment snapshot not built", exc_info=True)
        return ""
    if conversation_id:
        _cache[key] = text
        while len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)
    return text
