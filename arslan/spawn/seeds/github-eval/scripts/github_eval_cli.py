"""github-eval — evaluate a GitHub repo and match it to a need (read-only).

Credential resolution priority: --token flag > .env file > GITHUB_TOKEN env.
Uses the `gh` CLI; never modifies the target repo.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

DOC = """github-eval — usage:
  github_eval_cli.py doc                 show this help
  github_eval_cli.py eval <owner/repo>   stars/forks/license/activity + a recommendation

Read-only. Uses the `gh` CLI. Honors --token / .env / GITHUB_TOKEN for rate limits.
"""


def resolve_token(cli_value):
    if cli_value:
        return cli_value
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("GITHUB_TOKEN="):
                return line.split("=", 1)[1].strip()
    return os.environ.get("GITHUB_TOKEN")


def _recommend(stars, pushed_days):
    if stars >= 1000 and pushed_days is not None and pushed_days <= 180:
        return "高信任：活跃且广泛采用，可考虑挂载或借鉴（碰钱/副作用工具仍需用户批准）。"
    if stars >= 100:
        return "中等：展示详情，使用前人工审查。"
    return "低信任：星标少或不活跃，谨慎评估并做安全审查。"


def _eval(repo, token):
    env = dict(os.environ)
    if token:
        env["GH_TOKEN"] = token
    try:
        out = subprocess.run(
            ["gh", "api", f"repos/{repo}"],
            capture_output=True, text=True, timeout=30, env=env,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        sys.stderr.write(f"error: 无法调用 gh：{exc}\n")
        return 1
    if out.returncode != 0:
        sys.stderr.write(f"error: gh 失败：{out.stderr.strip()[:200]}\n")
        return 1

    data = json.loads(out.stdout or "{}")
    stars = data.get("stargazers_count", 0)
    license_name = (data.get("license") or {}).get("name") or "无（默认不可商用）"
    pushed = data.get("pushed_at") or ""
    print(f"仓库: {data.get('full_name', repo)}")
    print(f"  stars: {stars}  forks: {data.get('forks_count', 0)}  "
          f"open_issues: {data.get('open_issues_count', 0)}")
    print(f"  license: {license_name}")
    print(f"  最近更新: {pushed}")
    print(f"  描述: {data.get('description') or '（无）'}")
    print(f"建议: {_recommend(stars, None)}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="github_eval_cli.py", add_help=False)
    parser.add_argument("command", nargs="?", default="doc")
    parser.add_argument("repo", nargs="?", default="")
    parser.add_argument("--token", default=None)
    args, _ = parser.parse_known_args(argv)

    if args.command == "doc":
        print(DOC)
        return 0
    if args.command == "eval":
        if not args.repo:
            sys.stderr.write("usage: eval <owner/repo>\n")
            return 1
        return _eval(args.repo, resolve_token(args.token))
    sys.stderr.write(f"unknown command: {args.command}\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
