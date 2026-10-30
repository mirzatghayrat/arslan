"""What Arslan can do for you, as switches (0.1.55 §14).

One row per thing a person would recognise ("the terminal", "web search", "GitHub"),
in one of three sections (built-in, skills, connections). Each row is in one of four states:

  on     offered to the model now
  off    the user switched it off — not offered
  setup  one step missing (a key, a connection, a helper app); `fix` says which
  na     cannot work here; `reason` says why (not macOS, a runtime missing, …)

The states are read from the SAME gates `_arslan_tools` applies, and every built-in
row names the tool keys it stands for, so a test can hold the two to each other: a
row that says "on" while its tools are absent (or the reverse) is the silent
disappearance this page exists to end.

v0.1.64 CAP3a-1: each row also says its `section` (built-in, skills, connections), its `origin`
(built in; installed by the user or from a card; written by Arslan; a connection added by hand),
whether it can be deleted, and when it was last used (from the run records). Only what the user
installed, Arslan wrote, or the user added by hand can be deleted: `remove` refuses every other
row on the server, not only by the page hiding its button (the CAP card: security surface).
"""
from __future__ import annotations

import re
import sys
from datetime import datetime

from sqlalchemy import func, select

from server.db import session as db_session

DELETABLE = ("installed", "authored", "manual")
# A key the server may delete by: what every skill writer makes (skill_forge, skill_import, the seeder). The key
# names the scripts folder, and `{key:path}` lets "/" through (#499 review F3).
_SKILL_KEY = re.compile(r"[a-z0-9-]+")

# Built-in switches: capability key -> (settings key, default when unset).
SETTING_SWITCHES = {
    "files": "default_read_enabled",
    "terminal": "orchestrator_shell_enabled",
    "lan": "lan_discovery_enabled",
    "ssh": "ssh_enabled",
}


class _Row(dict):
    """A row as the page gets it; `uses` is not in it (#499 second review 4: a key popped before sending
    would leak on any path that skipped the pop)."""
    __slots__ = ("uses",)


def _row(key: str, state: str, *, tools: tuple[str, ...] = (), switch: str | None = None,
         reason: str | None = None, fix: str | None = None, name: str | None = None,
         detail: str | None = None, section: str = "builtin", origin: str = "builtin",
         source_id: str | None = None, uses: tuple[str, ...] | None = None, family: str | None = None,
         removable: bool = True, reach: str | None = None) -> _Row:
    """`uses`: the tools whose calls count as this row's use, whatever its state (default: `tools`); `family`:
    a tool-name prefix whose every call counts too (the browser's, Hands', Shortcuts'). `source_id`: the
    capability source of what was installed from a card (its dossier). `removable`: False when `remove` would
    refuse the row whatever its origin (a skill key that is not a plain key), so the page offers no button.
    `reach`: how a connection is reached (its command and arguments, or its address), which the page's search
    matches too (#500 recheck: "the one I pointed at playwright" is how people find it)."""
    row = _Row(key=key, state=state, tools=list(tools), switch=switch, reason=reason, fix=fix, name=name,
               detail=detail, section=section, origin=origin, deletable=origin in DELETABLE and removable,
               source_id=source_id, reach=reach)
    row.uses = (tools if uses is None else uses, family)
    return row


