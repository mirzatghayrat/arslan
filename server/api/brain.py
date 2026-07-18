"""Typed Second Brain tree + entry detail. Replaces the client-assembled tree so
every leaf carries provenance/confidence/usage from one authoritative place.

brain-P1 Task 5 adds the human proposal-adjudication API (list/accept/dismiss on
memory_proposals) and surfaces the temporal columns (valid_from/superseded_by, plus
the real audit provenance) added by migration 0032. Superseded rows are NOT filtered
out here — unlike the active-only retrieval paths (facts_text/save_facts), the brain
views are meant to stay visible/correctable; how to *render* a superseded node is a
front-end concern for a later round."""
from __future__ import annotations

import json as _json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth import require_auth
from server.db import session as db_session
from server.db.models import Learning, MemoryProposal, Note, Spawn, UserFact
from server.services import brain_usage, memory_temporal
from server.services.memory_temporal import SupersedeError

router = APIRouter(tags=["brain"], dependencies=[Depends(require_auth)])

# brain-P2 Task 5: "notes" and "spawns" added — accept_proposal materializes
# Tier2 kinds onto both (append_suspect/delete_suspect on notes;
# delete_suspect/preference_overwrite_suspect on spawns), and list_proposals
# needs both to render excerpts instead of silently going blank (self-check
# MINOR: notes proposals used to always excerpt None since Note wasn't here).
_TABLE_MODELS = {"user_facts": UserFact, "learnings": Learning, "notes": Note, "spawns": Spawn}

# Sentinel distinguishing "caller didn't pass this kwarg" from "caller passed None"
# — valid_from/superseded_by are legitimately NULL for most rows (legacy backfill,
# still-active facts), so an `is not None` presence check would wrongly hide the key.
_UNSET = object()


def _iso(ts):
    # usage_map reads via raw SQL, so SQLite hands back last_used_at as a str
    # already; only call isoformat() when it's a real datetime.
    if ts is None:
        return None
    return ts.isoformat() if hasattr(ts, "isoformat") else ts


def _json_field(raw):
    """Raw-SQL JSON columns come back as strings (or None) under sqlite+aiosqlite,
    not pre-parsed — mirrors the existing _note_tags() pattern in brain_tree()."""
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    try:
        return _json.loads(raw)
    except Exception:  # noqa: BLE001
        return None


def _leaf(kind, ref_key, label, provenance, confidence, umap, weight=1, category=None, tags=None,
          valid_from=_UNSET, superseded_by=_UNSET):
    """weight = content richness (material: chunk count; profile/learning: 1). The
    sunburst angular size is weight + usage_count. category/tags/valid_from/
    superseded_by are optional and only emitted when the caller passes them — they
    drive the left-nav sub-grouping + tag explorer (category/tags) or are P1 temporal
    fields only meaningful for profile/learning leaves (valid_from/superseded_by)."""
    u = umap.get((kind, ref_key), {})
    out = {
        "kind": kind, "ref": ref_key, "label": label, "provenance": provenance,
        "confidence": confidence,
        "usage_count": u.get("usage_count", 0),
        "last_used_at": _iso(u.get("last_used_at")),
        "last_used_ref": u.get("last_used_ref"),
        "value": weight + u.get("usage_count", 0),
    }
    if category is not None:
        out["category"] = category
    if tags is not None:
        out["tags"] = tags
    if valid_from is not _UNSET:
        out["valid_from"] = _iso(valid_from)
    if superseded_by is not _UNSET:
        out["superseded_by"] = superseded_by
    return out


def _mat_ref(collection_id, spawn_id, source) -> str:
    return (f"material:coll:{collection_id}:{source}" if collection_id is not None
            else f"material:spawn:{spawn_id}:{source}")


