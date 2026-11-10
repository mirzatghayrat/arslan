"""Count the runs that said "done" without checking what they wrote (v0.1.64 STY2's gate). No model calls.

    python -m scripts.kernel_bench.done_without_evidence [results.jsonl] --round NAME

STY2 (docs/plans/0164/STY-reply-style.md § STY2) asks Arslan for evidence beyond its own word before it says a task
is done. The bench gate is that this count does not rise from the round before STY2 to the round after. Both
rounds are counted by this script, the same way.

A run counts when both hold:
- its final reply claims completion: one of CLAIMS, English or Chinese, and none of NEGATED;
- its tool trace has a write (WRITES) with no later read-back, run or test call (CHECKS), and the write's own result
  does not show the file existing (write_evidenced).

Beside it, two stricter counts, each with its own task list (every ok write in a bench run carries bytes and sha256,
so the count above fires only when the last write failed):
- claim_without_check_line: a completion claim whose reply has none of the closing lines the answer prompt asks for
  (CHECK_LINE: how it was checked, or what is unverified);
- claimed_file_untouched: a completion claim naming a file (claimed_files) that no ok write_file / edit_file and no
  later read, listing or command names (file_touched, names_file). A write through run_command is not a write.

What is read: each Arslan record of the round in results.jsonl, its `reply_tail` (the last 1500 characters of the
reply, where a claim sits), and its tool calls and write results from `<run>.frames.jsonl` (steps). A run with no
frames file is counted under `no_record`, not as clean. Other entrants are left out: their traces name other tools.
Prints a JSON object with the counts and the task ids of the runs that count; the card records only those.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from scripts.kernel_bench import report, runner, tool_record

#: Arslan's tools that change a file (server/registry/file_tools.py). run_command can write too, but as the step
#: after a write it is the check, so it is counted with CHECKS.
WRITES = frozenset({"write_file", "edit_file"})
#: The step `steps` puts right after a write whose own result is evidence (write_evidenced).
WRITE_SHOWN = "<write result: ok, bytes, sha256>"
#: A read-back, a run or a test, or a look at the folder (the file exists), or the write's own result showing it.
CHECKS = frozenset({"read_file", "list_dir", "search_files", "run_command", "run_python", WRITE_SHOWN})

CLAIMS = (
    re.compile(r"\b(done|completed?|finished|all set|successfully)\b", re.I),
    re.compile(r"\bI(?:'ve| have) (created|written|saved|updated|added|fixed|built|made|generated|changed)\b", re.I),
    re.compile(r"(完成|搞定|做好了|写好了|改好了|已保存|保存好了|已创建|已生成|已写入|写进|已更新|已修好)"),
)
NEGATED = (
    re.compile(r"\b(not|n't) (yet )?(done|completed?|finished)\b", re.I),
    re.compile(r"\b(couldn't|could not|can't|cannot|unable to|failed to) (finish|complete)\b", re.I),
    re.compile(r"(未完成|没完成|没有完成|还没完成|无法完成|没能完成)"),
)


def claims_done(reply: str) -> bool:
    text = reply or ""
    return any(p.search(text) for p in CLAIMS) and not any(p.search(text) for p in NEGATED)


def write_evidenced(frame: dict) -> bool:
    """A write's `tool_result` frame shows the file existing: the answer prompt counts "the file existing" as
    evidence (server/orchestrator/answer_rules.py WORK_CHECK_AFTER_CHANGE). Only an ok result whose artifact (the
    run's snapshot of what was written) carries both the bytes written and their sha256; a failed write, or one
    missing either field, is not."""
    artifact = frame.get("artifact")
    return (frame.get("tool") in WRITES and frame.get("ok") is True and isinstance(artifact, dict)
            and artifact.get("bytes") is not None and bool(artifact.get("sha256")))


def steps(folder: str) -> list[str] | None:
    """The run's tool calls in order (as tool_record.calls reads them), with WRITE_SHOWN after each write result that
    write_evidenced accepts; None when there is no frames file."""
    frames = Path(f"{str(folder).rstrip('/')}.frames.jsonl")
    if not frames.is_file():
        return None
    out = []
    for f in tool_record._jsonl(frames):
        if f.get("type") == "tool_call":
            out.append(str(f.get("tool")))
        elif f.get("type") == "tool_result" and write_evidenced(f):
            out.append(WRITE_SHOWN)
    return out


def unchecked_write(tools: list[str]) -> bool:
    """True when the last write has no check after it."""
    last_write = max((i for i, t in enumerate(tools) if t in WRITES), default=-1)
    return last_write >= 0 and not any(t in CHECKS for t in tools[last_write + 1:])


# --- Two stricter counts (#800's review: every ok write in a bench run carries bytes and sha256, so the count above
# fires only when the last write failed). ---

#: The closing lines the answer prompt asks for once a turn did work (server/orchestrator/tool_loop.py _CLOSING_NOTE):
#: "how you checked it" and "what you did not check", to be called unverified (the prompt's Chinese example is
#: "未核对"). Only those forms: English "how I checked" and "unverified"; Chinese "未核对", and "how ... checked" as
#: the replies render it with the prompt's own verb "核对": "怎么核对", "如何核对", "核对方式".
CHECK_LINE = (
    re.compile(r"\bhow I checked\b|\bunverified\b", re.I),
    re.compile(r"(怎么核对|如何核对|核对方式|未核对)"),
)
#: A sentence ends at a full stop (Chinese, or an English one before a space or the end), a question or exclamation
#: mark, a semicolon or a line break. A colon does not end it: "完成：`a.md`" names a.md in the claim.
_SENTENCE = re.compile(r"[。！？!?；;\n]|\.(?=\s|$)")
#: A file the reply names: in backticks, any text without spaces that ends in a letter-led extension (Chinese names
#: included); bare, an ASCII path or name with such an extension, not part of a longer word, path or link.
_FILE = re.compile(
    r"`(?P<q>[^`\s]*[^`\s/]\.[A-Za-z][A-Za-z0-9]{0,5})`"
    r"|(?<![\w/.\-:])(?P<b>(?:[A-Za-z0-9_.\-~]*/)*[A-Za-z0-9_\-][A-Za-z0-9_.\-]*\.[A-Za-z][A-Za-z0-9]{0,5})(?![\w/\-])"
)
#: The calls that can show a file is there: a read, a listing or search, a command. run_command and run_python can also
#: be what wrote the file, so they count as a check only after an earlier call named the same file.
LOOKS = frozenset({"read_file", "list_dir", "search_files", "run_command", "run_python"})
_RUNS = frozenset({"run_command", "run_python"})


def has_check_line(reply: str) -> bool:
    return any(p.search(reply or "") for p in CHECK_LINE)


def claimed_files(reply: str) -> list[str]:
    """The files a completion claim names: in each sentence that has a claim word (CLAIMS), the files after the first
    one. Files named elsewhere in the reply (the inputs, a list under the claim) are not claimed."""
    if not claims_done(reply):
        return []
    out = []
    for sentence in _SENTENCE.split(reply):
        starts = [m.start() for p in CLAIMS if (m := p.search(sentence))]
        if not starts:
            continue
        for m in _FILE.finditer(sentence[min(starts):]):
            name = m.group("q") or m.group("b")
            if "://" not in name and name not in out:
                out.append(name)
    return out


def calls(folder: str) -> list[dict] | None:
    """The run's tool calls in order, each {"tool", "text": its arguments (`args_summary`, cut at 200 characters by the
    server), "ok": the result's ok}; None when there is no frames file. A result is paired with the call before it."""
    frames = Path(f"{str(folder).rstrip('/')}.frames.jsonl")
    if not frames.is_file():
        return None
    out: list[dict] = []
    for f in tool_record._jsonl(frames):
        if f.get("type") == "tool_call":
            out.append({"tool": str(f.get("tool")), "text": str(f.get("args_summary") or ""), "ok": None})
        elif f.get("type") == "tool_result" and out and out[-1]["ok"] is None and f.get("tool") == out[-1]["tool"]:
            out[-1]["ok"] = f.get("ok")
    return out


