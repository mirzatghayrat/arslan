"""L11-3b (v0.1.64, card docs/plans/0164/L11-3-rule-followups.md), the part that isn't UI: each lesson Memory lists
says where it stands with the folder's rules, so Memory can show the offer after a reload and the line once it is in
the file. `rule` is the offer (Add / Not now) or the added line (Open / Remove), with the file as Overview names it
and the conversation the card was offered in; nothing for "not now", "removed", or no offer. Memory's buttons reuse
the card's and Overview's endpoints with exactly these values, so their checks are unchanged. Fixture text is
synthetic."""
import pytest
from sqlalchemy import select

from server.db.models import Lesson
from server.services import folder_rules, judgment, lessons
from server.services import personal_context as pc

CID, OTHER = "c-rules", "c-other"
LINE = "writing reports → use 24-hour times, like 14:30"
FILE = "~/Projects/photo/AGENTS.md"


@pytest.fixture(autouse=True)
def _a_local_turn():
    with pc.bind(pc.TaskMemoryContext(task_id="t", run_id="r", conversation_id=CID, model_is_local=True)):
        yield


@pytest.fixture
def judge(monkeypatch):
    async def fake(point, state, *, ref=None, conversation_id=None):
        return judgment.Verdict(True, 0.99, 1)
    monkeypatch.setattr(judgment, "judge", fake)


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    folders = {CID: h / "Projects" / "photo", OTHER: h / "Projects" / "other"}
    for f in folders.values():
        f.mkdir(parents=True)
    monkeypatch.setattr(folder_rules, "_home", lambda: h)

    async def folder(_db, cid):
        return folders.get(cid)
    monkeypatch.setattr(folder_rules, "conversation_folder", folder)
    monkeypatch.setattr(folder_rules, "chosen_folder", folder)
    return h


def agents(home):
    return home / "Projects" / "photo" / "AGENTS.md"


async def _offered_id(db) -> int:
    correction = lessons.candidate("writing reports", "use 24-hour times, like 14:30", source="user_correction",
                                   evidence={"answers_earlier_reply": True})
    for _ in range(2):
        await lessons.capture([correction], conversation_id=CID, emit=lambda _f: None)
    async with db() as s:
        return (await s.scalars(select(Lesson))).one().id


async def _listed(client, lid):
    rows = (await client.get("/api/v1/lessons")).json()
    return next(r for r in rows if r["id"] == lid)


async def _rule(client, lid, action, cid=CID):
    return await client.post(f"/api/v1/lessons/{lid}/rule", json={"conversation_id": cid, "action": action})


async def test_an_offer_nobody_answered_is_listed_with_its_file_and_conversation(client, execution_db, judge, home):
    lid = await _offered_id(execution_db)
    assert (await _listed(client, lid))["rule"] == {"state": "offered", "file": FILE, "conversation_id": CID, "line": LINE}


async def test_memorys_add_with_the_listed_values_writes_the_line(client, execution_db, judge, home):
    lid = await _offered_id(execution_db)
    rule = (await _listed(client, lid))["rule"]
    assert (await _rule(client, lid, "add", rule["conversation_id"])).status_code == 200
    assert agents(home).read_text() == f"- {LINE}\n"
    assert (await _listed(client, lid))["rule"] == {"state": "added", "file": FILE, "conversation_id": CID, "line": LINE}


async def test_memorys_remove_through_overviews_endpoint_with_the_listed_values(client, execution_db, judge, home):
    lid = await _offered_id(execution_db)
    await _rule(client, lid, "add")
    rule = (await _listed(client, lid))["rule"]
    r = await client.post(f"/api/v1/conversations/{rule['conversation_id']}/folder-rules/remove",
                          json={"file": rule["file"], "lesson_id": lid, "line": rule["line"]})
    assert r.status_code == 200 and r.json()["in_file"] is True
    assert agents(home).read_text() == ""
    assert (await _listed(client, lid))["rule"] is None


@pytest.mark.parametrize("action", ["skip", "remove"])
async def test_not_now_and_removed_show_nothing(client, execution_db, judge, home, action):
    lid = await _offered_id(execution_db)
    if action == "remove":
        await _rule(client, lid, "add")
    assert (await _rule(client, lid, action)).status_code == 200
    assert (await _listed(client, lid))["rule"] is None


async def test_a_lesson_never_offered_shows_nothing(client, execution_db):
    async with execution_db() as s:
        s.add(Lesson(situation="naming files", advice="dates as 2026-11-01", polarity="do", source="user_correction",
                     status="active", evidence={}))
        await s.commit()
        lid = (await s.scalars(select(Lesson))).one().id
    assert (await _listed(client, lid))["rule"] is None


async def test_an_offer_the_lesson_has_outgrown_is_not_listed(client, execution_db, judge, home):
    """Add refuses an offer once the lesson changed (`lesson_changed`, #603 F2), so Memory doesn't show one it would
    refuse. A pin counts as a change today, as it does for the card in the chat."""
    lid = await _offered_id(execution_db)
    await client.post(f"/api/v1/lessons/{lid}/pin", json={"pinned": True})
    assert (await _listed(client, lid))["rule"] is None
    assert (await _rule(client, lid, "add")).json()["detail"] == "lesson_changed"


@pytest.mark.parametrize("record", [{}, {"line": LINE}, {"path": "/x/AGENTS.md"},
                                    {"line": LINE, "path": "/x/AGENTS.md", "conversation_id": None}, "not a dict"])
async def test_a_partial_record_shows_nothing(client, execution_db, record):
    async with execution_db() as s:
        s.add(Lesson(situation="s", advice="a", polarity="do", source="user_correction", status="active",
                     evidence={lessons.RULE_OFFER: "added", lessons.RULE_RECORD: record}))
        await s.commit()
        lid = (await s.scalars(select(Lesson))).one().id
    assert (await _listed(client, lid))["rule"] is None


async def test_a_file_outside_home_is_named_by_its_full_path(client, execution_db, home, tmp_path):
    path = tmp_path / "elsewhere" / "AGENTS.md"
    async with execution_db() as s:
        s.add(Lesson(situation="s", advice="a", polarity="do", source="user_correction", status="active",
                     evidence={lessons.RULE_OFFER: "added", lessons.RULE_RECORD: {
                         "line": "s → a", "path": str(path), "conversation_id": CID, "updated_at": "x"}}))
        await s.commit()
        lid = (await s.scalars(select(Lesson))).one().id
    assert (await _listed(client, lid))["rule"]["file"] == str(path)
