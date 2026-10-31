"""DIFF2-1 (v0.1.64, card docs/plans/0164/DIFF2-git-changes.md): Changes for a working folder that is a git repo, as
Claude desktop shows them (the user's picks, 2026-10-31): the branch against its base, its commits, every file changed
since the branch left the base (committed or not), one file's diff in DIFF1's shape, and the branch's PRs through `gh`.

git only reads its object store and refs (rev-parse, symbolic-ref, merge-base, log, ls-tree, cat-file, ls-files
--others); Arslan reads and hashes the working files itself. `git diff` or `status` against the working tree would run
a filter driver the repo's own .git/config names (the card's probe), and a turn can write that file. So no program the
repo's config names runs here: no filter, textconv, external diff, fsmonitor, hook, pager or signature check (and no
`%G` placeholder in `log --format`, which would run gpg). Every call pins `--git-dir` and `--work-tree`, so neither the
repo's `core.worktree` nor the environment moves them (⓪Plan's review of #583). `gh` runs with `--repo owner/name` read
from `remote.origin.url` (github.com only), from a folder outside the repo, so it runs no git there. Read only; callers
run these off the event loop.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from server.mcp.spawn_env import merged_path
from server.services import checkpoints
from server.services.checkpoints import NoDiff
from server.services.workspace_paths import is_secret_name

GIT_TIMEOUT_S = 10.0
GH_TIMEOUT_S = 10.0
PR_CACHE_S = 60.0
MAX_FILES = 500
MAX_COMMITS = 50
_SAFE = ("-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null")
_ENV = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"}
# Variables that would point git somewhere else than the repo found (⓪Plan's review of #583).
_DROP_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
             "GIT_COMMON_DIR", "GIT_NAMESPACE")
#: On a Mac without the command-line tools this is a shim that opens macOS's install dialog (SBX-M runbook).
_SHIM = "/usr/bin/git"
_ON_MAC = sys.platform == "darwin"
_LFS = b"version https://git-lfs.github.com/spec/"
_GITLINK = "160000"                      # a submodule's commit: not a file here

# (root, rel) -> (size, mtime_ns, blob id); (old blob, new blob) -> (added, removed) or None; (root, branch) -> (at, PRs)
_hashes: dict[tuple[str, str], tuple[int, int, str]] = {}
_counts: dict[tuple[str | None, str | None], tuple[int, int] | None] = {}
_pr_cache: dict[tuple[str, str], tuple[float, dict]] = {}


class GitError(Exception):
    pass


def repo_root(folder: Path, home: Path) -> Path | None:
    """The repo `folder` is in: it, or a folder above it up to but not including `home`, holding a `.git` entry
    (found by name). Outside home only the folder itself counts."""
    try:
        folder.relative_to(home)
        inside = folder != home
    except ValueError:
        inside = False
    candidates = [folder] if not inside else [p for p in (folder, *folder.parents) if p != home and home in p.parents]
    return next((p for p in candidates if os.path.lexists(p / ".git")), None)


def _git_exe() -> str | None:
    """git, unless it is macOS's shim with no command-line tools behind it (no install dialog from a poll)."""
    exe = shutil.which("git", path=merged_path())
    if exe and _ON_MAC and os.path.realpath(exe) == _SHIM:
        select = shutil.which("xcode-select", path=merged_path()) or "/usr/bin/xcode-select"
        try:
            if subprocess.run([select, "-p"], capture_output=True, timeout=GIT_TIMEOUT_S).returncode != 0:
                return None
        except (OSError, subprocess.TimeoutExpired):
            return None
    return exe


def git_dir(root: Path) -> Path:
    """The repo's git folder: `.git` itself, or where a `.git` file's `gitdir:` line points (a linked worktree or a
    submodule). Reading objects and refs there is fine; nothing is written."""
    dot = root / ".git"
    if dot.is_file() and not dot.is_symlink():
        line = dot.read_text(errors="replace").strip()
        if line.startswith("gitdir:"):
            return (root / line.removeprefix("gitdir:").strip()).resolve()
    return dot


