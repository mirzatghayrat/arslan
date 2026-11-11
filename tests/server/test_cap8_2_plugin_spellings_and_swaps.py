"""CAP8-2's plugin follow-up, second round: spellings, an update's other refusals, and a swap killed mid-install.

- **Spellings.** Claude Code opens its fixed names (`hooks/hooks.json`, `.claude-plugin/plugin.json`, `commands/`, and
  the rest) by one spelling, and the default macOS disk opens that spelling for any letter case and any Unicode form
  that folds to it. So a plugin naming one of them in another case or form is refused, and so is a plugin holding two
  files that one such disk would open as one.
- **An update** whose other-tool copy is refused for anything switches the installed import off, a blocking hook
  first among the reasons: no other refusal hides it.
- **A real kill** while one of the new group's skills is half in (folder written, no row yet) is put back by the swap's
  record at the next start: the old group exactly as it was, no half copy, and a later Add works. The swap and the
  start run in their own processes, on this test's database, HOME and data folder.

On a scratch HOME and data folder, with fake Claude Code folders: nothing reads a real `~/.claude`, `~/.agents` or
data folder.
"""
import json
import logging
import os
import signal
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

import pytest

from server.db import session as db_session
from server.db.models import CapabilitySource, SkillPack
from server.services import agent_skills, plugin_package, skill_import, tool_import
from tests.server.test_cap8_2_import_skills_plugins import (BLOCKED, PLUGIN_FILES, SKILL_MD, _all, _plugin, _row, _scan,
                                                            _skill, _tick, _write, api, home, offline)
from tests.server.test_cap8_2_plugin_hooks import _files_under, _frontmatter_skill, _hooks, _install, _post, _update

pytestmark = pytest.mark.asyncio
__all__ = ["api", "home", "offline"]           # fixtures, used by name

REPO = Path(__file__).resolve().parents[2]
BLOCKING = _hooks("SessionStart", "PreToolUse")
INLINE = json.dumps({"name": "release-kit", "version": "1.0.0", "hooks": {"PreToolUse": [{"hooks": [
    {"type": "command", "command": "echo hi"}]}]}})


def _without(files: dict, *paths: str) -> dict:
    return {k: v for k, v in files.items() if k not in paths}


# ── spellings ────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("files", [
    {**PLUGIN_FILES, "Hooks/hooks.json": BLOCKING},
    {**PLUGIN_FILES, "hooks/Hooks.json": BLOCKING},
    {**PLUGIN_FILES, "HOOKS/HOOKS.JSON": BLOCKING},
    {**PLUGIN_FILES, "hooKs/hooks.json": BLOCKING},                      # KELVIN SIGN folds to k
    {**PLUGIN_FILES, "hookſ/hooks.json": BLOCKING},                      # LONG S folds to s
    {**_without(PLUGIN_FILES, ".claude-plugin/plugin.json"), ".Claude-Plugin/plugin.json": INLINE,
     "plugin.json": json.dumps({"name": "release-kit", "version": "1.0.0"})},
    {**PLUGIN_FILES, "Commands/deploy.md": "Deploy.\n"},
    {**PLUGIN_FILES, "AGENTS/guard.md": "Guard.\n"},
    {**PLUGIN_FILES, ".LSP.json": "{}"},
    {**PLUGIN_FILES, "Settings.json": "{}"},
    {**PLUGIN_FILES, "Output-Styles/terse.md": "Short.\n"},
    {**PLUGIN_FILES, ".MCP.json": json.dumps({"mcpServers": {}})},
    {".claude-plugin/plugin.json": PLUGIN_FILES[".claude-plugin/plugin.json"],      # the only skills folder
     "Skills/guard/SKILL.md": _frontmatter_skill("guard", "PreToolUse")},
    {**PLUGIN_FILES, "skills/guard/Skill.md": _frontmatter_skill("guard", "PreToolUse")},
], ids=["Hooks-dir", "Hooks-file", "HOOKS", "kelvin", "long-s", "manifest-dir", "Commands", "AGENTS", "LSP", "Settings",
        "Output-Styles", "MCP", "Skills-dir", "Skill.md"])
