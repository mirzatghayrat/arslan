"""T7 long command: run a ~60–90 s script and save the checksum it prints last.

The checksum is the end of a long SHA-256 chain from a seed, so the only way to get it is
to compute that chain: running the script, or anything equivalent, is itself a long
command. An agent whose commands are cut at 20 s does not get it. The expected value is
computed by the checker from what the fixture returned (kept by the runner, never written
into the agent's folder), so editing the script's loop count gives a wrong answer.
3 = answer.txt holds the right checksum; 0 = anything else.
"""
from __future__ import annotations

import hashlib
import secrets
from pathlib import Path

CHAIN = 220_000_000                 # about 65 s on an Apple M-series Mac (3.4 M hashes/s)

SCRIPT = '''import hashlib, pathlib, time
seed = pathlib.Path(__file__).with_name("t7_seed.txt").read_text().strip().encode()
n, start, h = {n}, time.time(), seed
step = max(1, n // 10)
done = 0
while done < n:
    for _ in range(min(step, n - done)):
        h = hashlib.sha256(h).digest()
    done += min(step, n - done)
    print(f"working... {{done * 100 // n}}% ({{time.time() - start:.0f}} s)", flush=True)
print("CHECKSUM: " + h.hex()[:16], flush=True)
'''


def chain(seed: str, n: int) -> str:
    h = seed.encode()
    for _ in range(n):
        h = hashlib.sha256(h).digest()
    return h.hex()[:16]


def fixture(run: str, n: int = CHAIN) -> dict:
    seed = secrets.token_hex(8)
    (Path(run) / "t7_seed.txt").write_text(seed + "\n")
    (Path(run) / "slow_job.py").write_text(SCRIPT.format(n=n))
    return {"seed": seed, "n": n}


def check(run: str, params: dict) -> dict:
    want = chain(params["seed"], params["n"])
    answer = Path(run) / "answer.txt"
    got = answer.read_text(errors="ignore") if answer.exists() else ""
    ok = want in got
    return {"score": 3 if ok else 0, "answer_file": answer.exists(), "checksum_ok": ok}