@router.get("/brain/tree")
async def brain_tree() -> dict:
    async with db_session.AsyncSessionLocal() as db:
        facts = (await db.execute(sa_text(
            "SELECT id, content, label, category, source, confidence, valid_from, superseded_by "
            "FROM user_facts ORDER BY id"))).all()
        mats = (await db.execute(sa_text(
            "SELECT collection_id, spawn_id, source, COUNT(*) n FROM knowledge_chunks "
            "GROUP BY collection_id, spawn_id, source"))).all()
        learns = (await db.execute(sa_text(
            "SELECT id, content, label, source_kind, confidence, valid_from, superseded_by "
            "FROM learnings ORDER BY id"))).all()
        notes = (await db.execute(sa_text(
            "SELECT id, title, tags FROM notes ORDER BY updated_at DESC"))).all()

    keys: list[tuple[str, str]] = []
    keys += [("profile", f"fact:{r[0]}") for r in facts]
    keys += [("material", _mat_ref(m[0], m[1], m[2])) for m in mats]
    keys += [("learning", f"learning:{r[0]}") for r in learns]
    keys += [("note", f"note:{r[0]}") for r in notes]
    umap = await brain_usage.usage_map(keys)

    profile_leaves = [
        _leaf("profile", f"fact:{r[0]}", r[2] or r[1], r[4] or "auto", r[5], umap,
              category=r[3], valid_from=r[6], superseded_by=r[7]) for r in facts]
    material_leaves = [
        _leaf("material", _mat_ref(m[0], m[1], m[2]), m[2],
              ("投喂" if m[0] is not None else "分身"), None, umap, weight=m[3])
        for m in mats]
    learning_leaves = [
        _leaf("learning", f"learning:{r[0]}", r[2] or (r[1] or "")[:40], r[3], r[4], umap,
              valid_from=r[5], superseded_by=r[6]) for r in learns]

    import json as _json_tree
    def _note_tags(raw):
        try:
            return raw if isinstance(raw, list) else _json_tree.loads(raw or "[]")
        except Exception:  # noqa: BLE001
            return []
    note_leaves = [_leaf("note", f"note:{r[0]}", r[1], "手写", None, umap,
                         tags=_note_tags(r[2])) for r in notes]

    return {"branches": [
        {"kind": "material", "label": "材料", "children": material_leaves},
        {"kind": "learning", "label": "心得", "children": learning_leaves},
        {"kind": "profile", "label": "画像", "children": profile_leaves},
        {"kind": "note", "label": "笔记", "children": note_leaves},
    ]}


