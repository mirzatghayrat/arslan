"""Typed Second Brain tree + entry detail. Replaces the client-assembled tree so
every leaf carries provenance/confidence/usage from one authoritative place.

brain-P1 Task 5 adds the human proposal-adjudication API (list/accept/dismiss on
memory_proposals) and surfaces the temporal columns (valid_from/superseded_by, plus
the real audit provenance) added by migration 0032. Superseded rows are NOT filtered
out here — unlike the active-only retrieval paths (facts_text/save_facts), the brain
views are meant to stay visible/correctable; how to *render* a superseded node is a
front-end concern for a later round.

🔴 `sensitive` ON THESE PAYLOADS IS A RENDERING HINT, NOT PROTECTION. The three read
endpoints below return a sensitive fact's full text as `label` / `excerpt` and always
have; exposing the flag lets the UI draw a lock badge, and changes nothing about what
is on the wire. Real protection would mean masking the content too — a separate,
larger decision. Do not describe this as "the second brain isolates sensitive facts".
The flag is coerced FAIL-CLOSED (NULL ⇒ sensitive), mirroring memory.facts_text and
RecallExecutor, because the column is nullable and raw inserts leave it NULL.
"""
from __future__ import annotations

import json as _json
import re as _re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
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


#: an ISO offset at the very end, e.g. "+08:00" / "-05:00" — NOT a date's hyphens
_HAS_OFFSET = _re.compile(r"[+-]\d{2}:?\d{2}$")


def _iso(ts):
    # usage_map reads via raw SQL, so SQLite hands back last_used_at as a str
    # already; only call isoformat() when it's a real datetime.
    #
    # D5: that passthrough string is SQLite's storage form,
    # "YYYY-MM-DD HH:MM:SS.ffffff" — a SPACE where ISO-8601 wants a T. `new Date(...)`
    # on it is implementation-defined: Chrome accepts it, Safari returns Invalid Date.
    # Survivable while these timestamps were only rendered as text; the activity
    # timeline PLOTS them, so normalize here instead of making every caller remember.
    # ...and it must carry a UTC designator. Every datetime the brain stores is written
    # with datetime.utcnow() — naive UTC — so a bare "2026-07-19T10:19:03" is parsed by
    # `new Date()` as LOCAL time and shifts the whole activity timeline by the viewer's
    # offset. Emitting "Z" costs one character and is the difference between a plotted
    # timeline being right and being off by hours for everyone outside UTC.
    if ts is None:
        return None
    text = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
    text = text.replace(" ", "T", 1) if " " in text else text
    # already carries an offset (a tz-aware value somewhere upstream) — leave it alone
    if text.endswith("Z") or _HAS_OFFSET.search(text):
        return text
    return text + "Z"


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


def _sensitive(value) -> bool:
    """FAIL-CLOSED: NULL means sensitive; only an explicit false value means it is not.

    Two traps in one line:
      * the column is nullable and raw inserts leave it NULL, so `bool(value)` would
        render an unmarked fact as SAFE — the opposite of the house rule used by
        memory.facts_text and RecallExecutor;
      * those two use the idiom `f.sensitive is False`, which works on ORM objects but
        NOT here: these endpoints read through `sa_text`, and SQLite hands back integers
        0/1, so `0 is not False` is True and every fact would report sensitive.
    """
    return value is None or bool(value)


def _leaf(kind, ref_key, label, provenance, confidence, umap, weight=1, category=None, tags=None,
          valid_from=_UNSET, superseded_by=_UNSET, sensitive=_UNSET):
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
    if sensitive is not _UNSET:
        # profile leaves ONLY: user_facts is the sole table with the column, so a
        # learning/material/note leaf must not carry a flag it never checked.
        out["sensitive"] = sensitive
    return out


def _mat_ref(collection_id, spawn_id, source) -> str:
    return (f"material:coll:{collection_id}:{source}" if collection_id is not None
            else f"material:spawn:{spawn_id}:{source}")


