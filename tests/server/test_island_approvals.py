"""0.1.55 decision 3: the island answers every card except a risky one.

Risky = it deletes, sends, pays, buys, transfers or submits (and anything this rule
does not know). Those show "Open in Arslan"; approving one from the island is refused
by the server, not only hidden by the page. Declining is always allowed.
Frames come from the real protocol builders, so a field rename breaks this test.
"""
import asyncio

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from server import auth
from server.api.approvals import router
from server.db.models import PermissionGrant
from server.services import approvals, permission_store, permissions
from server.ws import protocol


@pytest.fixture(autouse=True)
def _clean():
    approvals._reset_for_tests()
    yield
    approvals._reset_for_tests()


def cmd(text: str, **kw) -> dict:
    return protocol.propose_run_command("c1", text, [], **kw)


@pytest.mark.parametrize("frame, ok", [
    # Harmless or merely changing local things: the island may approve.
    (protocol.propose_workspace_write("w", "~/Arslan", "write", "notes.md"), True),
    (protocol.propose_schedule("s", "Morning brief", "cron: 0 9 * * *"), True),
    (protocol.propose_action("a", "browser_site", "example.com", ""), True),
    (protocol.propose_action("a", "desktop_look", "Notes", ""), True),
    (protocol.propose_action("a", "desktop_app", "Notes", ""), True),
    (protocol.propose_action("a", "mac_shortcut", "Morning", ""), True),
    (cmd("git status"), True),                                  # shown under "ask for everything"
    (cmd("ffmpeg -i a.mov b.mp4"), True),
    (cmd("brew list"), True),
    # Risky: delete, send, publish, reach elsewhere, install, control apps.
    (protocol.propose_action("a", "desktop_risky", "Mail · Send", "click Send"), False),
    (protocol.propose_action("a", "mac_script", "Finder", 'tell application "Finder" to delete file "a.txt"'), False),
    (protocol.propose_action("a", "mac_script", "Mail", 'tell application "Mail" to send theMessage'), False),
    (protocol.propose_action("a", "mac_script", "Finder", 'do shell script "ls"'), False),
    (cmd("rm notes.txt"), False),
    (cmd("ls && rm -r build"), False),                         # the second command decides
    (cmd("git push origin main"), False),
    (cmd("curl -X POST https://example.test/api"), False),
    (cmd("mail -s hi someone@example.test"), False),
    (cmd("osascript -e 'tell app \"Finder\" to get name'"), False),   # could send/delete; read it in Arslan
    (cmd("brew install wget"), False),
    (cmd("ls", remote_host="192.168.1.8"), False),
    (cmd("mv a.txt ~/Desktop/", sandbox="outside", why="move it"), False),
    ({"type": "propose_something_new", "call_id": "n"}, False),
])
def test_what_the_island_may_answer(frame, ok):
    assert approvals.island_may_answer(frame) is ok


def test_a_harmless_applescript_that_only_reads_is_answerable():
    # A false-positive guard: reading a name is not risky.
    frame = protocol.propose_action("a", "mac_script", "Notes", 'tell application "Notes" to get name of every note')
    assert approvals.island_may_answer(frame) is True


@pytest.fixture
async def api(monkeypatch):
    monkeypatch.setattr(auth, "active_token", lambda: "synthetic-island-token")
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                headers={"Authorization": "Bearer synthetic-island-token"}) as client:
        yield client


async def test_a_risky_card_is_refused_from_the_island_but_declinable_and_approvable_in_arslan(api):
    risky = approvals.open_card("c", protocol.propose_run_command("r1", "rm old.txt", []), broadcast=False)
    safe = approvals.open_card("c", protocol.propose_schedule("s1", "Brief", "every: 3600"), broadcast=False)
    listed = {row["call_id"]: row for row in (await api.get("/api/v1/approvals/pending")).json()}
    assert listed["r1"]["island_ok"] is False and listed["s1"]["island_ok"] is True

    refused = await api.post("/api/v1/approvals/r1/answer", json={"approve": True, "source": "island"})
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "open_in_arslan"
    assert not risky.future.done()                                  # nothing was decided

    assert (await api.post("/api/v1/approvals/s1/answer", json={"approve": True, "source": "island"})).status_code == 200
    assert safe.future.result()["approved"] is True and safe.future.result()["by"] == "island"

    # Declining a risky card from the island is fine: saying no is always safe.
    assert (await api.post("/api/v1/approvals/r1/answer", json={"approve": False, "source": "island"})).status_code == 200
    assert risky.future.result()["approved"] is False


