"""CAP8-2's plugin follow-up: plugins on the import sheet, with the user's hook rule.

The rule (the user's, 2026-11-10): a hook is judged by its event's name only, never by what it runs. A plugin whose
hooks all fire on one of the 16 events that can't block or stop anything comes in, with its hooks never registered or
run; any other event, or one not recognised, refuses the whole plugin and leaves nothing. No hook config reaches
`~/.agents/skills` (a skill's frontmatter hooks are stripped: Arslan writes a SKILL.md of its own, name and description
only). An update that adds a blocking hook switches the plugin off, and only its card brings it back. Only hooks are
loosened: commands, agents, language servers and unknown parts still refuse the plugin.

Also: three items of #809's review (a file over the size cap refused instead of cut, MAX_ITEMS caps what is read, the
parse and scan off the event loop). On a scratch HOME and data folder, with fake Claude Code folders.
"""
import asyncio
import json
import os
import subprocess
import threading
from pathlib import Path

import pytest
import yaml
from sqlalchemy import select

from server.db import session as db_session
from server.db.models import CapabilitySource, SkillPack
from server.services import agent_skills, plugin_package, skill_import, tool_import
from tests.server.test_cap8_2_import_skills_plugins import (PLUGIN_FILES, SKILL_MD, URL, _all, _pack, _plugin, _row,
                                                            _scan, _skill, _tick, _write, api, home, offline)

pytestmark = pytest.mark.asyncio
__all__ = ["api", "home", "offline"]           # fixtures, used by name

QUIET = ["SessionStart", "Setup", "PermissionDenied", "PostToolUse", "PostToolUseFailure", "Notification",
         "MessageDisplay", "SubagentStart", "StopFailure", "InstructionsLoaded", "CwdChanged", "DirectoryAdded",
         "FileChanged", "PostCompact", "PostModelSwitch", "SessionEnd"]
CONNECTION = {".mcp.json": json.dumps({"mcpServers": {"tools": {"command": "npx", "args": ["-y", "markdown-tools"]}}})}


def _hooks(*events: str, command: str = "echo hi") -> str:
    """A hooks.json as Claude Code reads it: the event map under a top-level `hooks`."""
    return json.dumps({"description": "x", "hooks": {event: [{"matcher": "*", "hooks": [
        {"type": "command", "command": command}]}] for event in events}})


def _frontmatter_skill(name: str, event: str, command: str = "echo hi") -> str:
    return (f"---\nname: {name}\ndescription: Writes release notes.\nhooks:\n  {event}:\n    - matcher: \"*\"\n"
            f"      hooks:\n        - type: command\n          command: \"{command}\"\n---\n\nCollect the changes.\n")


def _files_under(*bases: Path) -> dict[str, bytes]:
    return {str(p): p.read_bytes() for base in bases if base.exists() for p in sorted(base.rglob("*")) if p.is_file()}


async def _post(api, *, plugins=(), skills=()) -> dict:
    response = await api.post(URL, json={"servers": [], "skills": list(skills), "plugins": list(plugins)})
    assert response.status_code == 200, response.text
    return {result["id"]: result for result in response.json()["results"]}


async def _install(api, home, files=None, **where) -> dict:
    """Through the sheet's route: the card first, then a yes to exactly it."""
    _plugin(home, files, **where)
    row = _row(await _scan(api), "plugins", "release-kit")
    card = (await _post(api, plugins=[_tick(row)]))[row["id"]]
    assert card["state"] == "card", card
    done = (await _post(api, plugins=[_tick(row, card=card["card_digest"])]))[row["id"]]
    assert done["state"] == "on", done
    return card


# ── the rule: by event name only ────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("event", QUIET)
async def test_a_hook_on_each_of_the_16_quiet_events_may_come_in(api, home, event):
    _plugin(home, {**PLUGIN_FILES, "hooks/hooks.json": _hooks(event)})
    row = _row(await _scan(api), "plugins", "release-kit")
    assert row["refused"] is None and row["hooks"] == [event]


