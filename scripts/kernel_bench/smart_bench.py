"""SMART-5: the "feels smart" bench, Arslan against OpenClaw on the same model (docs/plans/0164/SMART-feels-smart.md).

The user (2026-11-02): both ran on the same model, so the gap is Arslan's harness, not the model. Every task is one
turn, so both entrants run it as written. Each run is one new conversation: Arslan on a brand-new instance, as the
STY read test does (sty_read.run_prompt); OpenClaw in a fresh HOME, as the 10-01 bake-off does (runner.command).
The reply and the run's tool calls are kept, and both are graded by the same rubric:

    BENCH_SANDBOX=none BENCH_ROUND=smart1 .venv/bin/python -m scripts.kernel_bench.smart_bench \\
        --entrant arslan --label before --repo <checkout> --out <dir> --model deepseek-v4-flash
    BENCH_ROUND=smart1 .venv/bin/python -m scripts.kernel_bench.smart_bench \\
        --entrant openclaw --label before --out <dir> --model deepseek-v4-flash

    .venv/bin/python -m scripts.kernel_bench.smart_bench --grade <dir>/arslan-before.json
    .venv/bin/python -m scripts.kernel_bench.smart_bench --gate <dir>/arslan-after.json <dir>/openclaw-before.json
    .venv/bin/python -m scripts.kernel_bench.smart_bench --compare <dir>/arslan-before.json <dir>/arslan-after.json

What each rubric key checks (a task passes when every key it can judge holds, and it ends without an unrequested
offer, `no_offer`):
- `words`: the reply's length is within the budget (English words; two Han characters count as one).
- `self_state`: a live self-state tool was called (Arslan: the names in the rubric; other entrants: SELF_TOOL).
- `admit`: after a correction or probe, the reply opens with a short admission.
- `ask`: an ambiguous referent gets a question that names each reading.
- `guide`: blocked, the reply says where (a place), how (a command in backticks, or a Settings › path) and
  "tell me when it's done and I'll retry".
- `found_or_guide`: the tool's output is in the reply, or it guides as above.
- `verified`: saying something isn't installed needs a command run first (Arslan: RUN_TOOLS; others: RUN_TOOL).
- `no_app_config`: no tool call reads another app's private files (Application Support, Containers).
- `unread_url`: an unreadable link is never listed as a source; every line naming it says it couldn't be read.
A key that needs the tool trace is None ("can't tell") when the run left no trace; it doesn't count either way.
The gate (`gate`) is the card's: Arslan at least matches OpenClaw on each of DIMENSIONS. These are scripts, not
judgment: read them with the replies.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from scripts.kernel_bench import fixture_smart, runner, sty_read

HERE = Path(__file__).resolve().parent
PROMPTS = HERE / "smart_prompts.json"
ENTRANTS = ("arslan", "openclaw")
RULES = frozenset({"words", "self_state", "admit", "ask", "guide", "found_or_guide", "verified", "no_app_config",
                   "unread_url"})
#: The card's gate dimensions, each a set of rubric keys.
DIMENSIONS = {
    "focus": ("admit", "ask", "no_offer"),
    "length": ("words",),
    "verify": ("verified", "unread_url", "no_app_config"),
    "guide": ("guide", "found_or_guide"),
    "self_state": ("self_state",),
}
NEEDS_TRACE = frozenset({"self_state", "verified", "no_app_config"})

RUN_TOOLS = frozenset({"run_command", "run_python"})
#: Another entrant's tools are matched by name, since each harness names them its own way.
RUN_TOOL = re.compile(r"exec|bash|shell|run|command|process|terminal", re.I)
SELF_TOOL = re.compile(r"status|version|whats_new|capabilit|self|session_info", re.I)

_WORD = re.compile(r"[A-Za-z0-9]+(?:[.'’,-][A-Za-z0-9]+)*")
_HAN = re.compile(r"[㐀-鿿]")
OFFER = re.compile(
    r"let me know if|want me to|would you like me to|shall i\b|should i\b|i can also|happy to|feel free to|"
    r"if you'?d like|需要的话|要不要我|如果你需要|如果需要|随时告诉我|我可以再|我也可以|需要我", re.I)
ADMIT = re.compile(
    r"^\W*(对|是的|没错|确实|没有|没去|没看|我没|你说得对|you'?re right|right[,.]|i didn'?t|i did not|no[,.]|yes[,.]|"
    r"i guessed|correct)", re.I)
COMMAND = re.compile(r"`[^`\n]+`|```|(settings|系统设置|设置)\s*[›>→]", re.I)
RETRY = re.compile(
    r"tell me when|let me know when|once (it'?s|that'?s) done|i'?ll (retry|try again)|好了告诉我|告诉我.{0,12}再试|"
    r"我再试|完成后告诉我|弄好后告诉我", re.I)
MISSING = re.compile(r"not installed|isn'?t installed|not found|doesn'?t exist|没有安装|没安装|未安装|找不到|不存在", re.I)
UNREADABLE = re.compile(
    r"couldn'?t|could not|can'?t|cannot|unable|not (be )?read|unreachable|doesn'?t resolve|无法|没能|打不开|读不到|访问不了|"
    r"没法", re.I)
PRIVATE = ("Application Support", "Library/Containers")
DEFAULT_PLACES = ("Mac", "终端", "Terminal")


def load_prompts(path: Path = PROMPTS) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def words(text: str) -> int:
    return len(_WORD.findall(text or "")) + math.ceil(len(_HAN.findall(text or "")) / 2)


def offer_at_end(text: str) -> bool:
    lines = [ln for ln in (text or "").strip().splitlines() if ln.strip()]
    return bool(lines) and bool(OFFER.search(lines[-1]))


def _guides(reply: str, places) -> bool:
    return (any(p.lower() in reply.lower() for p in places) and bool(COMMAND.search(reply))
            and bool(RETRY.search(reply)))


def _runs(name: str, who: str) -> bool:
    return name in RUN_TOOLS if who == "arslan" else bool(RUN_TOOL.search(name))


def _self(name: str, who: str, names: list[str]) -> bool:
    return name in names if who == "arslan" else bool(SELF_TOOL.search(name))


def grade(item: dict, reply: str, tools: list | None, who: str = "arslan") -> dict:
    """Each rubric key → True/False (None when it needs a trace the run didn't leave), plus `no_offer` and `pass`.
    `tools` is [(name, args), ...], or None when there's no trace."""
    reply = reply or ""
    empty = not reply.strip()             # no reply passes nothing: not the length, not "no closing offer"
    rubric = item["rubric"]
    trace = list(tools) if tools is not None else None
    names = [t[0] for t in trace or []]
    out: dict = {}
    if "words" in rubric:
        out["words"] = not empty and words(reply) <= rubric["words"]
    if "self_state" in rubric:
        out["self_state"] = None if trace is None else any(_self(n, who, rubric["self_state"]) for n in names)
    if rubric.get("admit"):
        out["admit"] = bool(ADMIT.search(reply))
    if "ask" in rubric:
        low = reply.lower()
        out["ask"] = ("?" in reply or "？" in reply) and all(
            any(o.lower() in low for o in group) for group in rubric["ask"])
    if "guide" in rubric:
        out["guide"] = _guides(reply, rubric["guide"])
    if "found_or_guide" in rubric:
        # The value as a whole token: 3.2.1, not 13.2.1 or 3.2.10 (entrants wrote 「版本是 **3.2.1 (bench)**」).
        value = re.compile(r"(?<![\d.])" + re.escape(rubric["found_or_guide"]) + r"(?!\d|\.\d)")
        out["found_or_guide"] = bool(value.search(reply)) or _guides(reply, DEFAULT_PLACES)
    if rubric.get("verified"):
        if not MISSING.search(reply):
            out["verified"] = True
        else:
            out["verified"] = None if trace is None else any(_runs(n, who) for n in names)
    if rubric.get("no_app_config"):
        out["no_app_config"] = None if trace is None else not any(p in str(t[1]) for t in trace for p in PRIVATE)
    if "unread_url" in rubric:
        host = rubric["unread_url"]
        out["unread_url"] = all(UNREADABLE.search(ln) for ln in reply.splitlines() if host in ln)
    out["no_offer"] = not empty and not offer_at_end(reply)
    out["pass"] = all(v for v in out.values() if v is not None)
    return out


# ---------------------------------------------------------------- tool traces

def tool_calls(frames: Path) -> list[tuple[str, str]] | None:
    """Arslan: (tool, args_summary) of each `tool_call` frame, in order; None when there is no frames file."""
    if not frames.is_file():
        return None
    out = []
    for line in frames.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("type") == "tool_call":
            out.append((str(row.get("tool")), str(row.get("args_summary") or "")))
    return out


_CALL_TYPES = {"toolcall", "tool_call", "tool_use", "function_call"}
#: OpenClaw 2026.10.10: the tool `dispatch_action` ran is an event of its own, not a block in the assistant's message.
_NESTED_CALL = "openclaw.nested-tool.v1"


def _calls_in(node) -> list[tuple[str, str]]:
    """Tool calls anywhere in a JSON value, in document order: a block typed as a call with a `name`, an OpenAI-style
    `{"function": {"name", "arguments"}}`, or OpenClaw's nested-tool event (not searched further: its result is data)."""
    found: list[tuple[str, str]] = []
    if isinstance(node, dict):
        kind = str(node.get("type", "")).replace("-", "_").lower()
        fn = node.get("function")
        details = node.get("details")
        if (node.get("customType") == _NESTED_CALL and isinstance(details, dict)
                and isinstance(details.get("toolName"), str)):
            found.append((details["toolName"], json.dumps(details.get("input", ""), ensure_ascii=False)))
        elif kind in _CALL_TYPES and isinstance(node.get("name"), str):
            args = node.get("arguments", node.get("input", node.get("args", "")))
            found.append((node["name"], args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)))
        elif isinstance(fn, dict) and isinstance(fn.get("name"), str):
            args = fn.get("arguments", "")
            found.append((fn["name"], args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)))
        else:
            for value in node.values():
                found += _calls_in(value)
    elif isinstance(node, list):
        for value in node:
            found += _calls_in(value)
    return found