def _git(root: Path, *args: str, data: bytes | None = None) -> bytes:
    exe = _git_exe()
    if exe is None:
        raise GitError("no git")
    env = {k: v for k, v in os.environ.items() if k not in _DROP_ENV}
    env.update(_ENV, PATH=merged_path(), GIT_CEILING_DIRECTORIES=str(root.parent))
    try:
        done = subprocess.run([exe, f"--git-dir={git_dir(root)}", f"--work-tree={root}", *_SAFE, *args], cwd=root,
                              input=data, capture_output=True, timeout=GIT_TIMEOUT_S, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitError(type(exc).__name__) from None
    if done.returncode != 0:
        raise GitError(done.stderr.decode(errors="replace")[:200])
    return done.stdout


def _maybe(root: Path, *args: str) -> str | None:
    try:
        return _git(root, *args).decode().strip() or None
    except GitError:
        return None


def _tree(root: Path, rev: str | None) -> dict[str, tuple[str, str]]:
    """path -> (mode, blob id) for every entry of `rev`'s tree."""
    if rev is None:
        return {}
    out = {}
    for item in _git(root, "ls-tree", "-r", "-z", "--full-tree", rev).split(b"\0"):
        if item:
            meta, path = item.split(b"\t", 1)
            mode, _type, sha = meta.decode().split()
            out[path.decode("utf-8", "surrogateescape")] = (mode, sha)
    return out


def _blob(root: Path, sha: str) -> bytes:
    if int(_git(root, "cat-file", "-s", sha)) > checkpoints.DIFF_MAX_BYTES:
        raise NoDiff("too_big")
    return _git(root, "cat-file", "blob", sha)


def _hash_file(root: Path, rel: str) -> str | None:
    """git's blob id for the working file at `rel`, read by Arslan: every folder opened without following a link, a
    link itself hashed as its target text (as git stores it), never followed. None when there is none."""
    parts = tuple(rel.split("/"))
    try:
        fd = checkpoints._open_folder(root, parts[:-1], create=False)
    except OSError:
        return None
    try:
        st = os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)
        if stat.S_ISLNK(st.st_mode):
            data = os.fsencode(os.readlink(parts[-1], dir_fd=fd))
        elif stat.S_ISREG(st.st_mode):
            digest = hashlib.sha1(b"blob %d\0" % st.st_size)
            handle = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            with os.fdopen(handle, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    digest.update(chunk)
            return digest.hexdigest()
        else:
            return None
    except OSError:
        return None
    finally:
        os.close(fd)
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _working_id(root: Path, rel: str) -> str | None:
    try:
        st = os.lstat(root / rel)
    except OSError:
        return None
    key = (str(root), rel)
    hit = _hashes.get(key)
    if hit and hit[:2] == (st.st_size, st.st_mtime_ns):
        return hit[2]
    sha = _hash_file(root, rel)
    if sha is not None:
        _hashes[key] = (st.st_size, st.st_mtime_ns, sha)
    return sha


def _contained(rel: str) -> bool:
    return bool(rel) and not rel.startswith("/") and ".." not in rel.split("/") and rel.split("/")[0] != ".git"


def _state(root: Path, folder: Path) -> dict:
    """Branch, base, merge base and the changed paths under `folder`, before counts and caps."""
    head = _maybe(root, "rev-parse", "--verify", "-q", "HEAD")
    branch = _maybe(root, "symbolic-ref", "-q", "--short", "HEAD")
    base_ref = _maybe(root, "symbolic-ref", "-q", "refs/remotes/origin/HEAD")
    if base_ref is None:
        base_ref = next((ref for ref in ("refs/heads/main", "refs/heads/master")
                         if _maybe(root, "rev-parse", "--verify", "-q", ref)), None)
    base = base_ref.removeprefix("refs/remotes/").removeprefix("refs/heads/") if base_ref else None
    merge_base = (_maybe(root, "merge-base", "HEAD", base_ref) if head and base_ref else None) or head
    prefix = "" if folder == root else folder.relative_to(root).as_posix() + "/"
    then, now = _tree(root, merge_base), _tree(root, head)
    untracked = [p.decode("utf-8", "surrogateescape") for p in
                 _git(root, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0") if p]
    changed = []
    for rel in sorted({*then, *now, *untracked}):
        if not rel.startswith(prefix) or not _contained(rel):
            continue
        old, committed = then.get(rel), now.get(rel)
        if (old and old[0] == _GITLINK) or (committed and committed[0] == _GITLINK):
            continue
        current = _working_id(root, rel)
        if old is None and current is None or old is not None and old[1] == current:
            continue
        changed.append({"path": rel, "kind": "made" if old is None else "deleted" if current is None else "edited",
                        "uncommitted": (committed[1] if committed else None) != current,
                        "old": old[1] if old else None, "new": current})
    return {"head": head, "branch": branch, "base": base, "merge_base": merge_base, "changed": changed}


def _counts_for(root: Path, item: dict) -> tuple[int, int] | None:
    key = (item["old"], item["new"])
    if key not in _counts:
        try:
            d = _diff_of(root, item)
            _counts[key] = (d["added"], d["removed"])
        except (NoDiff, GitError):
            _counts[key] = None
    return _counts[key]


def summary(root: Path, folder: Path) -> dict:
    """What Overview's Changes shows for a repo: the branch (None when detached, then `detached` is the short sha),
    its base, the commits since the merge base, and the changed files under `folder` (at most MAX_FILES; `more`
    counts the rest), each made / edited / deleted, `uncommitted` when it differs from HEAD, and its +/- counts
    (None for a file with no line diff)."""
    s = _state(root, folder)
    commits = []
    if s["head"] and s["merge_base"] and s["merge_base"] != s["head"]:
        raw = _git(root, "log", "--no-show-signature", f"--max-count={MAX_COMMITS}", "--format=%h%x1f%s%x1e",
                   f"{s['merge_base']}..HEAD")
        commits = [dict(zip(("sha", "subject"), r.strip().split("\x1f", 1))) for r in raw.decode().split("\x1e") if r.strip()]
    files = []
    for item in s["changed"][:MAX_FILES]:
        counted = _counts_for(root, item)
        files.append({"path": item["path"], "kind": item["kind"], "uncommitted": item["uncommitted"],
                      "added": counted[0] if counted else None, "removed": counted[1] if counted else None})
    return {"branch": s["branch"], "detached": None if s["branch"] or not s["head"] else s["head"][:7],
            "base": s["base"], "commits": commits, "files": files, "more": max(0, len(s["changed"]) - MAX_FILES)}


def _diff_of(root: Path, item: dict) -> dict:
    before = _blob(root, item["old"]) if item["old"] else None
    if before is not None and before.startswith(_LFS):
        raise NoDiff("lfs")
    after = checkpoints._read_side(root, tuple(item["path"].split("/"))) if item["new"] else None
    return checkpoints.line_diff(before, after)


def file_diff(root: Path, folder: Path, rel: str) -> dict:
    """One listed path as DIFF1's lines: the merge base's blob against the file now. NoDiff `not_listed` for a path
    that isn't among the changed ones under `folder`, `hidden` for a secret-shaped name, `lfs` for a file Git LFS
    stores, and DIFF1's `too_big` / `not_text`."""
    item = next((c for c in _state(root, folder)["changed"] if c["path"] == rel), None)
    if item is None:
        raise NoDiff("not_listed")
    if any(is_secret_name(part) for part in rel.split("/")):
        raise NoDiff("hidden")
    return {"kind": item["kind"], **_diff_of(root, item), "since": False}


def _checks(rollup: list) -> str | None:
    if not rollup:
        return None
    states = [str(c.get("conclusion") or c.get("state") or "").upper() for c in rollup]
    if any(s in ("FAILURE", "ERROR", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE") for s in states):
        return "failing"
    if any(str(c.get("status") or "COMPLETED").upper() != "COMPLETED" or str(c.get("state") or "").upper()
           in ("PENDING", "EXPECTED") for c in rollup):
        return "running"
    return "passed"


def github_repo(root: Path) -> str | None:
    """`owner/name` from `remote.origin.url` when it is on github.com (https, ssh or scp-like), else None."""
    url = _maybe(root, "config", "--get", "remote.origin.url") or ""
    for lead in ("https://github.com/", "ssh://git@github.com/", "git@github.com:"):
        if url.startswith(lead):
            parts = url[len(lead):].removesuffix("/").removesuffix(".git").split("/")
            if len(parts) == 2 and all(p and all(c.isalnum() or c in "-_." for c in p) for p in parts):
                return "/".join(parts)
    return None


def prs(repo: str, branch: str) -> dict:
    """The branch's PRs on GitHub repo `owner/name` through `gh`, newest first, cached PR_CACHE_S: number, title,
    state (open / closed / merged), draft, url (https only) and checks (passed / failing / running / None).
    `signed_in` is False when `gh` is missing or not signed in; `error` "unavailable" when it didn't answer in time.
    `gh` runs from a folder outside the repo with `--repo`, so it runs no git in the repo."""
    key = (repo, branch)
    hit = _pr_cache.get(key)
    if hit and time.monotonic() - hit[0] < PR_CACHE_S:
        return hit[1]
    exe = shutil.which("gh", path=merged_path())
    env = {**os.environ, "GH_PROMPT_DISABLED": "1", "GH_NO_UPDATE_NOTIFIER": "1", "PATH": merged_path()}
    out: dict = {"signed_in": False, "prs": []}
    try:
        away = tempfile.gettempdir()
        if exe and subprocess.run([exe, "auth", "status", "--hostname", "github.com"], cwd=away, env=env,
                                  capture_output=True, timeout=GH_TIMEOUT_S).returncode == 0:
            done = subprocess.run([exe, "pr", "list", "--repo", repo, "--head", branch, "--state", "all", "--limit", "10",
                                   "--json", "number,title,state,isDraft,url,statusCheckRollup"],
                                  cwd=away, env=env, capture_output=True, timeout=GH_TIMEOUT_S)
            out = {"signed_in": True, "prs": []} if done.returncode == 0 else \
                {"signed_in": True, "prs": [], "error": "unavailable"}
            for p in json.loads(done.stdout or b"[]") if done.returncode == 0 else []:
                url = str(p.get("url") or "")
                out["prs"].append({"number": int(p["number"]), "title": str(p.get("title") or "")[:300],
                                   "state": str(p.get("state") or "").lower(), "draft": bool(p.get("isDraft")),
                                   "url": url if url.startswith("https://") else None,
                                   "checks": _checks(p.get("statusCheckRollup") or [])})
    except subprocess.TimeoutExpired:
        out = {"signed_in": True, "prs": [], "error": "unavailable"}
    except (OSError, ValueError, KeyError, TypeError):
        out = {"signed_in": True, "prs": [], "error": "unavailable"}
    _pr_cache[key] = (time.monotonic(), out)
    return out
