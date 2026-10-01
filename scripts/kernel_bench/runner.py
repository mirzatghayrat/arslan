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
import time
from pathlib import Path

from scripts.kernel_bench import check_t3, check_t5

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("BENCH_ROOT", "/tmp/arslan-kernel-bench")).resolve()
PROXY = os.environ.get("BENCH_PROXY", "http://127.0.0.1:8900/c")
MODEL = os.environ.get("BENCH_MODEL", "deepseek-v4-pro")
ARSLAN_API = os.environ.get("ARSLAN_API", "http://127.0.0.1:8762/api/v1")
HERMES = os.environ.get("HERMES_BIN", str(Path.home() / ".local/bin/hermes"))
BASE_PATH = "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin"
TIMEOUT = 15 * 60
CHECKS = {"T3": lambda run, reply: check_t3.check(run), "T5": lambda run, reply: check_t5.check(run, reply)}


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
    if who == "arslan":
        pf = Path(f"{run}.prompt")
        pf.write_text(prompt)
        return [sys.executable, "-m", "scripts.kernel_bench.arslan_driver", ARSLAN_API, str(run), str(pf),
                f"{PROXY}/{label}", MODEL], dict(os.environ)
    raise SystemExit(f"unknown entrant {who}")


def reply_text(who: str, run: Path) -> str:
    out = Path(f"{run}.stdout")
    text = out.read_text(encoding="utf-8", errors="ignore") if out.exists() else ""
    if who == "arslan":
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


def run_one(task: str, who: str, n: int, prompts: dict, sb: str) -> dict:
    label = f"{who}-{task}-r{n}"
    run = ROOT / "runs" / label
    shutil.rmtree(run, ignore_errors=True)
    run.mkdir(parents=True)
    if task == "T5":
        subprocess.run([sys.executable, str(HERE / "fixture_t5.py"), str(run)], check=True, capture_output=True)
    prompt = prompts[task].format(dir=run)
    cmd, e = command(who, label, run, prompt, sb)
    started = time.time()
    with open(f"{run}.stdout", "w") as out, open(f"{run}.stderr", "w") as err:
        try:
            rc = subprocess.run(cmd, cwd=run, env=e, stdout=out, stderr=err, timeout=TIMEOUT).returncode
        except subprocess.TimeoutExpired:
            rc = "timeout"
    reply = reply_text(who, run)
    record = {"run": label, "task": task, "entrant": who, "repeat": n, "model": MODEL, "rc": rc,
              "wall_s": round(time.time() - started), "prompt": prompt,
              "check": CHECKS[task](str(run), reply), "usage": usage(label),
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
    args = ap.parse_args()
    (ROOT / "tmp").mkdir(parents=True, exist_ok=True)
    prompts = json.loads((HERE / "prompts.json").read_text())
    sb = sandbox_profile()
    for n in range(1, args.repeats + 1):            # interleave entrants within each repeat
        for task in args.tasks.split(","):
            for who in args.entrants.split(","):
                rec = run_one(task, who, n, prompts, sb)
                print(json.dumps({k: rec[k] for k in ("run", "passed", "rc")} | {"score": rec["check"].get("score"),
                      "usd_peak": rec["usage"]["usd_peak"], "span_s": rec["usage"]["span_s"]}), flush=True)


if __name__ == "__main__":
    main()
