"""scripts/dev/merge_json_keys.py, in real git merges of a locale file: what a text merge conflicts on merges clean and in
order, and a key both sides changed is still a conflict."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRIVER = f'python3 "{ROOT}/scripts/dev/merge_json_keys.py" %O %A %B'
LOCALE = "web/src/locales/en.json"


def _git(repo: Path, *args: str, driver: str | None = DRIVER) -> subprocess.CompletedProcess:
    setting = ["-c", f"merge.json-keys.driver={driver}"] if driver else []
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *setting, *args], cwd=repo,
                          capture_output=True, text=True, timeout=60)


def _commit(repo: Path, doc: dict, message: str) -> None:
    (repo / LOCALE).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _git(repo, "add", ".")
    assert _git(repo, "commit", "-m", message).returncode == 0


def test_key_level_merges_in_real_git(tmp_path):
    repo = tmp_path
    _git(repo, "init", "-b", "main")
    (repo / ".gitattributes").write_text((ROOT / ".gitattributes").read_text(encoding="utf-8"), encoding="utf-8")
    (repo / LOCALE).parent.mkdir(parents=True)
    base = {"a": {"one": "1", "two": "2"}, "b": {"gone": "x", "kept": "y"}}
    _commit(repo, base, "base")

    # Next to each other, and each side's last key in `a` gains a comma: a text merge conflicts on both.
    _git(repo, "checkout", "-q", "-b", "pr")
    _commit(repo, {"a": {"one": "1", "two": "2", "mine": "m"}, "b": {"gone": "x", "kept": "y", "added": "z"}}, "pr")
    _git(repo, "checkout", "-q", "main")
    _commit(repo, {"a": {"one": "1", "two": "2", "theirs": "t"}, "b": {"kept": "y"}, "c": {"clé": "gardée"}}, "main")
    assert _git(repo, "merge-tree", "--write-tree", "pr", "main", driver=None).returncode == 1
    _git(repo, "checkout", "-q", "pr")
    merged = _git(repo, "merge", "--no-edit", "main")
    assert merged.returncode == 0, merged.stdout + merged.stderr
    text = (repo / LOCALE).read_text(encoding="utf-8")
    doc = json.loads(text)
    assert doc == {"a": {"one": "1", "two": "2", "mine": "m", "theirs": "t"}, "b": {"kept": "y", "added": "z"},
                   "c": {"clé": "gardée"}}
    assert list(doc) == ["a", "b", "c"] and list(doc["a"]) == ["one", "two", "theirs", "mine"]
    assert text == json.dumps(doc, ensure_ascii=False, indent=2) + "\n"          # no reformatting, no \uXXXX

    # One key, changed both ways: nothing can choose, so it stays an ordinary conflict.
    _git(repo, "checkout", "-q", "-b", "other", "main")
    _commit(repo, {**doc, "a": {**doc["a"], "one": "theirs"}}, "other")
    _git(repo, "checkout", "-q", "pr")
    _commit(repo, {**doc, "a": {**doc["a"], "one": "mine"}}, "mine")
    clash = _git(repo, "merge", "--no-edit", "other")
    assert clash.returncode != 0
    assert "<<<<<<<" in (repo / LOCALE).read_text(encoding="utf-8")
    assert LOCALE in _git(repo, "diff", "--name-only", "--diff-filter=U").stdout
