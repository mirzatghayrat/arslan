"""D1 guardrail: the three brain read endpoints must survive the .mappings() refactor
byte-for-byte.

Why this exists. The D round widens all three SELECTs (sensitive, provenance), and the
three endpoints consume their rows in three DIFFERENT unsafe ways:

  * brain_graph unpacks a fixed arity — `for fid, _content, _label, category, _source,
    _confidence, _superseded_by in facts` — so one extra column is a hard ValueError at
    runtime. Worse, that loop body only runs for rows whose category is non-blank, so a
    smoke test against an empty or category-less DB passes while production 500s.
  * brain_tree and brain_entry index positionally (r[0]..r[7], row[0]..row[7]) with no
    unpack at all, so inserting a column mid-SELECT silently SHIFTS every later value —
    a fact's confidence would render as its valid_from with no exception raised.

So the refactor to named access comes FIRST, on its own, with this test pinning that it
changed nothing. Seeded data deliberately includes a category-bearing fact (the row
shape that triggers the graph unpack) and a superseded row.
"""
from __future__ import annotations

import pytest

from server.db.models import ArslanMessage, Learning, Note, Spawn, UserFact

AUTH: dict[str, str] = {}


@pytest.fixture
async def seeded(client, monkeypatch):
    """One row of every kind the three endpoints render, including the shapes whose
    absence would make this guardrail pass vacuously.

    The three brain READ endpoints open the production AsyncSessionLocal directly (only
    the proposal-adjudication routes take Depends(get_session)), so the client fixture's
    dependency override does NOT reach them — point the production sessionmaker at the
    test DB, the same way tests/server/test_brain_api.py does.
    """
    from server.db import session as db_session

    monkeypatch.setattr(db_session, "AsyncSessionLocal", client.db_maker)
    async with client.db_maker() as s:
        s.add(Spawn(id=1, name="S", domain_category="g", system_prompt="sp"))
        # category NON-BLANK: this is what makes brain_graph enter its fact tag loop
        s.add(UserFact(content="用户偏好简短", source="auto", confidence=0.8,
                       category="偏好", label="简短", sensitive=False))
        # a superseded fact — exercises the temporal columns on the read path
        s.add(UserFact(content="旧偏好", source="auto", confidence=0.5,
                       category="偏好", superseded_by=1, sensitive=True))
        s.add(Learning(content="心得内容", label="心得", source_kind="distill",
                       source_ref={"conversation_id": "c1"}, confidence=0.7))
        s.add(Note(title="笔记", content="正文 [[心得]]", tags=["t1"]))
        s.add(ArslanMessage(conversation_id="c1", role="spawn_summary",
                            content="x", display_content="x", spawn_id=1))
        await s.commit()
    return client


async def test_tree_payload_shape(seeded):
    r = await seeded.get("/api/v1/brain/tree", headers=AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    kinds = {b["kind"] for b in body["branches"]}
    assert kinds == {"material", "learning", "profile", "note"}

    profile = next(b for b in body["branches"] if b["kind"] == "profile")
    leaf = profile["children"][0]
    # the exact key set the frontend contract depends on
    assert set(leaf) == {
        "kind", "ref", "label", "provenance", "confidence", "usage_count",
        "last_used_at", "last_used_ref", "value", "category",
        "valid_from", "superseded_by",
    }
    assert leaf["ref"] == "fact:1"
    assert leaf["label"] == "简短"          # label wins over content
    assert leaf["provenance"] == "auto"     # the legacy DISPLAY string, not the record
    assert leaf["confidence"] == 0.8
    assert leaf["category"] == "偏好"

    learning = next(b for b in body["branches"] if b["kind"] == "learning")
    lleaf = learning["children"][0]
    assert lleaf["ref"] == "learning:1"
    assert lleaf["provenance"] == "distill"
    assert {"valid_from", "superseded_by"} <= set(lleaf)


async def test_graph_payload_shape(seeded):
    r = await seeded.get("/api/v1/brain/graph", headers=AUTH)
    assert r.status_code == 200, r.text
    body = r.json()

    fact_nodes = [n for n in body["nodes"] if n["kind"] == "profile"]
    assert {n["ref"] for n in fact_nodes} == {"fact:1", "fact:2"}
    n1 = next(n for n in fact_nodes if n["ref"] == "fact:1")
    assert set(n1) == {"id", "ref", "kind", "label", "val",
                       "source", "confidence", "superseded_by"}
    assert n1["source"] == "auto" and n1["confidence"] == 0.8

    learn = next(n for n in body["nodes"] if n["kind"] == "learning")
    assert set(learn) == {"id", "ref", "kind", "label", "val", "superseded_by"}

    # the fact->tag edge: this is the loop whose positional unpack the refactor removes
    tag_edges = [e for e in body["links"]
                 if e["type"] == "tag" and e["source"].startswith("fact:")]
    assert {e["source"] for e in tag_edges} == {"fact:1", "fact:2"}
    assert all(e["target"] == "tag:偏好" for e in tag_edges)

    # The three CONSUMER LOOPS that also read these rows. My first pass at the refactor
    # converted the SELECTs and the node builders but left these three unpacking tuples,
    # which under .mappings() silently iterate COLUMN NAMES instead of values — no
    # exception, just wrong edges. They are pinned here so that cannot recur.
    link_edges = [e for e in body["links"] if e["type"] == "link"]
    assert any(e["source"] == "note:1" for e in link_edges), (
        "note [[wiki link]] edges must survive the row-access refactor")

    tag_edges_from_notes = [e for e in body["links"]
                            if e["type"] == "tag" and e["source"].startswith("note:")]
    assert {e["target"] for e in tag_edges_from_notes} == {"tag:t1"}

    # synthetic nodes bypass _gnode entirely — they must keep exactly five keys
    for kind in ("tag", "self"):
        node = next((n for n in body["nodes"] if n["kind"] == kind), None)
        if node is not None:
            assert set(node) == {"id", "ref", "kind", "label", "val"}


async def test_entry_payload_shape(seeded):
    r = await seeded.get("/api/v1/brain/entry/profile/fact:1", headers=AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {
        "kind", "ref", "label", "provenance", "confidence", "excerpt",
        "usage_count", "last_used_at", "last_used_ref",
        "valid_from", "superseded_by", "provenance_record",
    }
    assert body["excerpt"] == "用户偏好简短"
    assert body["confidence"] == 0.8
    # `provenance` is the legacy display STRING; `provenance_record` is the audit payload
    assert isinstance(body["provenance"], str)

    r2 = await seeded.get("/api/v1/brain/entry/learning/learning:1", headers=AUTH)
    assert r2.status_code == 200, r2.text
    b2 = r2.json()
    assert b2["provenance_record"] == {"source_kind": "distill",
                                       "source_ref": {"conversation_id": "c1"}}
