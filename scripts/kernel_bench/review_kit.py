"""Shared parts of the code-review tasks (T13 Python, T14 TypeScript, T15 Swift, v0.1.64 M64):
build the PR repo, read the review, score it against the planted bugs.

Each task is a small synthetic repo (no real project's code) made in the run folder as a git
repo: `main` holds the base version, branch `feature` (checked out) one commit on top, the PR.
The planted bugs live in that task's check script (check_t13/14/15.BUGS), never in the agent's
folder. Every bug has an identifier: file and line range (in the files on `feature`; a bug whose
cause and effect sit in two files has both places), and a type with its keywords.

Matching rule (the same for every entrant):

1. What is read: `<run>/review.md` when it exists and is not empty, else the reply.
2. Findings. The text is read line by line. A line that names a file of the repo (its path or its file name; file names are unique within
   each repo) starts a finding about that file. A line that names no file but cites a line
   number and starts like a list item, a heading or a table row starts a finding about the file
   named last. Any other line continues the finding before it.
3. Line numbers a finding cites: `file:12`, `file:12-15`, `#L12`, `L12`, `line 12`, `lines 12-15`,
   `第 12 行`, `12-15 行`, `行 12`, and table cells that hold only `12` or `12-15`. A range wider
   than MAX_SPAN lines cites nothing. Files and line numbers are read in code too (inline code
   and fenced blocks), keywords are not (rule 4).
4. Each finding is assigned to at most one planted bug: the nearest one by line, among the
   places in files the finding names. Distance is 0 when a cited line is inside the bug's range,
   else the gap in lines; only bugs within TOLERANCE lines count. On a tie, the first tied bug
   whose type it names. The finding catches that bug when it names the bug's type: one of its
   keywords, matched case-insensitively in the finding's prose only (inline code and fenced
   blocks are left out, so quoted code never names a type; an ASCII keyword must not follow a
   letter or digit, so `seconds` does not match `nowSeconds`). A bug counts once.
5. A finding that catches nothing:
   - "extra" when it is within TOLERANCE of a known extra (check_t1x.EXTRAS: true flaws the
     fixture has that were not planted, such as T14's ESM imports without `.js`) and names its
     keywords: neither caught nor a false positive, so a careful review loses nothing for them;
   - else "located" when a planted bug is within TOLERANCE (right place, type not recognised):
     neither caught nor a false positive;
   - else a false positive: it cites lines near nothing planted and nothing known.
   A finding that cites no line is ignored ("unlocated").

Score: 3 = every planted bug caught and at most one false positive; 2 = all but one caught and at
most two false positives; 1 = at least one caught; 0 = none. A repo left changed (the prompt says
not to touch it; files on `feature` compared byte for byte, new files ignored) caps the score at 2.

Every finding's verdict is in the result (`findings`: what it cites and the bug, extra, "located"
or "false positive" it got), for the hand check of runs that decide a gate (card M64, risks).
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

TOLERANCE = 3
MAX_SPAN = 15
Place = tuple[str, tuple[int, int]]


@dataclass(frozen=True)
class Bug:
    id: str
    file: str  # path in the repo
    lines: tuple[int, int]  # first and last line, on `feature`
    kind: str  # the bug's type
    keywords: tuple[str, ...]  # any one of them names the type
    anchor: str  # text on a line inside `lines` (a test pins it to the fixture)
    context: bool = False  # found only by reading code the PR does not change
    also: tuple[Place, ...] = ()  # the bug's other place, e.g. the untouched caller that breaks

    @property
    def places(self) -> tuple[Place, ...]:
        return ((self.file, self.lines), *self.also)


@dataclass(frozen=True)
class Extra:
    """A true flaw of the fixture that was not planted: flagging it costs nothing."""

    id: str
    places: tuple[Place, ...]
    keywords: tuple[str, ...]
    note: str


@dataclass
class Finding:
    files: set[str]
    spans: list[tuple[int, int]] = field(default_factory=list)
    text: str = ""  # prose only: inline code left out
    raw: str = ""


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
_INLINE_CODE = re.compile(r"`[^`]*`")
_FENCE = re.compile(r"^\s*(```|~~~)")


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
    fenced = False
    for line in text.splitlines():
        if _FENCE.match(line):
            fenced = not fenced
            continue
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
        out[-1].text += ("" if fenced else _INLINE_CODE.sub(" ", line)) + "\n"
        out[-1].raw += line + "\n"
    return out


def _distance(finding: Finding, places: tuple[Place, ...]) -> float:
    """Lines between what the finding cites and the nearest of `places` (0 = inside)."""
    best = float("inf")
    for path, (lo, hi) in places:
        if path not in finding.files:
            continue
        for a, b in finding.spans:
            best = min(best, 0 if a <= hi and b >= lo else lo - b if b < lo else a - hi)
    return best


def names(text: str, keywords: tuple[str, ...]) -> bool:
    """Any keyword in `text` (lower-cased prose); an ASCII keyword must not follow a letter or digit."""
    for k in keywords:
        k = k.lower()
        if k.isascii():
            if re.search(rf"(?<![a-z0-9]){re.escape(k)}", text):
                return True
        elif k in text:
            return True
    return False


def assign(
    finding: Finding, bugs: tuple[Bug, ...], extras: tuple[Extra, ...] = ()
) -> tuple[str, str]:
    """(verdict, id): ("caught", bug), ("extra", extra), ("located", bug) or ("false positive", "")."""
    text = finding.text.lower()
    near = {b.id: _distance(finding, b.places) for b in bugs}
    closest = min(near.values(), default=float("inf"))
    tied = [b for b in bugs if near[b.id] == closest] if closest <= TOLERANCE else []
    hit = next((b for b in tied if names(text, b.keywords)), None)
    if hit:
        return "caught", hit.id
    extra = next(
        (
            e
            for e in extras
            if _distance(finding, e.places) <= TOLERANCE and names(text, e.keywords)
        ),
        None,
    )
    if extra:
        return "extra", extra.id
    if tied:
        return "located", tied[0].id
    return "false positive", ""


def score(text: str, bugs: tuple[Bug, ...], files, extras: tuple[Extra, ...] = ()) -> dict:
    caught: set[str] = set()
    false_positive, verdicts = [], []
    counts = {"located": 0, "extra": 0, "unlocated": 0}
    for f in findings(text, files):
        cites = ", ".join(f"{a}-{b}" for a, b in f.spans)
        if not f.spans:
            counts["unlocated"] += 1
            continue
        verdict, what = assign(f, bugs, extras)
        verdicts.append({"files": sorted(f.files), "lines": cites, "verdict": verdict, "id": what})
        if verdict == "caught":
            caught.add(what)
        elif verdict == "false positive":
            false_positive.append(f.raw.strip()[:200])
        else:
            counts[verdict] += 1
    planted = len(bugs)
    n, fp = len(caught), len(false_positive)
    points = 3 if n == planted and fp <= 1 else 2 if n >= planted - 1 and fp <= 2 else 1 if n else 0
    context = [b.id for b in bugs if b.context]
    return {
        "score": points,
        "caught": n,
        "planted": planted,
        "false_positives": fp,
        **counts,
        "caught_ids": sorted(caught),
        "missed": [b.id for b in bugs if b.id not in caught],
        "context_caught": f"{sum(1 for b in context if b in caught)}/{len(context)}",
        "false_positive_findings": false_positive[:5],
        "findings": verdicts[:30],
    }


def check(
    run: str,
    reply: str,
    bugs: tuple[Bug, ...],
    head: dict[str, str],
    extras: tuple[Extra, ...] = (),
) -> dict:
    text, source = review_text(run, reply)
    res = score(text, bugs, head, extras)
    repo = Path(run) / "repo"
    changed = sorted(
        name
        for name, body in head.items()
        if not (repo / name).is_file() or (repo / name).read_text(errors="ignore") != body
    )
    if changed:
        res["score"] = min(res["score"], 2)
    return {**res, "source": source, "repo_changed": changed}
