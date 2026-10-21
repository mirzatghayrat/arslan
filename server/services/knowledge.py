"""The ONLY knowledge-retrieval gate. Scope filtering is written INTO the SQL
(never post-filtered): a spawn sees its own well + its bound collections;
Arslan direct chat (spawn_id=None) sees ALL shared collections and NEVER any
spawn well. Hybrid FTS5 + vector routes merged by Reciprocal Rank Fusion; the
vector route silently drops out when no embedding provider / no vectors —
leaving exactly today's FTS5 behavior."""
from __future__ import annotations

import logging
import os
import re

from sqlalchemy import bindparam, text as sa_text

from server.db import session as db_session
from server.services import embedding_service

logger = logging.getLogger(__name__)

# Word tokens: CJK *runs* or alphanumeric runs. Used to build a safe FTS5 query.
# CJK is matched as a run (not per-char) so a query like "猫粮" produces the token
# "猫粮" — which is exactly how FTS5's default (unicode61) tokenizer indexes a CJK
# run. Per-char tokens (["猫","粮"]) never match that single index token, so CJK
# retrieval would silently return nothing. ASCII behavior is unchanged.
_TOKEN_RE = re.compile(r"[0-9A-Za-z]+|[一-鿿]+")

RRF_K = 60          # standard reciprocal-rank-fusion constant
CANDIDATES = 20     # per-route candidate pool before fusion

# Recall-biased default: 4 BYOK providers have different similarity scales,
# openai-3-small true-relevant pairs commonly land 0.15–0.30. Better to let a
# low-quality neighbor through (rerank backstops it) than silently kill a real
# one. env-tunable, not precision-tuned.
_MIN_COSINE = float(os.environ.get("ARSLAN_MIN_COSINE", "0.15"))


def _safe_match_query(query: str) -> str:
    """Build an FTS5 MATCH string from query tokens (each quoted, OR-joined) so
    arbitrary user text never triggers FTS5 syntax errors. Empty → ''."""
    tokens = _TOKEN_RE.findall(query or "")
    if not tokens:
        return ""
    return " OR ".join(f'"{t}"' for t in tokens)