async def _builtin_rows() -> list[dict]:
    from server.registry import hands_tools
    from server.registry.executors import _search_provider
    from server.services import agent_browser, hands_client, managed_browser, settings_service

    async with db_session.AsyncSessionLocal() as db:
        default_read = await settings_service.default_read_enabled(db)
        workspace = await settings_service.workspace_dir(db)
        shell = await settings_service.shell_enabled(db)
        lan = await settings_service.lan_discovery_enabled(db)
        ssh = await settings_service.ssh_enabled(db)
        from server.services import ssh_nodes
        enrolled = ssh and bool(await ssh_nodes.list_nodes(db))   # C3b: running needs an enrolled machine
    rows: list[dict] = []
    darwin = sys.platform == "darwin"

    # Mac
    # "files" is reading the Desktop, Documents and Downloads (default_read). Arslan's own
    # working folder stays readable and writable either way, so the off row says so
    # rather than claiming file tools vanished.
    file_tools = ("read_file", "list_dir", "search_files", "attach_file") + (("write_file", "edit_file") if workspace else ())
    rows.append(_row("files", "on" if default_read else "off", switch="setting",
                     tools=file_tools if default_read else (),
                     uses=("read_file", "list_dir", "search_files", "attach_file", "write_file", "edit_file"),
                     detail=None if default_read else ("own_folder_only" if workspace is not None else None)))
    rows.append(_row("terminal", "on" if shell else "off", switch="setting",
                     tools=("run_command",) if shell else (), uses=("run_command",)))
    if agent_browser.available():
        rows.append(_row("browser", "on", tools=("browser_open", "browser_look"), family="browser_",
                         detail="first_use_setup" if managed_browser.status()["reason"] == "setup_required" else None))
    else:
        why = managed_browser.status()["reason"]
        rows.append(_row("browser", "na", reason="not_macos" if why == "macos_required" else "runtime_missing",
                         detail="node" if why == "node_required" else None, family="browser_"))
    rows.append(_row("shortcuts", "on", tools=("mac_list_shortcuts",), family="mac_") if darwin
                else _row("shortcuts", "na", reason="not_macos", family="mac_"))
    if not darwin:
        rows.append(_row("hands", "na", reason="not_macos", family="desktop_"))
    elif not hands_client.available():
        rows.append(_row("hands", "setup", reason="hands_missing", fix="open_settings:abilities",
                         family="desktop_"))
    else:
        on = hands_tools.desktop_available()
        rows.append(_row("hands", "on" if on else "off", switch="hands",
                         tools=("desktop_apps", "desktop_look") if on else (), family="desktop_"))

    # Research and making
    resolved = await _search_provider()
    if resolved.provider is None:
        rows.append(_row("web", "setup", reason=resolved.reason, fix="open_settings:connections",
                         tools=("web_extract",), uses=("web_search", "web_extract")))
    else:
        rows.append(_row("web", "on", tools=("web_search", "web_extract")))
    rows.append(_row("charts", "on", tools=("render_chart",)))

    # Work
    rows.append(_row("schedule", "on", tools=("schedule_task", "list_my_tasks", "cancel_task")))
    rows.append(_row("lan", "on" if lan else "off", switch="setting",
                     tools=("scan_local_network",) if lan else (), uses=("scan_local_network",)))
    rows.append(_row("ssh", "on" if ssh else "off", switch="setting",
                     tools=(("ssh_probe", "enroll_node") + (("ssh_run", "list_nodes") if enrolled else ()))
                     if ssh else (), uses=("ssh_probe", "enroll_node", "ssh_run", "list_nodes")))
    return rows


def _runtime_missing(server: dict) -> str | None:
    """The command a stdio server needs, when it cannot be found — not when Arslan runs it on its
    own pinned runtime or can fetch that runtime here (0.1.61 §B1)."""
    from server.mcp import spawn_env
    from server.services import capability_runtime
    command = (server.get("command") or "").strip()
    if server.get("transport") != "stdio" or not command:
        return None
    runtime = spawn_env.runtime_for(command)
    if runtime is not None and (capability_runtime.ready(runtime) or capability_runtime.available()):
        return None
    try:
        spawn_env.resolve_command(command)
    except Exception:  # noqa: BLE001 — any miss is "not found"; the row says which command
        return command
    return None


