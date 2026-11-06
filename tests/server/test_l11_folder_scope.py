"""L11 (b) PR-B (v0.1.64; the user's decision, 2026-11-02): when the same correction
recurs in a folder, Arslan keeps the practice in its own memory, scoped to that folder, and applies it only there.

⓪Plan's rule (Q2): a practice is scoped only when every one of its corrections came from that one chosen folder. A
correction with no chosen folder, or in another folder, keeps it (or makes it again) a practice for everywhere:
narrowing never happens silently to one that already works everywhere. Lessons from before this keep no record of
where they were corrected, so they stay global (no backfill). Detours never scope. Fixture text is synthetic.

Project rows and both folder lookups are real here, and the judge reports conflicts: #718's review found three bugs
that a mocked lookup and a judge that never conflicts had hidden."""
import pytest
from sqlalchemy import select

from server.db.companion_models import ConversationContext, Project
from server.db.models import Lesson
from server.services import folder_rules, judgment, lessons, settings_service
from server.services import personal_context as pc

CA, CB, CN = "c-photo", "c-site", "c-plain"
QUERY = "write the weekly reports"
ADVICE = "use 24-hour times, like 14:30"
OPPOSITE = "use 12-hour times, like 2:30 pm"


@pytest.fixture
def judge(monkeypatch):
    """Two lessons are the same practice only when their words are; only 24-hour and 12-hour times conflict."""
    async def fake(point, state, *, ref=None, conversation_id=None):
        if point == "memory.merge":
            return judgment.Verdict(state["candidate"] == state["existing"], 0.99, 1)
        if point == "memory.conflict":
            texts = state["candidate"] + state["existing"]
            return judgment.Verdict("24-hour" in texts and "12-hour" in texts, 0.99, 1)
        return judgment.Verdict(True, 0.99, 1)
    monkeypatch.setattr(judgment, "judge", fake)


async def project(db, cid: str, ref: str | None):
    async with db() as s:
        s.add(Project(id=f"p-{cid}", name=cid, workspace_ref=ref))
        await s.flush()
        s.add(ConversationContext(id=cid, project_id=f"p-{cid}"))
        await s.commit()


@pytest.fixture
async def folders(execution_db, tmp_path, monkeypatch):
    home = (tmp_path / "home").resolve()
    chosen = {CA: home / "Projects" / "photo", CB: home / "Projects" / "site"}
    for f in chosen.values():
        f.mkdir(parents=True)
    default = home / "Arslan"
    default.mkdir()
    monkeypatch.setattr(folder_rules, "_home", lambda: home)
    monkeypatch.setenv("ARSLAN_DEFAULT_WORKSPACE", str(default))
    for cid, folder in chosen.items():
        await project(execution_db, cid, str(folder))
    return {"home": home, "default": default, **chosen}


async def correct(cid: str, advice: str = ADVICE, source: str = "user_correction", answers: bool = True):
    cand = lessons.candidate("writing reports", advice, source=source, evidence={"answers_earlier_reply": answers})
    with pc.bind(pc.TaskMemoryContext(task_id="t", run_id="r", conversation_id=cid, model_is_local=True)):
        await lessons.capture([cand], conversation_id=cid, external_seen=False)


async def recalled_in(cid: str) -> list[int]:
    with pc.bind(pc.TaskMemoryContext(task_id="t", run_id="r", conversation_id=cid, model_is_local=True, query=QUERY)):
        return [item["id"] for item in await lessons.recall(QUERY)]


async def only(db) -> Lesson:
    async with db() as s:
        return (await s.scalars(select(Lesson))).one()


async def by_advice(db) -> dict[str, Lesson]:
    async with db() as s:
        return {row.advice: row for row in (await s.scalars(select(Lesson))).all()}


async def pin_only(db):
    async with db() as s:
        (await s.scalars(select(Lesson))).one().pinned = True
        await s.commit()


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


async def test_home_is_never_a_scope(execution_db, judge, folders):
    await project(execution_db, "c-home", str(folders["home"]))
    await correct("c-home")
    await correct("c-home")
    assert lessons.FOLDER_SCOPE not in (await only(execution_db)).evidence