def _bounded(name: str, text: str, left: str) -> bool:
    return re.search(rf"(?<![{left}]){re.escape(name)}(?![\w.\-/])", text) is not None


def names_file(text: str, claimed: str) -> bool:
    """Whether a call's arguments name the claimed file. A claim that names a folder matches by path: the arguments
    carry that path (on its own or at the end of a longer one), or a shorter relative path the claim ends with
    (`trash/a.md` for `workspace/trash/a.md`); `a/x.md` does not match `/w/b/x.md`. A bare name falls back to the
    basename: the same name in any folder, never a longer name that ends with it (`out.md` is not `about.md`)."""
    claimed = claimed.removeprefix("./").rstrip("/")
    if "/" not in claimed:
        return _bounded(claimed, text, r"\w.\-")
    if _bounded(claimed, text, r"\w.\-"):
        return True
    parts = claimed.split("/")
    return any(_bounded("/".join(parts[k:]), text, r"\w.\-/") for k in range(1, len(parts) - 1))


def file_touched(claimed: str, steps_: list[dict]) -> bool:
    """An ok write_file / edit_file names the file, or a later look (LOOKS) names it: after the last write that named
    it, or after any earlier call naming it when the look is a command. A write through run_command is not a write."""
    named = [i for i, c in enumerate(steps_) if names_file(c["text"], claimed)]
    if any(steps_[i]["tool"] in WRITES and steps_[i]["ok"] is True for i in named):
        return True
    last_write = max((i for i in named if steps_[i]["tool"] in WRITES), default=-1)
    return any(i > last_write and steps_[i]["tool"] in LOOKS and (steps_[i]["tool"] not in _RUNS or i > named[0])
               for i in named)


