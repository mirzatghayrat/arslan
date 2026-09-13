"""Bounded-memory exact cosine top-k; independent of retrieval permissions/SQL.

The caller supplies at most one batch at a time. We retain only k scores/IDs,
never document text or the full vector corpus. Still O(N), not an ANN index.
"""
from __future__ import annotations

import heapq

import numpy as np

BATCH_SIZE = 256


class CosineTopK:
    def __init__(self, query: list[float], *, k: int, minimum: float):
        self.query = np.asarray(query, dtype=np.float32)
        if self.query.ndim != 1 or not self.query.size or not np.isfinite(self.query).all():
            raise ValueError("Invalid query vector")
        self.norm = float(np.linalg.norm(self.query))
        self.k, self.minimum = k, minimum
        self.heap: list[tuple[float, int, int]] = []
        self.skipped = 0

    def add(self, rows) -> None:
        if len(rows) > BATCH_SIZE:
            raise ValueError("Vector batch exceeds bounded scan limit")
        ids, vectors = [], []
        for row in rows:
            cid, blob = row[0], row[1]
            if len(blob) != self.query.size * 4:
                self.skipped += 1
                continue
            vector = np.frombuffer(blob, dtype="<f4")
            if not np.isfinite(vector).all():
                self.skipped += 1
                continue
            ids.append(cid)
            vectors.append(vector)
        if not vectors or self.norm == 0 or self.k <= 0:
            return
        matrix = np.stack(vectors)
        norms = np.linalg.norm(matrix, axis=1)
        scores = matrix @ self.query / (norms * self.norm + 1e-9)
        for cid, score in zip(ids, scores, strict=True):
            value = float(score)
            if not np.isfinite(value) or value < self.minimum:
                continue
            item = (value, -cid, cid)  # lower ID wins equal-score ties, independent of batches
            if len(self.heap) < self.k:
                heapq.heappush(self.heap, item)
            elif item > self.heap[0]:
                heapq.heapreplace(self.heap, item)

    def ids(self) -> list[int]:
        return [item[2] for item in sorted(self.heap, reverse=True)]
