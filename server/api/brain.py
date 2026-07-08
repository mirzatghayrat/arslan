"""Typed Second Brain tree + entry detail. Replaces the client-assembled tree so
every leaf carries provenance/confidence/usage from one authoritative place."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import text as sa_text

from server.db import session as db_session
from server.services import brain_usage

router = APIRouter(tags=["brain"])


def _iso(ts):
    # usage_map reads via raw SQL, so SQLite hands back last_used_at as a str
    # already; only call isoformat() when it's a real datetime.
    if ts is None:
        return None
    return ts.isoformat() if hasattr(ts, "isoformat") else ts


def _leaf(kind, ref_key, label, provenance, confidence, umap, weight=1):
    """weight = content richness (material: chunk count; profile/learning: 1). The
    sunburst angular size is weight + usage_count, so the map shows the SHAPE of the
    brain (big fed docs vs many small facts) and grows further with use."""
    u = umap.get((kind, ref_key), {})
    return {
        "kind": kind, "ref": ref_key, "label": label, "provenance": provenance,
        "confidence": confidence,
        "usage_count": u.get("usage_count", 0),
        "last_used_at": _iso(u.get("last_used_at")),
        "last_used_ref": u.get("last_used_ref"),
        "value": weight + u.get("usage_count", 0),
    }


def _mat_ref(collection_id, spawn_id, source) -> str:
    return (f"material:coll:{collection_id}:{source}" if collection_id is not None
            else f"material:spawn:{spawn_id}:{source}")


@router.get("/brain/tree")
async def brain_tree() -> dict:
    async with db_session.AsyncSessionLocal() as db:
        facts = (await db.execute(sa_text(
            "SELECT id, content, label, category, source, confidence FROM user_facts ORDER BY id"))).all()
        mats = (await db.execute(sa_text(
            "SELECT collection_id, spawn_id, source, COUNT(*) n FROM knowledge_chunks "
            "GROUP BY collection_id, spawn_id, source"))).all()
        learns = (await db.execute(sa_text(
            "SELECT id, content, label, source_kind, confidence FROM learnings ORDER BY id"))).all()
        notes = (await db.execute(sa_text(
            "SELECT id, title FROM notes ORDER BY updated_at DESC"))).all()

    keys: list[tuple[str, str]] = []
    keys += [("profile", f"fact:{r[0]}") for r in facts]
    keys += [("material", _mat_ref(m[0], m[1], m[2])) for m in mats]
    keys += [("learning", f"learning:{r[0]}") for r in learns]
    keys += [("note", f"note:{r[0]}") for r in notes]
    umap = await brain_usage.usage_map(keys)

    profile_leaves = [
        _leaf("profile", f"fact:{r[0]}", r[2] or r[1], r[4] or "auto", r[5], umap) for r in facts]
    material_leaves = [
        _leaf("material", _mat_ref(m[0], m[1], m[2]), m[2],
              ("投喂" if m[0] is not None else "分身"), None, umap, weight=m[3])
        for m in mats]
    learning_leaves = [
        _leaf("learning", f"learning:{r[0]}", r[2] or (r[1] or "")[:40], r[3], r[4], umap) for r in learns]
    note_leaves = [_leaf("note", f"note:{r[0]}", r[1], "手写", None, umap) for r in notes]

    return {"branches": [
        {"kind": "material", "label": "材料", "children": material_leaves},
        {"kind": "learning", "label": "心得", "children": learning_leaves},
        {"kind": "profile", "label": "画像", "children": profile_leaves},
        {"kind": "note", "label": "笔记", "children": note_leaves},
    ]}


@router.get("/brain/graph")
async def brain_graph() -> dict:
    """Force-graph data: every entry (4 types) as a node, edges from note [[links]]
    (unresolved → ghost node) + best-effort 心得→spawn-well-material provenance."""
    import json as _json

    from server.services import note_service

    async with db_session.AsyncSessionLocal() as db:
        facts = (await db.execute(sa_text(
            "SELECT id, content, label FROM user_facts ORDER BY id"))).all()
        mats = (await db.execute(sa_text(
            "SELECT collection_id, spawn_id, source, COUNT(*) n FROM knowledge_chunks "
            "GROUP BY collection_id, spawn_id, source"))).all()
        learns = (await db.execute(sa_text(
            "SELECT id, content, label, source_ref FROM learnings ORDER BY id"))).all()
        notes = (await db.execute(sa_text(
            "SELECT id, title, content FROM notes ORDER BY id"))).all()

    keys: list[tuple[str, str]] = []
    keys += [("profile", f"fact:{r[0]}") for r in facts]
    keys += [("material", _mat_ref(m[0], m[1], m[2])) for m in mats]
    keys += [("learning", f"learning:{r[0]}") for r in learns]
    keys += [("note", f"note:{r[0]}") for r in notes]
    umap = await brain_usage.usage_map(keys)

    def _gnode(kind, ref, label, weight=1):
        u = umap.get((kind, ref), {})
        return {"id": ref, "ref": ref, "kind": kind,
                "label": label or "", "val": weight + u.get("usage_count", 0)}

    nodes = []
    nodes += [_gnode("profile", f"fact:{r[0]}", r[2] or r[1]) for r in facts]
    nodes += [_gnode("material", _mat_ref(m[0], m[1], m[2]), m[2], weight=m[3]) for m in mats]
    nodes += [_gnode("learning", f"learning:{r[0]}", r[2] or (r[1] or "")[:40]) for r in learns]
    nodes += [_gnode("note", f"note:{r[0]}", r[1]) for r in notes]

    by_label = {n["label"].lower(): n["id"] for n in nodes if n["label"]}
    links: list[dict] = []
    ghosts: dict[str, dict] = {}
    for nid, _title, content in notes:
        src = f"note:{nid}"
        for target in note_service.parse_links(content):
            tid = by_label.get(target.lower())
            if tid and tid != src:
                links.append({"source": src, "target": tid, "type": "link"})
            elif not tid:
                gid = f"ghost:{target}"
                ghosts.setdefault(gid, {"id": gid, "ref": gid, "kind": "ghost", "label": target, "val": 0.5})
                links.append({"source": src, "target": gid, "type": "link"})

    mat_by_spawn: dict[int, list[str]] = {}
    for m in mats:
        if m[1] is not None:
            mat_by_spawn.setdefault(m[1], []).append(_mat_ref(m[0], m[1], m[2]))
    for lid, _c, _lbl, sref in learns:
        try:
            ref = sref if isinstance(sref, dict) else _json.loads(sref or "{}")
        except Exception:  # noqa: BLE001
            ref = {}
        for mref in mat_by_spawn.get(ref.get("spawn_id"), []):
            links.append({"source": f"learning:{lid}", "target": mref, "type": "provenance"})

    nodes += list(ghosts.values())
    return {"nodes": nodes, "links": links}


@router.get("/brain/entry/{kind}/{ref:path}")
async def brain_entry(kind: str, ref: str) -> dict:
    async with db_session.AsyncSessionLocal() as db:
        if kind == "profile" and ref.startswith("fact:"):
            fid = int(ref.split(":", 1)[1])
            row = (await db.execute(sa_text(
                "SELECT content, label, category, source, confidence FROM user_facts WHERE id = :i"),
                {"i": fid})).first()
            if not row:
                raise HTTPException(404)
            excerpt, label, prov, conf = row[0], row[1], f"{row[2] or ''} · {row[3] or 'auto'}", row[4]
        elif kind == "learning" and ref.startswith("learning:"):
            lid = int(ref.split(":", 1)[1])
            row = (await db.execute(sa_text(
                "SELECT content, label, source_kind, source_ref, confidence FROM learnings WHERE id = :i"),
                {"i": lid})).first()
            if not row:
                raise HTTPException(404)
            excerpt, label, prov, conf = row[0], row[1], f"{row[2]} · {row[3]}", row[4]
        elif kind == "material":
            # ref = material:coll:<id>:<source>  OR  material:spawn:<id>:<source>
            parts = ref.split(":", 3)
            if len(parts) < 4:
                raise HTTPException(404)
            scope_col, scope_id, source = parts[1], parts[2], parts[3]
            col = "collection_id" if scope_col == "coll" else "spawn_id"
            rows = (await db.execute(sa_text(
                f"SELECT text FROM knowledge_chunks WHERE {col} = :i AND source = :s "
                "ORDER BY chunk_index LIMIT 3"), {"i": int(scope_id), "s": source})).all()
            if not rows:
                raise HTTPException(404)
            excerpt = "\n\n".join(r[0] for r in rows)
            label, prov, conf = source, ("投喂" if scope_col == "coll" else "分身"), None
        else:
            raise HTTPException(404)

    u = (await brain_usage.usage_map([(kind, ref)])).get((kind, ref), {})
    return {
        "kind": kind, "ref": ref, "label": label, "provenance": prov, "confidence": conf,
        "excerpt": excerpt,
        "usage_count": u.get("usage_count", 0),
        "last_used_at": _iso(u.get("last_used_at")),
        "last_used_ref": u.get("last_used_ref"),
    }
