"""Kernel bench runner: tasks x entrants x repeats, each run in a fresh folder.

    python -m scripts.kernel_bench.runner --tasks T3,T5 --entrants arslan,hermes --repeats 3
    python -m scripts.kernel_bench.runner --tasks T5 --entrants arslan,claude-code \
        --models arslan=claude-sonnet-5-5,claude-code=claude-sonnet-5-5

Every entrant talks to the metering proxy (scripts/kernel_bench/meter.py) under a label
`<entrant>-<task>-r<n>`, so each run's cost is exact and capped. Entrants other than
Arslan run inside a macOS sandbox that can only write under BENCH_ROOT and cannot read
the user's real agent configs, SSH keys or keychains (DeepSeek Harness sandboxes its own
shell and cannot nest, so it runs without ours; the T5 sentinel still checks it).

Environment:
  BENCH_ROOT   work folder (default /tmp/arslan-kernel-bench); holds homes, runs, pkgs, node24
  BENCH_PROXY  metering proxy base (default http://127.0.0.1:8900/c), DeepSeek upstream
  BENCH_ANTHROPIC_PROXY  second metering proxy for Claude models (default http://127.0.0.1:8901/c)
  BENCH_MODEL  default deepseek-v4-pro; --models sets one per entrant
  ARSLAN_API   Arslan test instance (default http://127.0.0.1:8762/api/v1)
  HERMES_BIN   default ~/.local/bin/hermes
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from scripts.kernel_bench import (check_t1, check_t2, check_t3, check_t4, check_t5, check_t6, check_t7,
                                  check_t8, check_t9, check_t10, check_t11, check_t12)
from scripts.kernel_bench.arslan_driver import snapshot

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("BENCH_ROOT", "/tmp/arslan-kernel-bench")).resolve()
PROXY = os.environ.get("BENCH_PROXY", "http://127.0.0.1:8900/c")
ANTHROPIC_PROXY = os.environ.get("BENCH_ANTHROPIC_PROXY", "http://127.0.0.1:8901/c")
MODEL = os.environ.get("BENCH_MODEL", "deepseek-v4-pro")
ARSLAN_API = os.environ.get("ARSLAN_API", "http://127.0.0.1:8762/api/v1")
# Paired attribution: a second Arslan instance started with ARSLAN_TOOL_PROTOCOL=legacy.
ARSLAN_LEGACY_API = os.environ.get("ARSLAN_LEGACY_API", "http://127.0.0.1:8763/api/v1")
HERMES = os.environ.get("HERMES_BIN", str(Path.home() / ".local/bin/hermes"))
BASE_PATH = "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin"
TIMEOUT = 15 * 60
CHECKS = {
    "T1": lambda run, reply, ctx: check_t1.check(ctx["list"], reply),
    "T2": lambda run, reply, ctx: check_t2.check(run, reply),
    "T3": lambda run, reply, ctx: check_t3.check(run),
    "T4": lambda run, reply, ctx: check_t4.check(reply, ctx["site"].log(), mode="change",
                                                 initial=ctx["initial"], change=ctx.get("change")),
    "T4x": lambda run, reply, ctx: check_t4.check(reply, ctx["site"].log(), mode="expired",
                                                  initial=ctx["initial"]),
    "T5": lambda run, reply, ctx: check_t5.check(run, reply),
    # 0.1.62 round (M1b): local tasks, no web pages.
    # What a fixture returns (T7's seed and chain length, T10's cause line) stays here in ctx,
    # never in the agent's folder (③Hands' review of #191).
    "T7": lambda run, reply, ctx: check_t7.check(run, ctx["fixture"]),
    "T8": lambda run, reply, ctx: check_t8.check(run),
    "T9": lambda run, reply, ctx: check_t9.check(run),
    "T10": lambda run, reply, ctx: check_t10.check(run, reply, ctx["fixture"]),
    "T11": lambda run, reply, ctx: check_t11.check(run, declined=ctx.get("declined", 0)),
    # The Hands trace lives in the instance's data folder (start_arslan.sh: $BENCH_ROOT/data/<name>).
    "T12": lambda run, reply, ctx: check_t12.check(reply, os.environ.get("BENCH_ARSLAN_DATA"), ctx["started"]),
}
FIXTURES = {"T7": check_t7.fixture, "T8": check_t8.fixture, "T9": check_t9.fixture,
            "T10": check_t10.fixture, "T11": check_t11.fixture}
# Recorded without running (no spend): capabilities an entrant does not have.
# Arslan's browser is isolated by design (throwaway profile, public-internet
# proxy, no loopback: server/services/managed_browser.py), so it cannot use a
# page the user logged into; it has no phone/messaging channel.
UNSUPPORTED = {"arslan": {"T4", "T4x", "T6"}, "arslan-legacy": {"T4", "T4x", "T6"},
               # No browser of its own and no phone channel; no Hands (T12 is a Hands task).
               "claude-code": {"T4", "T4x", "T6", "T12"},
               "hermes": {"T12"}}
ARSLAN = ("arslan", "arslan-legacy")
# Entrants that can take a task of several turns: Arslan keeps one conversation, Claude
# Code resumes its session. The others are recorded as unsupported for such tasks.
MULTI_TURN = {"arslan", "arslan-legacy", "claude-code"}
CLAUDE_ON = {"arslan", "arslan-legacy", "claude-code"}       # entrants that can run on a Claude model
T4_CHANGE_AFTER_S = 60
# BENCH_ROUND goes into the run label. The meter's per-run cap counts a label over the proxy's
# whole life and run folders are named by label, so a label reused in a later round starts near
# the cap and overwrites the earlier folder (K1's after-runs, 2026-10-19: arslan-T2-r1 was
# refused with 402 at its first call, the baseline and K1's before-run had spent $1.03 on it).
# It also keeps T1's Reminders lists apart: a list left from an earlier round would be read as
# this run's. One round per model when two models share a round's tasks.
ROUND = os.environ.get("BENCH_ROUND", "")


def sandbox_profile() -> str:
    path = ROOT / "sandbox.sb"
    text = (HERE / "sandbox.sb.template").read_text().replace("{ROOT}", str(ROOT)).replace("{HOME}", str(Path.home()))
    path.write_text(text)
    return str(path)


def env(extra: dict, node: bool = False) -> dict:
    e = {"PATH": (f"{ROOT}/node24/bin:" if node else "") + BASE_PATH, "TMPDIR": str(ROOT / "tmp"),
         "TERM": "dumb", "LANG": "en_US.UTF-8"}
    e.update(extra)
    return e


def parse_models(spec: str) -> dict:
    """`arslan=claude-sonnet-5-5,claude-code=claude-sonnet-5-5` -> {entrant: model}."""
    return dict(item.split("=", 1) for item in spec.split(",") if "=" in item) if spec else {}


def model_for(who: str, models: dict) -> str:
    return models.get(who, MODEL)


def is_claude(model: str) -> bool:
    return model.startswith("claude-")


def proxy_for(model: str) -> str:
    return ANTHROPIC_PROXY if is_claude(model) else PROXY


# Bumped when the pass rule changes; report.py keeps rows judged by different rules apart.
JUDGE_VERSION = 2


def judge(check: dict, end: str | None, who: str = "arslan") -> bool:
    """A run passes when the checker gives 3 and, for Arslan, the run ended cleanly ("done"):
    a task left on "needs you", failed, cancelled, timed out, a background job that ended
    blocked or out of budget, or a driver that never reported (killed, crashed) is not a pass,
    whatever the files say. Other entrants report no end; their checker score decides."""
    if check.get("score") != 3:
        return False
    return end == "done" if who in ARSLAN else True


def command(who: str, label: str, run: Path, prompt, sb: str, *, model: str = MODEL, turn: int = 0,
            session: str | None = None, decline: dict | None = None) -> tuple[list, dict]:
    """The command for one entrant. `prompt` is a string, or (Arslan only) a list of turns;
    Claude Code gets one turn at a time (`turn`, resuming `session` after the first)."""
    if is_claude(model) and who not in CLAUDE_ON:
        raise SystemExit(f"{who} runs on DeepSeek only; {model} is for {sorted(CLAUDE_ON)}")
    home = ROOT / "home" / who
    home.mkdir(parents=True, exist_ok=True)
    jail = ["sandbox-exec", "-f", sb]
    if who == "hermes":
        return jail + [HERMES, "-z", prompt, "--provider", "deepseek", "-m", MODEL, "--ignore-user-config",
                       "--usage-file", f"{run}.hermes-usage.json"], env(
            {"HOME": str(home), "HERMES_HOME": f"{home}/.hermes", "DEEPSEEK_API_KEY": "bench-dummy",
             "DEEPSEEK_BASE_URL": f"{PROXY}/{label}/v1"})
    if who == "goose":
        return jail + [str(ROOT / "pkgs/goose/goose"), "run", "--no-session", "-t", prompt, "--max-turns", "60"], env(
            {"HOME": str(home), "GOOSE_PROVIDER": "openai", "GOOSE_MODEL": MODEL, "OPENAI_API_KEY": "bench-dummy",
             "OPENAI_HOST": f"{PROXY}/{label}", "OPENAI_BASE_PATH": "v1/chat/completions", "GOOSE_DISABLE_KEYRING": "1"})
    if who == "dsh":
        return [str(ROOT / "pkgs/dsh/node_modules/.bin/dsh"), "headless", prompt], env(
            {"HOME": str(home), "DSH_HOME": f"{home}/.dsh", "DEEPSEEK_API_KEY": "bench-dummy",
             "DEEPSEEK_BASE_URL": f"{PROXY}/{label}/anthropic/v1",
             "DEEPSEEK_SEARCH_BASE_URL": f"{PROXY}/{label}/anthropic/v1"}, node=True)
    if who == "openclaw":
        home = ROOT / "home" / f"openclaw-{label}-{int(time.time())}"   # it remembers workspaces
        (home / ".openclaw").mkdir(parents=True, exist_ok=True)
        cfg = {"agents": {"defaults": {"model": {"primary": f"bench/{MODEL}"}, "workspace": str(run)}},
               "models": {"mode": "merge", "providers": {"bench": {
                   "baseUrl": f"{PROXY}/{label}/v1", "apiKey": "bench-dummy", "api": "openai-completions",
                   "models": [{"id": MODEL, "name": MODEL}]}}}}
        (home / ".openclaw/openclaw.json").write_text(json.dumps(cfg, indent=1))
        return jail + [str(ROOT / "pkgs/openclaw/node_modules/.bin/openclaw"), "agent", "--local", "-m", prompt,
                       "--json", "--timeout", str(TIMEOUT - 30)], env({"HOME": str(home)}, node=True)
    if who == "claude-code":
        # --bare: no hooks, no CLAUDE.md discovery, no keychain; the key is only the dummy one
        # (the metering proxy swaps in the real key). HOME is the bench's, so the user's
        # ~/.claude is never read; no MCP servers. Writes are limited by the sandbox, so
        # permissions are skipped (flags as of 2.1.96, `claude --help`).
        cmd = jail + [str(ROOT / "pkgs/claude-code/node_modules/.bin/claude"), "--bare", "-p", prompt,
                      "--output-format", "json", "--model", model, "--dangerously-skip-permissions",
                      "--strict-mcp-config", "--mcp-config", '{"mcpServers": {}}']
        cmd += ["--resume", session] if turn else ["--session-id", session or str(uuid.uuid4())]
        # Claude models go to the Anthropic proxy; a DeepSeek model through the DeepSeek
        # proxy's Anthropic-compatible path (the one DeepSeek Harness uses).
        base = f"{ANTHROPIC_PROXY}/{label}" if is_claude(model) else f"{PROXY}/{label}/anthropic"
        return cmd, env({"HOME": str(home), "ANTHROPIC_BASE_URL": base,
                         "ANTHROPIC_API_KEY": "bench-dummy", "DISABLE_AUTOUPDATER": "1",
                         "DISABLE_TELEMETRY": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}, node=True)
    if who in ARSLAN:
        pf = Path(f"{run}.prompt")
        pf.write_text(json.dumps(prompt, ensure_ascii=False) if isinstance(prompt, list) else prompt)
        api = ARSLAN_API if who == "arslan" else ARSLAN_LEGACY_API
        claude = is_claude(model)
        base = f"{ANTHROPIC_PROXY}/{label}/v1" if claude else f"{PROXY}/{label}"
        cmd = [sys.executable, "-m", "scripts.kernel_bench.arslan_driver", api, str(run), str(pf), base, model,
               "--provider", "anthropic" if claude else "openai"]
        for rule in (decline or {}).get("rules", ()):
            cmd += ["--decline-rule", rule]
        if decline and decline.get("note"):
            cmd += ["--decline-note", decline["note"]]
        # The driver runs in the task folder; without this it is imported from wherever the
        # environment's editable install points, which may be another checkout on another branch.
        return cmd, dict(os.environ, PYTHONPATH=str(HERE.parents[1]))
    raise SystemExit(f"unknown entrant {who}")


def entrant_version(who: str) -> str | None:
    """The installed version, recorded with each result (flags change between versions)."""
    if who != "claude-code":
        return None
    try:
        return subprocess.run([str(ROOT / "pkgs/claude-code/node_modules/.bin/claude"), "--version"],
                              capture_output=True, text=True, timeout=30, env=env({}, node=True)).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None


def reply_text(who: str, run: Path) -> str:
    out = Path(f"{run}.stdout")
    text = out.read_text(encoding="utf-8", errors="ignore") if out.exists() else ""
    if who == "claude-code":                    # one JSON result per turn, appended; the last is the answer
        for line in reversed(text.strip().splitlines()):
            try:
                return json.loads(line).get("result", "") or ""
            except (json.JSONDecodeError, AttributeError):
                continue
        return text
    if who in ARSLAN:
        try:
            return json.loads(text.strip().splitlines()[-1]).get("final", "")
        except Exception:
            return text
    if who == "openclaw":
        try:
            data = json.loads(text[text.index("{"):])
            return data.get("result", {}).get("terminalReply", {}).get("text", "") or text
        except Exception:
            return text
    return text


def _usage_rows() -> list[dict]:
    """usage.jsonl as rows; a line the meter is still writing is skipped, not fatal."""
    log, rows = ROOT / "usage.jsonl", []
    for line in (log.open() if log.exists() else ()):
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def usage(label: str, since: float = 0.0) -> dict:
    """This run's model calls: its label, from when it started (the same label comes back in
    later rounds and on other models; usage.jsonl keeps them all)."""
    rows = _usage_rows()
    mine = [r for r in rows if r["cand"] == label and r["model"] != "?" and r["t"] >= since]
    if not mine:
        return {"model_calls": 0, "usd_peak": 0.0, "span_s": 0.0}
    start = min(r["t"] - r["secs"] for r in mine)
    end = max(r["t"] for r in mine)
    return {"model_calls": len(mine), "usd_peak": round(sum(r["usd_peak"] for r in mine), 5),
            "span_s": round(end - start, 1), "out_tokens": sum(r["out"] for r in mine),
            "cache_hit_tokens": sum(r["hit"] for r in mine), "cache_miss_tokens": sum(r["miss"] for r in mine)}


def settle(label: str, since: float, ended: float = 0.0, quiet_s: float = 20.0, max_s: float = 120.0) -> float:
    """Wait until `quiet_s` has passed since the later of the driver's exit (`ended`) and this
    run's last model call (at most `max_s`), and return the seconds waited. Arslan makes a few
    calls right after a turn ends (memory, learning); those are part of what the run costs.
    The meter writes a row only when a call finishes, so a call still running when the driver
    exits is invisible until then: quiet is counted from the exit too (③Hands' review), long
    enough for a slow after-turn call to land. Calls much later (idle-time work) are not waited
    for; the round report shows them apart."""
    waited = 0.0
    while waited < max_s:
        rows = _usage_rows()
        last = max((r["t"] for r in rows if r["cand"] == label and r["t"] >= since), default=0.0)
        if time.time() - max(last, ended) >= quiet_s:
            break
        time.sleep(1.0)
        waited += 1.0
    return waited


def _t4_setup(task: str, who: str, ctx: dict, manual_login: bool) -> None:
    """Start the local site and have the human log in, in this entrant's own
    browser. The password goes to this terminal only, never into the run folder."""
    if not manual_login:
        raise SystemExit("T4 needs a person to log in once per entrant: rerun with --manual-login")
    site = check_t4_site().start()
    ctx.update(site=site, initial=list(site.items))
    print(f"\n[T4] Log in as {who} at {site.url}  user={site.username}  password={site.password}", flush=True)
    input("[T4] Press Enter once you are logged in in that entrant's browser... ")
    if not any(a["ok"] and a["phase"] == "human" for a in site.log()["login_attempts"]):
        raise SystemExit("[T4] no successful human login recorded on the test site")
    if task == "T4x":
        site.expire_sessions()
    site.set_phase("agent")
    if task == "T4":
        def change():
            ctx["change"] = site.change()
        ctx["timer"] = threading.Timer(T4_CHANGE_AFTER_S, change)
        ctx["timer"].start()


def check_t4_site():
    from scripts.kernel_bench.site_t4 import Site
    return Site()


# Tasks whose stand-in person declines a card with a sentence: {task: {"rules": [...], "note": "..."}}.
# Only Arslan's driver can answer a card that way; other entrants are recorded as unsupported.
DECLINES: dict = {"T11": {"rules": [r"delete|\brm\b|\brmdir\b|unlink"], "note": check_t11.NOTE}}   # patterns on the rule


def driver_out(who: str, run: Path) -> dict:
    """Arslan's driver summary (its last stdout line): end, approvals, declined, ...; {} for
    other entrants or when the driver never reported."""
    if who not in ARSLAN:
        return {}
    out = Path(f"{run}.stdout")
    try:
        data = json.loads(out.read_text(encoding="utf-8").strip().splitlines()[-1])
        return data if isinstance(data, dict) else {}
    except (OSError, IndexError, json.JSONDecodeError):
        return {}


def driver_end(who: str, run: Path) -> str | None:
    """How Arslan's run ended (`done`, `task_waiting_user`, `timeout`, ...); None for others."""
    return driver_out(who, run).get("end")


def _unsupported(task: str, who: str, n: int, label: str, model: str, why: str) -> dict:
    record = {"run": label, "task": task, "entrant": who, "repeat": n, "model": model, "rc": None,
              "wall_s": 0, "prompt": None, "usage": usage(label, time.time()), "passed": False,
              "judge": JUDGE_VERSION,
              "check": check_t6.unsupported(who) if task == "T6" else {"score": 0, "unsupported": True, "note": why}}
    with open(ROOT / "results.jsonl", "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def _run(cmd: list, e: dict, run: Path, mode: str = "w"):
    with open(f"{run}.stdout", mode) as out, open(f"{run}.stderr", mode) as err:
        try:
            return subprocess.run(cmd, cwd=run, env=e, stdout=out, stderr=err, timeout=TIMEOUT).returncode
        except subprocess.TimeoutExpired:
            return "timeout"


def run_one(task: str, who: str, n: int, prompts: dict, sb: str, manual_login: bool = False,
            models: dict | None = None) -> dict:
    label = f"{who}-{task}-r{n}" + (f"-{ROUND}" if ROUND else "")
    run = ROOT / "runs" / label
    model = model_for(who, models or {})
    shutil.rmtree(run, ignore_errors=True)
    for old in run.parent.glob(f"{label}.turn*"):     # snapshots of an earlier round of this label
        shutil.rmtree(old, ignore_errors=True)
    run.mkdir(parents=True)
    raw = prompts.get(task, "")              # unsupported tasks are recorded without a prompt
    turns_raw = raw if isinstance(raw, list) else [raw]
    if task in UNSUPPORTED.get(who, set()):
        return _unsupported(task, who, n, label, model, f"{who} cannot use a page the user logged into")
    if len(turns_raw) > 1 and who not in MULTI_TURN:
        return _unsupported(task, who, n, label, model, f"{who}: several turns in one session not set up")
    if task in DECLINES and who not in ARSLAN:
        return _unsupported(task, who, n, label, model, f"{who}: no way to decline a card with a note")
    if task == "T6":
        raise SystemExit(f"T6 for {who}: the gateway launch (fake Telegram base_url) is not verified yet")
    ctx: dict = {}
    if task == "T5":
        subprocess.run([sys.executable, str(HERE / "fixture_t5.py"), str(run)], check=True, capture_output=True)
    if task == "T12":
        check_t12.fixture_up()
    if task in FIXTURES:
        ctx["fixture"] = FIXTURES[task](str(run))
    if task == "T1":
        # The model is in the name: the same label runs on several models in one round, and a second
        # model's reminders landed in the first model's list (M1B, 2026-10-19: 6 items, scored 0).
        ctx["list"] = f"对比测试-{label}-{model}"
    if task in ("T4", "T4x"):
        _t4_setup(task, who, ctx, manual_login)
    fill = {"dir": run, "list": ctx.get("list", ""), "url": ctx["site"].url if "site" in ctx else ""}
    turns = [t.format(**fill) for t in turns_raw]
    started = time.time()
    ctx["started"] = started
    if who == "claude-code":                       # one process per turn, resuming the same session
        session = str(uuid.uuid4())
        for i, prompt in enumerate(turns):
            cmd, e = command(who, label, run, prompt, sb, model=model, turn=i, session=session)
            rc = _run(cmd, e, run, "w" if i == 0 else "a")
            if i + 1 < len(turns):
                snapshot(str(run), i + 1)
    else:
        prompt = turns if (len(turns) > 1 and who in ARSLAN) else turns[0]
        cmd, e = command(who, label, run, prompt, sb, model=model, decline=DECLINES.get(task))
        rc = _run(cmd, e, run)
    ended = time.time()
    if "timer" in ctx:
        ctx["timer"].cancel()
    reply = reply_text(who, run)
    ctx["declined"] = driver_out(who, run).get("declined", 0)
    try:
        verdict = CHECKS[task](str(run), reply, ctx)
    finally:
        if "site" in ctx:
            ctx["site"].stop()
    end = driver_end(who, run)
    settled = settle(label, started, ended)
    record = {"run": label, "task": task, "entrant": who, "repeat": n, "model": model, "rc": rc,
              "entrant_version": entrant_version(who), "end": end,
              "wall_s": round(time.time() - started), "prompt": turns if len(turns) > 1 else turns[0],
              "check": verdict, "usage": usage(label, started), "settled_s": settled, "judge": JUDGE_VERSION,
              "artifacts": {"stdout": f"{run}.stdout", "stderr": f"{run}.stderr", "folder": str(run)},
              "reply_tail": reply[-1500:]}
    record["passed"] = judge(verdict, end, who)
    Path(f"{run}.record.json").write_text(json.dumps(record, ensure_ascii=False, indent=1))
    with open(ROOT / "results.jsonl", "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--entrants", required=True)
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--manual-login", action="store_true", help="T4: a person logs in once per entrant")
    ap.add_argument("--models", default="", help="per entrant, e.g. arslan=claude-sonnet-5-5,claude-code=claude-sonnet-5-5")
    args = ap.parse_args()
    (ROOT / "tmp").mkdir(parents=True, exist_ok=True)
    prompts = json.loads((HERE / "prompts.json").read_text())
    sb = sandbox_profile()
    for n in range(1, args.repeats + 1):            # interleave entrants within each repeat
        for task in args.tasks.split(","):
            for who in args.entrants.split(","):
                rec = run_one(task, who, n, prompts, sb, args.manual_login, parse_models(args.models))
                print(json.dumps({k: rec[k] for k in ("run", "model", "passed", "rc")} | {"score": rec["check"].get("score"),
                      "usd_peak": rec["usage"]["usd_peak"], "span_s": rec["usage"]["span_s"]}), flush=True)


if __name__ == "__main__":
    main()