@router.get("/brain/graph")
async def brain_graph() -> dict:
    """Force-graph data. Every entry (4 types) is a node; edges come from note
    [[links]] (unresolved → ghost), 心得→spawn-well-material provenance, note/fact
    tags (shared tag → tag node), and a synthetic 「你」 hub that anchors every tag
    cluster and catches any otherwise-orphaned entry — so the whole brain is ONE
    connected constellation centered on you."""
    from server.services import note_service

    async with db_session.AsyncSessionLocal() as db:
        # brain-P1 Task 5: widened to carry source/confidence/superseded_by (facts) and
        # superseded_by (learnings) into the node payload. This changes the tuple arity
        # (facts 4->7, learnings 4->5) — every positional unpack/index of these two
        # result sets below (the profile/learning node builders, and the tag-linking
        # loops further down) had to be updated in lockstep or this crashes at runtime.
        facts = (await db.execute(sa_text(
            "SELECT id, content, label, category, source, confidence, superseded_by "
            "FROM user_facts ORDER BY id"))).all()
        mats = (await db.execute(sa_text(
            "SELECT collection_id, spawn_id, source, COUNT(*) n FROM knowledge_chunks "
            "GROUP BY collection_id, spawn_id, source"))).all()
        learns = (await db.execute(sa_text(
            "SELECT id, content, label, source_ref, superseded_by FROM learnings ORDER BY id"))).all()
        notes = (await db.execute(sa_text(
            "SELECT id, title, content, tags FROM notes ORDER BY id"))).all()

    keys: list[tuple[str, str]] = []
    keys += [("profile", f"fact:{r[0]}") for r in facts]
    keys += [("material", _mat_ref(m[0], m[1], m[2])) for m in mats]
    keys += [("learning", f"learning:{r[0]}") for r in learns]
    keys += [("note", f"note:{r[0]}") for r in notes]
    umap = await brain_usage.usage_map(keys)

    def _gnode(kind, ref, label, weight=1, **extra):
        u = umap.get((kind, ref), {})
        node = {"id": ref, "ref": ref, "kind": kind,
                "label": label or "", "val": weight + u.get("usage_count", 0)}
        node.update(extra)
        return node

    nodes = []
    nodes += [_gnode("profile", f"fact:{r[0]}", r[2] or r[1],
                     source=r[4], confidence=r[5], superseded_by=r[6]) for r in facts]
    nodes += [_gnode("material", _mat_ref(m[0], m[1], m[2]), m[2], weight=m[3]) for m in mats]
    nodes += [_gnode("learning", f"learning:{r[0]}", r[2] or (r[1] or "")[:40],
                     superseded_by=r[4]) for r in learns]
    nodes += [_gnode("note", f"note:{r[0]}", r[1]) for r in notes]

    by_label = {n["label"].lower(): n["id"] for n in nodes if n["label"]}
    links: list[dict] = []
    ghosts: dict[str, dict] = {}

    # 1) note [[links]] → resolved link / ghost node
    for nid, _title, content, _tags in notes:
        src = f"note:{nid}"
        for target in note_service.parse_links(content):
            tid = by_label.get(target.lower())
            if tid and tid != src:
                links.append({"source": src, "target": tid, "type": "link"})
            elif not tid:
                gid = f"ghost:{target}"
                ghosts.setdefault(gid, {"id": gid, "ref": gid, "kind": "ghost", "label": target, "val": 0.5})
                links.append({"source": src, "target": gid, "type": "link"})

    # 2) 心得 → spawn-well material provenance
    mat_by_spawn: dict[int, list[str]] = {}
    for m in mats:
        if m[1] is not None:
            mat_by_spawn.setdefault(m[1], []).append(_mat_ref(m[0], m[1], m[2]))
    for lid, _c, _lbl, sref, _superseded_by in learns:
        try:
            ref = sref if isinstance(sref, dict) else _json.loads(sref or "{}")
        except Exception:  # noqa: BLE001
            ref = {}
        for mref in mat_by_spawn.get(ref.get("spawn_id"), []):
            links.append({"source": f"learning:{lid}", "target": mref, "type": "provenance"})

    # 3) tag nodes: note tags ∪ fact category. Shared tag → items connect through it.
    tag_ids: dict[str, str] = {}   # lower-name → node id

    def _tag_node(name: str) -> str:
        key = name.strip().lower()
        tid = f"tag:{key}"
        if key and tid not in tag_ids:
            tag_ids[key] = tid
        return tid

    for nid, _title, _content, tags in notes:
        try:
            tag_list = tags if isinstance(tags, list) else _json.loads(tags or "[]")
        except Exception:  # noqa: BLE001
            tag_list = []
        for t in tag_list:
            if isinstance(t, str) and t.strip():
                links.append({"source": f"note:{nid}", "target": _tag_node(t), "type": "tag"})
    for fid, _content, _label, category, _source, _confidence, _superseded_by in facts:
        if category and str(category).strip():
            links.append({"source": f"fact:{fid}", "target": _tag_node(category), "type": "tag"})

    tag_nodes = [{"id": tid, "ref": tid, "kind": "tag", "label": tid[4:], "val": 1}
                 for tid in tag_ids.values()]

    # 4) degree over everything built so far → orphan fallback to 「你」
    degree: dict[str, int] = {}
    for edge in links:
        degree[edge["source"]] = degree.get(edge["source"], 0) + 1
        degree[edge["target"]] = degree.get(edge["target"], 0) + 1

    # 「你」 anchors every tag cluster …
    for tid in tag_ids.values():
        links.append({"source": "self", "target": tid, "type": "hub"})
    # … and catches any real node with no edge yet (profile w/o category included)
    for n in nodes:
        if degree.get(n["id"], 0) == 0:
            links.append({"source": "self", "target": n["id"], "type": "hub"})

    max_val = max((n["val"] for n in nodes), default=1)
    self_node = {"id": "self", "ref": "self", "kind": "self", "label": "你", "val": max_val + 2}

    return {"nodes": [self_node, *nodes, *tag_nodes, *ghosts.values()], "links": links}


