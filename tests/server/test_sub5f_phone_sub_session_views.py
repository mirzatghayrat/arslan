"""SUB5f, step 2 (the user, 2026-11-15): the phone views a conversation's sub-sessions, read-only.

What the Bridge reads for a phone (`/phone/*`, behind the API token like every phone route):
- each item of the phone's conversation list may carry `sub: {total, running, waiting}`, counted over the whole tree
  under it; an item with no sub-session has no `sub`;
- a commander's phone history may carry `details.sub_sessions: [{id, title, state, depth, parent_id}]`, the whole tree
  in the order the Mac's panel lists it, `state` in the window's words (`web/src/lib/subTree.ts` `subStatus`, with
  "reporting" read as running);
- `GET /phone/conversations/{commander}/sub-sessions/{child}/history`: one sub-session's transcript, view-only (text
  only: no files, no runs), and only through a commander whose tree it is in. Anything else is `not_found`.

It never links: the Bridge links a conversation for a phone only after `/phone/conversations/{id}/history` answers,
which a sub-session's still never does, and the Mac's socket refuses a phone's message in a sub-session (step 1). So
after a child's transcript was read, a phone message to it is still refused.
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from server.db import session as db_session
from server.db.companion_models import ConversationContext
from server.db.models import ArslanMessage, Run
from server.api import phone
from server.services import background_jobs, phone_ids, phone_reads, side_chats, sub_sessions

ROOT, KID_A, KID_B, GRANDKID = "c-commander", "sub-a", "sub-b", "sub-a1"
OTHER, OTHER_KID = "c-other", "sub-other"
LONE = "c-lone"                 # an ordinary conversation with no sub-session
GONE = "sub-gone"               # a sub-session deleted (its tombstone), once ROOT's
SIDE: dict[str, str] = {}       # the side chat under ROOT (its id is minted)


def _at(minute: int) -> datetime:
    return datetime(2026, 11, 15, 12, minute)


def history(commander: str, child: str, query: str = "") -> str:
    return f"/api/v1/phone/conversations/{commander}/sub-sessions/{child}/history{query}"


async def _family(client, monkeypatch):
    """ROOT ⟶ KID_A ⟶ GRANDKID, ROOT ⟶ KID_B; OTHER ⟶ OTHER_KID; a side chat under ROOT; a tombstone once under ROOT.
    The list's order (most recently active first) is KID_B, KID_A, GRANDKID."""
    monkeypatch.setattr(db_session, "AsyncSessionLocal", client.db_maker)
    SIDE.clear()
    async with client.db_maker() as db:
        for cid in (ROOT, OTHER, LONE):
            db.add(ConversationContext(id=cid, kind="chat"))
            db.add(ArslanMessage(conversation_id=cid, role="user", content=f"say {cid}", timestamp=_at(1)))
        await db.commit()
    for parent, child in ((ROOT, KID_A), (ROOT, KID_B), (KID_A, GRANDKID), (OTHER, OTHER_KID), (ROOT, GONE)):
        async with client.db_maker() as db:
            await sub_sessions.create_child(db, parent, child)
            await db.commit()
    async with client.db_maker() as db:
        for cid, minute in ((KID_A, 20), (KID_B, 30), (GRANDKID, 10), (OTHER_KID, 5)):
            # A brief is the commander's words, stored in the user's role (`sub_sessions.start`); framed when the
            # starting turn read outside content, its own words shown.
            db.add(ArslanMessage(conversation_id=cid, role="user", content=f"FRAMED brief {cid}",
                                 display_content=f"brief {cid}", source=sub_sessions.BRIEF_SOURCE, timestamp=_at(minute)))
        db.add(ArslanMessage(conversation_id=KID_B, role="arslan", content="all done", job_outcome="done",
                             timestamp=_at(31)))
        await sub_sessions.tombstone(db, [GONE])         # a delete removes its messages too: it has none here
        await db.commit()
        SIDE["id"] = (await side_chats.create(db, ROOT, None))["conversation_id"]
    async with client.db_maker() as db:
        db.add(ArslanMessage(conversation_id=SIDE["id"], role="user", content="a side question", timestamp=_at(40)))
        await db.commit()


@pytest.fixture
def at_work(monkeypatch):
    """KID_A waits on a card; GRANDKID has finished, its report not delivered yet (the window: running, "reporting")."""
    monkeypatch.setattr(background_jobs, "unreported", lambda: [SimpleNamespace(conversation_id=GRANDKID)])
    with sub_sessions.waiting_on_user(KID_A):
        yield
    sub_sessions._reset_for_tests()


# ------------------------------------------------------------------ the state, in the window's words

@pytest.mark.parametrize(("state", "outcome", "shown"), [
    ("working", None, "running"), ("waiting", None, "waiting"), ("done", "done", "done"), ("done_unseen", None, "done"),
    ("failed", "stopped", "stopped"), ("unfinished", "interrupted", "interrupted"), ("unfinished", "partial", "failed"),
    ("failed", None, "failed"), ("idle", None, "ended"), (None, None, "ended")])
