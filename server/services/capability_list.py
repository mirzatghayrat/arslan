"""What Arslan can do for you, as switches (0.1.55 §14).

One row per thing a person would recognise ("the terminal", "web search", "GitHub"),
grouped by what it does. Each row is in one of four states:

  on     offered to the model now
  off    the user switched it off — not offered
  setup  one step missing (a key, a connection, a helper app); `fix` says which
  na     cannot work here; `reason` says why (not macOS, a runtime missing, …)

The states are read from the SAME gates `_arslan_tools` applies, and every built-in
row names the tool keys it stands for, so a test can hold the two to each other: a
row that says "on" while its tools are absent (or the reverse) is the silent
disappearance this page exists to end.
"""
from __future__ import annotations

import sys

from sqlalchemy import func, select

from server.db import session as db_session

GROUPS = ("mac", "work", "research", "methods")

# Built-in switches: capability key -> (settings key, default when unset).
SETTING_SWITCHES = {
    "files": "default_read_enabled",
    "terminal": "orchestrator_shell_enabled",
    "lan": "lan_discovery_enabled",
    "ssh": "ssh_enabled",
}


def _row(key: str, group: str, state: str, *, tools: tuple[str, ...] = (), switch: str | None = None,
         reason: str | None = None, fix: str | None = None, name: str | None = None,
         detail: str | None = None, source: str = "builtin") -> dict:
    return {"key": key, "group": group, "state": state, "tools": list(tools), "switch": switch,
            "reason": reason, "fix": fix, "name": name, "detail": detail, "source": source}


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
    rows: list[dict] = []
    darwin = sys.platform == "darwin"

    # Mac
    # "files" is reading the Desktop, Documents and Downloads (default_read). Arslan's own
    # working folder stays readable and writable either way, so the off row says so
    # rather than claiming file tools vanished.
    file_tools = ("read_file", "list_dir", "search_files") + (("write_file", "edit_file") if workspace else ())
    rows.append(_row("files", "mac", "on" if default_read else "off", switch="setting",
                     tools=file_tools if default_read else (),
                     detail=None if default_read else ("own_folder_only" if workspace is not None else None)))
    rows.append(_row("terminal", "mac", "on" if shell else "off", switch="setting",
                     tools=("run_command",) if shell else ()))
    if agent_browser.available():
        rows.append(_row("browser", "mac", "on", tools=("browser_open", "browser_look", "browser_back"),
                         detail="first_use_setup" if managed_browser.status()["reason"] == "setup_required" else None))
    else:
        why = managed_browser.status()["reason"]
        rows.append(_row("browser", "mac", "na", reason="not_macos" if why == "macos_required" else "runtime_missing",
                         detail="node" if why == "node_required" else None))
    rows.append(_row("shortcuts", "mac", "on", tools=("mac_list_shortcuts",)) if darwin
                else _row("shortcuts", "mac", "na", reason="not_macos"))
    if not darwin:
        rows.append(_row("hands", "mac", "na", reason="not_macos"))
    elif not hands_client.available():
        rows.append(_row("hands", "mac", "setup", reason="hands_missing", fix="open_settings:abilities"))
    else:
        on = hands_tools.desktop_available()
        rows.append(_row("hands", "mac", "on" if on else "off", switch="hands",
                         tools=("desktop_apps", "desktop_look") if on else ()))

    # Research and making
    resolved = await _search_provider()
    if resolved.provider is None:
        rows.append(_row("web", "research", "setup", reason=resolved.reason, fix="open_settings:connections",
                         tools=("web_extract",)))
    else:
        rows.append(_row("web", "research", "on", tools=("web_search", "web_extract")))
    rows.append(_row("charts", "research", "on", tools=("render_chart",)))

    # Work
    rows.append(_row("schedule", "work", "on", tools=("schedule_task", "list_my_tasks", "cancel_task")))
    rows.append(_row("lan", "work", "on" if lan else "off", switch="setting",
                     tools=("scan_local_network",) if lan else ()))
    rows.append(_row("ssh", "work", "on" if ssh else "off", switch="setting",
                     tools=("ssh_probe", "ssh_run", "list_nodes", "enroll_node") if ssh else ()))
    return rows


def _runtime_missing(server: dict) -> str | None:
    """The command a stdio server needs, when it cannot be found on the user's PATH."""
    from server.mcp.spawn_env import resolve_command
    command = (server.get("command") or "").strip()
    if server.get("transport") != "stdio" or not command:
        return None
    try:
        resolve_command(command)
    except Exception:  # noqa: BLE001 — any miss is "not found"; the row says which command
        return command
    return None


async def _mcp_rows() -> list[dict]:
    from server.services import mcp_service
    rows = []
    for server in await mcp_service.list_servers():
        key, name = f"mcp:{server['id']}", server.get("label") or f"MCP {server['id']}"
        missing = _runtime_missing(server)
        if missing:
            rows.append(_row(key, "work", "na", reason="runtime_missing", detail=missing, name=name, source="mcp"))
        elif server.get("status") == "error":
            rows.append(_row(key, "work", "setup", reason="mcp_error", fix="open_tab:mcps", name=name, source="mcp",
                             detail=(server.get("last_error") or "")[:200] or None, switch="mcp"))
        elif server.get("status") != "connected":
            rows.append(_row(key, "work", "setup", reason="not_connected", fix="connect", name=name, source="mcp",
                             switch="mcp"))
        else:
            rows.append(_row(key, "work", "on" if server.get("host_allowed") else "off", name=name, source="mcp",
                             switch="mcp"))
    return rows


async def _skill_rows() -> list[dict]:
    from server.db.models import SkillPack
    async with db_session.AsyncSessionLocal() as db:
        packs = (await db.execute(select(SkillPack).where(
            SkillPack.status == "registered", SkillPack.body.is_not(None), func.trim(SkillPack.body) != "",
        ).order_by(SkillPack.key))).scalars().all()
    return [_row(f"skill:{p.key}", "methods", "off" if p.enabled is False else "on", switch="skill",
                 name=p.name, detail=p.description[:160] if p.description else None, source="skill")
            for p in packs]


async def capabilities() -> list[dict]:
    return [*await _builtin_rows(), *await _mcp_rows(), *await _skill_rows()]


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
    if key.startswith("mcp:") and key[4:].isdigit():
        if not any(s["id"] == int(key[4:]) for s in await mcp_service.list_servers()):
            raise NotSwitchable(key)
        await mcp_service.set_host_allowed(int(key[4:]), on)
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