@router.get("/brain/tree")
async def brain_tree() -> dict:
    async with db_session.AsyncSessionLocal() as db:
        # .mappings(): rows are read BY NAME everywhere below. Positional access made
        # widening a SELECT unsafe in two different ways — brain_graph unpacked a fixed
        # arity (hard ValueError, and only on rows with a non-blank category, so an
        # empty-DB smoke passed while production 500'd), while tree/entry indexed
        # r[0]..r[7] so an inserted column SILENTLY shifted every later value.
        facts = (await db.execute(sa_text(
            "SELECT id, content, label, category, source, confidence, valid_from, superseded_by, "
            "sensitive FROM user_facts ORDER BY id"))).mappings().all()
        mats = (await db.execute(sa_text(
            "SELECT collection_id, spawn_id, source, COUNT(*) n FROM knowledge_chunks "
            "GROUP BY collection_id, spawn_id, source"))).mappings().all()
        learns = (await db.execute(sa_text(
            "SELECT id, content, label, source_kind, confidence, valid_from, superseded_by "
            "FROM learnings ORDER BY id"))).mappings().all()
        notes = (await db.execute(sa_text(
            "SELECT id, title, tags FROM notes ORDER BY updated_at DESC"))).mappings().all()

    keys: list[tuple[str, str]] = []
    keys += [("profile", f"fact:{r['id']}") for r in facts]
    keys += [("material", _mat_ref(m["collection_id"], m["spawn_id"], m["source"]))
             for m in mats]
    keys += [("learning", f"learning:{r['id']}") for r in learns]
    keys += [("note", f"note:{r['id']}") for r in notes]
    umap = await brain_usage.usage_map(keys)

    profile_leaves = [
        _leaf("profile", f"fact:{r['id']}", r["label"] or r["content"],
              r["source"] or "auto", r["confidence"], umap,
              category=r["category"], valid_from=r["valid_from"],
              superseded_by=r["superseded_by"],
              sensitive=_sensitive(r["sensitive"])) for r in facts]
    material_leaves = [
        _leaf("material", _mat_ref(m["collection_id"], m["spawn_id"], m["source"]),
              m["source"], ("投喂" if m["collection_id"] is not None else "分身"),
              None, umap, weight=m["n"])
        for m in mats]
    learning_leaves = [
        _leaf("learning", f"learning:{r['id']}",
              r["label"] or (r["content"] or "")[:40], r["source_kind"], r["confidence"],
              umap, valid_from=r["valid_from"], superseded_by=r["superseded_by"])
        for r in learns]

    import json as _json_tree
    def _note_tags(raw):
        try:
            return raw if isinstance(raw, list) else _json_tree.loads(raw or "[]")
        except Exception:  # noqa: BLE001
            return []
    note_leaves = [_leaf("note", f"note:{r['id']}", r["title"], "手写", None, umap,
                         tags=_note_tags(r["tags"])) for r in notes]

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
            "SELECT id, content, label, category, source, confidence, superseded_by, "
            "sensitive, provenance FROM user_facts ORDER BY id"))).mappings().all()
        mats = (await db.execute(sa_text(
            "SELECT collection_id, spawn_id, source, COUNT(*) n FROM knowledge_chunks "
            "GROUP BY collection_id, spawn_id, source"))).mappings().all()
        learns = (await db.execute(sa_text(
            "SELECT id, content, label, source_kind, source_ref, superseded_by "
            "FROM learnings ORDER BY id"))).mappings().all()
        notes = (await db.execute(sa_text(
            "SELECT id, title, content, tags FROM notes ORDER BY id"))).mappings().all()

    keys: list[tuple[str, str]] = []
    keys += [("profile", f"fact:{r['id']}") for r in facts]
    keys += [("material", _mat_ref(m["collection_id"], m["spawn_id"], m["source"]))
             for m in mats]
    keys += [("learning", f"learning:{r['id']}") for r in learns]
    keys += [("note", f"note:{r['id']}") for r in notes]
    umap = await brain_usage.usage_map(keys)

    def _gnode(kind, ref, label, weight=1, **extra):
        """D4: usage is now emitted explicitly, not only folded into `val`.

        `val` is a RENDER SIZE (weight + usage) — the frontend cannot recover the raw
        count from it, which is what the活跃时间条 needs. Both are emitted; they are
        not redundant. Missing keys default to 0/None rather than being omitted, so
        "never used" is distinguishable from "not reported".

        Synthetic nodes (tag / self / ghost) are built as literals elsewhere and
        deliberately do NOT come through here: they have no usage or provenance
        concept, and emitting usage_count: 0 for them would be a false claim that
        usage was looked up."""
        u = umap.get((kind, ref), {})
        node = {"id": ref, "ref": ref, "kind": kind,
                "label": label or "", "val": weight + u.get("usage_count", 0),
                "usage_count": u.get("usage_count", 0),
                "last_used_at": _iso(u.get("last_used_at"))}
        node.update(extra)
        return node

    nodes = []
    nodes += [_gnode("profile", f"fact:{r['id']}", r["label"] or r["content"],
                     source=r["source"], confidence=r["confidence"],
                     superseded_by=r["superseded_by"],
                     sensitive=_sensitive(r["sensitive"]),
                     # same shape /brain/entry returns — a node's claim and the panel
                     # that opens from it must not disagree
                     provenance_record=_json_field(r["provenance"])) for r in facts]
    nodes += [_gnode("material", _mat_ref(m["collection_id"], m["spawn_id"], m["source"]),
                     m["source"], weight=m["n"]) for m in mats]
    nodes += [_gnode("learning", f"learning:{r['id']}",
                     r["label"] or (r["content"] or "")[:40],
                     superseded_by=r["superseded_by"],
                     # learnings have no provenance column by design: source_kind +
                     # source_ref ARE the provenance. Synthesized identically to
                     # /brain/entry so the two cannot drift.
                     provenance_record={"source_kind": r["source_kind"],
                                        "source_ref": _json_field(r["source_ref"])})
              for r in learns]
    nodes += [_gnode("note", f"note:{r['id']}", r["title"]) for r in notes]

    by_label = {n["label"].lower(): n["id"] for n in nodes if n["label"]}
    links: list[dict] = []
    ghosts: dict[str, dict] = {}

    # 1) note [[links]] → resolved link / ghost node
    for r in notes:
        src = f"note:{r['id']}"
        for target in note_service.parse_links(r["content"]):
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
        if m["spawn_id"] is not None:
            mat_by_spawn.setdefault(m["spawn_id"], []).append(
                _mat_ref(m["collection_id"], m["spawn_id"], m["source"]))
    for r in learns:
        sref = r["source_ref"]
        try:
            ref = sref if isinstance(sref, dict) else _json.loads(sref or "{}")
        except Exception:  # noqa: BLE001
            ref = {}
        for mref in mat_by_spawn.get(ref.get("spawn_id"), []):
            links.append({"source": f"learning:{r['id']}", "target": mref,
                          "type": "provenance"})

    # 3) tag nodes: note tags ∪ fact category. Shared tag → items connect through it.
    tag_ids: dict[str, str] = {}   # lower-name → node id

    def _tag_node(name: str) -> str:
        key = name.strip().lower()
        tid = f"tag:{key}"
        if key and tid not in tag_ids:
            tag_ids[key] = tid
        return tid

    for r in notes:
        tags = r["tags"]
        try:
            tag_list = tags if isinstance(tags, list) else _json.loads(tags or "[]")
        except Exception:  # noqa: BLE001
            tag_list = []
        for t in tag_list:
            if isinstance(t, str) and t.strip():
                links.append({"source": f"note:{r['id']}", "target": _tag_node(t),
                              "type": "tag"})
    for r in facts:
        category = r["category"]
        if category and str(category).strip():
            links.append({"source": f"fact:{r['id']}", "target": _tag_node(category),
                          "type": "tag"})

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
    sensitive = None
    async with db_session.AsyncSessionLocal() as db:
        if kind == "profile" and ref.startswith("fact:"):
            fid = int(ref.split(":", 1)[1])
            row = (await db.execute(sa_text(
                "SELECT content, label, category, source, confidence, valid_from, "
                "superseded_by, provenance, sensitive FROM user_facts WHERE id = :i"),
                {"i": fid})).mappings().first()
            if not row:
                raise HTTPException(404)
            excerpt, label = row["content"], row["label"]
            prov = f"{row['category'] or ''} · {row['source'] or 'auto'}"
            conf = row["confidence"]
            valid_from, superseded_by = row["valid_from"], row["superseded_by"]
            provenance_record = _json_field(row["provenance"])
            sensitive = _sensitive(row["sensitive"])
        elif kind == "learning" and ref.startswith("learning:"):
            lid = int(ref.split(":", 1)[1])
            row = (await db.execute(sa_text(
                "SELECT content, label, source_kind, source_ref, confidence, valid_from, "
                "superseded_by FROM learnings WHERE id = :i"),
                {"i": lid})).mappings().first()
            if not row:
                raise HTTPException(404)
            excerpt, label = row["content"], row["label"]
            prov = f"{row['source_kind']} · {row['source_ref']}"
            conf = row["confidence"]
            valid_from, superseded_by = row["valid_from"], row["superseded_by"]
            # Learning has no provenance column by design (models.py: source_kind +
            # source_ref ARE its provenance — a separate column would be a second,
            # competing source of truth); synthesize the same shape from those two.
            provenance_record = {"source_kind": row["source_kind"],
                                 "source_ref": _json_field(row["source_ref"])}
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
        # rendering hint only — see the module docstring
        **({"sensitive": sensitive} if sensitive is not None else {}),
        "usage_count": u.get("usage_count", 0),
        "last_used_at": _iso(u.get("last_used_at")),
        "last_used_ref": u.get("last_used_ref"),
    }