def test_a_sub_sessions_state_reads_as_the_windows_status_icon(state, outcome, shown):
    assert phone_reads.sub_status(state, outcome) == shown
    assert shown in phone_reads.SUB_STATES


# ------------------------------------------------------------------ counts on the phone's list

async def test_each_list_item_counts_its_whole_tree(client, monkeypatch, at_work):
    await _family(client, monkeypatch)
    items = {r["id"]: r for r in (await client.get("/api/v1/phone/conversations?limit=50")).json()["conversations"]}
    assert items[ROOT]["sub"] == {"total": 3, "running": 1, "waiting": 1}     # the grandchild counts, and runs
    assert items[OTHER]["sub"] == {"total": 1, "running": 0, "waiting": 0}
    assert "sub" not in items[LONE]                                          # none: left out, not zeros
    assert not {KID_A, KID_B, GRANDKID, OTHER_KID, GONE, SIDE["id"]} & set(items)      # still never listed themselves


# ------------------------------------------------------------------ the tree in a commander's history

async def test_a_commanders_history_lists_its_whole_tree_with_depth_and_parent(client, monkeypatch, at_work):
    await _family(client, monkeypatch)
    got = (await client.get(f"/api/v1/phone/conversations/{ROOT}/history")).json()
    assert got["details"]["sub_sessions"] == [
        {"id": KID_B, "title": f"brief {KID_B}", "state": "done", "depth": 1, "parent_id": ROOT},
        {"id": KID_A, "title": f"brief {KID_A}", "state": "waiting", "depth": 1, "parent_id": ROOT},
        {"id": GRANDKID, "title": f"brief {GRANDKID}", "state": "running", "depth": 2, "parent_id": KID_A}]
    lone = (await client.get(f"/api/v1/phone/conversations/{LONE}/history")).json()
    assert "sub_sessions" not in lone["details"]
    for child in (KID_A, GRANDKID):
        refused = await client.get(f"/api/v1/phone/conversations/{child}/history")
        assert (refused.status_code, refused.json()["detail"]) == (404, "not_found")


# ------------------------------------------------------------------ one sub-session's transcript

async def test_a_sub_sessions_transcript_reads_view_only_text(client, monkeypatch):
    from server.api import phone
    await _family(client, monkeypatch)
    async with client.db_maker() as db:
        db.add(Run(id=7, conversation_id=GRANDKID, user_message="the brief", status="recorded"))
        await db.flush()
        db.add(ArslanMessage(conversation_id=GRANDKID, role="arslan", content="found it", run_id=7, timestamp=_at(11)))
        db.add(ArslanMessage(conversation_id=ROOT, role="arslan", content="started two", run_id=7, timestamp=_at(2)))
        await db.commit()
    made = [{"id": "run_7_x_report.md", "name": "report.md", "size": 1, "mime_type": "text/plain", "sha256": "0" * 64}]
    monkeypatch.setattr(phone, "run_files", lambda run_id: made if run_id else [])
    got = await client.get(history(ROOT, GRANDKID))                   # a grandchild, through the top of its tree
    assert got.status_code == 200
    body = got.json()
    assert set(body) == {"conversation_id", "sub_session_id", "messages", "view_only"}
    assert (body["conversation_id"], body["sub_session_id"], body["view_only"]) == (ROOT, GRANDKID, True)
    assert [(m["role"], m["text"], m.get("source")) for m in body["messages"]] == [
        ("user", f"brief {GRANDKID}", "commander"), ("assistant", "found it", None)]
    for m in body["messages"]:
        assert set(m) <= {"id", "role", "text", "ts", "attachments", "source"} and m["attachments"] == []
    assert body["messages"][1]["ts"] == "2026-11-15T12:11:00Z"
    # The commander's own history still carries its files and runs: only the sub-session's read leaves them out.
    root = (await client.get(f"/api/v1/phone/conversations/{ROOT}/history")).json()["messages"]
    assert root[-1]["attachments"] == made and root[-1]["run_id"] == 7


@pytest.mark.parametrize(("commander", "child"), [
    (ROOT, OTHER_KID),            # another conversation's sub-session
    (OTHER, KID_A),
    (ROOT, "sub-unknown"),        # no such id
    (ROOT, GONE),                 # deleted: a tombstone
    (ROOT, "side"),               # a side chat under it (its minted id)
    (ROOT, ROOT),                 # the commander itself
    (ROOT, LONE),                 # an ordinary conversation
    (KID_A, GRANDKID),            # through a sub-session: never on the phone itself
    ("c-unknown", KID_A),
])
async def test_a_sub_session_outside_the_commanders_tree_is_not_found(client, monkeypatch, commander, child):
    await _family(client, monkeypatch)
    got = await client.get(history(commander, SIDE["id"] if child == "side" else child))
    assert (got.status_code, got.json()["detail"]) == (404, "not_found")