async def test_a_special_name_in_another_spelling_refuses_the_plugin(api, home, offline, files):
    _plugin(home, files)
    row = _row(await _scan(api), "plugins", "release-kit")
    assert row["refused"] == "unreadable" and row["tick"] is False, row
    assert (await _post(api, plugins=[_tick(row)]))[row["id"]]["state"] == "refused"
    assert await _all(CapabilitySource) == [] and offline == []


async def test_a_plugin_in_the_skills_folder_with_its_manifest_folder_in_another_case_is_judged_as_a_plugin(api, home):
    _write(home / ".claude" / "skills" / "guard-kit", {".Claude-Plugin/plugin.json": INLINE,
                                                       "SKILL.md": SKILL_MD.format(name="guard-kit")})
    scan = await _scan(api)
    assert not [r for r in scan["skills"] if r["name"] == "guard-kit"]
    row = next(r for r in scan["plugins"] if r["id"] == "plugin:skills/guard-kit")
    assert row["refused"] == "unreadable" and row["tick"] is False


@pytest.mark.parametrize(("files", "manifest"), [
    ({"hooks/hooks.json": _hooks("SessionStart"), "hooks/HOOKS.json": BLOCKING}, None),
    ({"hooks/hooks.json": _hooks("SessionStart"), "Hooks/hooks.json": BLOCKING}, None),
    ({"config/more.json": _hooks("SessionStart"), "Config/more.json": BLOCKING}, "./config/more.json"),
    ({"skills/a/SKILL.md": SKILL_MD.format(name="a"), "skills/a/skill.md": _frontmatter_skill("a", "Stop")}, None),
])
async def test_two_spellings_one_disk_would_open_as_one_file_refuse_the_plugin(files, manifest):
    """A disk that tells case apart can hold both (a GitHub repository can); Claude Code's disk opens one of them."""
    head = {"name": "release-kit", "version": "1.0.0", **({"hooks": manifest} if manifest else {})}
    snap = plugin_package.Snapshot("x", "0" * 40, {k: v.encode() for k, v in
                                                   {".claude-plugin/plugin.json": json.dumps(head), **files}.items()})
    with pytest.raises(plugin_package.Refused) as refused:
        plugin_package.parts(snap, hooks=True)
    assert refused.value.code == "unreadable"


async def test_the_exact_spellings_still_come_in(api, home):
    _plugin(home, {**PLUGIN_FILES, "hooks/hooks.json": _hooks("SessionStart"), "hooks/format.sh": "#!/bin/sh\n",
                   "README.md": "Kit.\n", "docs/Hooks.md": "About hooks.\n"})
    row = _row(await _scan(api), "plugins", "release-kit")
    assert row["refused"] is None and row["hooks"] == ["SessionStart"]


# ── an update: a blocking hook is judged first, and any refusal switches the import off ─────────────────────────────

@pytest.mark.parametrize("extra", [{"commands/deploy.md": "Deploy.\n"}, {"agents/guard.md": "Guard.\n"},
                                   {".lsp.json": "{}"},
                                   {"skills/aaa-setup/SKILL.md": BLOCKED.format(name="aaa-setup")}],
                         ids=["command", "agent", "lsp", "blocked-scan"])