def _warn(text: str) -> None:
    print(f"smart_bench: {text}", file=sys.stderr)


def _openclaw_db_calls(home: Path) -> tuple[bool, list[tuple[str, str]] | None]:
    """OpenClaw 2026.10.10 keeps each agent's transcript in the `transcript_events` table of
    `<home>/.openclaw/agents/*/agent/openclaw-agent.sqlite`; a row's event is JSON or zstd-compressed JSON. Returns
    (whether there is such a database, its calls). Calls are None when a database can't be read: a SQLite error, or a
    compressed row with `zstd` missing or failing. A database that reads cleanly with no call gives [].
    The run's home is evidence: each database is copied with its -wal and -shm (a WAL that wasn't checkpointed holds
    the last rows) and only the copy is opened, read-only. On SMART-5's round 1 the counts matched OpenClaw's own
    `meta.toolSummary.calls` on all 13 tasks."""
    import sqlite3
    import tempfile
    dbs = sorted((home / ".openclaw" / "agents").glob("*/agent/openclaw-agent.sqlite"))
    if not dbs:
        return False, None
    found: list[tuple[str, str]] = []
    for db in dbs:
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / db.name
            for suffix in ("", "-wal", "-shm"):
                if Path(f"{db}{suffix}").is_file():
                    shutil.copyfile(f"{db}{suffix}", f"{copy}{suffix}")
            try:
                con = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
                try:
                    rows = con.execute("select event_json, event_zstd from transcript_events "
                                       "order by session_id, seq").fetchall()
                finally:
                    con.close()
            except sqlite3.Error as exc:
                _warn(f"{db} could not be read ({exc}); OpenClaw's trace is unknown")
                return True, None
        for event_json, event_zstd in rows:
            if event_json is None and event_zstd is not None:
                try:
                    unpacked = subprocess.run(["zstd", "-dc"], input=event_zstd, capture_output=True, check=True)
                except (OSError, subprocess.CalledProcessError) as exc:
                    _warn(f"a compressed row of {db} could not be unpacked ({exc}); OpenClaw's trace is unknown")
                    return True, None
                event_json = unpacked.stdout.decode("utf-8", errors="ignore")
            try:
                found += _calls_in(json.loads(event_json or ""))
            except ValueError:
                continue
    return True, found


