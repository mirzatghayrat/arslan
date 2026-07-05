"""The ONLY knowledge-retrieval gate. Scope filtering is written INTO the SQL
(never post-filtered): a spawn sees its own well + its bound collections;
Arslan direct chat (spawn_id=None) sees ALL shared collections and NEVER any
spawn well. Hybrid FTS5 + vector routes merged by Reciprocal Rank Fusion; the
vector route silently drops out when no embedding provider / no vectors —
leaving exactly today's FTS5 behavior."""
from __future__ import annotations

import logging
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
    """Re-ranking seam (cross-encoder / LLM later). v1: passthrough."""
    return candidates


def _scope_clause(spawn_id: int | None, coll_ids: list[int]) -> tuple[str, dict]:
    """The partition rule, expressed as SQL. NEVER widened by callers."""
    if spawn_id is None:
        return "kc.collection_id IS NOT NULL", {}
    if coll_ids:
        return "(kc.spawn_id = :sid OR kc.collection_id IN :cids)", {"sid": spawn_id, "cids": coll_ids}
    return "kc.spawn_id = :sid", {"sid": spawn_id}


async def _bound_collection_ids(db, spawn_id: int) -> list[int]:
    rows = await db.execute(
        sa_text("SELECT collection_id FROM spawn_collections WHERE spawn_id = :sid"),
        {"sid": spawn_id})
    return [r[0] for r in rows.all()]


def _bind(stmt, params: dict):
    if "cids" in params:
        stmt = stmt.bindparams(bindparam("cids", expanding=True))
    return stmt


async def _fts_route(db, query: str, where: str, params: dict) -> tuple[list[int], dict]:
    match = _safe_match_query(query)
    if not match:
        return [], {}
    stmt = _bind(sa_text(
        "SELECT kc.id, kc.source, kc.text FROM knowledge_chunks_fts f "
        "JOIN knowledge_chunks kc ON kc.id = f.rowid "
        f"WHERE f.text MATCH :q AND {where} ORDER BY rank LIMIT :lim"), params)
    rows = (await db.execute(stmt, {**params, "q": match, "lim": CANDIDATES})).all()
    return [r[0] for r in rows], {r[0]: (r[1], r[2]) for r in rows}


async def _vector_route(db, query: str, where: str, params: dict) -> tuple[list[int], dict]:
    """Cosine top-CANDIDATES over the scope's vectors (active model only).
    Any failure or absence of provider/vectors → empty route (non-fatal)."""
    if not (query or "").strip():
        return [], {}
    try:
        provider = await embedding_service.active_provider()
        if provider is None:
            return [], {}
        # Fetch the scope's vector rows BEFORE embedding the query: an empty
        # vector scope (fresh spawn / backfill pending) must not pay a network
        # embedding call on every dispatch. Provider resolution above is cheap
        # (pure DB read) and supplies the model_id filter for this SELECT.
        stmt = _bind(sa_text(
            "SELECT kc.id, kc.source, kc.text, kc.embedding FROM knowledge_chunks kc "
            f"WHERE {where} AND kc.embedding IS NOT NULL AND kc.embedding_model = :em"), params)
        rows = (await db.execute(stmt, {**params, "em": provider.model_id})).all()
        if not rows:
            return [], {}
        qvec = (await provider.embed([query]))[0]
        import numpy as np
        mat = np.array([embedding_service.blob_to_vec(r[3]) for r in rows], dtype=np.float32)
        q = np.array(qvec, dtype=np.float32)
        sims = mat @ q / (np.linalg.norm(mat, axis=1) * (np.linalg.norm(q) or 1e-9) + 1e-9)
        order = np.argsort(-sims, kind="stable")[:CANDIDATES]
        return ([rows[i][0] for i in order],
                {rows[i][0]: (rows[i][1], rows[i][2]) for i in order})
    except Exception as exc:  # noqa: BLE001 — vector route is never fatal
        logger.warning("vector route failed (non-fatal): %s", exc)
        return [], {}


async def retrieve_scoped(query: str, *, spawn_id: int | None, k: int = 5) -> list[tuple[str, str]]:
    """Return up to k (source, text) chunks for the query within the caller's
    partition. This is the single retrieval entry point for dispatch (live +
    eval) and Arslan direct chat alike."""
    async with db_session.AsyncSessionLocal() as db:
        coll_ids = await _bound_collection_ids(db, spawn_id) if spawn_id is not None else []
        where, params = _scope_clause(spawn_id, coll_ids)
        fts_ids, meta = await _fts_route(db, query, where, params)
        vec_ids, vmeta = await _vector_route(db, query, where, params)
    meta.update(vmeta)
    merged = rrf_merge([r for r in (fts_ids, vec_ids) if r], k=k)
    return rerank(query, [meta[cid] for cid in merged])


def knowledge_block(chunks: list[tuple[str, str]]) -> str:
    """Format retrieved (source, text) chunks as a system-prompt section with
    provenance tags, or '' if none."""
    if not chunks:
        return ""
    body = "\n- ".join(f"[{src}] {txt}" for src, txt in chunks)
    return ("\n\nYour knowledge base (use when relevant; do not fabricate beyond it):\n- "
            + body)