@pytest.mark.parametrize("where", ["hooks.json", "frontmatter"])
async def test_an_update_adding_a_blocking_hook_beside_another_refusal_switches_it_off(api, home, extra, where):
    files = {**PLUGIN_FILES, "hooks/hooks.json": _hooks("SessionStart")}
    await _install(api, home, files)
    old = next(r for r in await _all(CapabilitySource) if r.kind == "plugin")
    hooked = ({"hooks/hooks.json": BLOCKING} if where == "hooks.json"
              else {"skills/release-notes/SKILL.md": _frontmatter_skill("release-notes", "PreToolUse")})
    _update(home, "1.1.0", {**files, **hooked, **extra}, "1.0.0")
    row = _row(await _scan(api), "plugins", "release-kit")
    assert row["refused"] == "hooks" and row["refused_part"] == "PreToolUse" and row["here"] is False, row
    assert not any(p.enabled for p in await _all(SkillPack))
    listed = next(r for r in (await api.get("/api/v1/capabilities")).json() if r["key"] == f"plugin:{old.id}")
    assert listed["reason"] == "plugin_hooks" and listed["detail"] == "PreToolUse"
    assert (await api.put(f"/api/v1/capabilities/plugin:{old.id}", json={"on": True})).status_code == 409


@pytest.mark.parametrize(("extra", "code"), [({"commands/deploy.md": "Deploy.\n"}, "commands"),
                                             ({"Commands/deploy.md": "Deploy.\n"}, "unreadable"),
                                             ({"skills/aaa-setup/SKILL.md": BLOCKED.format(name="aaa-setup")}, "scan")])
async def test_an_update_refused_for_anything_else_switches_it_off_too(api, home, extra, code):
    files = {**PLUGIN_FILES, "hooks/hooks.json": _hooks("SessionStart")}
    await _install(api, home, files)
    old = next(r for r in await _all(CapabilitySource) if r.kind == "plugin")
    _update(home, "1.1.0", {**files, **extra}, "1.0.0")
    row = _row(await _scan(api), "plugins", "release-kit")
    assert row["refused"] == code and row["here"] is False, row
    assert not any(p.enabled for p in await _all(SkillPack))
    listed = next(r for r in (await api.get("/api/v1/capabilities")).json() if r["key"] == f"plugin:{old.id}")
    assert listed["state"] == "setup" and listed["reason"] == "plugin_refused" and listed["detail"] == code
    assert (await api.put(f"/api/v1/capabilities/plugin:{old.id}", json={"on": True})).status_code == 409


async def test_an_update_that_cant_be_read_switches_it_off(api, home):
    files = {**PLUGIN_FILES, "hooks/hooks.json": _hooks("SessionStart")}
    await _install(api, home, files)
    base = home / ".claude" / "plugins" / "cache" / "acme" / "release-kit"
    _update(home, "1.1.0", files, "1.0.0")
    (base / "1.1.0" / "hooks" / "more.json").symlink_to(base / "1.1.0" / "hooks" / "hooks.json")
    row = _row(await _scan(api), "plugins", "release-kit")
    assert row["refused"] == "unreadable" and row["here"] is False
    assert not any(p.enabled for p in await _all(SkillPack))


async def test_an_update_too_broken_to_name_itself_is_matched_by_where_claude_code_keeps_it(api, home):
    """Its folder isn't named as its manifest names it, and the update can't be read, so no name is known."""
    files = {**PLUGIN_FILES, "hooks/hooks.json": _hooks("SessionStart")}
    base = _plugin(home, files, name="kit-folder").parent
    row = _row(await _scan(api), "plugins", "release-kit")
    card = (await _post(api, plugins=[_tick(row)]))[row["id"]]
    assert (await _post(api, plugins=[_tick(row, card=card["card_digest"])]))[row["id"]]["state"] == "on"
    _write(base / "1.1.0", files)
    (base / "1.1.0" / "hooks" / "more.json").symlink_to(base / "1.1.0" / "hooks" / "hooks.json")
    (base / "1.0.0" / ".orphaned_at").write_text("1")
    assert _row(await _scan(api), "plugins", "kit-folder")["refused"] == "unreadable"
    assert not any(p.enabled for p in await _all(SkillPack))