@pytest.mark.parametrize("where", ["hooks.json", "manifest path", "manifest inline", "a skill's frontmatter"])
@pytest.mark.parametrize("event", ["PreToolUse", "Stop", "UserPromptSubmit", "PermissionRequest", "SubagentStop"])
async def test_a_blocking_hook_is_refused_and_leaves_no_files(api, home, offline, tmp_path, event, where):
    files = {**PLUGIN_FILES, **CONNECTION}
    manifest = {"name": "release-kit", "version": "1.0.0", "description": "Release notes"}
    if where == "hooks.json":
        files["hooks/hooks.json"] = _hooks("SessionStart", event)
    elif where == "manifest path":
        files["config/more.json"] = _hooks(event)
        files[".claude-plugin/plugin.json"] = json.dumps({**manifest, "hooks": "./config/more.json"})
    elif where == "manifest inline":
        files[".claude-plugin/plugin.json"] = json.dumps({**manifest, "hooks": [{event: [{"hooks": [
            {"type": "command", "command": "echo hi"}]}]}]})
    else:
        files["skills/release-notes/SKILL.md"] = _frontmatter_skill("release-notes", event)
    _plugin(home, files)
    row = _row(await _scan(api), "plugins", "release-kit")
    assert row["refused"] == "hooks" and row["refused_part"] == event and row["tick"] is False
    before = _files_under(tmp_path / "data")
    result = (await _post(api, plugins=[_tick(row)]))[row["id"]]
    assert result["state"] == "refused" and result["code"] == "hooks"
    # A digest from anywhere changes nothing: the rule is the server's.
    assert (await _post(api, plugins=[_tick(row, card="0" * 64)]))[row["id"]]["state"] == "refused"
    assert offline == []                                # refused before any connection was locked
    assert not (home / ".agents").exists() and not (home / ".Trash").exists()
    assert _files_under(tmp_path / "data") == before
    assert await _all(CapabilitySource) == [] and await _all(SkillPack) == []


@pytest.mark.parametrize("event", ["FutureEvent", "sessionstart", "SessionStart ", "", "TaskCreated"])
async def test_an_unknown_event_is_refused(api, home, offline, event):
    _plugin(home, {**PLUGIN_FILES, "hooks/hooks.json": _hooks("PostToolUse", event)})
    row = _row(await _scan(api), "plugins", "release-kit")
    assert row["refused"] == "hooks" and row["tick"] is False
    assert (await _post(api, plugins=[_tick(row)]))[row["id"]]["state"] == "refused"
    assert await _all(CapabilitySource) == []


@pytest.mark.parametrize("text", ["[]", "{\"hooks\": []}", "{\"hooks\": {\"PostToolUse\": {}}}",
                                  "{\"hooks\": {\"PostToolUse\": [{\"hooks\": \"x\"}]}}", "not json"])
async def test_a_hooks_file_that_cant_be_read_refuses_the_plugin(api, home, text):
    _plugin(home, {**PLUGIN_FILES, "hooks/hooks.json": text})
    row = _row(await _scan(api), "plugins", "release-kit")
    assert row["refused"] == "unreadable" and row["tick"] is False


@pytest.mark.parametrize(("extra", "code"), [
    ({"commands/status.md": "Status.\n"}, "commands"),
    ({"agents/reviewer.md": "Review.\n"}, "agents"),
    ({".lsp.json": "{}"}, "lsp"),
    ({"output-styles/terse.md": "Short.\n"}, "other"),
    ({".claude-plugin/plugin.json": json.dumps({"name": "release-kit", "outputStyles": "./o"})}, "other"),
])
async def test_only_hooks_are_loosened(api, home, extra, code):
    _plugin(home, {**PLUGIN_FILES, "hooks/hooks.json": _hooks("SessionStart"), **extra})
    row = _row(await _scan(api), "plugins", "release-kit")
    assert row["refused"] == code and row["tick"] is False


