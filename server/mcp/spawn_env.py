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


# ── 0.1.61 §B1: Arslan's pinned Node and uv for bare npx/node/npm/uvx/uv ─────────────────

#: bare command → (runtime, the binary inside that runtime's folder)
_PINNED = {"node": ("node", "bin/node"), "npm": ("node", "bin/npm"), "npx": ("node", "bin/npx"),
           "uv": ("uv", "uv"), "uvx": ("uv", "uvx")}


def runtime_for(command: str) -> str | None:
    """'node' | 'uv' when `command` is a bare name Arslan pins, else None. (No key of _PINNED
    holds a path separator, so an explicit path is never a match.)"""
    entry = _PINNED.get(command or "")
    return entry[0] if entry else None


def pinned_command(command: str) -> tuple[str, str | None]:
    """(absolute pinned binary, its bin dir) when that exact binary is installed; else
    (command, None). Never downloads: the supervisor decides when to fetch (0.1.61 §B1)."""
    entry = _PINNED.get(command or "")
    if entry is None:
        return command, None
    from server.services import capability_runtime

    path = capability_runtime.binary(entry[0], entry[1])
    if not (capability_runtime.ready(entry[0]) and path.is_file()):
        return command, None
    return str(path), str(path.parent)


# ── 0.1.61 §B1: a server's own secrets never leave in its error text ──────────────────────

_TRIVIAL = frozenset({"true", "false", "yes", "no", "null", "none", "on", "off"})


def secret_forms(server: dict) -> list[str]:
    """Every form in which this server's own secrets could appear in its error text: its env
    values (header values for http, and the token after "Bearer"), the query values and the
    userinfo of its URL. `httpx.HTTPStatusError` prints the URL exactly as written, so the query
    values are taken both decoded and as written (`a+b/c==`, lower-case `%2f`, a partly encoded
    value all print differently from any re-encoding), and the userinfo both as written and
    decoded (a token may be the username alone). Each is added raw, `quote`d with the default
    safe set, `quote`d with none, and `quote_plus`'d. Longest first, so a short secret inside a
    longer one never leaves the longer one's tail behind. Under 4 characters, or a plain boolean
    word, is not a secret."""
    import urllib.parse

    values = [str(v) for v in (server.get("env") or {}).values() if v]
    values += [str(v) for v in (server.get("secrets") or {}).values() if v]      # SEC1: moved secrets
    url = urllib.parse.urlsplit(server.get("url") or "")
    values += [v for _, v in urllib.parse.parse_qsl(url.query) if v]
    values += [pair.partition("=")[2] for pair in url.query.split("&") if "=" in pair]
    for userinfo in (url.username, url.password):
        if userinfo:
            values += [userinfo, urllib.parse.unquote(userinfo)]
    forms: set[str] = set()
    for value in values:
        for part in (value, *value.split()[1:2]):
            if len(part) >= 4 and part.lower() not in _TRIVIAL:
                forms |= {part, urllib.parse.quote(part, safe=""), urllib.parse.quote(part),
                          urllib.parse.quote_plus(part)}
    return sorted(forms, key=len, reverse=True)


def mask(text: str, secrets: list[str]) -> str:
    """Replace every secret with ****, longest first."""
    for secret in sorted({s for s in secrets if s}, key=len, reverse=True):
        text = text.replace(secret, "****")
    return text
