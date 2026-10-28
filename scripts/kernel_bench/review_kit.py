"""Shared parts of the code-review tasks (T13 Python, T14 TypeScript, T15 Swift, v0.1.64 M64):
build the PR repo, read the review, score it against the planted bugs.

Each task is a small synthetic repo (no real project's code) made in the run folder as a git
repo: `main` holds the base version, branch `feature` (checked out) one commit on top, the PR.
The planted bugs live in that task's check script (check_t13/14/15.BUGS), never in the agent's
folder. Every bug has an identifier: file, line range (in the file on `feature`) and type.

Matching rule (the same for every entrant):

1. What is read: `<run>/review.md` when it exists and is not empty, else the reply.
2. Findings. The text is read line by line. A line that names a file of the repo (its path or
   its file name; file names are unique within each repo) starts a finding about that file. A
   line that names no file but cites a line number and starts like a list item, a heading or a
   table row starts a finding about the file named last. Any other line continues the finding
   before it.
3. Line numbers a finding cites: `file:12`, `file:12-15`, `#L12`, `L12`, `line 12`, `lines 12-15`,
   `第 12 行`, `12-15 行`, `行 12`, and table cells that hold only `12` or `12-15`. A range wider
   than MAX_SPAN lines cites nothing.
4. A finding catches a planted bug when it names the bug's file, cites a line inside the bug's
   range widened by TOLERANCE lines on each side, and contains one of the bug's type keywords
   (case-insensitive substring). A bug counts once, however many findings catch it.
5. A finding that catches nothing but cites a line inside a planted bug's widened range in a
   file it names is "located" (right place, type not recognised): neither caught nor a false
   positive. A finding that cites lines near no planted bug is a false positive: the fixture code
   has no other bugs. A finding that cites no line is ignored ("unlocated").

Score: 3 = every planted bug caught and at most one false positive; 2 = all but one caught and at
most two false positives; 1 = at least one caught; 0 = none. A repo left changed (the prompt says
not to touch it; files on `feature` compared byte for byte, new files ignored) caps the score at 2.

Keyword matching misses a bug said in other words: spot-check the `missed` and `false_positive`
findings by hand (card M64, risks).
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

TOLERANCE = 3
MAX_SPAN = 15


@dataclass(frozen=True)
class Bug:
    id: str
    file: str  # path in the repo
    lines: tuple[int, int]  # first and last line, on `feature`
    kind: str  # the bug's type
    keywords: tuple[str, ...]  # any one of them names the type
    anchor: str  # text on a line inside `lines` (a test pins it to the fixture)
    context: bool = False  # found only by reading beyond the changed lines


@dataclass
class Finding:
    files: set[str]
    spans: list[tuple[int, int]] = field(default_factory=list)
    text: str = ""


def _git_env(root: Path) -> dict:
    """No user or system git config, fixed author and dates: the same repo bytes every run."""
    when = "2026-10-01T12:00:00Z"
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(root),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_AUTHOR_NAME": "Bench",
        "GIT_AUTHOR_EMAIL": "bench@example.invalid",
        "GIT_COMMITTER_NAME": "Bench",
        "GIT_COMMITTER_EMAIL": "bench@example.invalid",
        "GIT_AUTHOR_DATE": when,
        "GIT_COMMITTER_DATE": when,
    }


def build_repo(root: Path, base: dict[str, str], pr: dict[str, str], message: str) -> None:
    """`main` = base; `feature` (checked out) = base with the PR's files written over it, one commit."""
    root.mkdir(parents=True)
    env = _git_env(root)

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=root, env=env, check=True, capture_output=True)

    def write(files: dict[str, str]) -> None:
        for name, text in files.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(text)

    git("init", "-q")
    git("symbolic-ref", "HEAD", "refs/heads/main")
    write(base)
    git("add", "-A")
    git("commit", "-q", "-m", "Initial version")
    git("checkout", "-q", "-b", "feature")
    write(pr)
    git("add", "-A")
    git("commit", "-q", "-m", message)


def review_text(run: str, reply: str) -> tuple[str, str]:
    path = Path(run) / "review.md"
    text = path.read_text(encoding="utf-8", errors="ignore") if path.is_file() else ""
    return (text, "review.md") if text.strip() else (reply or "", "reply")