@router.get("/brain/entry/{kind}/{ref:path}")
async def brain_entry(kind: str, ref: str) -> dict:
    # brain-P1 Task 5: fact/learning detail gains valid_from/superseded_by/provenance.
    # "provenance" (the display string built below, e.g. "身份背景 · auto") already
    # existed pre-P1 and is a live frontend contract (BrainEntryDetail.tsx renders it
    # as text; BrainNav.tsx groups by it — see test_brain_entry_material_excerpt).
    # The real temporal audit payload is therefore surfaced under the non-colliding
    # key "provenance_record" instead of overloading "provenance" — see
    # test_brain_api.py's brain-P1 Task 5 section and task-5-report.md for the
    # rationale. material has no temporal concept, so these three stay None for it.
    valid_from = superseded_by = provenance_record = None
    async with db_session.AsyncSessionLocal() as db:
        if kind == "profile" and ref.startswith("fact:"):
            fid = int(ref.split(":", 1)[1])
            row = (await db.execute(sa_text(
                "SELECT content, label, category, source, confidence, valid_from, "
                "superseded_by, provenance FROM user_facts WHERE id = :i"),
                {"i": fid})).first()
            if not row:
                raise HTTPException(404)
            excerpt, label, prov, conf = row[0], row[1], f"{row[2] or ''} · {row[3] or 'auto'}", row[4]
            valid_from, superseded_by = row[5], row[6]
            provenance_record = _json_field(row[7])
        elif kind == "learning" and ref.startswith("learning:"):
            lid = int(ref.split(":", 1)[1])
            row = (await db.execute(sa_text(
                "SELECT content, label, source_kind, source_ref, confidence, valid_from, "
                "superseded_by FROM learnings WHERE id = :i"),
                {"i": lid})).first()
            if not row:
                raise HTTPException(404)
            excerpt, label, prov, conf = row[0], row[1], f"{row[2]} · {row[3]}", row[4]
            valid_from, superseded_by = row[5], row[6]
            # Learning has no provenance column by design (models.py: source_kind +
            # source_ref ARE its provenance — a separate column would be a second,
            # competing source of truth); synthesize the same shape from those two.
            provenance_record = {"source_kind": row[2], "source_ref": _json_field(row[3])}
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
        "valid_from": _iso(valid_from),
        "superseded_by": superseded_by,
        "provenance_record": provenance_record,
        "usage_count": u.get("usage_count", 0),
        "last_used_at": _iso(u.get("last_used_at")),
        "last_used_ref": u.get("last_used_ref"),
    }


# ---------------------------------------------------------------------------------
# Proposal adjudication (brain-P1 Task 5): memory_proposals is the rule layer's soft
# flag for supersede/contradiction pairs it isn't confident enough to auto-resolve
# (see server.services.fact_dedup.fuzzy_kind + the rule-supersede call sites in
# server/orchestrator/memory.py and server/services/learning_service.py). A human
# accepts (deterministically executes the pointer write via the same
# memory_temporal.execute_supersede guarded executor the rule path uses) or dismisses
# (no-op cleanup) each one. These three endpoints use the FastAPI get_session
# dependency (unlike the three read endpoints above) so tests can override it via
# app.dependency_overrides, matching the rest of the proposal-shaped routers
# (server/api/evolution.py).
# ---------------------------------------------------------------------------------


def _proposal_dict(p: MemoryProposal, *, new_excerpt=_UNSET, old_excerpt=_UNSET) -> dict:
    out = {
        "id": p.id, "kind": p.kind, "table_name": p.table_name,
        "new_id": p.new_id, "old_id": p.old_id, "reason": p.reason,
        "status": p.status, "provenance": p.provenance,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "resolved_at": p.resolved_at.isoformat() if p.resolved_at else None,
    }
    if new_excerpt is not _UNSET:
        out["new_excerpt"] = new_excerpt
    if old_excerpt is not _UNSET:
        out["old_excerpt"] = old_excerpt
    return out


