"""CAP4a-3d (v0.1.64; the user's Q3, 2026-10-31): before an installed Registry server starts, once a day and after
an update of Arslan, its entry is asked again. Withdrawn or changed: parked, in Arslan's words, until the user keeps
it. The Registry not answering: no answer. No network: the Registry is a fake behind httpx."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from mcp import types

from server import config
from server.db.models import CapabilitySource, MCPServer
from server.mcp import discovery, session, supervisor as supervisor_mod
from server.services import capability_dossier, capability_recheck as rc

PKG = {"id": "registry:com.example/notes@1.2.0", "kind": "mcp", "name": "notes", "source": "registry",
       "runtime": "uv", "remote": None,
       "package": {"registry_type": "pypi", "identifier": "notes-mcp", "version": "1.2.0", "arguments": []}}
REMOTE = {**PKG, "id": "registry:com.example/notes-cloud@2.0.0", "runtime": "remote", "package": None,
          "remote": {"type": "streamable-http", "url": "https://mcp.example.com/notes"}}


def _entry(packages=None, remotes=None, status=None, version="1.2.0"):
    meta = {"io.modelcontextprotocol.registry/official": {"status": status}} if status else {}
    return {"server": {"name": "com.example/notes", "version": version, "packages": packages or [],
                       "remotes": remotes or []}, "_meta": meta}


SAME = _entry(packages=[{"registryType": "pypi", "identifier": "notes-mcp", "version": "1.2.0"}])


@pytest.fixture
def world(execution_db, monkeypatch):
    """A server installed from the Registry two days ago, and the Registry as a queue of answers."""
    monkeypatch.setattr(config, "_app_version", lambda: "0.1.64")
    answers, calls = [], []

    def handler(request):
        calls.append(str(request.url))
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, int):
            return httpx.Response(answer, json={})
        return httpx.Response(200, json=answer)
    real = httpx.AsyncClient
    monkeypatch.setattr(rc.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return SimpleNamespace(maker=execution_db, answers=answers, calls=calls)


async def _install(world, cand=PKG, *, days_ago=2, test=None):
    async with world.maker() as s:
        s.add(MCPServer(id=1, label="notes", command="x", args=[], status="registered"))
        await s.flush()
        s.add(CapabilitySource(id="src1", kind="mcp", name="notes", candidate_id=cand.get("id", "c"),
                               runtime=cand.get("runtime"), needs={}, grants={}, state="installed", mcp_server_id=1,
                               candidate=cand or None, test=test,
                               checked_at=datetime.utcnow() - timedelta(days=days_ago), created_at=datetime.utcnow()))
        await s.commit()


async def _check(world):
    async with world.maker() as s:
        return ((await s.get(CapabilitySource, "src1")).test or {}).get("registry_check") or {}


async def test_the_same_entry_starts_and_is_not_asked_again_within_a_day(world):
    await _install(world)
    world.answers.append(SAME)
    await rc.before_start(1)
    assert world.calls == ["https://registry.modelcontextprotocol.io/v0/servers/com.example%2Fnotes/versions/1.2.0"]
    check = await _check(world)
    assert check["problem"] is None and check["arslan"] == "0.1.64" and check["at"].endswith("Z")
    await rc.before_start(1)
    assert len(world.calls) == 1


async def test_a_just_installed_server_counts_as_checked(world):
    await _install(world, days_ago=0)
    await rc.before_start(1)
    assert world.calls == []


async def test_an_update_of_arslan_makes_the_check_due_again(world, monkeypatch):
    await _install(world)
    world.answers += [SAME, SAME]
    await rc.before_start(1)
    monkeypatch.setattr(config, "_app_version", lambda: "0.1.65")
    await rc.before_start(1)
    assert len(world.calls) == 2 and (await _check(world))["arslan"] == "0.1.65"


async def test_a_day_later_it_is_asked_again(world):
    old = (datetime.utcnow() - timedelta(days=1, minutes=1)).isoformat() + "Z"
    await _install(world, test={"registry_check": {"at": old, "arslan": "0.1.64", "problem": None}})
    world.answers.append(SAME)
    await rc.before_start(1)
    assert len(world.calls) == 1


@pytest.mark.parametrize("answer", [404, _entry(packages=SAME["server"]["packages"], status="deleted")],
                         ids=["gone", "marked deleted"])
async def test_a_withdrawn_entry_parks_it(world, answer):
    await _install(world)
    world.answers.append(answer)
    with pytest.raises(rc.SourceChanged) as stopped:
        await rc.before_start(1)
    assert stopped.value.problem == rc.WITHDRAWN and stopped.value.line == rc.LINES[rc.WITHDRAWN]
    assert (await _check(world))["problem"] == rc.WITHDRAWN


@pytest.mark.parametrize("packages", [
    [{"registryType": "pypi", "identifier": "notes-mcp-evil", "version": "1.2.0"}],     # another package
    [{"registryType": "pypi", "identifier": "notes-mcp", "version": "1.2.1"}],          # another version
    [{"registryType": "npm", "identifier": "notes-mcp", "version": "1.2.0"}],           # no package of that type
], ids=["package", "version", "type"])
async def test_a_changed_package_parks_it(world, packages):
    await _install(world)
    world.answers.append(_entry(packages=packages))
    with pytest.raises(rc.SourceChanged) as stopped:
        await rc.before_start(1)
    assert stopped.value.problem == rc.CHANGED


async def test_a_remote_whose_url_changed_is_parked_and_the_same_url_starts(world):
    await _install(world, REMOTE)
    world.answers += [_entry(remotes=[{"type": "streamable-http", "url": "https://mcp.example.com/notes"}])]
    await rc.before_start(1)
    async with world.maker() as s:
        row = await s.get(CapabilitySource, "src1")
        row.test = {}
        row.checked_at = datetime.utcnow() - timedelta(days=2)
        await s.commit()
    world.answers.append(_entry(remotes=[{"type": "streamable-http", "url": "https://elsewhere.example.net/notes"}]))
    with pytest.raises(rc.SourceChanged):
        await rc.before_start(1)


@pytest.mark.parametrize("failure", [503, httpx.ConnectError("down")], ids=["5xx", "unreachable"])
async def test_no_answer_starts_a_server_that_passed_and_asks_again_next_time(world, failure):
    await _install(world)
    world.answers += [failure, SAME]
    await rc.before_start(1)
    assert await _check(world) == {}                            # nothing recorded: the next start asks again
    await rc.before_start(1)
    assert len(world.calls) == 2 and (await _check(world))["problem"] is None


async def test_no_answer_keeps_a_parked_server_parked(world):
    await _install(world)
    world.answers += [404, httpx.ConnectError("down")]
    with pytest.raises(rc.SourceChanged):
        await rc.before_start(1)
    async with world.maker() as s:                               # a day later, the Registry is down
        row = await s.get(CapabilitySource, "src1")
        check = row.test["registry_check"]
        row.test = {"registry_check": {**check, "at": (datetime.utcnow() - timedelta(days=2)).isoformat() + "Z"}}
        await s.commit()
    with pytest.raises(rc.SourceChanged):
        await rc.before_start(1)


@pytest.mark.parametrize("cand", [{**PKG, "id": "github:acme/notes"}, None], ids=["not from the Registry", "no card"])
async def test_a_server_with_no_registry_entry_is_not_asked(world, cand):
    await _install(world, cand or {})
    await rc.before_start(1)
    assert world.calls == []


async def test_a_hand_added_server_is_not_asked(world):
    async with world.maker() as s:
        s.add(MCPServer(id=2, label="typed by hand", command="y", args=[], status="registered"))
        await s.commit()
    await rc.before_start(2)
    assert world.calls == []


async def test_keeping_a_parked_server_remembers_that_answer_only(world, monkeypatch):
    from server.services import mcp_service
    restarted = []

    async def restart(server_id):
        restarted.append(server_id)
    monkeypatch.setattr(mcp_service, "restart_after_edit", restart)
    await _install(world)
    world.answers += [404, 404, _entry(packages=[{"registryType": "pypi", "identifier": "other", "version": "9"}])]
    with pytest.raises(rc.SourceChanged):
        await rc.before_start(1)
    seen = (await _check(world))["seen"]
    with pytest.raises(capability_dossier.DossierError) as moved:
        await capability_dossier.accept_source("src1", "0" * 64)
    assert moved.value.code == "source_answer_moved" and restarted == []
    await capability_dossier.accept_source("src1", seen)
    assert restarted == [1]
    await rc.before_start(1)                                     # kept: not due, and the kept answer passes

    async def due():
        async with world.maker() as s:
            row = await s.get(CapabilitySource, "src1")
            check = row.test["registry_check"]
            row.test = {"registry_check": {**check, "at": (datetime.utcnow() - timedelta(days=2)).isoformat() + "Z"}}
            await s.commit()
    await due()
    await rc.before_start(1)                                     # the same answer again: still kept
    await due()
    with pytest.raises(rc.SourceChanged) as again:               # another answer parks it again
        await rc.before_start(1)
    assert again.value.problem == rc.CHANGED


async def test_a_kept_change_does_not_cover_another_change(world, monkeypatch):
    from server.services import mcp_service

    async def restart(server_id):
        return None
    monkeypatch.setattr(mcp_service, "restart_after_edit", restart)
    await _install(world)
    first = _entry(packages=[{"registryType": "pypi", "identifier": "notes-mcp", "version": "1.2.1"}])
    second = _entry(packages=[{"registryType": "pypi", "identifier": "notes-mcp-evil", "version": "1.2.0"}])
    world.answers += [first, second]
    with pytest.raises(rc.SourceChanged):
        await rc.before_start(1)
    await capability_dossier.accept_source("src1", (await _check(world))["seen"])
    async with world.maker() as s:
        row = await s.get(CapabilitySource, "src1")
        check = row.test["registry_check"]
        row.test = {"registry_check": {**check, "at": (datetime.utcnow() - timedelta(days=2)).isoformat() + "Z"}}
        await s.commit()
    with pytest.raises(rc.SourceChanged) as again:               # changed again, to something else
        await rc.before_start(1)
    assert again.value.problem == rc.CHANGED and (await _check(world))["names"]["identifier"] == "notes-mcp-evil"


async def test_keeping_with_nothing_to_keep_is_refused(world):
    await _install(world)
    with pytest.raises(capability_dossier.DossierError) as none:
        await capability_dossier.accept_source("src1", "0" * 64)
    assert none.value.code == "no_source_problem"


async def test_a_start_is_stopped_before_any_listing_and_parked_in_arslans_words(world, monkeypatch):
    await _install(world)
    world.answers.append(404)
    listed = []

    async def fake_list(server, cursor=None):
        listed.append(cursor)
        return SimpleNamespace(tools=[types.Tool(name="read", inputSchema={"type": "object"})], nextCursor=None)
    monkeypatch.setattr(session.manager, "list_tools", fake_list)
    with pytest.raises(rc.SourceChanged) as stopped:
        await discovery.connect_and_discover(1)
    assert listed == []
    state, line = supervisor_mod.classify(stopped.value, server={"transport": "stdio"}, non_json=0, budget_s=60)
    assert (state, line) == ("parked", rc.LINES[rc.WITHDRAWN]) and supervisor_mod.safe_reason(line) == line
    assert supervisor_mod.safe_reason(rc.LINES[rc.CHANGED]) == rc.LINES[rc.CHANGED]