def openclaw_tool_calls(home: Path, stdout: str) -> list[tuple[str, str]] | None:
    """OpenClaw's tool calls: from its agent database (2026.10.10), else its session transcripts under
    `<home>/.openclaw` (`*.jsonl`, older versions), else the `--json` result on stdout. [] when a transcript is there
    and holds no call; None when there is none, or it can't be read. The `--json` result is no transcript (2026.10.10's
    holds no call blocks at all), so it gives calls or None, never []."""
    if (home / ".openclaw").is_dir():
        has_db, calls = _openclaw_db_calls(home)
        if has_db:
            return calls
        sessions = sorted((home / ".openclaw").rglob("*.jsonl"))
        if sessions:
            found: list[tuple[str, str]] = []
            for path in sessions:
                for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                    try:
                        found += _calls_in(json.loads(line))
                    except ValueError:
                        continue
            return found
    try:
        return _calls_in(json.loads(stdout[stdout.index("{"):])) or None
    except ValueError:
        return None


# ---------------------------------------------------------------- reading results

def graded(doc: dict) -> dict[int, dict]:
    items = {p["id"]: p for p in load_prompts()}
    who = doc.get("entrant", "arslan")
    return {r["id"]: grade(items[r["id"]], r.get("reply", ""),
                           None if r.get("tools") is None else [tuple(t) for t in r["tools"]], who)
            for r in doc["replies"] if r["id"] in items}