async def test_the_inbox_inside_arslan_may_approve_a_risky_card(api):
    risky = approvals.open_card("c", protocol.propose_run_command("r2", "rm old.txt", []), broadcast=False)
    assert (await api.post("/api/v1/approvals/r2/answer", json={"approve": True, "source": "inbox"})).status_code == 200
    assert risky.future.result() == {"approved": True, "remember": False, "scope": None, "note": "",
                                     "by": "inbox"}
    await asyncio.sleep(0)


def test_a_running_job_tells_the_island_which_job_to_stop():
    from server.services import desktop_status
    desktop_status._reset_for_tests()
    with desktop_status.working("c", title="Collect postings", kind="job", job_id="job-42"):
        (activity,) = desktop_status.island_feed()["active"]
        assert activity["job_id"] == "job-42" and activity["kind"] == "job"
    with desktop_status.working("c"):
        assert desktop_status.island_feed()["active"][0]["job_id"] is None   # a turn has no job to stop
    desktop_status._reset_for_tests()


def test_the_job_runner_passes_its_id():
    # Source check on purpose: running a real job needs a model; the call site is one line.
    import inspect

    from server.services import background_jobs
    assert "job_id=job.job_id" in inspect.getsource(background_jobs)


# ── 0.1.61 CI fix wave F3 (spec §A4): the island answers a decide card by its permission kind ──
# "The island answers Once (For this task) or No for folder, app (look and act, merged), screen,
# MCP tool, schedule, site and Shortcut cards. Everything else opens Arslan." A card that
# permissions.decide shows carries `perm_kind`: that alone decides, never the legacy `kind` the
# caller's frame may keep (③Hands' frames keep theirs) — a takeover is answered in Arslan.

ISLAND_KINDS = {"folder", "app", "screen", "mcp_tool", "schedule", "site", "shortcut"}


def decided(perm_kind, legacy=None, detail=""):
    """A card as permissions.decide shows it: the caller's frame, or the generic one, plus its
    permission kind."""
    return protocol.propose_action("d1", legacy or perm_kind, "target", detail) | {
        "perm_kind": perm_kind, "options": ["once"]}


@pytest.mark.parametrize("kind", sorted(permissions.KINDS))
def test_a_decide_card_is_answerable_from_the_island_by_its_permission_kind(kind):
    assert approvals.island_may_answer(decided(kind)) is (kind in ISLAND_KINDS)


@pytest.mark.parametrize("legacy, perm_kind, ok", [
    ("desktop_takeover", "takeover", False),          # the legacy table alone says yes
    ("mac_script", "app", True),
    ("mac_script", "app_risky", False),               # ...and to these two as well
    ("mac_script", "money", False),
    ("desktop_risky", "money", False),
    ("desktop_risky", "app_risky", False),
    ("desktop_app", "app", True),
    ("desktop_look", "app", True),
    ("browser_site", "site", True),
    ("mac_shortcut", "shortcut", True),
    ("browser_site", "send", False),
    # A legacy kind that is itself a permission kind's name never stands in for the card's own.
    ("app", "money", False),
    ("app", "takeover", False),
    ("site", "send", False),
    ("folder", "destructive", False),
    ("app", "command", False),                        # and a card kind that passes the gate, but is no island kind
    ("site", "workspace_write", False),
    ("money", "app", True),
])
def test_on_a_decide_card_the_permission_kind_decides_never_the_legacy_kind(legacy, perm_kind, ok):
    frame = decided(perm_kind, legacy, 'tell application "Notes" to get name of every note')
    assert approvals.island_may_answer(frame) is ok


LEGACY_KINDS = sorted(permissions.KINDS) + ["desktop_takeover", "desktop_risky", "desktop_app", "desktop_look",
                                            "browser_site", "mac_shortcut", "mac_script", "made_up"]