async def _mcp_rows() -> list[dict]:
    """"on" is the same gate `_arslan_tools` applies to a server's tools: the row says `ready` AND the
    session manager holds a live session for it (`supervisor.ready_now`, 0.1.61 §B1). A `ready` left
    from the last run, or whose session died while its restart waits, is starting by itself — the
    page must not say "on" while the model is offered none of its tools."""
    from server.mcp.supervisor import ready_now
    from server.services import mcp_service
    from server.db.models import MCPServer
    from server.mcp.discovery import runtime_dict
    rows = []
    installed = await _installed_servers()
    async with db_session.AsyncSessionLocal() as db:            # each server's own secrets, to mask `reach`
        runtimes = {srv.id: runtime_dict(srv) for srv in (await db.execute(select(MCPServer))).scalars()}
    # the stored legacy status: "never connected" (registered) and an old error decide the row below;
    # `last_error` comes masked (final review I-2)
    for server in await mcp_service.list_servers(stored_status=True):
        key, name = f"mcp:{server['id']}", server.get("label") or f"MCP {server['id']}"
        # CAP3a-1: installed from a card (its capability source) or added by hand; its use is its tools'
        # calls (`mcp_<id>__…`, see capabilities()).
        where = {"section": "connections", "source_id": installed.get(server["id"]),
                 "reach": _reach(server, runtimes.get(server["id"])),
                 "origin": "installed" if server["id"] in installed else "manual"}
        missing = _runtime_missing(server)
        allowed = bool(server.get("host_allowed"))
        connected = server.get("status") == "connected"
        # starting by itself: the supervisor says so, or the row says it is connected and switched on
        # but nothing live stands behind it (a `ready` with no session; a switched-on `off` whose
        # `starting` write has not landed)
        starting = server.get("state") == "starting" or (
            allowed and connected and not ready_now(server["id"], server.get("state")))
        if missing:
            rows.append(_row(key, "na", reason="runtime_missing", detail=missing, name=name, **where))
        elif not allowed and server.get("state") == "off":
            # switched off reads "off" whatever its old status says (an install whose test failed is
            # left off with `status` error); the old error stays visible as the detail (Task 8 review M-1)
            rows.append(_row(key, "off", name=name, **where, switch="mcp",
                             detail=(server.get("last_error") or "")[:200] or None))
        elif server.get("status") == "error":
            rows.append(_row(key, "setup", reason="mcp_error", fix="open_tab:mcps", name=name, **where,
                             detail=(server.get("last_error") or "")[:200] or None, switch="mcp"))
        elif starting:
            # 0.1.61: starting by itself — no Connect fix to press (ruling 5: no new UI words in PR 4).
            rows.append(_row(key, "setup", reason="not_connected", name=name, **where,
                             switch="mcp"))
        elif not connected:
            rows.append(_row(key, "setup", reason="not_connected", fix="connect", name=name, **where,
                             switch="mcp"))
        else:
            # connected: switched on means ready in this process (`starting` above), else the user's off
            rows.append(_row(key, "on" if allowed else "off", name=name, **where, switch="mcp"))
    return rows


# What `reach` may keep of a connection's arguments (#500 rechecks: an allowlist, not a list of secret shapes): a
# lowercase package spec (`name`, `@scope/name`, `org/name`) whose version, if any, is a number or a dist tag, and
# that is a scoped package or names "mcp" as a word. Every flag goes, and so does the value after it, but for the
# common flags that take none.
_PACKAGE = re.compile(r"(@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*(/[a-z0-9][a-z0-9._-]*)?"
                      r"(@(?:[0-9][0-9a-z.+-]*|latest|next|beta|alpha|canary))?")
_MCP_WORD = re.compile(r"(?<![a-z0-9_])mcp(?![a-z0-9_])")
_NO_VALUE_FLAGS = ("-y", "--yes", "-i", "--rm", "--verbose", "--quiet", "-q")


