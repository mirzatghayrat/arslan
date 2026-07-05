"""Deterministic gate for the orchestrator-only run_command tool (spec §组件1).

Pure functions, no IO. TWO independent lines of defence:
  1. binary whitelist — only these executables may ever run.
  2. hard-deny scan over every argv element — shell metacharacters, sudo,
     rm -rf, absolute-path executables — refused regardless of the binary.

argv is a LIST (never a shell string): the executor uses create_subprocess_exec
with *[command, *argv], so no shell parsing ever happens. This module additionally
guarantees no element can smuggle shell syntax that a downstream tool might re-parse.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

# v1 whitelist: high-value, non-code-fetching binaries. Extend HERE to add commands.
ALLOWED_BINARIES = frozenset({"git", "gh", "ffmpeg", "pandoc"})

# Any argv element containing one of these is refused (shell metacharacters that
# would matter if the string were ever re-parsed by a shell).
_SHELL_META = re.compile(r"[|&;<>$`\n\r()]")
# Tokens that are dangerous even as bare argv elements.
_DENY_TOKENS = frozenset({"sudo", "rm"})


def validate(command: str, argv) -> dict:
    """Return {"ok": bool, "reason": str}. Structural + policy check only —
    does NOT execute anything."""
    if not command or not isinstance(command, str):
        return {"ok": False, "reason": "empty command"}
    if command not in ALLOWED_BINARIES:
        return {"ok": False, "reason": f"binary '{command}' not allowed (v1 whitelist: "
                f"{', '.join(sorted(ALLOWED_BINARIES))})"}
    if not isinstance(argv, list):
        return {"ok": False, "reason": "argv must be a list of strings"}
    for el in argv:
        if not isinstance(el, str):
            return {"ok": False, "reason": "every argv element must be a string"}
        if _SHELL_META.search(el):
            return {"ok": False, "reason": f"argv element contains shell metacharacters: {el!r}"}
        if el in _DENY_TOKENS:
            return {"ok": False, "reason": f"denied token in argv: {el!r}"}
        if el.startswith("/") and _looks_executable(el):
            return {"ok": False, "reason": f"absolute-path executable denied: {el!r}"}
    for el in argv:
        if el.startswith("-") and set(el[1:]) >= {"r", "f"}:
            return {"ok": False, "reason": "destructive rm pattern denied"}
    return {"ok": True, "reason": ""}


def _looks_executable(path: str) -> bool:
    """Absolute paths to common shells/interpreters are the real risk; a plain
    /tmp/data.mp4 file argument is fine. Refuse paths whose basename is a known
    interpreter/shell."""
    base = path.rsplit("/", 1)[-1]
    return base in {"sh", "bash", "zsh", "python", "python3", "node", "perl", "ruby", "env"}


# Deterministic risk classification (spec §组件1). Borrowed from OpenHands'
# SecurityAnalyzer tiers, but only the pattern layer — no LLM. Per-binary lookup on
# the first subcommand; fail-safe = unknown shapes are never LOW.
_GIT_LOW = frozenset({"status", "log", "diff", "show", "branch", "remote", "ls-files",
                      "rev-parse", "describe"})
_GIT_HIGH = frozenset({"push", "pull", "fetch", "clone", "submodule"})
# `config` is MEDIUM (not LOW): git config core.sshCommand/core.pager/alias.x=!cmd
# writes stored config that makes git execute an arbitrary program later —
# stored-command-injection. Must always show a confirmation card under ask_risky.
_GIT_MEDIUM = frozenset({"add", "commit", "checkout", "init", "restore", "reset", "rm",
                         "mv", "tag", "stash", "merge", "rebase", "apply", "clean", "config"})


def classify(command: str, argv) -> str:
    """Return "LOW" | "MEDIUM" | "HIGH". Deterministic; no IO, no LLM.

    The subcommand's risk always wins: a HIGH/MEDIUM git subcommand is never
    downgraded to LOW by a coincidental verbose flag (e.g. `git push -v`)."""
    args = [a for a in (argv if isinstance(argv, list) else []) if isinstance(a, str)]
    if command == "gh":
        return "HIGH"
    if command == "git":
        sub = args[0] if args else ""
        if sub in _GIT_HIGH:
            return "HIGH"
        if sub in _GIT_MEDIUM:
            return "MEDIUM"
        if sub in _GIT_LOW:
            return "LOW"
        # No recognized subcommand: a bare version/help probe is LOW, else fail-safe HIGH.
        if _is_probe(args):
            return "LOW"
        return "HIGH"
    if command in ("ffmpeg", "pandoc"):
        # A pure version/help probe is LOW; anything else produces output → MEDIUM.
        return "LOW" if _is_probe(args) else "MEDIUM"
    return "HIGH"


def _is_probe(args) -> bool:
    """True when the args are ONLY a version/help probe (no other tokens), so a
    verbose flag riding on a real operation can never masquerade as a probe."""
    probe = {"--version", "-version", "version", "--help", "-h", "-v"}
    return len(args) == 1 and args[0] in probe


# git subcommands that touch the network (vs local-only status/log/commit/…).
_GIT_NETWORK = frozenset({"push", "pull", "fetch", "clone", "submodule", "ls-remote"})


def is_network_command(command: str, argv) -> bool:
    """True if this command needs the network (gh always; git only for network subcommands).
    Local commands (local git, ffmpeg, pandoc) run fully offline as today."""
    args = [a for a in (argv if isinstance(argv, list) else []) if isinstance(a, str)]
    if command == "gh":
        return True
    if command == "git":
        return bool(args) and args[0] in _GIT_NETWORK
    return False


def _url_host(s: str) -> str | None:
    if "://" in s:
        return (urlparse(s).hostname or "").lower() or None
    if "@" in s and ":" in s:                    # scp-like: git@github.com:owner/repo.git
        return s.split("@", 1)[1].split(":", 1)[0].lower() or None
    return None


def resolve_target_host(command: str, argv, *, repo_remotes: dict) -> str | None:
    """Best-effort target host of a network command. `repo_remotes` maps remote-name→url
    (the caller resolves it from the repo config). Returns a lowercased host or None."""
    if command == "gh":
        return "github.com"
    args = [a for a in (argv if isinstance(argv, list) else []) if isinstance(a, str)]
    for a in args[1:]:                            # skip subcommand
        if a.startswith("-"):
            continue
        h = _url_host(a)
        if h:
            return h
        if a in repo_remotes:
            return _url_host(repo_remotes[a])
    return _url_host(repo_remotes["origin"]) if "origin" in repo_remotes else None


_GITHUB_HOSTS = frozenset({"github.com", "api.github.com"})


def is_host_allowed(host, *, repo_remote_hosts: set) -> bool:
    """v1 allowlist: GitHub + the hosts of THIS repo's configured remotes. Everything else refused."""
    if not host:
        return False
    h = host.lower()
    return h in _GITHUB_HOSTS or h in {str(r).lower() for r in repo_remote_hosts}


def push_targets_current_branch(argv, current_branch: str) -> bool:
    """Guard: a `git push` may only push the CURRENT branch (or HEAD) — never an arbitrary ref.
    Deterministic; `current_branch` is resolved host-side. Non-push commands pass through."""
    args = [a for a in (argv if isinstance(argv, list) else []) if isinstance(a, str)]
    if not args or args[0] != "push":
        return True
    refs = [a for a in args[1:] if not a.startswith("-")]
    refspecs = refs[1:] if refs else []                # first non-flag is the remote
    if not refspecs:
        return True                                    # `git push [origin]` pushes current branch
    allowed = {current_branch, "HEAD", f"+{current_branch}"}
    return all(r in allowed for r in refspecs)