def test_whatever_legacy_kind_a_decide_card_keeps_its_permission_kind_alone_decides():
    """Every legacy kind a caller's frame may keep, with every permission kind — including a legacy
    kind that is itself a permission kind's name (the generic frame's own)."""
    wrong = [(legacy, perm_kind) for legacy in LEGACY_KINDS for perm_kind in sorted(permissions.KINDS)
             if approvals.island_may_answer(decided(perm_kind, legacy)) is not (perm_kind in ISLAND_KINDS)]
    assert wrong == []


@pytest.mark.parametrize("frame, ok", [
    # A card without a permission kind: the 0.1.55 table, unchanged (③Hands' legacy cards).
    (protocol.propose_action("a", "desktop_takeover", "Keynote", "about 5 minutes"), True),
    (protocol.propose_action("a", "mac_script", "Finder", 'tell application "Finder" to delete file "a.txt"'), False),
    (protocol.propose_action("a", "mac_script", "Notes", 'tell application "Notes" to get name'), True),
    # Other card types keep their own rule, whatever permission kind they carry.
    (protocol.propose_workspace_write("w", "~/Arslan", "write", "notes.md") | {"perm_kind": "workspace_write"}, True),
    (protocol.propose_schedule("s", "Morning brief", "cron: 0 9 * * *") | {"perm_kind": "schedule"}, True),
    (cmd("git status") | {"perm_kind": "command"}, True),
    (cmd("rm notes.txt") | {"perm_kind": "command"}, False),
    # A permission kind that is not a kind's name: never answerable, never an error.
    (protocol.propose_action("a", "desktop_app", "Notes", "") | {"perm_kind": ["app"]}, False),
    (protocol.propose_action("a", "desktop_app", "Notes", "") | {"perm_kind": None}, False),
])
def test_what_else_the_island_may_answer_is_unchanged(frame, ok):
    assert approvals.island_may_answer(frame) is ok


# ── PR 2 fix wave 2 (M4): a card's permission kind gates every card type ─────────────────────────
# PR 3a routes category cards (send, destructive, system, opaque, other_agent, …) through
# `propose_run_command` frames. Their permission kind refuses the island whatever the command
# text reads like — and the same for the other frame types a caller may attach.

CARD_OWN_KINDS = {"command", "workspace_write"}        # besides the island's seven: those cards' own
NOT_THE_ISLANDS = sorted(permissions.KINDS - ISLAND_KINDS - CARD_OWN_KINDS)
CARD_TYPES = {
    "write": lambda: protocol.propose_workspace_write("w", "~/Arslan", "write", "notes.md"),
    "schedule": lambda: protocol.propose_schedule("s", "Morning brief", "cron: 0 9 * * *"),
    "harmless_command": lambda: cmd("git status"),
}


def test_the_cards_below_run_over_the_kinds_the_spec_sends_to_arslan():
    # Not vacuous: money, send, delete, a risky step, a takeover, leaving the sandbox, system changes,
    # other agents' settings, new capabilities, another machine, opaque code (§A4).
    assert {"money", "send", "destructive", "app_risky", "takeover", "outside", "system", "other_agent",
            "capability", "remote", "opaque"} <= set(NOT_THE_ISLANDS)
    assert not set(NOT_THE_ISLANDS) & (ISLAND_KINDS | CARD_OWN_KINDS)


@pytest.mark.parametrize("card_type", sorted(CARD_TYPES))
@pytest.mark.parametrize("kind", NOT_THE_ISLANDS)
def test_a_card_of_a_kind_the_island_does_not_answer_is_not_answerable_whatever_its_type(kind, card_type):
    frame = CARD_TYPES[card_type]() | {"perm_kind": kind}
    assert approvals.island_may_answer(frame) is False


@pytest.mark.parametrize("card_type, kind", [
    ("write", "workspace_write"), ("schedule", "schedule"), ("harmless_command", "command"),
    # A folder, site or app card may ride on a command frame: the command's own rule then decides.
    *[("harmless_command", kind) for kind in sorted(ISLAND_KINDS)],
])
def test_a_card_of_a_kind_the_island_may_answer_keeps_its_types_own_rule(card_type, kind):
    frame = CARD_TYPES[card_type]() | {"perm_kind": kind}
    assert approvals.island_may_answer(frame) is True