# -- #718's review, finding 1: only a folder the user chose counts ---------------------------------------------------

@pytest.mark.parametrize("ref", [None, "/no/such/folder"], ids=["no-folder", "folder-gone"])
async def test_a_project_with_no_usable_folder_doesnt_scope_to_the_default(execution_db, judge, folders, ref):
    await project(execution_db, "c-a", ref)
    await project(execution_db, "c-b", ref)
    await correct("c-a")
    await correct("c-b")
    row = await only(execution_db)
    assert lessons.FOLDER_SCOPE not in row.evidence
    assert await recalled_in(CA) == [row.id] and await recalled_in(CN) == [row.id]


async def test_the_default_workspace_never_scopes_in_a_plain_chat(execution_db, judge, folders):
    await correct(CN)
    await correct(CN)
    row = await only(execution_db)
    assert lessons.FOLDER_SCOPE not in row.evidence
    assert await recalled_in(CA) == [row.id]


@pytest.mark.parametrize("key", ["other", "default"])
async def test_a_workspace_the_user_set_is_chosen_even_if_it_is_the_default(execution_db, judge, folders, key):
    folder = folders[CA] if key == "other" else folders["default"]
    async with execution_db() as s:
        await settings_service._set_raw(s, "workspace_dir", str(folder))
        await s.commit()
    await correct(CN)
    await correct(CN)
    assert (await only(execution_db)).evidence.get(lessons.FOLDER_SCOPE) == str(folder)


async def test_a_project_folder_that_cant_be_expanded_doesnt_lose_the_correction(execution_db, judge, folders):
    await project(execution_db, "c-tilde", "~no_such_user_for_this_test/photo")
    await correct("c-tilde")
    row = await only(execution_db)
    assert lessons.FOLDER_SCOPE not in row.evidence
    assert await recalled_in("c-tilde") == [row.id]


# -- #718's review, finding 2: a practice scoped elsewhere isn't a rival here ------------------------------------------

async def test_folders_with_opposite_practices_each_keep_their_own(execution_db, judge, folders):
    await correct(CA)
    await correct(CA)
    await correct(CB, advice=OPPOSITE)                          # one correction is for everywhere, so A briefly sees both
    rows = await by_advice(execution_db)
    a, b = rows[ADVICE].id, rows[OPPOSITE].id
    assert rows[ADVICE].status == "active" and rows[OPPOSITE].status == "active"
    assert sorted(await recalled_in(CA)) == [a, b] and await recalled_in(CB) == [b]
    await correct(CB, advice=OPPOSITE)
    assert await recalled_in(CA) == [a] and await recalled_in(CB) == [b] and await recalled_in(CN) == []


async def test_the_same_opposites_back_and_forth_settle_in_their_folders(execution_db, judge, folders):
    for cid, advice in ((CA, ADVICE), (CA, ADVICE), (CB, OPPOSITE), (CB, OPPOSITE), (CA, ADVICE), (CA, ADVICE)):
        await correct(cid, advice=advice)
    rows = await by_advice(execution_db)
    assert {r.status for r in rows.values()} == {"active"}
    assert await recalled_in(CA) == [rows[ADVICE].id] and await recalled_in(CB) == [rows[OPPOSITE].id]


async def test_a_pinned_practice_scoped_elsewhere_doesnt_hold_a_correction_back(execution_db, judge, folders):
    await correct(CA)
    await correct(CA)
    await pin_only(execution_db)
    await correct(CB, advice=OPPOSITE)
    rows = await by_advice(execution_db)
    assert rows[OPPOSITE].status == "active" and await recalled_in(CB) == [rows[OPPOSITE].id]


async def test_a_detour_still_waits_on_a_practice_scoped_elsewhere(execution_db, judge, folders):
    """A detour never narrows, so it would apply in A for good, against what the user said there."""
    await correct(CA)
    await correct(CA)
    await correct(CB, advice=OPPOSITE, source="detour")
    rows = await by_advice(execution_db)
    assert rows[ADVICE].status == "active" and rows[OPPOSITE].status == "proposed"
    assert rows[OPPOSITE].evidence[lessons.CONFLICTS_WITH] == rows[ADVICE].id


