"""Local fastembed (ONNX) embedding provider — on-demand download, never
bundled. fastembed is an OPTIONAL dependency (`pip install -e '.[embeddings]'`);
absent package or absent model weights both degrade to None (⇒ FTS-only /
API provider). Weights live under <data-dir>/models — the iron law stands:
no PyTorch, ever."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

LOCAL_MODEL = "intfloat/multilingual-e5-small"   # zh+en 多语,384 维,~120MB ONNX
LOCAL_MODEL_ID = "local:multilingual-e5-small"

# Single-process assumption: download state lives in this worker's memory only.
# Under a multi-worker deployment each worker has its own _state, so "downloading"
# is per-worker (disk presence is still shared via model_present()); horizontal
# scaling needs the transient state moved to the DB (or another shared store).
_state: dict = {"status": "absent", "error": None}  # absent|downloading|ready|error
_model = None  # cached fastembed.TextEmbedding


def _cache_dir() -> Path:
    from server.config import settings
    return Path(settings.db_path).parent / "models"


def model_present() -> bool:
    d = _cache_dir()
    return d.exists() and any(d.rglob("*.onnx"))


def download_status() -> dict:
    """Disk is the source of truth for the absent/ready axis: if weights are
    present, we're "ready" no matter what a stale in-memory _state says (a
    prior process/test may have recorded "error" before weights existed, or
    before this process's _state was reset). "downloading" is the one
    transient, non-disk-derived state we still report as-is; "error" is only
    reported while the model remains absent from disk."""
    if _state["status"] == "downloading":
        return dict(_state)
    if model_present():
        return {"status": "ready", "error": None}
    if _state["status"] == "error":
        return dict(_state)
    return {"status": "absent", "error": None}


def _load_model():
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        _model = TextEmbedding(model_name=LOCAL_MODEL, cache_dir=str(_cache_dir()))
    return _model


async def download_local_model() -> None:
    """Download weights (fastembed constructor pulls them). Single-flight;
    progress via download_status(). Import/network errors land in status."""
    if _state["status"] == "downloading":
        return
    _state.update(status="downloading", error=None)
    try:
        _cache_dir().mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(_load_model)
        _state.update(status="ready", error=None)
    except Exception as exc:  # noqa: BLE001 — download is never fatal
        logger.warning("local embedding model download failed: %s", exc)
        _state.update(status="error", error=str(exc))


class LocalEmbeddingProvider:
    model_id = LOCAL_MODEL_ID

    async def embed(self, texts: list[str]) -> list[list[float]]:
        def _run() -> list[list[float]]:
            model = _load_model()
            return [[float(x) for x in v] for v in model.embed(texts)]
        return await asyncio.to_thread(_run)


def provider_if_ready() -> LocalEmbeddingProvider | None:
    """Return the local provider iff weights are on disk (else None)."""
    return LocalEmbeddingProvider() if model_present() else None