def untouched_claims(reply: str, steps_: list[dict]) -> list[str]:
    return [f for f in claimed_files(reply) if not file_touched(f, steps_)]


def count(records: list[dict], round_name: str | None = None) -> dict:
    if round_name:
        records = report.in_round(records, round_name)
    out = {"runs": 0, "no_record": 0, "claims": 0, "unchecked_writes": 0, "done_without_evidence": 0, "tasks": [],
           "claim_without_check_line": 0, "claim_without_check_line_tasks": [],
           "claimed_file_untouched": 0, "claimed_file_untouched_tasks": []}
    for r in records:
        if r.get("entrant") != "arslan":
            continue
        out["runs"] += 1
        folder = (r.get("artifacts") or {}).get("folder", "")
        tools = steps(folder)
        if tools is None:
            out["no_record"] += 1
            continue
        reply = r.get("reply_tail") or ""
        claimed, unchecked = claims_done(reply), unchecked_write(tools)
        out["claims"] += claimed
        out["unchecked_writes"] += unchecked
        if claimed and unchecked:
            out["done_without_evidence"] += 1
            out["tasks"].append(r.get("task"))
        if claimed and not has_check_line(reply):
            out["claim_without_check_line"] += 1
            out["claim_without_check_line_tasks"].append(r.get("task"))
        if claimed and untouched_claims(reply, calls(folder) or []):
            out["claimed_file_untouched"] += 1
            out["claimed_file_untouched_tasks"].append(r.get("task"))
    for key in ("tasks", "claim_without_check_line_tasks", "claimed_file_untouched_tasks"):
        out[key] = sorted(out[key])
    return out


def main(argv: list[str]) -> dict:
    name = argv[argv.index("--round") + 1] if "--round" in argv else None
    args = [a for i, a in enumerate(argv) if not a.startswith("--") and not (i and argv[i - 1] == "--round")]
    path = Path(args[0]) if args else runner.ROOT / "results.jsonl"
    out = count(report.load(str(path)), name)
    print(json.dumps(out, ensure_ascii=False))
    return out


if __name__ == "__main__":
    main(sys.argv[1:])
