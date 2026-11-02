"""L11 (b) PR-C (v0.1.64): Memory's learned practices say where each applies. A practice scoped to a folder (PR-B) is
listed with `scope: {"folder": …}`, the folder named as Overview names it (home-relative, else the full path), so
Memory's row can say "applies in ~/X"; a practice for everywhere has `scope: null`. Fixture text is synthetic."""
import pytest
from sqlalchemy import select

from server.db.models import Lesson
from server.services import folder_rules, lessons


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setattr(folder_rules, "_home", lambda: h)
    return h


async def _listed(client, db, evidence) -> dict:
    async with db() as s:
        s.add(Lesson(situation="writing reports", advice="use 24-hour times", polarity="do", source="user_correction",
                     status="active", evidence=evidence))
        await s.commit()
        lid = (await s.scalars(select(Lesson))).one().id
    return next(r for r in (await client.get("/api/v1/lessons")).json() if r["id"] == lid)


async def test_a_scoped_practice_names_its_folder_as_overview_does(client, execution_db, home):
    folder = home / "Projects" / "photo"
    row = await _listed(client, execution_db, {lessons.CORRECTED_IN: str(folder), lessons.FOLDER_SCOPE: str(folder)})
    assert row["scope"] == {"folder": "~/Projects/photo"}


async def test_a_folder_outside_home_is_named_in_full(client, execution_db, home, tmp_path):
    folder = tmp_path / "elsewhere" / "site"
    row = await _listed(client, execution_db, {lessons.FOLDER_SCOPE: str(folder)})
    assert row["scope"] == {"folder": str(folder)}


@pytest.mark.parametrize("evidence", [{}, {lessons.CORRECTED_IN: "/x"}, {lessons.FOLDER_SCOPE: ""},
                                      {lessons.FOLDER_SCOPE: 7}])
async def test_a_practice_for_everywhere_has_no_scope(client, execution_db, home, evidence):
    assert (await _listed(client, execution_db, evidence))["scope"] is None