def _reach(server: dict, runtime: dict | None) -> str:
    """How a connection is reached, for the page's search only (never shown): the command's name, the arguments
    that look like a package, and the address's scheme, host and port (no userinfo, path, query or fragment).
    Nothing else is kept, and what is kept is masked with the server's own secrets, as its last_error is."""
    from pathlib import PurePosixPath
    from urllib.parse import urlsplit

    from server.mcp.supervisor import mask_for
    parts, skip = [PurePosixPath(server.get("command") or "").name], False
    for arg in map(str, server.get("args") or ()):
        if arg.startswith("-"):
            # A flag is never a value: it decides about the next argument itself. One that carries its value
            # ("--port=1", "-HAuthorization: …") or takes none leaves the next alone.
            skip = arg not in _NO_VALUE_FLAGS and "=" not in arg and (arg.startswith("--") or len(arg) == 2)
        elif skip:
            skip = False
        elif _PACKAGE.fullmatch(arg) and ((arg.startswith("@") and "/" in arg) or _MCP_WORD.search(arg)):
            parts.append(arg)
    if server.get("url"):
        try:
            address = urlsplit(server["url"])
            host = f"[{address.hostname}]" if ":" in (address.hostname or "") else address.hostname or ""
            if address.scheme and host:
                parts.append(f"{address.scheme}://{host}{f':{address.port}' if address.port else ''}")
        except ValueError:                                     # a malformed address: nothing of it
            pass
    text = " ".join(part for part in parts if part)
    return mask_for(runtime, text) if runtime else text


async def _installed_servers() -> dict[int, str]:
    """Connections installed from a card: server id -> its capability source. Only a source that is not removed,
    and only the server that was there when it was installed: a scan-blocked install deleted its server and kept
    the number, as every removal did before v0.1.64, and the next server added may get that number
    (mcp_servers.id has no AUTOINCREMENT; #499 second review 1)."""
    from server.db.models import CapabilitySource, MCPServer
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(select(CapabilitySource.mcp_server_id, CapabilitySource.id).join(
            MCPServer, MCPServer.id == CapabilitySource.mcp_server_id).where(
            CapabilitySource.kind == "mcp", CapabilitySource.state != "removed",
            MCPServer.created_at <= CapabilitySource.installed_at))).all()
    return {server_id: source_id for server_id, source_id in rows}


def _skill_origin(pack) -> str:
    """By the marks D7 reads as the user's (seeder._USERS_SKILL): written by Arslan (skill_forge.WRITTEN; a skill
    promoted from Skill Forge before CAP2a got one of those marks in migration 0077, and one the old Discover page
    made, in 0080), installed from a card (`source_id`) or pasted as a link ("imported"). Built in only when
    skill_trust says it is a seed row (SKF1: an allowlist); a row with no mark that is not a seed is "unknown",
    not deletable (D7 would retire it under a retired key). Written first: create_skill takes any plain key."""
    from server.registry import skill_trust
    from server.services import skill_forge
    if pack.category in skill_forge.WRITTEN:
        return "authored"
    if pack.source_id or pack.category == "imported":
        return "installed"
    return "builtin" if skill_trust.reads_as_own(pack) else "unknown"


async def _skill_rows() -> list[dict]:
    from server.db.models import SkillPack
    async with db_session.AsyncSessionLocal() as db:
        packs = (await db.execute(select(SkillPack).where(
            SkillPack.status == "registered", SkillPack.body.is_not(None), func.trim(SkillPack.body) != "",
        ).order_by(SkillPack.key))).scalars().all()
    return [_row(f"skill:{p.key}", "off" if p.enabled is False else "on", switch="skill",
                 name=p.name, detail=p.description[:160] if p.description else None,
                 section="skills", origin=_skill_origin(p), source_id=p.source_id, removable=safe_skill_key(p.key))
            for p in packs]


async def _method_rows() -> list[dict]:
    """The professional methods sit with the skills (v0.1.64 CAP3a; the CAP card, with SUB): built in, never
    switched or deleted here, revised in their editor (`revision`). Named by key while unrevised (the page
    translates it). Last used: the newest helper a task ran with it."""
    from server.db.worker_models import TaskWorker
    from server.services import professional_methods
    async with db_session.AsyncSessionLocal() as db:
        methods = await professional_methods.list_methods(db)
        await db.commit()                          # the defaults, written on first read
        used = dict((await db.execute(select(TaskWorker.method_key, func.max(TaskWorker.created_at))
                                      .group_by(TaskWorker.method_key))).all())
    rows = []
    for m in methods:
        row = _row(f"method:{m['key']}", "on", name=m["name"] if m["revision"] > 1 else None, section="skills")
        row.update(revision=m["revision"], last_used=_when(used.get(m["key"])))
        rows.append(row)
    return rows


