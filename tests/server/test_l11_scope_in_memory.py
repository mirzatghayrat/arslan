"""L11 (b) PR-C (v0.1.64): the web learns where each learned practice applies. PR-B scopes a practice to a folder, and
recall then leaves it out everywhere else, so Memory's list is where the user can find out why. `present()` says
`scope: {"folder": …}`, the folder as Overview names it (`~/…` under home, else the full path), or `scope: null` for a
practice for everywhere. Memory's row that shows it is L11-3b, which waits on its mock.

Project rows and both folder lookups are real, and the practices come from real corrections through `capture`, as in
test_l11_folder_scope.py. Each test names the break it catches. Fixture text is synthetic."""
from pathlib import Path

import pytest

from server.db.companion_models import ConversationContext, Project
from server.db.models import Lesson
from server.services import folder_rules, judgment, lessons
from server.services import personal_context as pc

ROOT = Path(__file__).resolve().parents[2]
CA, CB, CN = "c-photo", "c-site", "c-plain"


@pytest.fixture
def judge(monkeypatch):
    """Every practice here is in the same words, so each is the same one, and none conflicts with itself."""
    async def fake(point, state, *, ref=None, conversation_id=None):
        return judgment.Verdict(point != "memory.conflict", 0.99, 1)
    monkeypatch.setattr(judgment, "judge", fake)


async def project(db, cid: str, folder: Path):
    async with db() as s:
        s.add(Project(id=f"p-{cid}", name=cid, workspace_ref=str(folder)))
        await s.flush()
        s.add(ConversationContext(id=cid, project_id=f"p-{cid}"))
        await s.commit()


@pytest.fixture
async def home(execution_db, tmp_path, monkeypatch):
    home = (tmp_path / "home").resolve()
    (home / "Arslan").mkdir(parents=True)
    monkeypatch.setattr(folder_rules, "_home", lambda: home)
    monkeypatch.setenv("ARSLAN_DEFAULT_WORKSPACE", str(home / "Arslan"))
    for cid, name in ((CA, "photo"), (CB, "site")):
        (home / "Projects" / name).mkdir(parents=True)
        await project(execution_db, cid, home / "Projects" / name)
    return home


async def correct(cid: str):
    cand = lessons.candidate("writing reports", "use 24-hour times", source="user_correction",
                             evidence={"answers_earlier_reply": True})
    with pc.bind(pc.TaskMemoryContext(task_id="t", run_id="r", conversation_id=cid, model_is_local=True)):
        await lessons.capture([cand], conversation_id=cid, external_seen=False)


async def listed(client) -> dict:
    """The one row of the route Memory's list reads (lessonsApi.list)."""
    response = await client.get("/api/v1/lessons")
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    return rows[0]


async def test_a_folder_under_home_is_named_from_home(client, execution_db, judge, home):
    """Catches: present() dropping the key, scope_of always saying None, and the raw path instead of _shown (it would
    spell out the home folder, where Overview says ~)."""
    await correct(CA)
    await correct(CA)
    assert (await listed(client))["scope"] == {"folder": "~/Projects/photo"}


@pytest.mark.parametrize("parent", ["elsewhere", "home-other"], ids=["elsewhere", "beside-home"])
async def test_a_folder_outside_home_is_named_in_full(client, execution_db, judge, home, tmp_path, parent):
    """Catches: `~/` on a folder that isn't under home, including a string-prefix test fooled by a sibling whose path
    starts with home's."""
    folder = home.parent / parent / "site"
    folder.mkdir(parents=True)
    await project(execution_db, "c-out", folder)
    await correct("c-out")
    await correct("c-out")
    assert (await listed(client))["scope"] == {"folder": f"{tmp_path.resolve()}/{parent}/site"}


@pytest.mark.parametrize("order", [(CA,), (CA, CB), (CN, CN), (CA, CA, CB)],
                         ids=["once", "two-folders", "no-chosen-folder", "widened"])
async def test_a_practice_for_everywhere_has_a_null_scope(client, execution_db, judge, home, order):
    """Catches: a dict when there's no scope (Memory would name an empty folder), the folder read from corrected_in
    ("once" has that but isn't scoped), and a practice that widened still naming its old folder."""
    for cid in order:
        await correct(cid)
    assert (await listed(client))["scope"] is None


@pytest.mark.parametrize("evidence", [None, {}], ids=["null", "empty"])
async def test_a_lesson_from_before_scopes_is_listed_with_a_null_scope(client, execution_db, home, evidence):
    """Catches: reading a nullable column straight: one such row would fail the whole list, so Memory showed nothing."""
    async with execution_db() as s:
        s.add(Lesson(situation="writing reports", advice="use 24-hour times", polarity="do", source="user_correction",
                     status="active", evidence=evidence))
        await s.commit()
    assert (await listed(client))["scope"] is None


async def test_the_answers_the_web_types_as_a_lesson_keep_the_scope(client, execution_db, judge, home):
    """lessonsApi.pin and setStatus are typed as Lesson. Catches: a route answering without the scope, and pinning or
    retiring losing it, when Restore would bring the practice back for that folder only."""
    await correct(CA)
    await correct(CA)
    lid = (await listed(client))["id"]
    pinned = await client.post(f"/api/v1/lessons/{lid}/pin", json={"pinned": True})
    assert pinned.json()["scope"] == {"folder": "~/Projects/photo"}
    retired = await client.post(f"/api/v1/lessons/{lid}/status", json={"status": "archived"})
    assert retired.json()["scope"] == {"folder": "~/Projects/photo"}


def test_the_web_type_says_what_the_route_sends():
    """Catches: a rename on the web's side. The tests above pin `scope` and `folder` on the server's."""
    assert "scope?: { folder: string } | null;" in (ROOT / "web/src/api/lessons.ts").read_text()
