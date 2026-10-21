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

Under memory v2 (0.1.63 C2a-2) every well-formed request is refused for versioned review (409): the
v1 pointer rewrite is gone, and user_facts / learnings are read-only views, so nothing here seeds them.
What these tests pin is the request checks that still run first.
"""
from __future__ import annotations

import pytest



AUTH: dict[str, str] = {}


@pytest.fixture
async def seeded(client, monkeypatch):
    from server.db import session as db_session

    monkeypatch.setattr(db_session, "AsyncSessionLocal", client.db_maker)
    return client






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


async def test_a_well_formed_request_is_a_409_for_versioned_review(seeded):
    r = await seeded.post("/api/v1/brain/undo-supersede",
                          json={"kind": "profile", "ref": "fact:1"}, headers=AUTH)
    assert r.status_code == 409, r.text
    assert "user_facts" not in r.json()["detail"], (
        "the 4xx details must be as table-name-free as the 422 path — the service's "
        "own messages name the table, so they must not be passed through verbatim")




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
    other test in this file green. Without the check this request now reaches the service and gets
    its 409; with it, the caller's own words come back as a 422.
    """
    r = await seeded.post("/api/v1/brain/undo-supersede",
                          json={"kind": "profile", "ref": "learning:2"}, headers=AUTH)
    assert r.status_code == 422, r.text


async def test_a_unicode_digit_ref_is_a_422_not_a_500(seeded):
    """`isdigit()` is True for superscripts and other Unicode digit forms that int()
    then rejects, which would surface as an uncaught ValueError."""
    r = await seeded.post("/api/v1/brain/undo-supersede",
                          json={"kind": "profile", "ref": "fact:\u00b2"}, headers=AUTH)
    assert r.status_code == 422, r.text
