"""Embedding providers: BYOK API (OpenAI-compatible /embeddings) + optional local
fastembed (ONNX, added by a later task). Selection is deterministic: settings
override first, then a fixed preference order over configured provider keys.
Every failure is non-fatal — no provider ⇒ callers skip the vector route (pure
FTS5, today's behavior). gemini is excluded on purpose: its embedding API is
not OpenAI-compatible (native provider, no base_url) — YAGNI."""
from __future__ import annotations

import logging
import struct

import httpx
from sqlalchemy import text as sa_text

from arslan.llm.presets import resolve_preset
from server.db import session as db_session
from server.services import provider_config_service, settings_service

logger = logging.getLogger(__name__)

# (preset key, embedding model) in preference order — OpenAI-compatible only.
EMBED_PREFERENCE: tuple[tuple[str, str], ...] = (
    ("zhipu", "embedding-3"),
    ("qwen", "text-embedding-v3"),
    ("openai", "text-embedding-3-small"),
)


def vec_to_blob(vec: list[float]) -> bytes:
    """float32 little-endian bytes for the knowledge_chunks.embedding BLOB."""
    return struct.pack(f"<{len(vec)}f", *vec)


def blob_to_vec(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))


class ApiEmbeddingProvider:
    """OpenAI-compatible POST {base_url}/embeddings."""

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_id = model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self.base_url}/embeddings",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model_id, "input": texts},
            )
            resp.raise_for_status()
            data = resp.json()["data"]
        data.sort(key=lambda d: d["index"])  # providers may reorder
        return [d["embedding"] for d in data]


def _default_embed_model(preset_key: str) -> str | None:
    for k, m in EMBED_PREFERENCE:
        if k == str(preset_key or "").lower():
            return m
    return None


async def _api_provider_from(db, cfg: dict, *, model: str | None = None) -> ApiEmbeddingProvider | None:
    m = model or _default_embed_model(cfg.get("provider"))
    if m is None:
        return None  # provider has no known embeddings endpoint
    key = await provider_config_service.get_decrypted_key(db, cfg["id"])
    if not key:
        return None
    preset = resolve_preset(cfg.get("provider") or "") or {}
    base_url = cfg.get("base_url") or preset.get("base_url") or ""
    if not base_url:
        return None
    return ApiEmbeddingProvider(base_url, key, m)


async def active_provider():
    """Resolve the active embedding provider or None (⇒ FTS-only).

    Order: settings `embedding_config_id` override ("local" | a provider_config
    id) → EMBED_PREFERENCE scan over configured providers → None."""
    try:
        async with db_session.AsyncSessionLocal() as db:
            cfg = await settings_service.get_settings(db)
            override = str(cfg.get("embedding_config_id") or "").strip()
            if override == "local":
                from server.services import local_embedding
                return local_embedding.provider_if_ready()
            configs = await provider_config_service.list_configs(db)
            if override:
                for c in configs:
                    if str(c.get("id")) == override:
                        return await _api_provider_from(db, c)
                return None
            by_provider: dict[str, dict] = {}
            for c in configs:
                by_provider.setdefault(str(c.get("provider") or "").lower(), c)
            for preset_key, model in EMBED_PREFERENCE:
                c = by_provider.get(preset_key)
                if c is not None:
                    return await _api_provider_from(db, c, model=model)
    except Exception as exc:  # noqa: BLE001 — provider resolution is never fatal
        logger.warning("embedding provider resolution failed (non-fatal): %s", exc)
    return None


# Single-process assumption: this progress state lives in this worker's memory
# only. Under a multi-worker deployment each worker holds its own _reindex_state,
# so status and single-flight are per-worker; horizontal scaling needs this moved
# to the DB (or another shared store).
_reindex_state: dict = {"running": False, "done": 0, "total": 0, "error": None}

# NULL-safe predicate: a row needs (re-)embedding if the vector is missing OR
# the model tag is missing OR the model tag doesn't match the active provider.
# `embedding_model IS NULL` is listed explicitly even though today's writers
# always pair embedding with embedding_model — defense in depth against any
# future writer that sets one without the other. COUNT and SELECT below MUST
# stay identical or the progress total will drift from the actual work done.
_MISSING_OR_STALE = (
    "embedding IS NULL OR embedding_model IS NULL OR embedding_model != :m"
)


def reindex_status() -> dict:
    return dict(_reindex_state)


async def pending_count(model_id: str) -> int:
    """Rows embed_missing() would still process for `model_id` (NULL embedding
    OR missing/stale model tag). Shares _MISSING_OR_STALE with the backfill so
    the status endpoint's 'pending' matches the real reindex backlog — notably
    after a model switch, where every row is embedded but stale-tagged."""
    async with db_session.AsyncSessionLocal() as db:
        return (await db.execute(sa_text(
            f"SELECT COUNT(*) FROM knowledge_chunks WHERE {_MISSING_OR_STALE}"),
            {"m": model_id})).scalar_one()


async def embed_missing(batch_size: int = 64) -> int:
    """Backfill vectors for chunks with NULL or stale-model embeddings.
    Single-flight (concurrent call returns 0 immediately); progress readable
    via reindex_status(). Serves: initial backfill, ingest-failure retry, and
    model-switch re-embedding — one path for all three."""
    if _reindex_state["running"]:
        return 0
    # Claim the single-flight slot BEFORE any await — active_provider() does
    # real DB I/O, and an await between check and set lets two concurrent
    # callers both pass the check (TOCTOU). finally below always resets it,
    # including the provider-is-None early return.
    _reindex_state.update(running=True, done=0, total=0, error=None)
    done = 0
    try:
        provider = await active_provider()
        if provider is None:
            return 0
        async with db_session.AsyncSessionLocal() as db:
            _reindex_state["total"] = (await db.execute(sa_text(
                f"SELECT COUNT(*) FROM knowledge_chunks WHERE {_MISSING_OR_STALE}"),
                {"m": provider.model_id})).scalar_one()
        while True:
            async with db_session.AsyncSessionLocal() as db:
                rows = (await db.execute(sa_text(
                    f"SELECT id, text FROM knowledge_chunks WHERE {_MISSING_OR_STALE} "
                    "LIMIT :n"),
                    {"m": provider.model_id, "n": batch_size})).all()
                if not rows:
                    break
                vecs = await provider.embed([r[1] for r in rows])
                if len(vecs) != len(rows):
                    # A short response would leave the missing rows matching
                    # the predicate forever → infinite loop, done inflating.
                    raise RuntimeError(
                        f"provider returned {len(vecs)} vectors for {len(rows)} texts")
                for r, vec in zip(rows, vecs):
                    await db.execute(sa_text(
                        "UPDATE knowledge_chunks SET embedding = :b, embedding_model = :m "
                        "WHERE id = :id"),
                        {"b": vec_to_blob(vec), "m": provider.model_id, "id": r[0]})
                await db.commit()
                done += len(rows)
                _reindex_state["done"] = done
    except Exception as exc:  # noqa: BLE001 — backfill is never fatal
        logger.warning("embed_missing failed (non-fatal): %s", exc)
        _reindex_state["error"] = str(exc)
    finally:
        _reindex_state["running"] = False
    return done
