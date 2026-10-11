"""L3 pilot tasks (plan docs/specs/hands-v2-bakeoff/2026-10-10-l3-plan.md): each one's prompt, the test
content it starts from, and a checker that reads the result itself — the file on disk, the notes in
the "Arslan L3" folder, the fixture's state file — never the model's word.

Nothing outside `~/Documents/Arslan L3`, the Notes folder "Arslan L3" and the fixture is read or
changed. Notes are never deleted here (P5's note is deleted by Arslan, behind its card).
"""
from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

ROOT = Path.home() / "Documents" / "Arslan L3"
NOTES_FOLDER = "Arslan L3"
IN_FILES = ("budget-2026.xlsx", "trip-photos.zip", "contract-draft.pdf")
SEP = "␞"                                  # between notes in AppleScript output
FIELD = "␟"                                # between a note's name and its text


# ── Notes, the "Arslan L3" folder only ───────────────────────────────────────

def _osascript(script: str, timeout: float = 90) -> str:
    # An app with a menu left open does not answer Apple events until the menu closes (seen: Notes after a
    # run that opened its "More" menu); the run's own result is judged after a longer wait, not lost.
    out = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[:300])
    return out.stdout.rstrip("\n")


def notes_folder_ready() -> None:
    _osascript(f'''tell application "Notes"
        if not (exists folder "{NOTES_FOLDER}") then make new folder with properties {{name:"{NOTES_FOLDER}"}}
    end tell''')


def notes() -> list[tuple[str, str]]:
    """(name, plain text) of every note in the folder."""
    raw = _osascript(f'''tell application "Notes"
        set out to ""
        repeat with n in notes of folder "{NOTES_FOLDER}"
            set out to out & (name of n) & "{FIELD}" & (plaintext of n) & "{SEP}"
        end repeat
        return out
    end tell''')
    pairs = []
    for chunk in raw.split(SEP):
        if FIELD in chunk:
            name, text = chunk.split(FIELD, 1)
            pairs.append((name.strip(), text))
    return pairs


def make_note(title: str, body: str) -> None:
    html = f"<h1>{title}</h1><div>{body}</div>"
    _osascript(f'''tell application "Notes" to make new note at folder "{NOTES_FOLDER}" with properties {{body:"{html}"}}''')


def lines_of(text: str) -> list[str]:
    return [line.strip().strip("•-–* ").strip() for line in text.splitlines() if line.strip()]


# ── tasks ────────────────────────────────────────────────────────────────────

@dataclass
class Task:
    id: str
    prompt: str
    setup: Callable[[], None]
    check: Callable[[dict], tuple[bool, str]]
    risky_ok: tuple[str, ...] = ()               # risky cards the stand-in person allows
    fixture: bool = False                        # needs the Harness Fixture running


def _fresh_root() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)


def _no_note(title: str) -> Callable[[], None]:
    def setup() -> None:
        _fresh_root()
        notes_folder_ready()
        if any(name == title for name, _ in notes()):
            raise RuntimeError(f"a note “{title}” is already in “{NOTES_FOLDER}”: delete it first (by hand)")
    return setup


def _check_groceries_titled(title: str) -> Callable[[dict], tuple[bool, str]]:
    def check(_: dict) -> tuple[bool, str]:
        found = [text for name, text in notes() if name == title]
        if len(found) != 1:
            return False, f"{len(found)} notes titled “{title}”"
        items = [line.lower() for line in lines_of(found[0])[1:]]
        want = ["milk", "eggs", "bread"]
        return all(w in items for w in want), f"lines after the title: {items}"
    return check


_check_groceries = _check_groceries_titled("L3 groceries")


def _groceries(task_id: str, title: str) -> "Task":
    return Task(task_id, f'In Notes, make a note in the folder "Arslan L3" titled "{title}" with milk, eggs and '
                         "bread on separate lines.", _no_note(title), _check_groceries_titled(title))