def _excerpt_for(row) -> str | None:
    """Best-effort human-readable excerpt for a proposal's new/old referent —
    display-only, used by list_proposals. user_facts/learnings/notes all carry
    the text under `.content`; a "spawns" referent (preference proposals) has
    no free-text column, so its memory_facts array is joined instead."""
    if row is None:
        return None
    if hasattr(row, "content"):
        return (row.content or "")[:200]
    if hasattr(row, "memory_facts"):
        return "; ".join(row.memory_facts or [])[:200] or None
    return None


@router.get("/brain/proposals")
async def list_proposals(
    status: str = "pending", session: AsyncSession = Depends(db_session.get_session)
) -> list[dict]:
    rows = (await session.execute(
        select(MemoryProposal).where(MemoryProposal.status == status)
        .order_by(MemoryProposal.id)
    )).scalars().all()

    out = []
    for p in rows:
        model = _TABLE_MODELS.get(p.table_name)
        # brain-P2 Task 5 self-check MINOR: new_id is nullable (0033) and every
        # Tier2 proposal kind has new_id=None at propose time (nothing
        # materialized yet) — session.get(model, None) degrades to a "fully
        # NULL primary key" SAWarning rather than a real lookup, so skip the
        # call outright instead of relying on that degrade-path.
        new_row = await session.get(model, p.new_id) if (model and p.new_id is not None) else None
        old_row = await session.get(model, p.old_id) if (model and p.old_id is not None) else None
        out.append(_proposal_dict(
            p, new_excerpt=_excerpt_for(new_row), old_excerpt=_excerpt_for(old_row)))
    return out


def _supersede_error_response(exc: SupersedeError) -> HTTPException:
    """Shared SupersedeError -> 4xx mapping (plan #19), reused by both
    supersede_suspect (unchanged) and edit_high_conf_suspect (which
    materializes a new row first, then reuses the same guarded executor for
    the pointer write): dangling_new/dangling_old -> 410 (referenced row was
    deleted out from under a still-pending proposal); already_superseded/
    new_is_superseded/cycle/self_supersede -> 409 (state conflict); bad_table
    -> 422 (the proposal row's own table_name is corrupt — a data-integrity
    defect, not a conflict)."""
    if exc.code in ("dangling_new", "dangling_old"):
        return HTTPException(status_code=410, detail=exc.detail)
    if exc.code == "bad_table":
        return HTTPException(status_code=422, detail=exc.detail)
    return HTTPException(status_code=409, detail=exc.detail)


async def _accept_edit_high_conf(session: AsyncSession, p: MemoryProposal, pid: int,
                                 human_prov: dict) -> None:
    """Materialize the edited content as a NEW user_facts row — new_id is
    ALWAYS None at propose time (Task 4 never writes ahead of human
    confirmation; the content lives in provenance JSON) — then supersede the
    old row through the same guarded executor supersede_suspect uses.

    RememberExecutor's scope-downgrade branch only ever proposes
    edit_high_conf_suspect for kind="fact" (table_name="user_facts") — a
    spawn attempting to supersede/mark_stale a kind="note" is refused
    upfront by RememberExecutor itself (notes have no superseded_by column,
    no temporal concept at all, plan's "矩阵按表能力"; see
    test_memory_scope_isolation.py::test_spawn_supersede_note_is_a_clean_error_not_a_proposal),
    so it never reaches a MemoryProposal row in the first place. The
    table_name != "user_facts" guard below is defense in depth for a stale
    row from before that fix, or a malformed/manually-inserted proposal —
    refused cleanly (422) rather than writing an orphan fact that could
    never actually supersede anything.
    """
    content = (p.provenance or {}).get("content")
    if not content:
        raise HTTPException(status_code=422,
                            detail=f"proposal {pid}: edit_high_conf_suspect missing 'content'")
    if p.table_name != "user_facts":
        raise HTTPException(status_code=422,
                            detail=f"proposal {pid}: edit_high_conf_suspect unsupported for "
                                   f"table {p.table_name!r}")

    from server.orchestrator import memory

    # Drop "content" from the fact's own provenance blob — it would otherwise
    # duplicate the row's `content` column inside its own audit JSON. Every
    # edit_high_conf_suspect proposal is agentic-originated by construction
    # (RememberExecutor is its only writer) — if stripping "content" leaves
    # nothing behind (a minimal/degenerate provenance payload), fall back to
    # that honest default rather than letting save_facts' mandatory-provenance
    # guard raise an unhandled ValueError (500) here.
    fact_provenance = {k: v for k, v in (p.provenance or {}).items() if k != "content"}
    if not fact_provenance:
        fact_provenance = {"source_kind": "agentic"}
    new_rows = await memory.save_facts([{"content": content}], provenance=fact_provenance)
    if not new_rows:
        raise HTTPException(status_code=422,
                            detail=f"proposal {pid}: edit content could not be materialized "
                                   "(merged into an existing active fact)")
    new_id = new_rows[0].id

    try:
        await memory_temporal.execute_supersede(
            "user_facts", new_id, p.old_id, provenance=human_prov, db=session)
    except SupersedeError as exc:
        if exc.code == "already_superseded":
            # save_facts() runs its OWN exact/fuzzy dedup on every write
            # (active-only): if the edit content is an "extension" of
            # old_id's content, save_facts may have already auto-superseded
            # old_id onto this very new_id before we got here. That's not a
            # conflict — it's the same materialization via a different code
            # path — so only re-raise if old_id ended up pointed somewhere
            # else (a genuine out-of-band conflict).
            old_row = await session.get(UserFact, p.old_id)
            if old_row is not None and old_row.superseded_by == new_id:
                return
        raise _supersede_error_response(exc) from exc