# read_skill's key, from the call's stored arguments (`args_summary`: its JSON, cut at 200 characters).
_READ_SKILL_KEY = re.compile(r'"key":\s*"([^"\\]+)"')


async def _last_used() -> tuple[dict[str, datetime], dict[str, datetime]]:
    """When each tool was last called, and each skill last read (read_skill), from the run records: no new
    column (the CAP card). A call that failed counts too: the capability was used."""
    from server.db.models import RunStep
    tool = func.json_extract(RunStep.ref, "$.tool")
    async with db_session.AsyncSessionLocal() as db:
        tools = dict((await db.execute(select(tool, func.max(RunStep.started_at)).where(
            RunStep.kind == "tool_call").group_by(tool))).all())
        reads = (await db.execute(select(RunStep.detail, RunStep.started_at).where(
            RunStep.kind == "tool_call", tool == "read_skill"))).all()
    skills: dict[str, datetime] = {}
    for detail, when in reads:
        found = _READ_SKILL_KEY.search(str((detail or {}).get("args_summary") or ""))
        if found and when and (found[1] not in skills or when > skills[found[1]]):
            skills[found[1]] = when
    return {key: when for key, when in tools.items() if key and when}, skills


def _when(*times) -> str | None:
    latest = max((t for t in times if t), default=None)
    return latest.isoformat() + "Z" if latest else None


async def capabilities() -> list[dict]:
    from server.db.models import MCPServer
    rows = [*await _builtin_rows(), *await _mcp_rows(), *await _skill_rows(), *await _method_rows()]
    tools, skills = await _last_used()
    # When each connection was added. A server id is reused once the newest one is deleted (mcp_servers.id
    # has no AUTOINCREMENT), so a call before that is the old server's (#499 review F5).
    async with db_session.AsyncSessionLocal() as db:
        added = dict((await db.execute(select(MCPServer.id, MCPServer.created_at))).all())
    for row in rows:
        uses, family = row.uses
        if "last_used" in row:                                       # a method row says its own
            continue
        if (server := _server_id(row["key"])) is not None:
            since = added.get(server)
            row["last_used"] = _when(*(when for key, when in tools.items()
                                       if key.startswith(f"mcp_{server}__") and (since is None or when >= since)))
        elif row["key"].startswith("skill:"):
            row["last_used"] = _when(skills.get(row["key"][6:]))
        else:
            row["last_used"] = _when(*(tools.get(key) for key in uses),
                                     *(when for key, when in tools.items() if family and key.startswith(family)))
    return rows


def _server_id(key: str) -> int | None:
    """`mcp:<id>` with ASCII digits only: str.isdigit() also takes "١" (int() reads it as 1) and "²"."""
    tail = key[4:] if key.startswith("mcp:") else ""
    return int(tail) if tail.isascii() and tail.isdigit() else None


def safe_skill_key(key: str | None) -> bool:
    """Whether a stored skill key may name a folder under skill_scripts/ (#499 review F3)."""
    return bool(key and _SKILL_KEY.fullmatch(key))


class NotSwitchable(Exception):
    pass


