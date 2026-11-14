"""What the goal-mode tasks share (v0.1.64 L7-0, docs/plans/0164/L7-goal-mode.md, Bench plan).

- Which tasks are the goal tasks (T18–T21) and which are the 13 others the completion bar compares, and how many
  repeats each gets in a bench round (k=6 and k=3, `--repeats per-task`).
- The encoded data files of T19–T21 (base64 of zlib-compressed JSON). They are encoded, not secret: a worker that
  decodes one can see ahead, and each checker reports whether a worker call read it.
- Running a task's own check in a throwaway copy of the run folder, so a checker sees what the check says now
  without changing the folder it is judging.
"""
from __future__ import annotations

import base64
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

GOAL_TASKS = ("T18", "T19", "T20", "T21")
# STY2's 9 tasks and M64's 4 (the card's `T`): the bar's "no loss elsewhere" side.
OTHER_TASKS = ("T1", "T2", "T3", "T5", "T7", "T8", "T9", "T10", "T11", "T13", "T14", "T15", "T17")
GOAL_TASK_REPEATS = 6
OTHER_TASK_REPEATS = 3
# The PATH an Arslan test instance runs commands with (start_arslan.sh), so `python3` here is the one the worker got.
INSTANCE_PATH = "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin"
CHECK_TIMEOUT_S = 120


def repeats_for(task: str, spec: str) -> int:
    """`--repeats`: a number for every task, or `per-task` (6 for a goal task, 3 for any other)."""
    if spec == "per-task":
        return GOAL_TASK_REPEATS if task in GOAL_TASKS else OTHER_TASK_REPEATS
    if not spec.isdigit() or int(spec) < 1:
        raise ValueError(f"--repeats is a positive number or per-task, not {spec!r}")
    return int(spec)


def encode(data) -> str:
    return base64.b64encode(zlib.compress(json.dumps(data, ensure_ascii=False).encode("utf-8"), 9)).decode("ascii")


def decode(text: str):
    return json.loads(zlib.decompress(base64.b64decode(text)).decode("utf-8"))


# The decoder each fixture's check script carries (Python 3.9: the system python3 on macOS).
DECODER = '''def _decode(path):
    with open(path, "rb") as f:
        return json.loads(zlib.decompress(base64.b64decode(f.read())).decode("utf-8"))
'''

# Chaining (L7-0, after the first pilot: the worker decoded the data file and read every stage at once). Stage k+1
# is sealed under a key derived from stage k's CORRECT output on fixed probes: the results a correct stage-k module
# gives (T19), the cleaned values rule k asks for (T21), the code words and dates of batch k (T20). So the data file
# alone opens nothing past stage 1. The check scripts carry this exact source, and this module runs the same source,
# so the fixture seals with the key the script will derive. The keystream is SHA-256 in counter mode: enough to keep a
# stage unreadable without its key, not meant as general-purpose encryption.
SEAL = '''def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=True)


def _key(salt, stage, outputs):
    return hashlib.sha256(("%s|%d|" % (salt, stage)).encode("ascii") + _canonical(outputs).encode("ascii")).digest()


def _stream(key, n):
    out, i = b"", 0
    while len(out) < n:
        out += hashlib.sha256(key + i.to_bytes(8, "big")).digest()
        i += 1
    return out[:n]


def _tag(key):
    return hashlib.sha256(b"tag|" + key).hexdigest()[:16]


def _unseal(box, key):
    """The sealed text, or None when the key is not the one it was sealed under."""
    if _tag(key) != box["tag"]:
        return None
    data = base64.b64decode(box["data"])
    return bytes(a ^ b for a, b in zip(data, _stream(key, len(data)))).decode("utf-8")
'''
_SEALING: dict = {"json": json, "hashlib": hashlib, "base64": base64}
exec(compile(SEAL, "goal_tasks.SEAL", "exec"), _SEALING)


def derive_key(salt: str, stage: int, outputs) -> bytes:
    """The key that opens stage `stage` + 1: from the salt, the stage and stage `stage`'s correct outputs."""
    return _SEALING["_key"](salt, stage, outputs)


def seal(text: str, key: bytes) -> dict:
    data = text.encode("utf-8")
    sealed = bytes(a ^ b for a, b in zip(data, _SEALING["_stream"](key, len(data))))
    return {"tag": _SEALING["_tag"](key), "data": base64.b64encode(sealed).decode("ascii")}


def unseal(box: dict, key: bytes) -> str | None:
    return _SEALING["_unseal"](box, key)


def sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def changed(run: str, digests: dict[str, str]) -> list[str]:
    """The fixture's files (relative paths) whose sha256 differs from what the fixture recorded, or that are gone."""
    return sorted(rel for rel, want in digests.items() if sha256(Path(run) / rel) != want)


def python3() -> str:
    return shutil.which("python3", path=INSTANCE_PATH) or sys.executable


def run_check_in_copy(run: str, argv: list[str]) -> tuple[int | None, str]:
    """Run `python3 <argv>` in a copy of the run folder: (exit code, output tail). None when it timed out. A check that
    reveals the next stage writes into the copy, never into the folder being judged."""
    with tempfile.TemporaryDirectory(prefix="goal-check-") as tmp:
        copy = Path(tmp) / "run"
        shutil.copytree(run, copy, symlinks=True)
        try:
            done = subprocess.run([python3(), "-B", *argv], cwd=copy, capture_output=True, text=True,
                                  timeout=CHECK_TIMEOUT_S, env={"PATH": INSTANCE_PATH, "PYTHONDONTWRITEBYTECODE": "1"})
        except subprocess.TimeoutExpired:
            return None, "timed out"
        return done.returncode, (done.stdout + done.stderr)[-2000:]


def _frames(run: str):
    path = Path(f"{str(run).rstrip('/')}.frames.jsonl")
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            frame = json.loads(line)
        except ValueError:
            continue
        if isinstance(frame, dict):
            yield frame


def data_file_read(run: str, data_name: str, check_script: str) -> bool | None:
    """Whether a worker call named the data file other than by running the check itself (reported, never scored). Read
    from the driver's transcript: tool calls, and a background job's steps. None when there is no transcript."""
    if not Path(f"{str(run).rstrip('/')}.frames.jsonl").is_file():
        return None
    for frame in _frames(run):
        if frame.get("type") == "tool_call":
            said = str(frame.get("args_summary") or "")
        elif frame.get("type") == "job_update":
            said = str(frame.get("step") or "")
        else:
            continue
        if data_name in said and check_script not in said:
            return True
    return False