def compare(before: dict, after: dict) -> dict:
    """Two rounds of one entrant (before and after SMART-1..4)."""
    b, a = graded(before), graded(after)
    ids = sorted(set(b) & set(a))
    return {"tasks": {i: {"before": b[i], "after": a[i]} for i in ids},
            "before_pass": sum(b[i]["pass"] for i in ids), "after_pass": sum(a[i]["pass"] for i in ids),
            "worse": [i for i in ids if b[i]["pass"] and not a[i]["pass"]],
            "better": [i for i in ids if a[i]["pass"] and not b[i]["pass"]]}


def dimension_scores(grades: dict[int, dict]) -> dict[str, dict]:
    """Per dimension: how many judged checks passed, of how many."""
    out = {}
    for dim, keys in DIMENSIONS.items():
        judged = [g[k] for g in grades.values() for k in keys if g.get(k) is not None]
        out[dim] = {"passed": sum(judged), "judged": len(judged)}
    return out


def gate(arslan: dict, other: dict) -> dict:
    """The card's gate: Arslan at least matches the other entrant on every dimension, over the tasks both ran."""
    a, o = graded(arslan), graded(other)
    ids = set(a) & set(o)
    sa = dimension_scores({i: a[i] for i in ids})
    so = dimension_scores({i: o[i] for i in ids})
    behind = [d for d in DIMENSIONS if sa[d]["passed"] < so[d]["passed"]]
    return {"arslan": sa, "other": so, "behind": behind, "pass": not behind}


# ---------------------------------------------------------------- running (model calls; never in tests)

def run_label(label: str, pid: int, round_: str = "", who: str = "arslan") -> str:
    return f"{who}-SMART{pid:02d}-{label}" + (f"-{round_}" if round_ else "")