async def switch(key: str, on: bool) -> None:
    """Turn one row on or off through the switch that already governs it."""
    from server.services import hands_service, mcp_service, settings_service
    if key in SETTING_SWITCHES:
        async with db_session.AsyncSessionLocal() as db:
            await settings_service.update_settings(db, {SETTING_SWITCHES[key]: "true" if on else "false"})
        return
    if key == "hands":
        hands_service.update_settings(enabled=on)
        return
    if (server := _server_id(key)) is not None:
        if not any(s["id"] == server for s in await mcp_service.list_servers()):
            raise NotSwitchable(key)
        await mcp_service.set_host_allowed(server, on)
        return
    if key.startswith("skill:"):
        from server.db.models import SkillPack
        async with db_session.AsyncSessionLocal() as db:
            pack = await db.get(SkillPack, key[6:])
            if pack is None:
                raise NotSwitchable(key)
            pack.enabled = on
            await db.commit()
        return
    raise NotSwitchable(key)


class NotRemovable(Exception):
    pass


class NotFound(Exception):
    pass


async def remove(key: str) -> None:
    """Delete one row the page shows a delete button for (`deletable`), and refuse every other here, on the
    server (the CAP card, security surface): a built-in tool or skill is only switched. A skill goes with its
    capability source marked removed, and its scripts and a copy of its text to the Trash. A connection
    installed from a card goes through capability_install.remove (its folder to the Trash); one added by hand
    through delete_server. A skill key that is not a plain key is refused before anything is read."""
    if key.startswith("skill:") and safe_skill_key(key[6:]):
        return await _remove_skill(key[6:])
    if (server := _server_id(key)) is not None:
        return await _remove_server(server)
    raise NotRemovable(key)


def skill_to_trash(pack) -> None:
    """Move a skill's scripts folder to the Trash with a copy of its text, before its row goes: a failed move
    leaves the skill whole, never a row-less folder the next skill of that key would pick up (#499 review F4),
    and no copy behind. The copy is a SKILL.md skill_import reads again: a skill's text is only in the
    database, and one Arslan wrote is nowhere else (#499 second review 5). Nothing for a key that is not a
    plain key (F3). A folder that is a link is refused: the copy would be written through it, and only the
    link would go to the Trash (#499 recheck 1)."""
    import os

    import yaml

    from server import config
    from server.services import capability_install
    if not safe_skill_key(pack.key):
        return
    folder = config.data_dir() / "skill_scripts" / pack.key
    if folder.is_symlink():
        raise NotRemovable(pack.key)
    made, wrote = not folder.exists(), False
    copy = folder / "SKILL.md"
    head = yaml.safe_dump({"name": pack.name or pack.key, "description": pack.description or ""},
                          allow_unicode=True, sort_keys=False)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        if os.path.lexists(copy):
            copy.unlink()                   # a stray name, a link or another file's second name: only it goes
        _write_new(copy, f"---\n{head}---\n\n{(pack.body or '').strip()}\n")
        wrote = True
        capability_install.to_trash(folder)
    except Exception:
        if wrote:
            copy.unlink(missing_ok=True)
        if made and folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
        raise


def _write_new(path, text: str) -> None:
    """Write a file that did not exist, never through a link (#499 recheck 1)."""
    import os
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(text)


async def _remove_skill(skill_key: str) -> None:
    from server.db.models import CapabilitySource, SkillPack
    async with db_session.AsyncSessionLocal() as db:
        pack = await db.get(SkillPack, skill_key)
        if pack is None:
            raise NotFound(skill_key)
        if _skill_origin(pack) not in DELETABLE:
            raise NotRemovable(skill_key)
    skill_to_trash(pack)
    async with db_session.AsyncSessionLocal() as db:
        pack = await db.get(SkillPack, skill_key)
        source = await db.get(CapabilitySource, pack.source_id) if pack and pack.source_id else None
        if pack is not None:
            await db.delete(pack)
        if source is not None:
            source.state = "removed"
        await db.commit()


async def _remove_server(server_id: int) -> None:
    from server.db.models import MCPServer
    from server.services import capability_install, mcp_service
    async with db_session.AsyncSessionLocal() as db:
        if await db.get(MCPServer, server_id) is None:
            raise NotFound(server_id)
    source_id = (await _installed_servers()).get(server_id)
    if source_id:
        await capability_install.remove(source_id)
    else:
        await mcp_service.delete_server(server_id)