@pytest.mark.parametrize("perm_kind", [None, "", 0, False, ["command"], {"app": 1}, b"command", "Command",
                                       " command", "command\u200b", float("nan")])
@pytest.mark.parametrize("card_type", sorted(CARD_TYPES))
def test_a_permission_kind_that_is_no_kinds_name_is_never_answerable_on_any_card_type(card_type, perm_kind):
    """Fail-closed, and never an error (a list is not hashable): a card that carries a permission
    kind says what it is, or the island does not answer it."""
    assert approvals.island_may_answer(CARD_TYPES[card_type]() | {"perm_kind": perm_kind}) is False


@pytest.mark.parametrize("kind", sorted(ISLAND_KINDS | CARD_OWN_KINDS))
@pytest.mark.parametrize("frame", [
    cmd("rm notes.txt"),
    cmd("git push origin main"),
    cmd("ls", remote_host="192.168.1.8"),
    cmd("mv a.txt ~/Desktop/", sandbox="outside", why="move it"),
    {"type": "propose_something_new", "call_id": "n"},
], ids=["delete", "push", "remote", "outside", "unknown-type"])
def test_a_permission_kind_the_island_answers_does_not_open_what_the_types_own_rule_closes(kind, frame):
    assert approvals.island_may_answer(frame | {"perm_kind": kind}) is False


async def _waiting_card(decision_call) -> tuple[asyncio.Task, dict]:
    """Start a decide call on a job's card surface (every window, the Inbox, the island); return
    it and its card once the card waits."""
    async def on_the_jobs_surface():
        with permissions.asking_with(approvals.BroadcastAsker("conv-i")):
            return await decision_call()
    task = asyncio.create_task(on_the_jobs_surface())
    for _ in range(300):
        if approvals.all_pending():
            [row] = approvals.all_pending()
            return task, row
        await asyncio.sleep(0.01)
    raise AssertionError("no card was shown")


async def _grants(maker):
    async with maker() as db:
        assert await permission_store.list_rules(db) == []         # the island never stores "Always"
        return sorted((g.task_id, g.kind, g.target) for g in (await db.scalars(select(PermissionGrant))).all())


@pytest.mark.parametrize("kind, legacy, target", [("app", "desktop_app", "com.apple.Notes"),
                                                  ("site", "browser_site", "example.com")])
async def test_the_islands_yes_to_an_app_or_a_site_card_holds_for_the_task(execution_db, api, kind, legacy, target):
    request = permissions.Request(kind=kind, target=target, title="Go ahead?", always_label=target,
                                  frame=protocol.propose_action("x1", legacy, target, "look, then click"))
    context = permissions.Context(conversation_id="conv-i", job_id="job-i")
    asked, row = await _waiting_card(lambda: permissions.decide(request, context))
    assert row["island_ok"] is True and row["frame"]["options"][0] == "task"
    answered = await api.post(f"/api/v1/approvals/{row['call_id']}/answer",
                              json={"approve": True, "source": "island", "scope": "always"})
    assert answered.status_code == 200
    decision = await asyncio.wait_for(asked, 2)
    assert (decision.allowed, decision.by, decision.scope) == (True, "user", "task")
    assert await _grants(execution_db) == [("job-i", kind, target)]


async def test_the_islands_yes_to_a_many_app_card_holds_for_the_task_for_every_app(execution_db, api):
    apps = [permissions.Request(kind="app", target=bundle, title=f"Use {bundle}?", always_label=bundle)
            for bundle in ("com.apple.Notes", "com.apple.mail")]
    context = permissions.Context(conversation_id="conv-i", job_id="job-i")
    asked, row = await _waiting_card(lambda: permissions.decide_many(apps, context, title="Use Notes and Mail?"))
    assert row["island_ok"] is True and row["frame"]["kind"] == "app"
    answered = await api.post(f"/api/v1/approvals/{row['call_id']}/answer",
                              json={"approve": True, "source": "island", "scope": "conversation"})
    assert answered.status_code == 200
    decisions = await asyncio.wait_for(asked, 2)
    assert [(d.allowed, d.scope) for d in decisions] == [(True, "task"), (True, "task")]
    assert await _grants(execution_db) == [("job-i", "app", "com.apple.Notes"), ("job-i", "app", "com.apple.mail")]