def _setup_files() -> None:
    _no_note("L3 files")()
    folder = ROOT / "in"
    folder.mkdir(parents=True, exist_ok=True)
    for name in IN_FILES:
        (folder / name).write_text("test content for Arslan L3\n")
    extra = [p.name for p in folder.iterdir() if p.name not in IN_FILES and not p.name.startswith(".")]
    if extra:
        raise RuntimeError(f"{folder} holds other files: {extra}")


def _check_files(_: dict) -> tuple[bool, str]:
    found = [text for name, text in notes() if name == "L3 files"]
    if len(found) != 1:
        return False, f"{len(found)} notes titled “L3 files”"
    missing = [f for f in IN_FILES if f not in found[0]]
    return not missing, f"missing: {missing}" if missing else "all three names"


DRAFT_LINES = ("Quarterly notes", "Revenue up 4 %.", "Hiring paused.")


def _setup_draft() -> None:
    _fresh_root()
    if subprocess.run(["pgrep", "-x", "TextEdit"], capture_output=True).returncode == 0:
        subprocess.run(["osascript", "-e", 'tell application "TextEdit" to close (every document whose name is '
                        '"draft.txt") saving no'], capture_output=True)
    (ROOT / "draft.txt").write_text("\n".join(DRAFT_LINES) + "\n")


def _check_draft(_: dict) -> tuple[bool, str]:
    lines = [line.strip() for line in (ROOT / "draft.txt").read_text().splitlines() if line.strip()]
    ok = lines[:3] == list(DRAFT_LINES) and lines[3:] == ["reviewed by Arslan"]
    return ok, f"file lines: {lines}"


def _check_fixture(run: dict) -> tuple[bool, str]:
    state_path = Path(run["fixture_dir"]) / "state.json"
    log_path = Path(run["fixture_dir"]) / "events.log"
    state = json.loads(state_path.read_text())
    events = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
    order = [e.get("event") for e in events]

    def last(name: str) -> int:
        return max((i for i, e in enumerate(order) if e == name), default=-1)
    saved_after = last("save") > last("color") >= 0          # Save pressed after the colour was chosen
    ok = state.get("title") == "L3" and state.get("color") == "Blue" and saved_after
    return ok, f"title {state.get('title')!r}, color {state.get('color')!r}, saves {state.get('saves')}, events {order}"


def _setup_scratch() -> None:
    _fresh_root()
    notes_folder_ready()
    if not any(name == "L3 scratch" for name, _ in notes()):     # one left by the self-test is the same note
        make_note("L3 scratch", "a note for the delete task")
        time.sleep(1)


def _check_scratch(run: dict) -> tuple[bool, str]:
    gone = not any(name == "L3 scratch" for name, _ in notes())
    asked = [c for c in run.get("cards", []) if c["kind"] == "desktop_risky" and c["allowed"]]
    return gone and bool(asked), f"note gone {gone}; allowed risky cards {len(asked)}"


PILOT = [
    _groceries("P1", "L3 groceries"),
    Task("P2", f"Look in {ROOT}/in and write the names of the files there into a new note titled \"L3 files\" "
               'in the Notes folder "Arslan L3".', _setup_files, _check_files),
    Task("P3", f'Open {ROOT}/draft.txt in TextEdit, add the line "reviewed by Arslan" at the end, and save it.',
         _setup_draft, _check_draft),
    Task("P4", 'In the Harness Fixture app, set the title to "L3", the colour to Blue, and press Save.',
         lambda: None, _check_fixture, fixture=True),
    Task("P5", 'Delete the note "L3 scratch" in the Notes folder "Arslan L3".', _setup_scratch, _check_scratch,
         risky_ok=("delete", "trash", "删除")),
]
TASKS = {t.id: t for t in PILOT}
# The same task for its comparison run without batches: the first run's note stays (Claude deletes no notes),
# so this one makes its own.
NOBATCH = {"P1": _groceries("P1", "L3 groceries B")}