_DASH = r"\s*(?:[-–—~]|to|到|至)\s*"
_ITEM = re.compile(r"^\s*(?:[-*+•]|\d+[.)、]|#+|\|)")
_CELL = re.compile(rf"\s*L?(\d+)(?:{_DASH}L?(\d+))?\s*")
_LINE_PATTERNS = (
    re.compile(rf"#L(\d+)(?:{_DASH}L?(\d+))?"),
    re.compile(rf"(?<![\w#])L(\d+)(?:{_DASH}L?(\d+))?\b"),
    re.compile(rf"(?i)\blines?\s*[:：]?\s*(\d+)(?:{_DASH}(\d+))?"),
    re.compile(rf"第\s*(\d+)\s*(?:{_DASH}第?\s*(\d+)\s*)?行"),
    re.compile(rf"(?<![\d.])(\d+)\s*(?:{_DASH}(\d+)\s*)?行"),
    re.compile(r"行号?\s*[:：]?\s*(\d+)(?:\s*[-–—~到至]\s*(\d+))?"),
)


def _file_patterns(files) -> dict[str, re.Pattern]:
    by_name = {Path(f).name: f for f in files}
    assert len(by_name) == len(list(files)), "file names must be unique in a review repo"
    return {
        path: re.compile(rf"(?<![\w-]){re.escape(name)}(?!\w)") for name, path in by_name.items()
    }


def _spans(line: str, files: dict[str, re.Pattern]) -> list[tuple[int, int]]:
    found = []
    for path, pattern in files.items():
        tail = re.compile(pattern.pattern + rf"`?\s*:\s*L?(\d+)(?:{_DASH}L?(\d+))?")
        found += tail.findall(line)
    for pattern in _LINE_PATTERNS:
        found += pattern.findall(line)
    if line.strip().startswith("|"):
        for cell in line.strip().strip("|").split("|"):
            m = _CELL.fullmatch(cell)
            if m:
                found.append(m.groups(default=""))
    spans = []
    for first, last in found:
        a, b = int(first), int(last or first)
        a, b = min(a, b), max(a, b)
        if b - a <= MAX_SPAN:
            spans.append((a, b))
    return spans


def findings(text: str, files) -> list[Finding]:
    patterns = _file_patterns(files)
    out: list[Finding] = []
    last_files: set[str] = set()
    for line in text.splitlines():
        named = {path for path, pattern in patterns.items() if pattern.search(line)}
        spans = _spans(line, patterns)
        if named:
            out.append(Finding(named))
            last_files = named
        elif spans and last_files and _ITEM.match(line):
            out.append(Finding(set(last_files)))
        elif not out:
            continue
        out[-1].spans += spans
        out[-1].text += line + "\n"
    return out


def _near(finding: Finding, bug: Bug) -> bool:
    lo, hi = bug.lines[0] - TOLERANCE, bug.lines[1] + TOLERANCE
    return bug.file in finding.files and any(a <= hi and b >= lo for a, b in finding.spans)


def _names_type(finding: Finding, bug: Bug) -> bool:
    text = finding.text.lower()
    return any(k.lower() in text for k in bug.keywords)


def score(text: str, bugs: tuple[Bug, ...], files) -> dict:
    caught: set[str] = set()
    false_positive, located, unlocated = [], 0, 0
    for f in findings(text, files):
        if not f.spans:
            unlocated += 1
            continue
        hits = {b.id for b in bugs if _near(f, b) and _names_type(f, b)}
        caught |= hits
        if hits:
            continue
        if any(_near(f, b) for b in bugs):
            located += 1
        else:
            false_positive.append(f.text.strip()[:200])
    planted = len(bugs)
    n, fp = len(caught), len(false_positive)
    points = 3 if n == planted and fp <= 1 else 2 if n >= planted - 1 and fp <= 2 else 1 if n else 0
    context = [b.id for b in bugs if b.context]
    return {
        "score": points,
        "caught": n,
        "planted": planted,
        "false_positives": fp,
        "located": located,
        "unlocated": unlocated,
        "caught_ids": sorted(caught),
        "missed": [b.id for b in bugs if b.id not in caught],
        "context_caught": f"{sum(1 for b in context if b in caught)}/{len(context)}",
        "false_positive_findings": false_positive[:5],
    }


def check(run: str, reply: str, bugs: tuple[Bug, ...], head: dict[str, str]) -> dict:
    text, source = review_text(run, reply)
    res = score(text, bugs, head)
    repo = Path(run) / "repo"
    changed = sorted(
        name
        for name, body in head.items()
        if not (repo / name).is_file() or (repo / name).read_text(errors="ignore") != body
    )
    if changed:
        res["score"] = min(res["score"], 2)
    return {**res, "source": source, "repo_changed": changed}
