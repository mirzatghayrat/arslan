"""Synthetic SQLite exact-vector benchmark, isolated child per size/algorithm.

Run: uv run python -m scripts.benchmark_vector_scan
No network, credentials, real memories, or model-quality claims. JSON to stdout.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import resource
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path


async def measure(size: int, algorithm: str) -> dict:
    import numpy as np
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from server.services import embedding_service, knowledge

    rng = np.random.default_rng(20260914)
    query = rng.normal(size=384).astype("<f4")
    with tempfile.TemporaryDirectory(prefix="arslan-vector-bench-") as directory:
        path = Path(directory) / "synthetic.db"
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE knowledge_chunks (id INTEGER PRIMARY KEY, embedding BLOB, "
                       "embedding_model TEXT, spawn_id INTEGER, collection_id INTEGER, source TEXT, text TEXT)")
            for start in range(0, size, 256):
                vectors = rng.normal(size=(min(256, size - start), 384)).astype("<f4")
                if start == 0:
                    vectors[:30] = query + vectors[:30] * 0.1
                db.executemany("INSERT INTO knowledge_chunks VALUES (?,?,?,?,?,?,?)", [
                    (start + i, vector.tobytes(), "synthetic-384", 1, None, "fixture", "x" * 1024)
                    for i, vector in enumerate(vectors)
                ])
            # An exact-match vector in another user's scope must never be returned.
            db.execute("INSERT INTO knowledge_chunks VALUES (?,?,?,?,?,?,?)",
                       (size + 1, query.tobytes(), "synthetic-384", 2, None, "foreign", "private"))
        engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
        maker = async_sessionmaker(engine)

        class FakeProvider:
            model_id = "synthetic-384"

            async def embed(self, texts):
                return [query.tolist() for _ in texts]

        async def provider():
            return FakeProvider()

        embedding_service.active_provider = provider
        samples, result = [], []
        async with maker() as session:
            for _ in range(6):
                begin = time.perf_counter()
                if algorithm == "bounded":
                    result, _ = await knowledge._vector_route(
                        session, "synthetic", "kc.spawn_id = :sid", {"sid": 1})
                else:
                    rows = (await session.execute(text(
                        "SELECT id, embedding, source, text, collection_id, spawn_id FROM knowledge_chunks "
                        "WHERE spawn_id = 1 AND embedding_model = 'synthetic-384' ORDER BY id"
                    ))).all()
                    matrix = np.stack([np.frombuffer(r[1], dtype="<f4") for r in rows])
                    scores = matrix @ query / (np.linalg.norm(matrix, axis=1) * np.linalg.norm(query) + 1e-9)
                    order = np.argsort(-scores, kind="stable")
                    result = [rows[int(i)][0] for i in order if scores[i] >= knowledge._MIN_COSINE][:20]
                    del rows, matrix, scores
                samples.append((time.perf_counter() - begin) * 1000)
                assert size + 1 not in result
        await engine.dispose()
        measured = samples[1:]  # one warm-up; not cold-start latency
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return {"size": size, "algorithm": algorithm, "dimensions": 384,
                "warm_samples_ms": measured, "p50_ms": float(np.percentile(measured, 50)),
                "p95_ms": float(np.percentile(measured, 95)),
                "peak_process_rss_mib": rss / (1024 ** 2 if sys.platform == "darwin" else 1024),
                "top_ids": result, "model_calls": 0, "scope_canary_excluded": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, choices=[1000, 10000, 100000])
    parser.add_argument("--algorithm", choices=["bounded", "full-matrix-reference"])
    args = parser.parse_args()
    if bool(args.size) != bool(args.algorithm):
        parser.error("--size and --algorithm must be used together")
    if args.size:
        print(json.dumps(asyncio.run(measure(args.size, args.algorithm))))
        return
    results = []
    env = {**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1",
           "VECLIB_MAXIMUM_THREADS": "1", "ARSLAN_SECRET_KEY": "synthetic-benchmark-only",
           "ARSLAN_SECRET_KEY_FILE": ""}
    for size in (1000, 10000, 100000):
        for algorithm in ("bounded", "full-matrix-reference"):
            child = subprocess.run([sys.executable, "-m", "scripts.benchmark_vector_scan",
                                    "--size", str(size), "--algorithm", algorithm],
                                   env=env, text=True, capture_output=True, check=True)
            results.append(json.loads(child.stdout))
        assert results[-1]["top_ids"] == results[-2]["top_ids"], "Ranking mismatch"
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    source_hashes = {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in (
        "server/services/knowledge.py", "server/services/vector_scan.py", "scripts/benchmark_vector_scan.py")}
    print(json.dumps({"base_commit": commit, "working_tree": "may include uncommitted changes",
                      "source_sha256": source_hashes,
                      "platform": platform.platform(), "python": platform.python_version(),
                      "method": "temporary SQLite; real bounded SQL route vs full-matrix reference; "
                                "1 warm-up + 5 warm samples; fresh child process per condition; "
                                "peak RSS includes imports and database construction; synthetic, not semantic Recall",
                      "results": results}, indent=2))


if __name__ == "__main__":
    main()