async def test_a_long_plugin_name_is_still_switched_off_by_its_update(api, home):
    name = "release-kit-" + "x" * 130
    files = {**PLUGIN_FILES, ".claude-plugin/plugin.json": json.dumps({"name": name, "version": "1.0.0"})}
    _plugin(home, files)
    row = next(r for r in (await _scan(api))["plugins"])
    card = (await _post(api, plugins=[_tick(row)]))[row["id"]]
    assert (await _post(api, plugins=[_tick(row, card=card["card_digest"])]))[row["id"]]["state"] == "on"
    _update(home, "1.1.0", {**files, "hooks/hooks.json": BLOCKING}, "1.0.0")
    assert next(r for r in (await _scan(api))["plugins"])["refused"] == "hooks"
    assert not any(p.enabled for p in await _all(SkillPack))


# ── a skill's frontmatter: two `hooks:` keys ────────────────────────────────────────────────────────────────────────

async def test_a_frontmatter_with_two_hooks_keys_is_refused(api, home):
    raw = ("---\nname: notes\ndescription: Notes.\nhooks:\n  PreToolUse:\n    - hooks: []\nhooks:\n  PostToolUse:\n"
           "    - hooks: []\n---\n\nBody.\n")
    with pytest.raises(skill_import.HookRefused):
        skill_import.frontmatter_hooks(raw)
    _skill(home, "notes", text=raw)
    assert _row(await _scan(api), "skills", "notes")["refused"] == "unreadable"


# ── the swap's record: only paths inside the skills folder ───────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", ["aside-outside", "aside-renamed", "key", "new-key"])
async def test_settle_refuses_a_record_naming_a_path_outside_the_skills_folder(home, tmp_path, caplog, bad):
    outside = tmp_path / "outside"
    _write(outside, {"keep.txt": "mine\n"})
    agent_skills.root().mkdir(parents=True)
    held = {"row": {"key": "notes"}, "entry": None, "written": None, "aside": ".arslan-swap-notes"}
    new = [{"key": "notes", "files": ["SKILL.md"]}]
    if bad == "aside-outside":                          # the skills folder is <home>/.agents/skills
        held["aside"] = "../../../outside"
    elif bad == "aside-renamed":
        held["aside"] = "elsewhere"
    elif bad == "key":
        held["row"]["key"] = "../../../outside"
    else:
        new = [{"key": "../../../outside", "files": ["keep.txt"]}]
    swap = {"new": uuid.uuid4().hex, "held": [held], "new_skills": new}
    await _old_row(swap)
    with caplog.at_level(logging.WARNING):
        await plugin_package.settle("old")
    assert (outside / "keep.txt").read_text() == "mine\n"
    assert not os.path.lexists(agent_skills.folder("notes"))
    assert next(r for r in await _all(CapabilitySource)).test["swap"] == swap        # kept, untouched
    assert "outside the skills folder" in caplog.text


async def _old_row(swap: dict) -> None:
    async with db_session.AsyncSessionLocal() as db:
        db.add(CapabilitySource(id="old", kind="plugin", name="release-kit", candidate_id="import:x", runtime="plugin",
                                needs={}, grants={}, candidate={}, state="installed", created_at=datetime.utcnow(),
                                test={"swap": swap}))
        await db.commit()


async def test_only_a_folder_holding_nothing_but_the_new_skills_files_goes_to_the_trash(home):
    root = agent_skills.root()
    _write(root / "ours", {"SKILL.md": "x", "scripts/fmt.py": "y"})              # written in part
    _write(root / "theirs", {"SKILL.md": "x", "notes.txt": "mine\n"})
    _write(root / "linked", {"SKILL.md": "x"})
    (root / "linked" / "scripts").symlink_to(root / "theirs")
    names = ["SKILL.md", "scripts/fmt.py", "references/a.md"]
    plugin_package._drop_new({"held": [], "new_skills": [{"key": key, "files": names}
                                                         for key in ("ours", "theirs", "linked")]}, set())
    assert not os.path.lexists(root / "ours") and (home / ".Trash").exists()
    assert (root / "theirs" / "notes.txt").read_text() == "mine\n" and (root / "linked" / "SKILL.md").exists()


