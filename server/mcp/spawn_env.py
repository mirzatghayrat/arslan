"""PATH resolution for stdio MCP spawns.

A Finder-launched .app inherits LaunchServices' minimal PATH
(/usr/bin:/bin:/usr/sbin:/sbin) — Homebrew/nvm/volta dirs are absent, so a
`command: npx` server dies with [Errno 2] in the packaged build while dev,
which inherits the terminal's PATH, never reproduces it. The fix is twofold
because resolving the command alone is not enough: `npx` re-launches `node`
from the child's PATH, so the child env needs the merged PATH too.

The login-shell PATH is fetched once per process (the user's dotfiles are
where Homebrew/nvm append themselves) with hard fallbacks for when that
resolution fails.
"""
from __future__ import annotations

import functools
import os
import shutil
import subprocess

_FALLBACK_DIRS = ("/opt/homebrew/bin", "/usr/local/bin")
_SHELL_TIMEOUT = 5.0

# Ambient provider keys, the Arslan secret, SSH agents, NODE_OPTIONS and
# PYTHONPATH must not leak into every third-party MCP subprocess. This is
# least-privilege environment passing, NOT filesystem/process isolation.
_AMBIENT_KEYS = frozenset({
    "HOME", "USER", "LOGNAME", "PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ",
    "TMPDIR", "TMP", "TEMP", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT",
    "USERPROFILE", "APPDATA", "LOCALAPPDATA", "SSL_CERT_FILE", "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "NODE_EXTRA_CA_CERTS",
})


def child_environment(additions: dict, explicit: dict) -> dict:
    """Only runtime basics and explicitly configured server credentials cross."""
    ambient = {key: value for key, value in os.environ.items() if key.upper() in _AMBIENT_KEYS}
    return {**ambient, **additions, **explicit}


@functools.lru_cache(maxsize=1)
def login_shell_path() -> str:
    """The user's interactive PATH, or "" when the shell can't produce one."""
    shell = os.environ.get("SHELL") or "/bin/zsh"
    try:
        proc = subprocess.run(
            [shell, "-l", "-c", 'printf %s "$PATH"'],
            capture_output=True, text=True, timeout=_SHELL_TIMEOUT, check=False,
        )
    except Exception:  # noqa: BLE001 — a broken shell must never block a spawn
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def merged_path() -> str:
    """Current PATH first (dev behaviour unchanged), then login-shell additions,
    then hard fallbacks — deduplicated, order-preserving."""
    parts: list[str] = []
    for chunk in (os.environ.get("PATH", ""), login_shell_path(),
                  os.pathsep.join(_FALLBACK_DIRS)):
        for p in chunk.split(os.pathsep):
            if p and p not in parts:
                parts.append(p)
    return os.pathsep.join(parts)


def resolve_command(command: str) -> str:
    """Absolute path for a bare command name, searched on the merged PATH.

    Commands already carrying a path separator are the user's explicit choice
    and pass through untouched. A miss raises with the actual cause — the bare
    [Errno 2] the OS produces reads as a broken server, not a PATH problem.
    """
    if os.path.sep in command:
        return command
    found = shutil.which(command, path=merged_path())
    if found is None:
        hint = (
            " — install Node.js (e.g. `brew install node`)"
            if command in ("npx", "node", "npm") else ""
        )
        raise FileNotFoundError(
            f"command '{command}' was not found on PATH. The packaged app does not "
            f"inherit your terminal's PATH; the login shell's PATH was searched too{hint}"
        )
    return found