async def _accept_append_suspect(session: AsyncSession, p: MemoryProposal, pid: int) -> None:
    content = (p.provenance or {}).get("content")
    if not content:
        raise HTTPException(status_code=422,
                            detail=f"proposal {pid}: append_suspect missing 'content'")
    if p.table_name == "user_facts":
        from server.orchestrator import memory
        await memory.save_facts([{"content": content}], provenance=p.provenance)
    elif p.table_name == "notes":
        from server.services import note_service
        await note_service.create(title=content[:200], content=content)
    else:
        raise HTTPException(status_code=422,
                            detail=f"proposal {pid}: append_suspect unsupported for "
                                   f"table {p.table_name!r}")


async def _accept_delete_suspect(session: AsyncSession, p: MemoryProposal, pid: int) -> None:
    """🔴 Dangling-pointer guard: reconcile FIRST — any row whose
    superseded_by points at the row we're about to delete becomes active
    again — committed durably before the delete itself runs, so a still-live
    predecessor's pointer never ends up dangling at a now-gone id even if the
    delete step below then 410s. THEN delete. A target that's already gone
    (someone deleted it out of band, or a double-accept race) -> 410, same
    mapping as the supersede branches."""
    if p.table_name == "user_facts":
        await session.execute(sa_text(
            "UPDATE user_facts SET superseded_by = NULL WHERE superseded_by = :o"),
            {"o": p.old_id})
        await session.commit()
        from server.orchestrator import memory
        ok = await memory.delete_fact(p.old_id)
        if not ok:
            raise HTTPException(status_code=410,
                                detail=f"user_facts id {p.old_id} does not exist")
    elif p.table_name == "learnings":
        await session.execute(sa_text(
            "UPDATE learnings SET superseded_by = NULL WHERE superseded_by = :o"),
            {"o": p.old_id})
        await session.commit()
        row = await session.get(Learning, p.old_id)
        if row is None:
            raise HTTPException(status_code=410,
                                detail=f"learnings id {p.old_id} does not exist")
        await session.delete(row)
        await session.execute(sa_text("DELETE FROM learnings_fts WHERE rowid = :r"),
                              {"r": p.old_id})
    elif p.table_name == "notes":
        # No temporal concept on notes (no superseded_by column) — nothing to
        # reconcile; note_service.delete already sweeps the FTS row.
        from server.services import note_service
        ok = await note_service.delete(p.old_id)
        if not ok:
            raise HTTPException(status_code=410, detail=f"notes id {p.old_id} does not exist")
    elif p.table_name == "spawns":
        # Preference delete (RememberExecutor._propose stores target_spawn_id
        # explicitly; old_id mirrors it) — clears the whole preference array,
        # the only granularity memory_facts (a plain string list, no per-item
        # id) supports. No temporal concept, so no reconcile needed.
        sid = (p.provenance or {}).get("target_spawn_id", p.old_id)
        spawn = await session.get(Spawn, sid)
        if spawn is None:
            raise HTTPException(status_code=410, detail=f"spawns id {sid} does not exist")
        spawn.memory_facts = []
    else:
        raise HTTPException(status_code=422,
                            detail=f"proposal {pid}: delete_suspect unsupported for "
                                   f"table {p.table_name!r}")