async def test_an_old_folder_that_cant_go_back_keeps_the_record_until_it_can(home, caplog):
    root = agent_skills.root()
    _write(root / ".arslan-swap-notes", {"SKILL.md": "old\n"})
    _write(root / "notes", {"SKILL.md": "x", "mine.txt": "theirs\n"})          # not what the new skill would write
    row = {"key": "notes", "name": "notes", "category": "imported", "description": "x", "tier": "safe",
           "status": "registered", "body": "b"}
    swap = {"new": uuid.uuid4().hex, "held": [{"row": row, "entry": None, "written": None,
                                               "aside": ".arslan-swap-notes"}],
            "new_skills": [{"key": "notes", "files": ["SKILL.md"]}]}
    await _old_row(swap)
    with caplog.at_level(logging.WARNING):
        await plugin_package.settle("old")
    assert "could not go back" in caplog.text
    assert (root / ".arslan-swap-notes" / "SKILL.md").read_text() == "old\n"
    assert (root / "notes" / "mine.txt").read_text() == "theirs\n"
    assert next(r for r in await _all(CapabilitySource)).test["swap"] == swap
    with pytest.raises(plugin_package.Refused, match="swap_pending"):             # no second swap over it
        await plugin_package._set_aside("old", uuid.uuid4().hex, [])
    (root / "notes" / "mine.txt").unlink()
    (root / "notes" / "SKILL.md").unlink()
    (root / "notes").rmdir()                                                       # its owner took it away
    await plugin_package.settle("old")
    assert (root / "notes" / "SKILL.md").read_text() == "old\n" and not os.path.lexists(root / ".arslan-swap-notes")
    assert not next(r for r in await _all(CapabilitySource)).test.get("swap")
    assert [p.key for p in await _all(SkillPack)] == ["notes"]


# ── a real kill while a new skill is half in ─────────────────────────────────────────────────────────────────────

CHILD = r'''
import asyncio, json, os, signal, sys
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from server.db import session as db_session
args = json.loads(sys.argv[1])
db_session.AsyncSessionLocal = async_sessionmaker(db_session.build_engine("sqlite+aiosqlite:///" + args["db"]),
                                                  class_=AsyncSession, expire_on_commit=False)
from server.services import agent_skills, skill_import, tool_import
if args["what"] == "start":
    from server import main
    asyncio.run(main._boot_skills())
    sys.exit(0)
tool_import._DIGEST_KEY = bytes.fromhex(args["key"])
written = []
real_write, real_row = agent_skills.write_new, skill_import._install_row
def write_new(base, expected):
    out = real_write(base, expected)
    written.append(base.name)
    if args["at"] == "write_new_%d" % len(written):
        os.kill(os.getpid(), signal.SIGKILL)
    return out
async def install_row(*a, **k):
    if args["at"] == "install_row":
        os.kill(os.getpid(), signal.SIGKILL)
    return await real_row(*a, **k)
agent_skills.write_new, skill_import._install_row = write_new, install_row
asyncio.run(tool_import.add([], [args["tick"]]))
sys.exit(3)
'''


def _child(tmp_path: Path, **args) -> subprocess.CompletedProcess:
    """A process of its own on this test's database, HOME and data folder, started as `scripts/dev/probe.sh` starts
    one: an empty environment but for these, with a fake secret and no secret file."""
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
           "LANG": "en_US.UTF-8", "HOME": str(tmp_path / "home"), "PYTHONPATH": str(REPO),
           "ARSLAN_SECRET_KEY_FILE": "", "ARSLAN_SECRET_KEY": "test-fake-secret-not-a-real-key",
           "ARSLAN_DATA_DIR": str(tmp_path / "data"), "ARSLAN_MCP_SUPERVISOR": "0"}
    return subprocess.run([sys.executable, "-c", CHILD, json.dumps({"db": str(tmp_path / "execution.db"), **args})],
                          env=env, cwd=REPO, capture_output=True, text=True, timeout=240)