@router.get("/brain/usage-events")
async def brain_usage_events(
    since: str | None = None,
    limit: int = Query(default=brain_usage.DEFAULT_EVENT_PAGE),
) -> dict:
    """D5: the per-use event log behind the frontend's activity timeline.

    Three honesty properties are the BACKEND's job here, not the frontend's:

      * `covered_kinds` / `coverage_note` — record() has three call sites (material,
        learning, note). There is no record("profile", ...) anywhere in the repo, so
        profile facts produce no events. A timeline that silently omits a whole kind
        while the graph draws four would read as "these were never used". The backend
        states the coverage so a frontend cannot forget to.
      * `truncated` — the page is newest-first, so a cut list is missing its OLDEST
        end. Rendered without a flag, that reads as a quiet period: the opposite of
        the truth.
      * `window_start` — retention prunes old events, so an empty stretch before this
        point means "not retained", not "not used".

    `limit` is clamped to a hard ceiling rather than honored; `applied_limit` reports
    what was actually used.
    """
    applied_limit = max(1, min(limit, brain_usage.MAX_EVENT_PAGE))

    if since is None:
        window_start = datetime.utcnow() - timedelta(
            days=brain_usage.DEFAULT_EVENT_WINDOW_DAYS)
    else:
        # Refused, not silently defaulted: falling back to the default window would
        # return a DIFFERENT range than the caller asked for, which the UI would then
        # label with the requested date.
        try:
            parsed = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"since={since!r} is not an ISO-8601 timestamp") from exc
        # CONVERT to UTC, never just drop the offset. The DB stores naive UTC
        # (datetime.utcnow()), so stripping "+08:00" would compare a Beijing wall
        # clock against UTC and shift the window by 8 hours — silently returning a
        # DIFFERENT range than asked for, which is exactly what refusing an
        # unparsable `since` two lines up exists to prevent. Same normalization
        # settings_service._parse_iso_utc already does.
        window_start = (parsed.astimezone(timezone.utc).replace(tzinfo=None)
                        if parsed.tzinfo else parsed)

    try:
        async with db_session.AsyncSessionLocal() as db:
            rows = (await db.execute(sa_text(
                "SELECT kind, ref_key, used_at, used_ref FROM brain_usage_events "
                "WHERE used_at >= :since ORDER BY used_at DESC LIMIT :lim"),
                {"since": window_start, "lim": applied_limit + 1})).mappings().all()
    except Exception as exc:  # noqa: BLE001 — the timeline never breaks the brain page
        raise HTTPException(
            status_code=503,
            detail="usage events unavailable (the event table may not be migrated "
                   f"yet): {exc.__class__.__name__}") from exc

    truncated = len(rows) > applied_limit
    rows = rows[:applied_limit]

    # window_start is the QUERY bound, not the retention horizon — with the shipped
    # defaults (7-day window, 30-day retention) the two are a fortnight apart, so the
    # note must not claim that everything before window_start was pruned. It says the
    # two separate true things instead: this page is bounded by the query, and the
    # table is separately bounded by retention.
    note = (
        "Covers material / learning / note only — profile facts are not recorded as "
        "usage events, so their absence here does not mean they went unused. "
        "This page is bounded by the requested window (window_start); events before "
        "it were not queried, not necessarily absent. Separately, events older than "
        "the configured retention are pruned and are gone for good."
    )
    if truncated:
        note += (" This page was TRUNCATED at the limit: events are newest-first, so "
                 "the oldest part of the requested window is missing.")

    return {
        "covered_kinds": list(brain_usage.COVERED_KINDS),
        "coverage_note": note,
        "window_start": _iso(window_start),
        "applied_limit": applied_limit,
        "truncated": truncated,
        "events": [{"kind": r["kind"], "ref_key": r["ref_key"],
                    "used_at": _iso(r["used_at"]), "used_ref": r["used_ref"]}
                   for r in rows],
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
    status: str = "pending", limit: int = 100, offset: int = 0,
    session: AsyncSession = Depends(db_session.get_session)
) -> list[dict]:
    # Paginated: each row costs up to two extra session.get() calls for its excerpts,
    # so an unbounded inbox (which a background producer can now grow) turns one
    # request into thousands of queries. The response stays a JSON ARRAY — making it
    # an object would break every existing consumer.
    rows = (await session.execute(
        select(MemoryProposal).where(MemoryProposal.status == status)
        .order_by(MemoryProposal.id).limit(max(1, min(limit, 500))).offset(max(0, offset))
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

    # Validate old_id is present AND active BEFORE materializing anything. The
    # materialize step below (save_facts) opens its OWN session and self-commits
    # the new fact durably. If we let it run and only THEN discovered old_id was
    # deleted or superseded out-of-band between propose and accept,
    # execute_supersede would raise 410 (dangling_old) / 409 (already superseded
    # by a different row) while the freshly-committed new fact stays behind AND
    # the proposal stays pending — so every re-accept would leak ANOTHER orphan
    # fact and fail identically. Checking up front eliminates the orphan on the
    # common out-of-band cases. A tiny TOCTOU window remains between this check
    # and the execute_supersede below; the idempotency guard there already covers
    # the one way it can legitimately fire (save_facts' own extension-dedup),
    # so the residual window is acceptable.
    old = await session.get(UserFact, p.old_id)
    if old is None:
        raise HTTPException(status_code=410, detail=f"user_facts id {p.old_id} does not exist")
    if old.superseded_by is not None:
        raise HTTPException(
            status_code=409,
            detail=f"user_facts id {p.old_id} already superseded by {old.superseded_by}")

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
    # Validate before overwriting: memory_facts is a whole-array REPLACE, so an empty
    # or malformed array silently WIPES the spawn's memory. A background producer makes
    # that a live risk rather than a theoretical one.
    if (not isinstance(new_arr, list) or not new_arr
            or not all(isinstance(f, str) and f.strip() for f in new_arr)):
        raise HTTPException(status_code=422,
                            detail=f"proposal {pid}: new_array must be a non-empty list "
                                   "of non-blank strings")
    spawn = await session.get(Spawn, sid)
    if spawn is None:
        raise HTTPException(status_code=410, detail=f"spawns id {sid} does not exist")
    # Optimistic concurrency: memory_facts is a whole-array REPLACE, so accepting a
    # proposal derived from an older array would silently REVERT everything written
    # since it was filed. Curator proposals record what they were derived from.
    based_on = prov.get("based_on")
    if based_on is not None and list(spawn.memory_facts or []) != list(based_on):
        raise HTTPException(
            status_code=409,
            detail=f"proposal {pid}: this spawn's memory changed after the proposal was "
                   "filed; accepting it would revert that change. Dismiss and re-derive.")
    spawn.memory_facts = new_arr


class UndoSupersedeIn(BaseModel):
    kind: str
    ref: str


# The FRONTEND vocabulary (kind) -> the table the temporal service speaks. Only these
# two tables have a `superseded_by` column at all.
#
# 🔴 This map must REFUSE, not fall through. Two reasons, both real:
#   * `note` is not a typo case — it is a genuine brain kind the UI renders beside
#     profile/learning, and `notes` HAS NO superseded_by COLUMN. A note can never be
#     un-superseded because it can never be superseded.
#   * letting an unmapped kind reach the service yields SupersedeError("bad_table"),
#     whose detail string names the internal table — a client-facing leak. The 422
#     below is keyed on the caller's own word instead.
_UNDO_TABLES = {"profile": "user_facts", "learning": "learnings"}

# Which ref prefix each kind's rows carry, so `{"kind": "profile", "ref": "learning:2"}`
# cannot silently un-supersede a fact with the learning's id.
_UNDO_REF_PREFIX = {"profile": "fact", "learning": "learning"}


@router.post("/brain/undo-supersede")
async def undo_supersede(
    body: UndoSupersedeIn, session: AsyncSession = Depends(db_session.get_session)
) -> dict:
    """Restore a superseded entry to active — the write behind the frontend's undo
    button (D3). The service has existed since P1 with no caller.

    Error mapping is the same shape as the proposal routes: unsupportable kind or
    malformed ref -> 422, referenced row gone -> 410, row is already active -> 409.
    """
    table = _UNDO_TABLES.get(body.kind)
    if table is None:
        raise HTTPException(
            status_code=422,
            detail=f"kind {body.kind!r} cannot be un-superseded; only "
                   f"{sorted(_UNDO_TABLES)} carry supersession")

    prefix, _, raw_id = body.ref.partition(":")
    # `isdigit()` alone is not enough: it is True for superscripts and other Unicode
    # digit forms that int() then rejects, turning an intended 422 into an uncaught
    # ValueError -> 500. Require ASCII.
    if (prefix != _UNDO_REF_PREFIX[body.kind]
            or not raw_id.isascii() or not raw_id.isdigit()):
        raise HTTPException(
            status_code=422,
            detail=f"ref {body.ref!r} is not a valid {body.kind} ref "
                   f"(expected {_UNDO_REF_PREFIX[body.kind]}:<id>)")

    try:
        await memory_temporal.undo_supersede(
            table, int(raw_id),
            # The route always supplies provenance, so the service's
            # `missing_provenance` guard (mapped to 409 by _supersede_error_response)
            # is DEAD CODE on this path. It stays a programmer guard for direct
            # callers; it is not a client-reachable status.
            provenance={"source_kind": "human", "via": "undo_supersede"},
            db=session)
    except SupersedeError as exc:
        # Same STATUS mapping as the proposal routes, but the detail is rebuilt in the
        # caller's vocabulary. _supersede_error_response passes exc.detail verbatim,
        # and those messages name the table ("user_facts id 9999 does not exist") —
        # which is the exact leak the 422 above goes out of its way to avoid, so
        # reusing it here would have made the route inconsistent with itself. The
        # proposal routes keep the verbatim detail: their audience is an operator
        # adjudicating a proposal whose own table_name is corrupt, so the table name
        # is the useful part there.
        status = _supersede_error_response(exc).status_code
        raise HTTPException(
            status_code=status,
            detail=f"cannot restore {body.ref}: "
                   + {"dangling_old": "no such entry",
                      "not_superseded": "it is already active"}.get(
                          exc.code, "supersession state conflict")) from exc

    await session.commit()
    return {"kind": body.kind, "ref": body.ref, "superseded_by": None}


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
    # Invalidate genuinely-stale siblings in the SAME transaction: within ONE
    # conversation, two pending proposals of the same kind on the same row describe a
    # world that no longer exists (accepting the second would clobber the first; two
    # pending deletes leave the loser stuck pending forever, since its accept 410s
    # before writing a status).
    #
    # 🔴 Deliberately NARROW on two axes, each of which was a real data-loss bug:
    #   • same conversation_id — a DIFFERENT conversation's proposal for the same spawn
    #     is separate material that is already marked processed, so dismissing it
    #     destroys it with no way back (no marker to clear, no re-sweep, no manual
    #     retry). The propose-time dedup deliberately keeps those apart; accept must
    #     not undo that.
    #   • old_id != 0 — RememberExecutor coerces a target-less proposal's old_id to the
    #     sentinel 0, so EVERY append_suspect shares old_id=0. Matching on it would
    #     dismiss every unrelated target-less proposal the moment any one is accepted.
    if p.old_id:
        siblings = (await session.execute(select(MemoryProposal).where(
            MemoryProposal.kind == p.kind,
            MemoryProposal.table_name == p.table_name,
            MemoryProposal.old_id == p.old_id,
            MemoryProposal.conversation_id.is_not_distinct_from(p.conversation_id),
            MemoryProposal.status == "pending",
            MemoryProposal.id != p.id,
        ))).scalars().all()
        for sib in siblings:
            sib.status = "dismissed"
            sib.resolved_at = datetime.utcnow()
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