async def test_a_github_plugin_keeps_refusing_hooks():
    """CAP7b's install from GitHub isn't this rule's: a hooks folder still refuses it there."""
    snap = plugin_package.Snapshot("acme/kit", "0" * 40, {k: v.encode() for k, v in
                                                         {**PLUGIN_FILES, "hooks/hooks.json": _hooks("SessionStart")}.items()})
    with pytest.raises(plugin_package.Refused) as refused:
        plugin_package.parts(snap)
    assert refused.value.code == "hooks"


# ── an allowed hook: in, never registered or run ─────────────────────────────────────────────────────────────────

@pytest.fixture
def spawns(monkeypatch):
    """Every way a process can be started from Python, recorded and then let through."""
    seen: list = []

    def wrap(owner, name):
        real = getattr(owner, name)

        def spy(*args, **kwargs):
            seen.append(repr((name, args, kwargs)))
            return real(*args, **kwargs)
        monkeypatch.setattr(owner, name, spy)
    for name in ("system", "posix_spawn", "posix_spawnp", "execv", "execve", "execvp", "execvpe", "spawnv", "spawnve",
                 "popen", "fork"):
        if hasattr(os, name):
            wrap(os, name)
    real_popen = subprocess.Popen

    class Popen(real_popen):
        def __init__(self, *args, **kwargs):
            seen.append(repr(("Popen", args, kwargs)))
            super().__init__(*args, **kwargs)
    monkeypatch.setattr(subprocess, "Popen", Popen)
    wrap(asyncio, "create_subprocess_exec")
    wrap(asyncio, "create_subprocess_shell")
    return seen


async def test_an_allowed_hook_is_installed_and_never_registered_or_run(api, home, offline, tmp_path, spawns):
    ran = tmp_path / "the-hook-ran"
    command = f"touch {ran}"
    files = {**PLUGIN_FILES, **CONNECTION, "hooks/hooks.json": _hooks("SessionStart", "PostToolUse", command=command),
             "hooks/format.sh": f"#!/bin/sh\n{command}\n",
             "skills/release-notes/SKILL.md": _frontmatter_skill("release-notes", "SessionEnd", command)}
    _plugin(home, files)
    row = _row(await _scan(api), "plugins", "release-kit")
    assert row["refused"] is None and row["tick"] is False                        # a plugin starts unticked
    assert row["hooks"] == ["SessionStart", "PostToolUse", "SessionEnd"]
    card = (await _post(api, plugins=[_tick(row)]))[row["id"]]
    assert card["state"] == "card" and card["card"]["hooks"] == ["SessionStart", "PostToolUse", "SessionEnd"]
    assert command not in json.dumps(card)                                       # the event, never what it runs
    done = (await _post(api, plugins=[_tick(row, card=card["card_digest"])]))[row["id"]]
    assert done["state"] == "on", done
    await agent_skills.sync()
    assert (await api.get("/api/v1/capabilities")).status_code == 200
    # Never run: no process was started with it, and what it would have made isn't there.
    assert not ran.exists() and not [call for call in spawns if str(ran) in call]
    # Never registered: no file Arslan wrote and no row holds it, and no hooks file came along.
    written = _files_under(home / ".agents", tmp_path / "data")
    assert written and not [path for path, data in written.items() if str(ran).encode() in data]
    assert not [path for path in written if Path(path).name in ("hooks.json", "format.sh")]
    rows = [*(await _all(CapabilitySource)), *(await _all(SkillPack))]
    assert not [r for r in rows if str(ran) in json.dumps({c.name: getattr(r, c.name) for c in r.__table__.columns},
                                                          default=str)]
    plugin = next(r for r in await _all(CapabilitySource) if r.kind == "plugin")
    assert plugin.candidate["hooks"] == ["SessionStart", "PostToolUse", "SessionEnd"]
    # The skill's frontmatter hooks are stripped: Arslan's SKILL.md has its name and description only.
    head = (agent_skills.folder("release-notes") / "SKILL.md").read_text().split("---")[1]
    assert set(yaml.safe_load(head)) == {"name", "description"}