async def test_what_replaces_a_practice_for_everywhere_stays_for_everywhere(execution_db, judge, folders):
    await correct(CN)
    await correct(CA, advice=OPPOSITE)
    await correct(CA, advice=OPPOSITE)
    rows = await by_advice(execution_db)
    assert rows[ADVICE].status == "archived" and lessons.FOLDER_SCOPE not in rows[OPPOSITE].evidence
    assert await recalled_in(CB) == [rows[OPPOSITE].id] and await recalled_in(CN) == [rows[OPPOSITE].id]


async def test_what_replaces_a_practice_scoped_here_can_scope_here(execution_db, judge, folders):
    await correct(CA)
    await correct(CA)
    await correct(CA, advice=OPPOSITE)
    await correct(CA, advice=OPPOSITE)
    rows = await by_advice(execution_db)
    assert rows[ADVICE].status == "archived" and rows[OPPOSITE].evidence[lessons.FOLDER_SCOPE] == str(folders[CA])


# -- #718's review, finding 3: what the module says isn't a correction doesn't count ------------------------------------

async def test_a_first_message_after_a_correction_doesnt_scope_it(execution_db, judge, folders):
    await correct(CA)
    await correct(CA, answers=False)
    row = await only(execution_db)
    assert lessons.FOLDER_SCOPE not in row.evidence
    assert await recalled_in(CB) == [row.id]


async def test_a_first_message_then_one_correction_doesnt_scope_it(execution_db, judge, folders):
    await correct(CA, answers=False)
    await correct(CA)
    row = await only(execution_db)
    assert row.status == "active" and lessons.FOLDER_SCOPE not in row.evidence
    assert await recalled_in(CB) == [row.id]


async def test_with_learned_practices_off_a_correction_doesnt_scope_it(execution_db, judge, folders):
    await correct(CA)
    async with execution_db() as s:
        await settings_service._set_raw(s, "learned_practices_take_effect", "false")
        await s.commit()
    await correct(CA)
    assert lessons.FOLDER_SCOPE not in (await only(execution_db)).evidence


# -- A pinned practice doesn't narrow (⓪Plan, #718's review) -------------------------------------------------------

async def test_a_pinned_practice_doesnt_narrow(execution_db, judge, folders):
    await correct(CA)
    await pin_only(execution_db)
    await correct(CA)
    row = await only(execution_db)
    assert lessons.FOLDER_SCOPE not in row.evidence
    assert await recalled_in(CB) == [row.id]


async def test_pinning_a_scoped_practice_keeps_its_scope(execution_db, judge, folders):
    await correct(CA)
    await correct(CA)
    await pin_only(execution_db)
    await correct(CA)
    assert (await only(execution_db)).evidence[lessons.FOLDER_SCOPE] == str(folders[CA])


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


async def test_a_scoped_practice_is_skipped_when_the_lookup_fails(execution_db, judge, folders, monkeypatch):
    await correct(CA)
    await correct(CA)
    await correct(CB, advice="put the newest entries first")
    rows = await by_advice(execution_db)

    async def broken(_db, _cid):
        raise OSError("no folder")
    monkeypatch.setattr(folder_rules, "conversation_folder", broken)
    assert await recalled_in(CA) == [rows["put the newest entries first"].id]


async def test_a_global_practice_still_applies_everywhere_next_to_a_scoped_one(execution_db, judge, folders):
    await correct(CA)
    await correct(CA)
    await correct(CB, advice="put the newest entries first")
    async with execution_db() as s:
        rows = {r.advice: r.id for r in (await s.scalars(select(Lesson))).all()}
    assert len(rows) == 2
    assert sorted(await recalled_in(CA)) == sorted(rows.values())
    assert await recalled_in(CN) == [rows["put the newest entries first"]]
