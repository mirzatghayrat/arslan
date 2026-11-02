"""L11 (b) PR-B (v0.1.64; the user's decision, 2026-11-02): when the same correction
recurs in a folder, Arslan keeps the practice in its own memory, scoped to that folder, and applies it only there.

⓪Plan's rule (Q2): a practice is scoped only when every one of its corrections came from that one chosen folder. A
correction with no chosen folder, or in another folder, keeps it (or makes it again) a practice for everywhere:
narrowing never happens silently to one that already works everywhere. Lessons from before this keep no record of
where they were corrected, so they stay global (no backfill). Detours never scope. Fixture text is synthetic."""
import pytest
from sqlalchemy import select

from server.db.models import Lesson
from server.services import folder_rules, judgment, lessons
from server.services import personal_context as pc

CA, CB, CN = "c-photo", "c-site", "c-plain"
QUERY = "write the weekly reports"


@pytest.fixture
def judge(monkeypatch):
    """Two lessons are the same practice only when their words are; they never conflict."""
    async def fake(point, state, *, ref=None, conversation_id=None):
        if point == "memory.merge":
            return judgment.Verdict(state["candidate"] == state["existing"], 0.99, 1)
        if point == "memory.conflict":
            return judgment.Verdict(False, 0.99, 1)
        return judgment.Verdict(True, 0.99, 1)
    monkeypatch.setattr(judgment, "judge", fake)


@pytest.fixture
def folders(tmp_path, monkeypatch):
    home = tmp_path / "home"
    chosen = {CA: home / "Projects" / "photo", CB: home / "Projects" / "site"}
    for f in chosen.values():
        f.mkdir(parents=True)
    default = home / "Arslan"
    default.mkdir()
    monkeypatch.setattr(folder_rules, "_home", lambda: home)

    async def chosen_folder(_db, cid):
        return chosen.get(cid)

    async def conversation_folder(_db, cid):
        return chosen.get(cid, default)
    monkeypatch.setattr(folder_rules, "chosen_folder", chosen_folder)
    monkeypatch.setattr(folder_rules, "conversation_folder", conversation_folder)
    return {"home": home, **chosen}


async def correct(cid: str, advice: str = "use 24-hour times, like 14:30", source: str = "user_correction"):
    cand = lessons.candidate("writing reports", advice, source=source, evidence={"answers_earlier_reply": True})
    with pc.bind(pc.TaskMemoryContext(task_id="t", run_id="r", conversation_id=cid, model_is_local=True)):
        await lessons.capture([cand], conversation_id=cid)


async def recalled_in(cid: str) -> list[int]:
    with pc.bind(pc.TaskMemoryContext(task_id="t", run_id="r", conversation_id=cid, model_is_local=True, query=QUERY)):
        return [item["id"] for item in await lessons.recall(QUERY)]


async def only(db) -> Lesson:
    async with db() as s:
        return (await s.scalars(select(Lesson))).one()


async def test_twice_in_one_folder_scopes_it_there_and_applies_only_there(execution_db, judge, folders):
    await correct(CA)
    await correct(CA)
    row = await only(execution_db)
    assert row.evidence.get(lessons.FOLDER_SCOPE) == str(folders[CA])
    assert await recalled_in(CA) == [row.id]
    assert await recalled_in(CB) == [] and await recalled_in(CN) == []


async def test_a_single_correction_is_a_practice_for_everywhere(execution_db, judge, folders):
    await correct(CA)
    row = await only(execution_db)
    assert lessons.FOLDER_SCOPE not in row.evidence
    assert await recalled_in(CB) == [row.id]


async def test_corrections_in_two_folders_stay_global(execution_db, judge, folders):
    await correct(CA)
    await correct(CB)
    row = await only(execution_db)
    assert lessons.FOLDER_SCOPE not in row.evidence
    assert await recalled_in(CA) == [row.id] and await recalled_in(CB) == [row.id]


@pytest.mark.parametrize("order", [(CN, CA), (CA, CN)])
async def test_a_correction_without_a_chosen_folder_keeps_it_global(execution_db, judge, folders, order):
    for cid in order:
        await correct(cid)
    row = await only(execution_db)
    assert lessons.FOLDER_SCOPE not in row.evidence
    assert await recalled_in(CB) == [row.id]


async def test_a_later_correction_elsewhere_widens_a_scoped_practice_and_it_stays_wide(execution_db, judge, folders):
    await correct(CA)
    await correct(CA)
    await correct(CB)
    row = await only(execution_db)
    assert lessons.FOLDER_SCOPE not in row.evidence
    await correct(CA)                                           # back in A, twice: its corrections aren't all from A
    await correct(CA)
    row = await only(execution_db)
    assert lessons.FOLDER_SCOPE not in row.evidence
    assert await recalled_in(CB) == [row.id]


async def test_a_lesson_from_before_stays_global(execution_db, judge, folders):
    """No record of where its earlier corrections happened: it isn't narrowed."""
    await correct(CA)
    async with execution_db() as s:
        row = (await s.scalars(select(Lesson))).one()
        row.evidence = {k: v for k, v in row.evidence.items() if k != lessons.CORRECTED_IN}
        await s.commit()
    await correct(CA)
    row = await only(execution_db)
    assert row.evidence.get("seen") == 2 and lessons.FOLDER_SCOPE not in row.evidence


async def test_home_is_never_a_scope(execution_db, judge, folders, monkeypatch):
    async def at_home(_db, cid):
        return folders["home"]
    monkeypatch.setattr(folder_rules, "chosen_folder", at_home)
    await correct(CA)
    await correct(CA)
    assert lessons.FOLDER_SCOPE not in (await only(execution_db)).evidence


async def test_a_detour_never_scopes(execution_db, judge, folders):
    await correct(CA, source="detour")
    await correct(CA, source="detour")
    row = await only(execution_db)
    assert lessons.FOLDER_SCOPE not in row.evidence and lessons.CORRECTED_IN not in row.evidence


async def test_a_scoped_practice_is_skipped_where_the_folder_cant_be_told(execution_db, judge, folders, monkeypatch):
    await correct(CA)
    await correct(CA)

    async def unknown(_db, _cid):
        return None
    monkeypatch.setattr(folder_rules, "conversation_folder", unknown)
    assert await recalled_in(CA) == []


async def test_a_global_practice_still_applies_everywhere_next_to_a_scoped_one(execution_db, judge, folders):
    await correct(CA)
    await correct(CA)
    await correct(CB, advice="put the newest entries first")
    async with execution_db() as s:
        rows = {r.advice: r.id for r in (await s.scalars(select(Lesson))).all()}
    assert len(rows) == 2
    assert sorted(await recalled_in(CA)) == sorted(rows.values())
    assert await recalled_in(CN) == [rows["put the newest entries first"]]
