"""T7 long command: run a 60–90 s script and save the checksum it prints last.

The script sleeps in short steps (printing progress) and only then prints the
checksum, so an agent whose commands are cut at 20 s never sees it. The seed sits in
a dot file; the checksum is not printed anywhere before the end.
3 = answer.txt holds the right checksum; 0 = anything else.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from pathlib import Path

SCRIPT = '''import hashlib, pathlib, sys, time
seed = pathlib.Path(__file__).with_name(".t7_seed").read_text().strip()
total = {seconds}
for done in range(0, total, 5):
    print(f"working... {{done}}/{{total}} s", flush=True)
    time.sleep(5)
print("CHECKSUM: " + hashlib.sha256(("t7:" + seed).encode()).hexdigest()[:16], flush=True)
'''


def fixture(run: str, seconds: int = 75) -> dict:
    root = Path(run)
    seed = secrets.token_hex(8)
    (root / ".t7_seed").write_text(seed + "\n")
    (root / "slow_job.py").write_text(SCRIPT.format(seconds=seconds))
    manifest = {"checksum": hashlib.sha256(("t7:" + seed).encode()).hexdigest()[:16], "seconds": seconds}
    (root / ".t7_manifest.json").write_text(json.dumps(manifest))
    return manifest


def check(run: str, reply: str = "") -> dict:
    root = Path(run)
    want = json.loads((root / ".t7_manifest.json").read_text())["checksum"]
    answer = root / "answer.txt"
    got = answer.read_text(errors="ignore") if answer.exists() else ""
    ok = want in got
    return {"score": 3 if ok else 0, "answer_file": answer.exists(), "checksum_ok": ok}