def rrf_merge(rankings: list[list[int]], *, k: int) -> list[int]:
    """Fuse per-route id rankings: score(id) = Σ 1/(RRF_K + rank). Ties break by
    id for determinism. Returns top-k ids."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, cid in enumerate(ranking):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (RRF_K + rank + 1)
    ordered = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return [cid for cid, _ in ordered[:k]]


def rerank(query: str, candidates: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """轻量确定性重排:按 query 词元(_TOKEN_RE,CJK-run aware)与候选文本的
    重叠数降序;稳定排序 → 同分保持上游 RRF 顺序。非语义精排(cross-encoder/LLM
    是未来);纯 CJK 无共享分隔 run 时安全退回 RRF 原序。零依赖、零网络。"""
    qtokens = {t.lower() for t in _TOKEN_RE.findall(query or "")}
    if not qtokens or not candidates:
        return candidates

    def _overlap(item: tuple[str, str]) -> int:
        return len(qtokens & {t.lower() for t in _TOKEN_RE.findall(item[1] or "")})

    return sorted(candidates, key=lambda c: -_overlap(c))


def _bind(stmt, params: dict):
    if "cids" in params:
        stmt = stmt.bindparams(bindparam("cids", expanding=True))
    return stmt


async def _fts_route(db, query: str, where: str, params: dict) -> tuple[list[int], dict]:
    match = _safe_match_query(query)
    if not match:
        return [], {}
    stmt = _bind(sa_text(
        "SELECT kc.id, kc.source, kc.text, kc.collection_id, kc.spawn_id FROM knowledge_chunks_fts f "
        "JOIN knowledge_chunks kc ON kc.id = f.rowid "
        f"WHERE f.text MATCH :q AND {where} ORDER BY rank LIMIT :lim"), params)
    rows = (await db.execute(stmt, {**params, "q": match, "lim": CANDIDATES})).all()
    return [r[0] for r in rows], {r[0]: (r[1], r[2], r[3], r[4]) for r in rows}


async def _vector_route(db, query: str, where: str, params: dict) -> tuple[list[int], dict]:
    """Cosine top-CANDIDATES over the scope's vectors (active model only).
    Any failure or absence of provider/vectors → empty route (non-fatal)."""
    if not (query or "").strip():
        return [], {}
    from server.services.personal_context import current
    ctx = current()
    if ctx is None or not ctx.cloud_memory_allowed:
        # Use already-installed local embeddings only. Resolving a default
        # API provider must not silently authorize query externalization.
        from server.services import local_embedding
        local_provider = local_embedding.provider_if_ready()
        if local_provider is None:
            return [], {}
    else:
        local_provider = None
    try:
        provider = local_provider or await embedding_service.active_provider()
        if provider is None:
            return [], {}
        # Fetch the scope's vector rows BEFORE embedding the query: an empty
        # vector scope (fresh spawn / backfill pending) must not pay a network
        # embedding call on every dispatch. Provider resolution above is cheap
        # (pure DB read) and supplies the model_id filter for this SELECT.
        from server.services.vector_scan import BATCH_SIZE, CosineTopK
        stmt = _bind(sa_text(
            "SELECT kc.id, kc.embedding FROM knowledge_chunks kc "
            f"WHERE {where} AND kc.embedding IS NOT NULL AND kc.embedding_model = :em "
            "ORDER BY kc.id"), params)
        stream = await db.stream(stmt, {**params, "em": provider.model_id})
        try:
            rows = await stream.fetchmany(BATCH_SIZE)
            if not rows:
                return [], {}  # no embedding bill for an empty scope
            qvec = (await provider.embed([query]))[0]
            top = CosineTopK(qvec, k=CANDIDATES, minimum=_MIN_COSINE)
            while rows:
                top.add(rows)
                rows = await stream.fetchmany(BATCH_SIZE)
            if top.filtered or top.skipped:
                logger.debug("_MIN_COSINE=%s dropped %d vectors; skipped %d invalid vectors",
                             _MIN_COSINE, top.filtered, top.skipped)
            ids = top.ids()
        finally:
            await stream.close()
        if not ids:
            return [], {}
        # Fetch text only for the winners, and reapply the permission scope.
        details = _bind(sa_text(
            "SELECT kc.id, kc.source, kc.text, kc.collection_id, kc.spawn_id FROM knowledge_chunks kc "
            f"WHERE kc.id IN :ids AND {where} AND kc.embedding_model = :em"
        ).bindparams(bindparam("ids", expanding=True)), params)
        found = (await db.execute(details, {**params, "ids": ids, "em": provider.model_id})).all()
        meta = {row[0]: (row[1], row[2], row[3], row[4]) for row in found}
        return [cid for cid in ids if cid in meta], meta
    except Exception as exc:  # noqa: BLE001 — vector route is never fatal
        logger.warning("vector route failed (non-fatal): %s", exc)
        return [], {}


async def retrieve_scoped(query: str, *, spawn_id: int | None, k: int = 5,
                          used_ref: str | None = None,
                          record_usage: bool = True) -> list[tuple[str, str]]:
    """Return up to k (source, text) chunks for the query within the caller's
    partition. This is the single retrieval entry point for dispatch (live +
    eval) and Arslan direct chat alike. Records material usage on each hit
    (best-effort — usage never affects what's returned).

    record_usage=False (S2 E3 hermetic replay): retrieve identically but write NO
    brain_usage rows — a replay must not mutate the Second Brain's usage counters."""
    async with db_session.AsyncSessionLocal() as db:
        from server.db.models import Project
        from server.services.personal_context import current
        ctx = current()
        if ctx is None or ctx.no_memory or ctx.temporary:
            return []
        if not ctx.model_is_local and not ctx.cloud_memory_allowed:
            return []
        if spawn_id is not None and str(spawn_id) != ctx.expert_id:
            return []
        project = await db.get(Project, ctx.project_id) if ctx.project_id else None
        coll_ids = list(project.collection_ids or []) if (
            project and project.owner_id == ctx.owner_id and project.status == "active") else []
        if not coll_ids:
            return []
        # No ambient "all shared collections" access in a project task.
        where, params = "kc.collection_id IN :cids", {"cids": coll_ids}
        fts_ids, meta = await _fts_route(db, query, where, params)
        vec_ids, vmeta = await _vector_route(db, query, where, params)
    meta.update(vmeta)
    merged = rrf_merge([r for r in (fts_ids, vec_ids) if r], k=k)
    hits = [meta[cid] for cid in merged]           # (source, text, coll_id, spawn_id)
    from server.services import brain_usage
    # Count usage once per source per retrieval — "用过几次" means "retrieved in N
    # turns", not "how many chunks were injected" (a multi-chunk doc must not inflate).
    seen_refs: set[str] = set()
    for src, _txt, cid, sid in hits:
        ref_key = (f"material:coll:{cid}:{src}" if cid is not None
                   else f"material:spawn:{sid}:{src}")
        if ref_key in seen_refs:
            continue
        seen_refs.add(ref_key)
        if record_usage:
            await brain_usage.record("material", ref_key, used_ref=used_ref)
    # 0.1.63 C2a-2: the v1 心得 / 笔记 routes are gone; under memory v2 experiences and notes come in only
    # through personal_context, so those routes always returned nothing.
    return rerank(query, [(src, txt) for src, txt, _c, _s in hits])


def knowledge_block(chunks: list[tuple[str, str]]) -> str:
    """Format retrieved (source, text) chunks as a system-prompt section with
    provenance tags, or '' if none."""
    if not chunks:
        return ""
    body = "\n- ".join(f"[{src}] {txt}" for src, txt in chunks)
    return ("\n\nYour knowledge base (use when relevant; do not fabricate beyond it):\n- "
            + body)
