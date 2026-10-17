"""T9 precise edits across files: rename a setting in three named files and bump the
version in a fourth; touch nothing else.

3 = every edited file is byte for byte as expected, every other file is unchanged and
no file was added. An edit that is not exact scores 0; with exact edits, a changed
other file and an added file each cost a point.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

OLD, NEW = "max_retry_count", "retry_limit"
FILES = {
    "settings.toml": f'[worker]\n{OLD} = 3\ntimeout_s = 30\n',
    "worker.py": (f'from config import load\n\ncfg = load()\n\n\ndef retries() -> int:\n'
                  f'    return cfg["worker"]["{OLD}"]\n'),
    "docs/config.md": f"# Settings\n\n- `{OLD}`: how many times a job is retried (default 3).\n- `timeout_s`: seconds.\n",
    "pyproject.toml": '[project]\nname = "demo-worker"\nversion = "1.4.2"\n',
    # Not named in the prompt: must stay as it is, even though it mentions the old name.
    "legacy/old_worker.py": f'# kept for reference; do not edit\nRETRY_KEY = "{OLD}"\n',
    "CHANGELOG.md": "# Changelog\n\n## 1.4.2\n- Fix retries.\n",
}
EDITS = {"settings.toml", "worker.py", "docs/config.md"}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def expected() -> dict[str, bytes]:
    out = {}
    for name, text in FILES.items():
        if name in EDITS:
            text = text.replace(OLD, NEW)
        elif name == "pyproject.toml":
            text = text.replace('version = "1.4.2"', 'version = "1.5.0"')
        out[name] = text.encode()
    return out


def fixture(run: str) -> None:
    root = Path(run) / "project"
    for name, text in FILES.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)


def check(run: str) -> dict:
    root = Path(run) / "project"
    want = {n: _sha(b) for n, b in expected().items()}
    # Byte-compiled files from an agent checking its edit (`python -m py_compile`) are not
    # new files the task made.
    have = {str(p.relative_to(root)): _sha(p.read_bytes()) for p in root.rglob("*")
            if p.is_file() and p.name != ".DS_Store" and "__pycache__" not in p.parts}
    changed_ok = all(have.get(n) == want[n] for n in (*EDITS, "pyproject.toml"))
    others_ok = all(have.get(n) == want[n] for n in want if n not in EDITS and n != "pyproject.toml")
    added = sorted(set(have) - set(want))
    score = 3 - (not others_ok) - bool(added) if changed_ok else 0
    return {"score": score, "edits_exact": changed_ok, "others_unchanged": others_ok, "added": added}