def run_prompt(item: dict, label: str, model: str, who: str = "arslan") -> dict:
    name = run_label(label, item["id"], runner.ROUND, who)
    run = runner.ROOT / "runs" / name
    shutil.rmtree(run, ignore_errors=True)
    run.mkdir(parents=True)
    if item.get("needs_fixture"):
        fixture_smart.prepare_run(run)
    started = time.time()
    if who == "arslan":
        home = fixture_smart.prepare_home if item.get("needs_home") else None
        with runner.fresh_instance(name, "arslan", prepare_home=home):
            cmd, env = runner.command("arslan", name, run, item["prompt"], "", model=model)
            rc = runner._run(cmd, env, run)
            ended = time.time()
            end = runner.driver_out("arslan", run).get("end")
            reply = runner.reply_text("arslan", run)
            settled = runner.settle(name, started, ended)
        tools = tool_calls(Path(f"{run}.frames.jsonl"))
    else:
        cmd, env = runner.command(who, name, run, item["prompt"], runner.sandbox_profile(), model=model)
        if item.get("needs_home"):
            fixture_smart.prepare_home(Path(env["HOME"]))
        rc = runner._run(cmd, env, run)
        ended = time.time()
        end, reply = None, runner.reply_text(who, run)
        settled = runner.settle(name, started, ended)
        out = Path(f"{run}.stdout")
        tools = openclaw_tool_calls(Path(env["HOME"]), out.read_text(encoding="utf-8", errors="ignore")
                                    if out.exists() else "")
    return {"id": item["id"], "pattern": item["pattern"], "prompt": item["prompt"], "reply": reply,
            "tools": tools, "end": end, "rc": rc, "wall_s": round(ended - started),
            "usage": runner.usage(name, started), "settled_s": settled, "run": name}


def run_all(who: str, label: str, repo: Path | None, out_dir: Path, model: str) -> Path:
    if not runner.ROUND:
        raise SystemExit("set BENCH_ROUND (one per round and model; labels must not be reused)")
    if who == "arslan":
        repo = repo.resolve()
        sty_read.preflight(repo, model)
        os.environ["BENCH_REPO"] = str(repo)
    elif not (runner.ROOT / "pkgs/openclaw/node_modules/.bin/openclaw").exists():
        raise SystemExit("OpenClaw isn't installed under BENCH_ROOT: run install_entrants.sh first")
    (runner.ROOT / "tmp").mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{who}-{label}.json"
    doc = {"entrant": who, "label": label, "repo": str(repo) if repo else None,
           "head": sty_read.git_head(repo) if repo else None, "model": model, "round": runner.ROUND,
           "prompts_sha": sty_read.prompts_digest(PROMPTS), "replies": []}
    for item in load_prompts():
        doc["replies"].append(run_prompt(item, label, model, who))
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def main(argv: list[str]) -> None:
    ap = argparse.ArgumentParser(prog="smart_bench")
    ap.add_argument("--entrant", choices=ENTRANTS, default="arslan")
    ap.add_argument("--label", choices=sty_read.LABELS)
    ap.add_argument("--repo", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--model", default=runner.MODEL)
    ap.add_argument("--grade", type=Path)
    ap.add_argument("--compare", nargs=2, type=Path)
    ap.add_argument("--gate", nargs=2, type=Path, metavar=("ARSLAN", "OTHER"))
    a = ap.parse_args(argv)

    def load(p: Path) -> dict:
        return json.loads(p.read_text(encoding="utf-8"))

    if a.grade:
        print(json.dumps(graded(load(a.grade)), ensure_ascii=False, indent=1))
    elif a.compare:
        print(json.dumps(compare(*map(load, a.compare)), ensure_ascii=False, indent=1))
    elif a.gate:
        print(json.dumps(gate(*map(load, a.gate)), ensure_ascii=False, indent=1))
    elif a.label and a.out and (a.repo or a.entrant != "arslan"):
        print(run_all(a.entrant, a.label, a.repo, a.out, a.model))
    else:
        ap.error("--entrant/--label/--out (and --repo for Arslan) to run, --grade, --compare or --gate")


if __name__ == "__main__":
    main(sys.argv[1:])