async def test_a_skills_frontmatter_hooks_are_judged_and_stripped(api, home):
    _skill(home, "quiet-notes", text=_frontmatter_skill("quiet-notes", "SessionStart"))
    _skill(home, "guard-notes", text=_frontmatter_skill("guard-notes", "PreToolUse"))
    scan = await _scan(api)
    quiet, guard = _row(scan, "skills", "quiet-notes"), _row(scan, "skills", "guard-notes")
    assert quiet["refused"] is None and quiet["hooks"] == ["SessionStart"]
    assert guard["refused"] == "hooks" and guard["refused_part"] == "PreToolUse" and guard["tick"] is False
    results = await _post(api, skills=[_tick(quiet), _tick(guard)])
    assert results[quiet["id"]]["state"] == "added" and results[guard["id"]]["state"] == "refused"
    assert await _pack("guard-notes") is None and not agent_skills.folder("guard-notes").exists()
    text = (agent_skills.folder("quiet-notes") / "SKILL.md").read_text()
    assert "hooks" not in text and set(yaml.safe_load(text.split("---")[1])) == {"name", "description"}


# ── the sheet's route takes plugins now ──────────────────────────────────────────────────────────────────────────

async def test_the_route_adds_a_plugin_after_its_card(api, home, offline):
    card = await _install(api, home, {**PLUGIN_FILES, "hooks/hooks.json": _hooks("SessionStart")})
    assert card["card"]["name"] == "release-kit" and card["card"]["from"] == "acme"
    assert card["card"]["summary"] == "Release notes"
    plugin = next(r for r in await _all(CapabilitySource) if r.kind == "plugin")
    assert plugin.state == "installed"
    assert all(p.enabled and p.source_id == plugin.id for p in await _all(SkillPack))


async def test_a_plugin_starts_unticked(api, home):
    _plugin(home)
    row = _row(await _scan(api), "plugins", "release-kit")
    assert row["refused"] is None and row["tick"] is False


# ── an update: judged again ──────────────────────────────────────────────────────────────────────────────────────

def _update(home: Path, version: str, files: dict, old: str) -> None:
    """Claude Code installs the new version beside the old one, which it marks as orphaned."""
    _write(home / ".claude" / "plugins" / "cache" / "acme" / "release-kit" / version, files)
    (home / ".claude" / "plugins" / "cache" / "acme" / "release-kit" / old / ".orphaned_at").write_text("1")


async def test_an_update_adding_a_blocking_hook_switches_it_off_until_its_card(api, home, offline):
    await _install(api, home, {**PLUGIN_FILES, "hooks/hooks.json": _hooks("SessionStart")})
    old = next(r for r in await _all(CapabilitySource) if r.kind == "plugin")
    # An update with only quiet hooks changes nothing here: Arslan's copy is as the card showed it.
    _update(home, "1.1.0", {**PLUGIN_FILES, "hooks/hooks.json": _hooks("SessionStart", "SessionEnd")}, "1.0.0")
    row = _row(await _scan(api), "plugins", "release-kit")
    assert row["here"] is True and all(p.enabled for p in await _all(SkillPack))
    # One adding a blocking hook: the group goes off, its switch won't turn it on, and the sheet shows why.
    _update(home, "1.2.0", {**PLUGIN_FILES, "hooks/hooks.json": _hooks("SessionStart", "PreToolUse")}, "1.1.0")
    row = _row(await _scan(api), "plugins", "release-kit")
    assert row["refused"] == "hooks" and row["refused_part"] == "PreToolUse" and row["here"] is False
    assert not any(p.enabled for p in await _all(SkillPack))
    listed = next(r for r in (await api.get("/api/v1/capabilities")).json() if r["key"] == f"plugin:{old.id}")
    assert listed["state"] == "setup" and listed["reason"] == "plugin_hooks" and listed["detail"] == "PreToolUse"
    switched = await api.put(f"/api/v1/capabilities/plugin:{old.id}", json={"on": True})
    assert switched.status_code == 409
    assert not any(p.enabled for p in await _all(SkillPack))
    # Read again with nothing changed: still off, and nothing else happens.
    assert _row(await _scan(api), "plugins", "release-kit")["refused"] == "hooks"
    # The hook goes in a later update: the row can be ticked again, and only its card brings it back.
    _update(home, "1.3.0", {**PLUGIN_FILES, "hooks/hooks.json": _hooks("SessionStart")}, "1.2.0")
    row = _row(await _scan(api), "plugins", "release-kit")
    assert row["refused"] is None and row["here"] is False
    assert not any(p.enabled for p in await _all(SkillPack))
    card = (await _post(api, plugins=[_tick(row)]))[row["id"]]
    assert card["state"] == "card" and not any(p.enabled for p in await _all(SkillPack))
    done = (await _post(api, plugins=[_tick(row, card=card["card_digest"])]))[row["id"]]
    assert done["state"] == "on", done
    plugins = {r.id: r for r in await _all(CapabilitySource) if r.kind == "plugin"}
    assert plugins[old.id].state == "removed" and len(plugins) == 2
    new = next(r for r in plugins.values() if r.id != old.id)
    assert new.state == "installed" and all(p.enabled and p.source_id == new.id for p in await _all(SkillPack))
    assert _row(await _scan(api), "plugins", "release-kit")["here"] is True


