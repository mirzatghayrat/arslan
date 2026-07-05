"""Local fastembed (ONNX) embedding — filled in by the local-model task."""
from __future__ import annotations


def provider_if_ready():
    """Return a LocalEmbeddingProvider when the model is downloaded, else None."""
    return None
