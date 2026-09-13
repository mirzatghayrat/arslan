"""Exact-ranking and bounded-batch regression checks; no embedding API calls."""
import numpy as np
import pytest

from server.services.vector_scan import BATCH_SIZE, CosineTopK


def test_matches_full_matrix_reference():
    rng = np.random.default_rng(20260914)
    vectors = rng.normal(size=(3000, 384)).astype("<f4")
    query = rng.normal(size=384).astype(np.float32)
    scores = vectors @ query / (
        np.linalg.norm(vectors, axis=1) * np.linalg.norm(query) + 1e-9
    )
    expected = sorted(range(3000), key=lambda i: (-float(scores[i]), i))[:20]
    scan = CosineTopK(query.tolist(), k=20, minimum=-1)
    for start in range(0, len(vectors), BATCH_SIZE):
        scan.add([(i, vectors[i].tobytes()) for i in range(start, min(start + BATCH_SIZE, 3000))])
        assert len(scan.heap) <= 20
    assert scan.ids() == expected


def test_ties_are_id_order_independent_of_batches():
    scan = CosineTopK([1, 0], k=3, minimum=0.5)
    blob = np.array([1, 0], dtype="<f4").tobytes()
    scan.add([(9, blob), (3, blob)])
    scan.add([(7, blob), (1, blob), (2, blob)])
    assert scan.ids() == [1, 2, 3]


def test_corrupt_and_nonfinite_vectors_are_skipped():
    scan = CosineTopK([1, 0], k=20, minimum=0.1)
    scan.add([(1, b"x"), (2, np.array([float("nan"), 0], dtype="<f4").tobytes()),
              (3, np.array([0, 0], dtype="<f4").tobytes()),
              (4, np.array([1, 0], dtype="<f4").tobytes())])
    assert scan.ids() == [4]
    assert scan.skipped == 2


def test_zero_query_and_zero_k_return_empty():
    rows = [(1, np.array([1, 0], dtype="<f4").tobytes())]
    for query, k in [([0, 0], 20), ([1, 0], 0)]:
        scan = CosineTopK(query, k=k, minimum=0)
        scan.add(rows)
        assert scan.ids() == []


@pytest.mark.parametrize("query", [[], [float("nan")], [float("inf")], [[1]]])
def test_invalid_query_rejected(query):
    with pytest.raises(ValueError, match="Invalid query"):
        CosineTopK(query, k=20, minimum=0)


def test_oversized_batch_rejected():
    scan = CosineTopK([1], k=20, minimum=0)
    with pytest.raises(ValueError, match="batch"):
        scan.add([(1, b"1234")] * (BATCH_SIZE + 1))