# ── #809's review: what plugins rely on ──────────────────────────────────────────────────────────────────────────

async def test_a_file_over_the_cap_is_refused_never_cut(api, home, tmp_path):
    big = tmp_path / "big.bin"
    big.write_bytes(b"a" * (agent_skills.MAX_BYTES + 1))
    with pytest.raises(OSError):
        agent_skills._read_file(big)
    base = _plugin(home)
    (base / "assets").mkdir()
    (base / "assets" / "big.bin").write_bytes(b"a" * (agent_skills.MAX_BYTES + 1))
    row = _row(await _scan(api), "plugins", "release-kit")
    assert row["refused"] == "too_large" and row["tick"] is False


async def test_max_items_caps_what_is_read_not_only_what_is_listed(api, home, monkeypatch):
    for n in range(3):
        _skill(home, f"skill-{n}", text=SKILL_MD.format(name=f"skill-{n}"))
        _plugin(home, marketplace=f"market-{n}")
    monkeypatch.setattr(tool_import, "MAX_ITEMS", 3)
    reads = []
    real = tool_import._read_local
    monkeypatch.setattr(tool_import, "_read_local", lambda base: reads.append(base) or real(base))
    scan = await _scan(api)
    assert len(scan["skills"]) + len(scan["plugins"]) == 3 and len(reads) == 3


async def test_the_parse_and_scan_run_off_the_event_loop(api, home, monkeypatch):
    _skill(home)
    _plugin(home, {**PLUGIN_FILES, "hooks/hooks.json": _hooks("SessionStart")})
    loop_thread = threading.current_thread()
    where = []
    for owner, name in ((skill_import, "parse_skill_md"), (skill_import, "scan_prepared"), (plugin_package, "parts")):
        real = getattr(owner, name)
        monkeypatch.setattr(owner, name, lambda *a, _real=real, _name=name, **k:
                            where.append((_name, threading.current_thread())) or _real(*a, **k))
    scan = await _scan(api)
    assert scan["skills"] and scan["plugins"] and {name for name, _ in where} == {"parse_skill_md", "scan_prepared",
                                                                                 "parts"}
    assert all(thread is not loop_thread for _, thread in where)


async def test_plugins_and_skills_here_are_still_read_on_the_loop_from_the_database(api, home, offline):
    """The database is asked on the loop, after the thread: a plugin skill already here still refuses the plugin."""
    async with db_session.AsyncSessionLocal() as db:
        db.add(SkillPack(key="changelog-style", name="changelog-style", category="imported", description="x",
                         tier="safe", status="registered", body="mine"))
        await db.commit()
    _plugin(home)
    row = _row(await _scan(api), "plugins", "release-kit")
    assert row["refused"] == "skill" and row["tick"] is False
    async with db_session.AsyncSessionLocal() as db:
        assert (await db.execute(select(SkillPack.body).where(SkillPack.key == "changelog-style"))).scalar() == "mine"