@pytest.mark.parametrize("kind, legacy", [("takeover", "desktop_takeover"), ("app_risky", "desktop_risky"),
                                          ("money", "desktop_risky")])
async def test_the_island_cannot_approve_a_takeover_a_risky_step_or_money(execution_db, api, kind, legacy):
    request = permissions.Request(kind=kind, target="com.apple.Keynote", title="Go ahead?",
                                  frame=protocol.propose_action("x2", legacy, "Keynote", "click Buy"))
    asked, row = await _waiting_card(lambda: permissions.decide(
        request, permissions.Context(conversation_id="conv-i", job_id="job-i")))
    assert row["island_ok"] is False
    refused = await api.post(f"/api/v1/approvals/{row['call_id']}/answer",
                             json={"approve": True, "source": "island"})
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "open_in_arslan"
    assert not asked.done()                                          # nothing was decided
    declined = await api.post(f"/api/v1/approvals/{row['call_id']}/answer",
                              json={"approve": False, "source": "island"})
    assert declined.status_code == 200                               # saying no is always safe
    decision = await asyncio.wait_for(asked, 2)
    assert (decision.allowed, decision.by) == (False, "user")
    assert await _grants(execution_db) == []


# ── PR 2 fix wave 2 (M3 Z2, M4): the same, through the real card and the real endpoint ─────────────

async def _island_cannot_approve_but_can_decline(execution_db, api, asked, row, kind) -> None:
    assert row["frame"]["perm_kind"] == kind and row["island_ok"] is False
    refused = await api.post(f"/api/v1/approvals/{row['call_id']}/answer",
                             json={"approve": True, "source": "island"})
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "open_in_arslan"
    assert not asked.done()                                          # nothing was decided
    declined = await api.post(f"/api/v1/approvals/{row['call_id']}/answer",
                              json={"approve": False, "source": "island"})
    assert declined.status_code == 200                               # saying no is always safe
    decision = await asyncio.wait_for(asked, 2)
    assert (decision.allowed, decision.by) == (False, "user")
    assert await _grants(execution_db) == []


@pytest.mark.parametrize("kind, own", [("money", "app"), ("takeover", "site"), ("app_risky", "folder")])
async def test_a_callers_own_frame_cannot_give_its_card_a_permission_kind_the_island_answers(
        execution_db, api, kind, own):
    frame = protocol.propose_action("h1", "desktop_app", "Keynote", "click Buy") | {"perm_kind": own}
    request = permissions.Request(kind=kind, target="com.apple.Keynote", title="Go ahead?", frame=frame)
    asked, row = await _waiting_card(lambda: permissions.decide(
        request, permissions.Context(conversation_id="conv-i", job_id="job-i")))
    await _island_cannot_approve_but_can_decline(execution_db, api, asked, row, kind)


@pytest.mark.parametrize("card_type", sorted(CARD_TYPES))
@pytest.mark.parametrize("kind", ["send", "destructive", "system", "opaque", "other_agent", "capability",
                                  "outside", "remote", "money", "takeover", "app_risky"])
async def test_the_island_cannot_approve_a_category_card_whatever_frame_it_rides_on(
        execution_db, api, kind, card_type):
    """PR 3a: a send, delete or system card rides on a `propose_run_command` frame, and the command
    may read harmlessly ("git status"). The card's permission kind decides: it opens Arslan."""
    request = permissions.Request(kind=kind, target=f"t-{kind}", title="Go ahead?", frame=CARD_TYPES[card_type]())
    asked, row = await _waiting_card(lambda: permissions.decide(
        request, permissions.Context(conversation_id="conv-i", job_id="job-i")))
    await _island_cannot_approve_but_can_decline(execution_db, api, asked, row, kind)
