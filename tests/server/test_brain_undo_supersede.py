"""D3: POST /brain/undo-supersede — restore a superseded entry to active.

The service existed since P1 and was wired to nothing. Three things this route must get
right, each of which the read-only audit flagged:

  * kind -> table must REFUSE, not fall through. The frontend carries `kind`
    (profile|learning|material|note); the service takes a TABLE NAME and only knows
    user_facts/learnings. Letting an unmapped kind reach the service yields
    SupersedeError('bad_table') -> 422 whose detail leaks an internal table name, and
    `note` is not a typo case — it is a real frontend kind whose table has no
    superseded_by column at all.
  * the service must take `db=` like execute_supersede does, or the house test seam
    (Depends(get_session) + app.dependency_overrides) silently does not reach the write.
  * missing_provenance is a PROGRAMMER guard, so the route supplies provenance and that
    branch is dead — it must not be reachable as a client-facing 409.
"""
from __future__ import annotations

import pytest

from server.db.models import Learning, Note, UserFact

AUTH: dict[str, str] = {}


@pytest.fixture
async def seeded(client, monkeypatch):
    from server.db import session as db_session

    monkeypatch.setattr(db_session, "AsyncSessionLocal", client.db_maker)
    async with client.db_maker() as s:
        s.add(UserFact(content="新事实", source="auto", confidence=0.8))
        s.add(UserFact(content="旧事实", source="auto", confidence=0.5, superseded_by=1))
        s.add(Learning(content="新心得", source_kind="distill", source_ref={}, confidence=0.7))
        s.add(Learning(content="旧心得", source_kind="distill", source_ref={},
                       confidence=0.5, superseded_by=1))
        s.add(Note(title="笔记", content="正文"))
        await s.commit()
    return client


async def test_undo_restores_a_superseded_fact(seeded):
    r = await seeded.post("/api/v1/brain/undo-supersede",
                          json={"kind": "profile", "ref": "fact:2"}, headers=AUTH)
    assert r.status_code == 200, r.text
    assert r.json()["superseded_by"] is None

    async with seeded.db_maker() as s:
        row = await s.get(UserFact, 2)
    assert row.superseded_by is None


async def test_undo_restores_a_superseded_learning(seeded):
    r = await seeded.post("/api/v1/brain/undo-supersede",
                          json={"kind": "learning", "ref": "learning:2"}, headers=AUTH)
    assert r.status_code == 200, r.text
    async with seeded.db_maker() as s:
        row = await s.get(Learning, 2)
    assert row.superseded_by is None


@pytest.mark.parametrize("kind,ref", [("material", "material:coll:1:x.md"),
                                      ("note", "note:1"),
                                      ("ghost", "ghost:x")])
async def test_unsupportable_kinds_are_refused_before_reaching_the_service(seeded, kind, ref):
    """422 keyed on the FRONTEND vocabulary, raised before the service call — so the
    detail never leaks an internal table name. `note` matters most: it is a real kind
    whose table has no superseded_by column at all."""
    r = await seeded.post("/api/v1/brain/undo-supersede",
                          json={"kind": kind, "ref": ref}, headers=AUTH)
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert "user_facts" not in detail and "learnings" not in detail, (
        "the client-facing error must not name internal tables")
    assert kind in detail


async def test_undoing_an_active_row_is_a_409(seeded):
    r = await seeded.post("/api/v1/brain/undo-supersede",
                          json={"kind": "profile", "ref": "fact:1"}, headers=AUTH)
    assert r.status_code == 409, r.text
    assert "user_facts" not in r.json()["detail"], (
        "the 4xx details must be as table-name-free as the 422 path — the service's "
        "own messages name the table, so they must not be passed through verbatim")


async def test_undoing_a_missing_row_is_a_410(seeded):
    r = await seeded.post("/api/v1/brain/undo-supersede",
                          json={"kind": "profile", "ref": "fact:9999"}, headers=AUTH)
    assert r.status_code == 410, r.text
    assert "user_facts" not in r.json()["detail"], r.text


async def test_malformed_ref_is_refused(seeded):
    for ref in ("fact:notanint", "garbage", "fact:"):
        r = await seeded.post("/api/v1/brain/undo-supersede",
                              json={"kind": "profile", "ref": ref}, headers=AUTH)
        assert r.status_code == 422, f"{ref}: {r.text}"


async def test_a_ref_from_the_other_kind_is_refused(seeded):
    """🔴 The guard that actually prevents un-superseding the WRONG ROW. Both tables use
    small integer ids, so {"kind": "profile", "ref": "learning:2"} without this check
    would restore user_facts id 2 — a different entry entirely, silently, with a 200.

    A mutation check proved this was untested: deleting the prefix comparison left every
    other test in this file green.
    """
    async with seeded.db_maker() as s:
        before = (await s.get(UserFact, 2)).superseded_by
    assert before is not None

    r = await seeded.post("/api/v1/brain/undo-supersede",
                          json={"kind": "profile", "ref": "learning:2"}, headers=AUTH)
    assert r.status_code == 422, r.text

    async with seeded.db_maker() as s:
        assert (await s.get(UserFact, 2)).superseded_by == before, (
            "the fact must be untouched — a cross-kind ref must never reach the write")


async def test_a_unicode_digit_ref_is_a_422_not_a_500(seeded):
    """`isdigit()` is True for superscripts and other Unicode digit forms that int()
    then rejects, which would surface as an uncaught ValueError."""
    r = await seeded.post("/api/v1/brain/undo-supersede",
                          json={"kind": "profile", "ref": "fact:\u00b2"}, headers=AUTH)
    assert r.status_code == 422, r.text
