"""HOOK-4 (docs/plans/0164/HOOK-plugin-hooks.md): the server half of the web's hook switches.

- A plugin's row in GET /capabilities carries its hooks as stored (`plugin_hooks.card_rows`), for "Show what's inside".
- A switch flipped through HOOK-1's PUT /capability-hooks is what the next GET shows.
- The user's decision: a hook Arslan runs comes in on. None is run before HOOK-3, so every hook stored today is off.

On a scratch HOME and data folder, with fake Claude Code folders, as HOOK-1's tests.
"""
import pytest

from server.db import session as db_session
from server.db.models import CapabilitySource
from server.services import plugin_hooks
from tests.server.test_cap8_2_import_skills_plugins import PLUGIN_FILES, _all, api, home, offline
from tests.server.test_hook1_hooks_stored import _cmd, _install, _map

pytestmark = pytest.mark.asyncio
__all__ = ["api", "home", "offline"]           # fixtures, used by name


async def _plugin_row(api) -> dict:
    listed = await api.get("/api/v1/capabilities")
    assert listed.status_code == 200
    return next(row for row in listed.json() if row["section"] == "plugins")


async def test_a_plugins_row_carries_its_hooks_as_stored(api, home, offline):
    await _install(api, home, {**PLUGIN_FILES, "hooks/hooks.json": _map(
        PostToolUse=[("Edit|Write", _cmd("fmt --check", timeout=5))], SessionStart=[("startup", _cmd("cat rules.md"))])})
    hooks = (await _plugin_row(api))["hooks"]
    assert [(h["id"], h["event"], h["command"], h["matches"], h["kind"], h["on"]) for h in hooks] == [
        ("0", "PostToolUse", "fmt --check", ["edit_file", "write_file"], "wont_run", False),
        ("1", "SessionStart", "cat rules.md", ["startup"], "wont_run", False)]
    assert hooks[0]["timeout"] == 5 and hooks[0]["when"] == "after a tool runs"


async def test_a_switch_flipped_is_what_the_list_shows_next(api, home, offline):
    """As HOOK-3 will store a hook it runs (supported, on): switched off through the route, the list says off."""
    await _install(api, home, {**PLUGIN_FILES, "hooks/hooks.json": _map(SessionStart=[("startup", _cmd("cat rules.md"))])})
    (plugin,) = [r for r in await _all(CapabilitySource) if r.kind == "plugin"]
    async with db_session.AsyncSessionLocal() as db:
        row = await db.get(CapabilitySource, plugin.id)
        row.candidate = {**row.candidate, "hook_rows": [{**h, "kind": plugin_hooks.SUPPORTED, "on": True}
                                                         for h in row.candidate["hook_rows"]]}
        await db.commit()
    assert (await _plugin_row(api))["hooks"][0]["on"] is True
    switched = await api.put(f"/api/v1/capability-hooks/plugin:{plugin.id}/0", json={"on": False})
    assert switched.status_code == 200 and switched.json()["on"] is False
    assert (await _plugin_row(api))["hooks"][0]["on"] is False
    assert (await api.put(f"/api/v1/capability-hooks/plugin:{plugin.id}/0", json={"on": True})).status_code == 200
    assert (await _plugin_row(api))["hooks"][0]["on"] is True


def test_a_hook_arslan_runs_comes_in_on_and_one_it_doesnt_off(monkeypatch):
    """The default follows what Arslan does with the hook. Nothing is supported before HOOK-3, so a protection is
    made to read as one here (`NOT_YET` standing for `SUPPORTED`) to show the default it will get."""
    quiet = plugin_hooks._row("PostToolUse", "Bash", _cmd("x"), "hooks", {}, None)
    assert (quiet["kind"], quiet["on"]) == (plugin_hooks.WONT_RUN, False)
    monkeypatch.setattr(plugin_hooks, "NOT_YET", plugin_hooks.SUPPORTED)
    guard = plugin_hooks._row("PreToolUse", "Bash", _cmd("x"), "hooks", {}, None)
    assert (guard["kind"], guard["on"]) == (plugin_hooks.SUPPORTED, True)