async def _accept_preference_overwrite(session: AsyncSession, p: MemoryProposal, pid: int) -> None:
    prov = p.provenance or {}
    sid, new_arr = prov.get("target_spawn_id"), prov.get("new_array")
    if sid is None or new_arr is None:
        raise HTTPException(status_code=422,
                            detail=f"proposal {pid}: preference_overwrite_suspect missing "
                                   "target_spawn_id/new_array")
    spawn = await session.get(Spawn, sid)
    if spawn is None:
        raise HTTPException(status_code=410, detail=f"spawns id {sid} does not exist")
    spawn.memory_facts = new_arr


@router.post("/brain/proposals/{pid}/accept")
async def accept_proposal(
    pid: int, session: AsyncSession = Depends(db_session.get_session)
) -> dict:
    """Human confirms -> deterministic materialization, branched by kind
    (brain-P2 Task 5). supersede_suspect keeps the original P1 behavior
    unchanged (both rows already exist — pure pointer write). The four Tier2
    kinds Task 4's RememberExecutor can emit each get their own branch below;
    every one of them ends by falling through to the shared status=accepted +
    resolved_at write so there is exactly one success path. Each branch's own
    docstring/comments carry its specific error mapping; the common shape is
    dangling referent -> 410, state conflict -> 409, bad/missing data -> 422."""
    p = await session.get(MemoryProposal, pid)
    if p is None:
        raise HTTPException(status_code=404, detail=f"proposal {pid} not found")
    if p.status != "pending":
        raise HTTPException(status_code=409,
                            detail=f"proposal {pid} already resolved (status={p.status})")

    human_prov = {"source_kind": "human", "via": "proposal", "proposal_id": pid}

    if p.kind == "supersede_suspect":
        try:
            await memory_temporal.execute_supersede(
                p.table_name, p.new_id, p.old_id, provenance=human_prov, db=session)
        except SupersedeError as exc:
            raise _supersede_error_response(exc) from exc
    elif p.kind == "edit_high_conf_suspect":
        await _accept_edit_high_conf(session, p, pid, human_prov)
    elif p.kind == "append_suspect":
        await _accept_append_suspect(session, p, pid)
    elif p.kind == "delete_suspect":
        await _accept_delete_suspect(session, p, pid)
    elif p.kind == "preference_overwrite_suspect":
        await _accept_preference_overwrite(session, p, pid)
    else:
        raise HTTPException(status_code=422, detail=f"proposal {pid}: unmapped kind {p.kind!r}")

    p.status = "accepted"
    p.resolved_at = datetime.utcnow()
    await session.commit()
    await session.refresh(p)
    return _proposal_dict(p)


@router.post("/brain/proposals/{pid}/dismiss")
async def dismiss_proposal(
    pid: int, session: AsyncSession = Depends(db_session.get_session)
) -> dict:
    """Human rejects the suggestion: mark dismissed, no pointer write. Unlike accept,
    a dangling referent is NOT an error here — dismissing a proposal whose row was
    since deleted is valid inbox cleanup, not a supersede attempt."""
    p = await session.get(MemoryProposal, pid)
    if p is None:
        raise HTTPException(status_code=404, detail=f"proposal {pid} not found")
    if p.status != "pending":
        raise HTTPException(status_code=409,
                            detail=f"proposal {pid} already resolved (status={p.status})")

    p.status = "dismissed"
    p.resolved_at = datetime.utcnow()
    await session.commit()
    await session.refresh(p)
    return _proposal_dict(p)
