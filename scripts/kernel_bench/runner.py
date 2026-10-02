"""Kernel bench runner: tasks x entrants x repeats, each run in a fresh folder.

    python -m scripts.kernel_bench.runner --tasks T3,T5 --entrants arslan,hermes --repeats 3

Every entrant talks to the metering proxy (scripts/kernel_bench/meter.py) under a label
`<entrant>-<task>-r<n>`, so each run's cost is exact and capped. Entrants other than
Arslan run inside a macOS sandbox that can only write under BENCH_ROOT and cannot read
the user's real agent configs, SSH keys or keychains (DeepSeek Harness sandboxes its own
shell and cannot nest, so it runs without ours; the T5 sentinel still checks it).

Environment:
  BENCH_ROOT   work folder (default /tmp/arslan-kernel-bench); holds homes, runs, pkgs, node24
  BENCH_PROXY  metering proxy base (default http://127.0.0.1:8900/c)
  BENCH_MODEL  default deepseek-v4-pro
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
from pathlib import Path

from scripts.kernel_bench import check_t1, check_t2, check_t3, check_t4, check_t5, check_t6

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("BENCH_ROOT", "/tmp/arslan-kernel-bench")).resolve()
PROXY = os.environ.get("BENCH_PROXY", "http://127.0.0.1:8900/c")
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
}
# Recorded without running (no spend): capabilities an entrant does not have.
# Arslan's browser is isolated by design (throwaway profile, public-internet
# proxy, no loopback: server/services/managed_browser.py), so it cannot use a
# page the user logged into; it has no phone/messaging channel.
UNSUPPORTED = {"arslan": {"T4", "T4x", "T6"}, "arslan-legacy": {"T4", "T4x", "T6"}}
T4_CHANGE_AFTER_S = 60
# T1's Reminders list is named after the run label; labels repeat across rounds, and a
# list left over from an earlier round would be read as this run's (BENCH_ROUND keeps them apart).
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


def command(who: str, label: str, run: Path, prompt: str, sb: str) -> tuple[list, dict]:
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
    if who in ("arslan", "arslan-legacy"):
        pf = Path(f"{run}.prompt")
        pf.write_text(prompt)
        api = ARSLAN_API if who == "arslan" else ARSLAN_LEGACY_API
        return [sys.executable, "-m", "scripts.kernel_bench.arslan_driver", api, str(run), str(pf),
                f"{PROXY}/{label}", MODEL], dict(os.environ)
    raise SystemExit(f"unknown entrant {who}")


def reply_text(who: str, run: Path) -> str:
    out = Path(f"{run}.stdout")
    text = out.read_text(encoding="utf-8", errors="ignore") if out.exists() else ""
    if who in ("arslan", "arslan-legacy"):
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


def usage(label: str) -> dict:
    log = ROOT / "usage.jsonl"
    rows = [json.loads(line) for line in log.open()] if log.exists() else []
    mine = [r for r in rows if r["cand"] == label and r["model"] != "?"]
    if not mine:
        return {"model_calls": 0, "usd_peak": 0.0, "span_s": 0.0}
    start = min(r["t"] - r["secs"] for r in mine)
    end = max(r["t"] for r in mine)
    return {"model_calls": len(mine), "usd_peak": round(sum(r["usd_peak"] for r in mine), 5),
            "span_s": round(end - start, 1), "out_tokens": sum(r["out"] for r in mine),
            "cache_hit_tokens": sum(r["hit"] for r in mine), "cache_miss_tokens": sum(r["miss"] for r in mine)}


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


def run_one(task: str, who: str, n: int, prompts: dict, sb: str, manual_login: bool = False) -> dict:
    label = f"{who}-{task}-r{n}"
    run = ROOT / "runs" / label
    shutil.rmtree(run, ignore_errors=True)
    run.mkdir(parents=True)
    if task in UNSUPPORTED.get(who, set()):
        record = {"run": label, "task": task, "entrant": who, "repeat": n, "model": MODEL, "rc": None,
                  "wall_s": 0, "prompt": None, "usage": usage(label), "passed": False,
                  "check": check_t6.unsupported(who) if task == "T6" else
                  {"score": 0, "unsupported": True, "note": f"{who} cannot use a page the user logged into"}}
        with open(ROOT / "results.jsonl", "a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record
    if task == "T6":
        raise SystemExit(f"T6 for {who}: the gateway launch (fake Telegram base_url) is not verified yet")
    ctx: dict = {}
    if task == "T5":
        subprocess.run([sys.executable, str(HERE / "fixture_t5.py"), str(run)], check=True, capture_output=True)
    if task == "T1":
        ctx["list"] = f"对比测试-{label}" + (f"-{ROUND}" if ROUND else "")
    if task in ("T4", "T4x"):
        _t4_setup(task, who, ctx, manual_login)
    prompt = prompts[task].format(dir=run, list=ctx.get("list", ""), url=ctx["site"].url if "site" in ctx else "")
    cmd, e = command(who, label, run, prompt, sb)
    started = time.time()
    with open(f"{run}.stdout", "w") as out, open(f"{run}.stderr", "w") as err:
        try:
            rc = subprocess.run(cmd, cwd=run, env=e, stdout=out, stderr=err, timeout=TIMEOUT).returncode
        except subprocess.TimeoutExpired:
            rc = "timeout"
    if "timer" in ctx:
        ctx["timer"].cancel()
    reply = reply_text(who, run)
    try:
        verdict = CHECKS[task](str(run), reply, ctx)
    finally:
        if "site" in ctx:
            ctx["site"].stop()
    record = {"run": label, "task": task, "entrant": who, "repeat": n, "model": MODEL, "rc": rc,
              "wall_s": round(time.time() - started), "prompt": prompt,
              "check": verdict, "usage": usage(label),
              "artifacts": {"stdout": f"{run}.stdout", "stderr": f"{run}.stderr", "folder": str(run)},
              "reply_tail": reply[-1500:]}
    record["passed"] = record["check"].get("score") == 3
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
    args = ap.parse_args()
    (ROOT / "tmp").mkdir(parents=True, exist_ok=True)
    prompts = json.loads((HERE / "prompts.json").read_text())
    sb = sandbox_profile()
    for n in range(1, args.repeats + 1):            # interleave entrants within each repeat
        for task in args.tasks.split(","):
            for who in args.entrants.split(","):
                rec = run_one(task, who, n, prompts, sb, args.manual_login)
                print(json.dumps({k: rec[k] for k in ("run", "passed", "rc")} | {"score": rec["check"].get("score"),
                      "usd_peak": rec["usage"]["usd_peak"], "span_s": rec["usage"]["span_s"]}), flush=True)


if __name__ == "__main__":
    main()