async def test_the_retired_pocket_is_not_a_commander_even_with_a_sub_session_in_its_tree(client, monkeypatch):
    """The retired pocket is never on the phone (`phone_ids.POCKET`), so a sub-session under it is unreadable through
    it, though the tree itself holds the child: only the route's own pocket check refuses (the pocket is no sub-session)."""
    await _family(client, monkeypatch)
    child = "sub-in-pocket"
    async with client.db_maker() as db:
        db.add(ConversationContext(id=phone_ids.POCKET, kind="chat"))
        await db.commit()
    async with client.db_maker() as db:
        await sub_sessions.create_child(db, phone_ids.POCKET, child)
        db.add(ArslanMessage(conversation_id=child, role="user", content="brief", source=sub_sessions.BRIEF_SOURCE,
                             timestamp=_at(50)))
        await db.commit()
    async with client.db_maker() as db:
        assert child in (await sub_sessions.tree(db, phone_ids.POCKET))[1:]          # it is in the pocket's tree
        assert not await phone._off_the_phone(db, phone_ids.POCKET)                  # and the pocket is no sub-session
    got = await client.get(history(phone_ids.POCKET, child))
    assert (got.status_code, got.json()["detail"]) == (404, "not_found")


async def test_the_transcript_takes_the_phone_historys_limit_and_budget(client, monkeypatch):
    await _family(client, monkeypatch)
    async with client.db_maker() as db:
        for n in range(60):
            db.add(ArslanMessage(conversation_id=KID_B, role="arslan", content=f"line {n}", timestamp=_at(40)))
        await db.commit()
    default = (await client.get(history(ROOT, KID_B))).json()["messages"]
    assert len(default) == 50 and default[-1]["text"] == "line 59"                      # the newest 50, oldest first
    two = (await client.get(history(ROOT, KID_B, "?limit=2"))).json()
    assert [m["text"] for m in two["messages"]] == ["line 58", "line 59"] and "truncated" not in two
    assert len((await client.get(history(ROOT, KID_B, "?limit=200"))).json()["messages"]) == 62               # its brief, its answer, 60 more
    for bad in ("0", "201"):
        assert (await client.get(history(ROOT, KID_B, f"?limit={bad}"))).status_code == 422
    monkeypatch.setattr(phone_reads, "HISTORY_BUDGET", 400)
    cut = (await client.get(history(ROOT, KID_B, "?limit=10"))).json()
    assert cut["truncated"] is True and cut["view_only"] is True
    assert 0 < len(cut["messages"]) < 10 and cut["messages"][-1]["text"] == "line 59"
    assert phone_reads._json_size(cut) <= 400 + phone_reads._json_size({"truncated": True})


# ------------------------------------------------------------------ never links

def test_reading_a_sub_sessions_transcript_never_lets_the_phone_write_to_it(tmp_path, monkeypatch, portal):
    """After the read: the Bridge's link probe (`ConversationLinks.linkNamed` reads the phone history with `limit=1`)
    still answers `not_found`, the Mac's live list never names it, and a phone message on its socket is still refused,
    stored nowhere and runs nothing (step 1's guard)."""
    from tests.server.conftest import build_ws_client
    from tests.server.test_k9b_steering import _Model, _rows, _wire
    from tests.server.test_sub5f_phone_view_only import PHONE, PHONE_WORDS, REFUSED, _codes, _until_probe

    async def seed(maker):
        async with maker() as db:
            db.add(ArslanMessage(conversation_id=ROOT, role="user", content="the commander's words"))
            await sub_sessions.create_child(db, ROOT, KID_A)
            await db.commit()
            db.add(ArslanMessage(conversation_id=KID_A, role="user", content="the brief", source=sub_sessions.BRIEF_SOURCE))
            await db.commit()
    app_client = build_ws_client(portal, tmp_path, monkeypatch, seed=seed, db_name="sub5f-views.db")
    model = _Model()
    _wire(monkeypatch, model)
    read = app_client.get(history(ROOT, KID_A))
    assert read.status_code == 200 and [m["text"] for m in read.json()["messages"]] == ["the brief"]
    probe = app_client.get(f"/api/v1/phone/conversations/{KID_A}/history?limit=1")
    assert (probe.status_code, probe.json()["detail"]) == (404, "not_found")
    assert KID_A not in app_client.get("/api/v1/phone/live").json()["conversation_ids"]
    with app_client.websocket_connect(f"/ws/arslan/{KID_A}") as bridge:
        bridge.receive_json()                                         # history
        bridge.send_json(PHONE)
        frames = _until_probe(bridge, KID_A)
    assert _codes(frames) == REFUSED, frames
    assert PHONE_WORDS not in [content for _role, content, _run, _source in _rows(app_client, KID_A)]
    assert model.inputs == []


def test_the_transcript_is_behind_the_api_token_like_every_phone_route():
    from server.api import phone
    from server.auth import require_auth
    assert any(d.dependency is require_auth for d in phone.router.dependencies)
    assert "/phone/conversations/{conversation_id}/sub-sessions/{sub_session_id}/history" in {
        r.path for r in phone.router.routes}
