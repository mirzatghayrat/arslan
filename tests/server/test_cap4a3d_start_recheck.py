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


def _entry(packages=None, remotes=None, status=None, version="1.2.0", name="com.example/notes"):
    meta = {"io.modelcontextprotocol.registry/official": {"status": status}} if status else {}
    return {"server": {"name": name, "version": version, "packages": packages or [],
                       "remotes": remotes or []}, "_meta": meta}


SAME = _entry(packages=[{"registryType": "pypi", "identifier": "notes-mcp", "version": "1.2.0"}])
WITHDRAWN = _entry(packages=SAME["server"]["packages"], status="deleted")
URL = {"type": "streamable-http", "url": "https://mcp.example.com/notes"}
ELSEWHERE = {"type": "streamable-http", "url": "https://elsewhere.example.net/notes"}


def _cloud(*remotes):
    return _entry(remotes=list(remotes), name="com.example/notes-cloud", version="2.0.0")


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
        if isinstance(answer, tuple):                           # (status, raw body)
            return httpx.Response(answer[0], content=answer[1])
        return httpx.Response(200, json=answer)
    real = httpx.AsyncClient
    monkeypatch.setattr(rc.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return SimpleNamespace(maker=execution_db, answers=answers, calls=calls)


async def _install(world, cand=PKG, *, days_ago=2, test=None, state="installed"):
    async with world.maker() as s:
        s.add(MCPServer(id=1, label="notes", command="x", args=[], status="registered"))
        await s.flush()
        s.add(CapabilitySource(id="src1", kind="mcp", name="notes", candidate_id=cand.get("id", "c"),
                               runtime=cand.get("runtime"), needs={}, grants={}, state=state, mcp_server_id=1,
                               candidate=cand or None, test=test, installed_at=datetime.utcnow(),
                               checked_at=datetime.utcnow() - timedelta(days=days_ago), created_at=datetime.utcnow()))
        await s.commit()


async def _check(world):
    async with world.maker() as s:
        return ((await s.get(CapabilitySource, "src1")).test or {}).get("registry_check") or {}


async def test_the_same_entry_starts_and_is_not_asked_again_within_a_day(world):
    await _install(world)
    world.answers.append(SAME)
    await rc.before_start(1)
    assert world.calls == ["https://registry.modelcontextprotocol.io/v0/servers/com.example%2Fnotes/versions/1.2.0"
                           "?include_deleted=true"]      # #604 re-check 3: without it, a deleted version answers 404
    check = await _check(world)
    assert check["problem"] is None and check["arslan"] == "0.1.64" and check["at"].endswith("Z")
    await rc.before_start(1)
    assert len(world.calls) == 1


async def _age(world, days=2, **check):
    """The recorded check, made `days` ago (and changed by `check`)."""
    async with world.maker() as s:
        row = await s.get(CapabilitySource, "src1")
        old = row.test["registry_check"]
        when = (datetime.utcnow() - timedelta(days=days)).isoformat() + "Z"
        row.test = {**row.test, "registry_check": {**old, "at": when, **check}}
        await s.commit()


async def test_the_installs_own_start_records_the_cards_check_and_an_update_asks(world, monkeypatch):
    """#604 review F5: a server installed less than a day before an update was not asked at the first start after
    it, since no Arslan version was recorded for it."""
    await _install(world, days_ago=0)
    await rc.before_start(1)
    check = await _check(world)
    assert world.calls == [] and check["arslan"] == "0.1.64" and check["problem"] is None
    monkeypatch.setattr(config, "_app_version", lambda: "0.1.65")
    world.answers.append(SAME)
    await rc.before_start(1)
    assert len(world.calls) == 1 and (await _check(world))["arslan"] == "0.1.65"


@pytest.mark.parametrize("where", ["the check", "the install"])
async def test_a_check_dated_in_the_future_is_due(world, where):
    """#604 review F5: a clock set back since made `now - at` negative, and nothing was asked again."""
    future = datetime.utcnow() + timedelta(days=3)
    if where == "the check":
        await _install(world, test={"registry_check": {"at": future.isoformat() + "Z", "arslan": "0.1.64",
                                                       "problem": None}})
    else:
        await _install(world, days_ago=-3)
    world.answers.append(SAME)
    await rc.before_start(1)
    assert len(world.calls) == 1


async def test_a_source_whose_test_failed_is_asked_too(world):
    """#604 review F2: only `installed` sources were asked; one kept after a failed test can be switched on."""
    await _install(world, state="failed")
    world.answers.append(WITHDRAWN)
    with pytest.raises(rc.SourceChanged):
        await rc.before_start(1)


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


async def test_a_withdrawn_entry_parks_it_and_so_does_every_start_that_day(world):
    """#604 review F7 (M23): the park holds on a start that asks nothing (the probe, Reconnect, a restart)."""
    await _install(world)
    world.answers.append(WITHDRAWN)
    with pytest.raises(rc.SourceChanged) as stopped:
        await rc.before_start(1)
    assert stopped.value.problem == rc.WITHDRAWN and stopped.value.line == rc.LINES[rc.WITHDRAWN]
    assert (await _check(world))["problem"] == rc.WITHDRAWN
    with pytest.raises(rc.SourceChanged):
        await rc.before_start(1)
    assert len(world.calls) == 1


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
    world.answers += [_cloud(URL), _cloud(ELSEWHERE)]
    await rc.before_start(1)
    await _age(world)
    with pytest.raises(rc.SourceChanged):
        await rc.before_start(1)


@pytest.mark.parametrize("first, second, parked", [(URL, ELSEWHERE, False), (ELSEWHERE, URL, True)])
async def test_the_first_remote_is_the_one_compared(world, first, second, parked):
    """#604 review F7 (M30): the search installs `remotes[0]`, so the check compares that one."""
    await _install(world, REMOTE)
    world.answers.append(_cloud(first, second))
    if parked:
        with pytest.raises(rc.SourceChanged):
            await rc.before_start(1)
    else:
        await rc.before_start(1)


@pytest.mark.parametrize("parked", [False, True])
async def test_the_first_package_of_the_type_is_the_one_compared(world, parked):
    """#604 review F7 (M31): the search installs the first runnable package, so the check compares that one."""
    same, other = SAME["server"]["packages"][0], {"registryType": "pypi", "identifier": "notes-mcp-evil", "version": "1"}
    await _install(world)
    world.answers.append(_entry(packages=[other, same] if parked else [same, other]))
    if parked:
        with pytest.raises(rc.SourceChanged):
            await rc.before_start(1)
    else:
        await rc.before_start(1)


NOT_THE_ENTRY = {
    "5xx": 503, "unreachable": httpx.ConnectError("down"), "a 404": 404, "a plain-text 404": (404, b"page not found"),
    "an HTML page": (200, b"<html>portal</html>"), "a null body": None, "an empty object": {},
    "an error object": {"error": "rate limited"}, "an empty server": {"server": {}}, "a list of servers": {"servers": []},
    "another version": _entry(packages=SAME["server"]["packages"], version="9.9.9"),
    "another name": _entry(packages=SAME["server"]["packages"], name="com.example/other"),
    "a list": [], "a string": "x", "a number": 1, "a null server": {"server": None},
    "a null package": {"server": {"name": "com.example/notes", "version": "1.2.0", "packages": [None]}},
    "withdrawn, but another version": _entry(status="deleted", version="9.9.9"),
    # #604 re-check 1: the entry asked for, but in a shape the parser only half understands.
    "packages as an object": {"server": {"name": "com.example/notes", "version": "1.2.0", "packages": {}}},
    "packages as an empty string": {"server": {"name": "com.example/notes", "version": "1.2.0", "packages": ""}},
    "packages as 0": {"server": {"name": "com.example/notes", "version": "1.2.0", "packages": 0}},
    "packages as false": {"server": {"name": "com.example/notes", "version": "1.2.0", "packages": False}},
    "a renamed registryType": _entry(packages=[{"registry_type": "pypi", "identifier": "notes-mcp", "version": "1.2.0"}]),
    "a renamed identifier": _entry(packages=[{"registryType": "pypi", "name": "notes-mcp", "version": "1.2.0"}]),
    "no packages at all": _entry(),
}


@pytest.mark.parametrize("failure", list(NOT_THE_ENTRY.values()), ids=list(NOT_THE_ENTRY))
async def test_no_answer_starts_a_server_that_passed_and_asks_again_next_time(world, failure):
    """#604 review F1 (and M26): only the entry asked for decides; anything else was recorded as withdrawn or
    changed, so one change on the Registry's side parked every installed server."""
    await _install(world)
    world.answers += [failure, SAME]
    await rc.before_start(1)
    assert await _check(world) == {}                            # nothing recorded: the next start asks again
    await rc.before_start(1)
    assert len(world.calls) == 2 and (await _check(world))["problem"] is None


@pytest.mark.parametrize("answer", [_cloud(), _cloud({"type": "streamable-http"}), _cloud({"type": "sse", "uri": "x"})],
                         ids=["no remotes", "a remote without its URL", "a renamed URL field"])
async def test_a_remote_entry_that_names_no_url_is_no_answer(world, answer):
    """#604 re-check 1: for a remote install, an entry with no remote URL the parser can read is not a change."""
    await _install(world, REMOTE)
    world.answers.append(answer)
    await rc.before_start(1)
    assert await _check(world) == {}


@pytest.mark.parametrize("failure", [404, httpx.ConnectError("down")], ids=["a 404", "unreachable"])
async def test_no_answer_keeps_a_parked_server_parked(world, failure):
    await _install(world)
    world.answers += [WITHDRAWN, failure]
    with pytest.raises(rc.SourceChanged):
        await rc.before_start(1)
    await _age(world)                                            # a day later, the Registry does not answer
    with pytest.raises(rc.SourceChanged):
        await rc.before_start(1)
    assert len(world.calls) == 2


@pytest.mark.parametrize("cand", [{**PKG, "id": "github:acme/notes"}, None], ids=["not from the Registry", "no card"])
async def test_a_server_with_no_registry_entry_is_not_asked(world, cand):
    await _install(world, cand or {})
    await rc.before_start(1)
    assert world.calls == []


async def test_a_hand_added_server_on_a_reused_number_is_not_asked(world):
    """#577 re-check G2: a stale source keeps its server's number; a server added by hand on it later is not its."""
    long_ago = datetime.utcnow() - timedelta(days=30)
    async with world.maker() as s:
        s.add(CapabilitySource(id="old", kind="mcp", name="notes", candidate_id=PKG["id"], runtime="uv", needs={},
                               grants={}, state="installed", mcp_server_id=3, candidate=PKG, created_at=long_ago,
                               installed_at=long_ago, checked_at=long_ago))
        s.add(MCPServer(id=3, label="added by hand", command="z", args=[], status="registered",
                        created_at=datetime.utcnow()))
        await s.commit()
    await rc.before_start(3)
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
    world.answers += [WITHDRAWN, WITHDRAWN, _entry(packages=[{"registryType": "pypi", "identifier": "other",
                                                              "version": "9"}])]
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


async def test_a_clean_answer_ends_a_keep_so_a_later_withdrawal_parks_again(world, monkeypatch):
    """#604 review F4: the keep was carried forward on every answer, and "withdrawn" has one digest, so keeping one
    withdrawal also kept every later one."""
    from server.services import mcp_service

    async def restart(server_id):
        return None
    monkeypatch.setattr(mcp_service, "restart_after_edit", restart)
    await _install(world)
    world.answers += [WITHDRAWN, SAME, WITHDRAWN]
    with pytest.raises(rc.SourceChanged):
        await rc.before_start(1)
    await capability_dossier.accept_source("src1", (await _check(world))["seen"])
    await _age(world)
    await rc.before_start(1)                                     # restored: clean, and the keep ends
    assert (await _check(world))["accepted"] is None
    await _age(world)
    with pytest.raises(rc.SourceChanged):                        # withdrawn again: parked again
        await rc.before_start(1)


async def test_a_keep_holds_until_the_entry_changes_however_old(world, monkeypatch):
    """The user, 2026-11-01: no expiry (KEEP_FOR removed). A keep dated long ago, in the shape an earlier draft
    stored, still holds while the Registry gives the same answer."""
    from server.services import mcp_service

    async def restart(server_id):
        return None
    monkeypatch.setattr(mcp_service, "restart_after_edit", restart)
    await _install(world)
    world.answers += [WITHDRAWN, WITHDRAWN]
    with pytest.raises(rc.SourceChanged):
        await rc.before_start(1)
    await capability_dossier.accept_source("src1", (await _check(world))["seen"])
    check = await _check(world)
    assert check["accepted"] == {"seen": check["seen"]}
    async with world.maker() as s:
        row = await s.get(CapabilitySource, "src1")
        row.test = {**row.test, "registry_check": {**check, "accepted": {**check["accepted"],
                                                                         "at": "2020-01-01T00:00:00Z"}}}
        await s.commit()
    await rc.before_start(1)
    await _age(world)
    await rc.before_start(1)                                     # asked again, withdrawn again: still kept
    assert len(world.calls) == 2


@pytest.mark.parametrize("keep", [None, "yes", {}, {"seen": None}, {"seen": ""}, {"seen": "0" * 64}])
async def test_only_a_keep_of_that_very_answer_holds(world, keep):
    await _install(world)
    world.answers.append(WITHDRAWN)
    with pytest.raises(rc.SourceChanged):
        await rc.before_start(1)
    check = await _check(world)
    async with world.maker() as s:
        row = await s.get(CapabilitySource, "src1")
        row.test = {**row.test, "registry_check": {**check, "accepted": keep}}
        await s.commit()
    with pytest.raises(rc.SourceChanged):
        await rc.before_start(1)


async def test_a_check_with_no_digest_is_never_kept(world):
    """A stored check whose digest is missing matches no keep, not even one with no digest either."""
    await _install(world)
    world.answers.append(WITHDRAWN)
    with pytest.raises(rc.SourceChanged):
        await rc.before_start(1)
    check = await _check(world)
    async with world.maker() as s:
        row = await s.get(CapabilitySource, "src1")
        row.test = {**row.test, "registry_check": {**check, "seen": None, "accepted": {"seen": None}}}
        await s.commit()
    with pytest.raises(rc.SourceChanged):
        await rc.before_start(1)


async def test_keeping_with_nothing_to_keep_is_refused(world):
    await _install(world)
    with pytest.raises(capability_dossier.DossierError) as none:
        await capability_dossier.accept_source("src1", "0" * 64)
    assert none.value.code == "no_source_problem"


async def test_a_start_is_stopped_before_any_listing_and_parked_in_arslans_words(world, monkeypatch):
    await _install(world)
    world.answers.append(WITHDRAWN)
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
    for reason in rc.LINES.values():                             # only the user ends it, never Reconnect
        fix = supervisor_mod.fix_for("parked", has_headers=False, reason=reason)
        assert "reviews it in Capabilities" in fix and "Reconnect does not start it" in fix


# ── #604's web half, server side: the source view says what parked a server and what a keep sends ──
# The page's row and its keep button read `registry_parked` and need no rule of their own (#604 review F6).

_CLIENT = httpx.AsyncClient                  # the real client: `world` patches httpx's own AsyncClient


def _no_restart(monkeypatch):
    from server.services import mcp_service
    restarted = []

    async def restart(server_id):
        restarted.append(server_id)
    monkeypatch.setattr(mcp_service, "restart_after_edit", restart)
    return restarted


async def _view(world):
    return capability_dossier.view(await capability_dossier.source("src1"))


async def _parked_by(world, answer, cand=PKG):
    await _install(world, cand)
    world.answers.append(answer)
    with pytest.raises(rc.SourceChanged):
        await rc.before_start(1)
    return await _check(world)


async def test_the_view_shows_a_withdrawn_entry_and_the_digest_a_keep_sends(world):
    check = await _parked_by(world, WITHDRAWN)
    assert (await _view(world))["registry_parked"] == {
        "why": "withdrawn", "seen": check["seen"], "checked_at": check["at"],
        "installed": {"registry_type": "pypi", "identifier": "notes-mcp", "version": "1.2.0"}, "now": None}


async def test_the_view_shows_what_a_changed_entry_names_now(world):
    check = await _parked_by(world, _entry(packages=[{"registryType": "pypi", "identifier": "notes-mcp-next",
                                                      "version": "1.2.0"}]))
    parked = (await _view(world))["registry_parked"]
    assert parked["why"] == "changed" and parked["seen"] == check["seen"]
    assert parked["installed"] == {"registry_type": "pypi", "identifier": "notes-mcp", "version": "1.2.0"}
    assert parked["now"] == {"registry_type": "pypi", "identifier": "notes-mcp-next", "version": "1.2.0"}


async def test_a_changed_remote_shows_both_urls(world):
    await _parked_by(world, _cloud(ELSEWHERE), cand=REMOTE)
    parked = (await _view(world))["registry_parked"]
    assert parked["installed"] == {"url": URL["url"]} and parked["now"] == {"url": ELSEWHERE["url"]}


@pytest.mark.parametrize("state", ["the same entry", "kept", "never asked", "no answer"])
async def test_nothing_parked_shows_nothing(world, monkeypatch, state):
    _no_restart(monkeypatch)
    await _install(world)
    if state == "the same entry":
        world.answers.append(SAME)
        await rc.before_start(1)
    elif state == "kept":
        world.answers.append(WITHDRAWN)
        with pytest.raises(rc.SourceChanged):
            await rc.before_start(1)
        await capability_dossier.accept_source("src1", (await _check(world))["seen"])
    elif state == "no answer":
        world.answers.append(503)
        await rc.before_start(1)
    assert (await _view(world))["registry_parked"] is None


async def test_a_kept_answer_then_another_shows_the_new_one(world, monkeypatch):
    _no_restart(monkeypatch)
    kept = (await _parked_by(world, WITHDRAWN))["seen"]
    await capability_dossier.accept_source("src1", kept)
    await _age(world)
    world.answers.append(_entry(packages=[{"registryType": "pypi", "identifier": "other", "version": "9"}]))
    with pytest.raises(rc.SourceChanged):
        await rc.before_start(1)
    parked = (await _view(world))["registry_parked"]
    assert parked["why"] == "changed" and parked["seen"] == (await _check(world))["seen"] != kept


async def test_values_the_registry_sent_are_shown_cleaned(world):
    """The row shows what the Registry wrote, so it is cleaned as the card cleans a name (UNI1): a bidi override
    or a zero-width character never reaches the page, where it could make one name read as another."""
    hidden = "notes" + chr(0x202E) + "-mcp" + chr(0x200B) + "-next"
    cand = {**PKG, "package": {**PKG["package"], "identifier": "notes-" + chr(0x2066) + "mcp"}}
    await _parked_by(world, _entry(packages=[{"registryType": "pypi", "identifier": hidden, "version": "1.2.0"}]),
                     cand=cand)
    parked = (await _view(world))["registry_parked"]
    assert parked["now"]["identifier"] == "notes-mcp-next" and parked["installed"]["identifier"] == "notes-mcp"


async def test_the_route_shows_it_and_a_keep_with_that_digest_clears_it(world, monkeypatch):
    from fastapi import FastAPI
    from server import auth
    from server.api.capabilities import router
    restarted = _no_restart(monkeypatch)
    monkeypatch.setattr(auth, "active_token", lambda: "synthetic-capabilities-token")
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    await _parked_by(world, WITHDRAWN)
    async with _CLIENT(transport=httpx.ASGITransport(app=app), base_url="http://test",
                       headers={"Authorization": "Bearer synthetic-capabilities-token"}) as client:
        listed = (await client.get("/api/v1/capability-sources")).json()
        parked = (await client.get("/api/v1/capability-sources/src1")).json()["registry_parked"]
        assert [row["registry_parked"] for row in listed] == [parked] and parked["why"] == "withdrawn"
        moved = await client.post("/api/v1/capability-sources/src1/source/accept", json={"seen": "0" * 64})
        assert moved.status_code == 409 and moved.json()["detail"] == {"code": "source_answer_moved"}
        kept = await client.post("/api/v1/capability-sources/src1/source/accept", json={"seen": parked["seen"]})
        assert kept.status_code == 200 and kept.json()["registry_parked"] is None
        assert (await client.get("/api/v1/capability-sources/src1")).json()["registry_parked"] is None
    assert restarted == [1]
