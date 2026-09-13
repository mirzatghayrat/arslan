# Bounded exact-vector scan — 2026-09-14

This is a synthetic engineering benchmark, **not semantic recall evaluation**.
The query embedding is deterministic and local; no paid model calls occur.

Run `uv run python -m scripts.benchmark_vector_scan` from the repository root.
The runner creates temporary SQLite databases and removes them after measurement.
Each condition runs in a fresh process with BLAS thread limits set to one.
It records source hashes, commit, five warm samples after one warm-up, p50/p95,
peak process RSS, and the actual top IDs. Both methods must agree exactly.
An exact-match vector in another spawn's scope must be excluded.

Measured on Apple M4 Pro, 48 GiB RAM, macOS 26.6.2, Python 3.11.15. Each row has
a 384-dimensional float32 vector and 1 KiB synthetic text. Thirty candidates
are near the query; other rows are deterministic random vectors. Peak RSS
includes imports and database construction, not only the retrieval operation.
The reference loads all scoped vector/text rows and a full matrix. The bounded
method calls the production SQL route with 256-row batches, then fetches text
only for winners, reapplying scope. It retains exact cosine ranking, not ANN.

| Rows | Method | p50 ms | p95 ms | Peak RSS MiB |
| ---: | --- | ---: | ---: | ---: |
| 1,000 | Bounded | 2.93 | 3.21 | 85.66 |
| 1,000 | Full-matrix reference | 1.97 | 2.14 | 90.81 |
| 10,000 | Bounded | 25.49 | 25.68 | 86.22 |
| 10,000 | Full-matrix reference | 21.70 | 31.34 | 149.66 |
| 100,000 | Bounded | 247.21 | 248.98 | 86.66 |
| 100,000 | Full-matrix reference | 249.70 | 283.69 | 740.95 |

This supports lower memory growth, not a universal latency improvement: the
bounded path is slower at 1k and 10k in this run. It remains O(N), and these five
warm samples do not establish production tail latency, cold disk performance,
multi-user concurrency, or high-dimensional/remote-database behavior. Semantic
Recall@k and usefulness require separate labeled tasks and real embeddings.

Regression tests additionally compare 3,000 random vectors against a full NumPy
reference, verify deterministic equal-score ties, malformed/non-finite-vector
handling, zero-query behavior, and rejection of oversized batches. Existing
scope tests cover spawn wells and explicitly bound shared collections.