@pytest.mark.parametrize("at", ["write_new_1", "write_new_2", "write_new_3", "install_row"])
async def test_a_real_kill_while_a_new_skill_is_half_in_is_put_back_at_the_next_start(api, home, tmp_path, at):
    files = {**PLUGIN_FILES, "hooks/hooks.json": _hooks("SessionStart")}
    await _install(api, home, files)
    old = next(r for r in await _all(CapabilitySource) if r.kind == "plugin")
    _update(home, "1.1.0", {**files, "hooks/hooks.json": BLOCKING}, "1.0.0")
    await _scan(api)
    # The update brings a skill the old group hasn't, and changes one it has.
    _update(home, "1.2.0", {**files, "skills/release-notes/scripts/fmt.py": "print('new')\n",
                            "skills/aaa-new/SKILL.md": SKILL_MD.format(name="aaa-new")}, "1.1.0")
    row = _row(await _scan(api), "plugins", "release-kit")
    card = (await _post(api, plugins=[_tick(row)]))[row["id"]]
    order = ("aaa-new", "changelog-style", "release-notes")       # the order the new group's skills go in
    keys = order[1:]
    folders = {key: _files_under(agent_skills.folder(key)) for key in keys}
    entries, written = agent_skills.entries(), agent_skills._written()
    packs = {p.key: {c.name: getattr(p, c.name) for c in SkillPack.__table__.columns} for p in await _all(SkillPack)}

    killed = _child(tmp_path, what="swap", at=at, key=tool_import._DIGEST_KEY.hex(),
                    tick=_tick(row, card=card["card_digest"]))
    assert killed.returncode == -signal.SIGKILL, killed.stderr[-3000:]
    # Where it was killed: a new skill's folder is in under its key, its row isn't, and the record is there.
    done = int(at[-1]) - 1 if at.startswith("write_new") else 0              # the new skills whose rows are in
    assert (agent_skills.folder(order[done]) / "SKILL.md").is_file()
    plugins = {r.id: r for r in await _all(CapabilitySource) if r.kind == "plugin"}
    new_id = plugins[old.id].test["swap"]["new"]
    assert {p.key: p.source_id for p in await _all(SkillPack)} == {key: new_id for key in order[:done]}

    started = _child(tmp_path, what="start")
    assert started.returncode == 0, started.stderr[-3000:]
    plugins = {r.id: r for r in await _all(CapabilitySource) if r.kind == "plugin"}
    assert not any((r.test or {}).get("swap") for r in plugins.values())
    assert plugins[old.id].state == "installed" and plugins[old.id].test["hooks_added"]["event"] == "PreToolUse"
    assert plugins[new_id].state == "failed"
    assert {p.key: {c.name: getattr(p, c.name) for c in SkillPack.__table__.columns}
            for p in await _all(SkillPack)} == packs
    assert {key: _files_under(agent_skills.folder(key)) for key in keys} == folders
    assert not os.path.lexists(agent_skills.folder("aaa-new"))                  # no half copy
    assert agent_skills.entries() == entries and agent_skills._written() == written
    assert not list(agent_skills.root().glob(".arslan-swap-*"))
    assert (await api.put(f"/api/v1/capabilities/plugin:{old.id}", json={"on": True})).status_code == 409

    again = (await _post(api, plugins=[_tick(row, card=card["card_digest"])]))[row["id"]]
    assert again["state"] == "on", again
    assert {r.id: r.state for r in await _all(CapabilitySource) if r.kind == "plugin"}[old.id] == "removed"
    assert (agent_skills.folder("release-notes") / "scripts" / "fmt.py").read_text() == "print('new')\n"
    assert {p.key: p.source_id for p in await _all(SkillPack)} == {key: again["source_id"] for key in order}
