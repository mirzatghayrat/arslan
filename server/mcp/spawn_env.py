"""PATH resolution for stdio MCP spawns.

A Finder-launched .app inherits LaunchServices' minimal PATH
(/usr/bin:/bin:/usr/sbin:/sbin) — Homebrew/nvm/volta dirs are absent, so a
`command: npx` server dies with [Errno 2] in the packaged build while dev,
which inherits the terminal's PATH, never reproduces it. The fix is twofold
because resolving the command alone is not enough: `npx` re-launches `node`
from the child's PATH, so the child env needs the merged PATH too.

The user's PATH is fetched once per process from an INTERACTIVE login shell (the user's dotfiles are where
Homebrew, nvm and installers like `claude`'s append themselves; SMART-1: a zsh login shell alone never reads
~/.zshrc), with hard fallbacks for when that resolution fails. It runs in the server, outside every sandbox, with a
minimal environment. The commands run later read none of the user's shell startup files (`bash -p -c`).
"""
from __future__ import annotations

import functools
import os
import secrets
import shutil
import signal
import subprocess
import threading

_FALLBACK_DIRS = ("/opt/homebrew/bin", "/usr/local/bin")
#: SMART-1: where user-level installers put their tools, under ~ (added even when the shell can't answer).
_HOME_FALLBACK_DIRS = (".local/bin", "bin", ".cargo/bin")
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


#: SMART-1 review: the only variables the PATH-resolving shell gets. The server's own environment holds the Arslan
#: secret and provider keys, which an rc file has no business seeing.
_RESOLVING_KEYS = ("HOME", "USER", "LOGNAME", "SHELL", "ZDOTDIR", "XDG_CONFIG_HOME", "LANG", "LC_ALL", "LC_CTYPE",
                   "TZ", "TMPDIR")
#: Set while Arslan reads the PATH, so an rc can skip slow or interactive steps (unlocking credentials, say):
#: `[[ -n $ARSLAN_RESOLVING_ENVIRONMENT ]] && return`. VS Code sets VSCODE_RESOLVING_ENVIRONMENT the same way.
RESOLVING_FLAG = "ARSLAN_RESOLVING_ENVIRONMENT"


def _resolving_environment() -> dict:
    env = {key: os.environ[key] for key in _RESOLVING_KEYS if os.environ.get(key)}
    env.update(PATH="/usr/bin:/bin:/usr/sbin:/sbin", TERM="dumb", **{RESOLVING_FLAG: "1"})
    return env


def _shell_output(argv: list[str], env: dict) -> str:
    """What the shell printed on stdout within `_SHELL_TIMEOUT`. After the limit its whole process group is
    killed, and what it printed before the kill is still returned (an rc that leaves a child holding the pipe
    after the PATH was printed must not lose that PATH)."""
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, env=env, start_new_session=True)
    except Exception:  # noqa: BLE001 — a broken shell must never block a spawn
        return ""
    partial: bytes | str | None = None
    try:
        out, _ = proc.communicate(timeout=_SHELL_TIMEOUT)
        return _decoded(out)
    except subprocess.TimeoutExpired as exc:
        partial = exc.output
    except Exception:  # noqa: BLE001 — fails closed: the group is killed below and only what was read counts
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        try:
            proc.kill()
        except OSError:
            pass
    try:
        out, _ = proc.communicate(timeout=1)     # everything read so far, the part before the limit included
        return _decoded(out)
    except subprocess.TimeoutExpired as exc:   # a child that left the group still holds the pipe: give up on it
        return _decoded(exc.output or partial)
    except Exception:  # noqa: BLE001 — the pipes are abandoned, not waited on
        return _decoded(partial)


def _decoded(out: bytes | str | None) -> str:
    if isinstance(out, bytes):
        return out.decode("utf-8", errors="replace")
    return out or ""


#: #674 review: one read at a time, so calls that overlap before the cache is filled (the supervisor's prewarm,
#: a command, the turn's environment note) run the user's rc once, not once each.
_RESOLVE_LOCK = threading.Lock()


def login_shell_path() -> str:
    """The user's interactive PATH (read once per process, see `_login_shell_path_once`). It may wait for the
    shell, up to about 12 s at worst, so callers on the event loop call it, or `merged_path`, in a thread."""
    with _RESOLVE_LOCK:
        return _login_shell_path_once()


@functools.lru_cache(maxsize=1)
def _login_shell_path_once() -> str:
    """The user's interactive PATH, or "" when the shell can't produce one in time.

    SMART-1: `-i -l`, so zsh reads ~/.zshrc as well as ~/.zprofile (the old `-l` alone never read ~/.zshrc). When
    that gives no PATH (an rc that hangs, say), `-l` alone is tried, so what ~/.zprofile adds isn't lost too. The
    PATH is printed between a marker made fresh for each try, so whatever the rc files print (a banner, a fake
    marker) is ignored; stdin is empty, so a prompt in them reads EOF; the environment is minimal
    (`_resolving_environment`); and the whole process group gets `_SHELL_TIMEOUT` seconds, then is killed, so an
    rc that hangs, or leaves a child holding the pipes, can't hold a spawn."""
    shell = os.environ.get("SHELL") or "/bin/zsh"
    env = _resolving_environment()
    for flags in (("-i", "-l"), ("-l",)):
        token = secrets.token_hex(8)
        script = f'printf "\\n__ARSLAN_PATH_{token}__%s__END_{token}__\\n" "$PATH"'
        start, end = f"__ARSLAN_PATH_{token}__", f"__END_{token}__"
        for line in _shell_output([shell, *flags, "-c", script], env).splitlines():
            if line.startswith(start) and line.endswith(end):
                found = line[len(start):-len(end)].strip()
                if found:
                    return found
    return ""


login_shell_path.cache_clear = _login_shell_path_once.cache_clear   # type: ignore[attr-defined]


def merged_path() -> str:
    """Current PATH first (dev behaviour unchanged), then login-shell additions,
    then hard fallbacks — deduplicated, order-preserving. Only absolute folders: a `.` or a relative entry (an rc
    that adds `.`) would let a file planted in a command's working folder shadow the real tool (#674 review)."""
    parts: list[str] = []
    home = os.environ.get("HOME") or os.path.expanduser("~")
    fallbacks = [*_FALLBACK_DIRS, *(os.path.join(home, d) for d in _HOME_FALLBACK_DIRS)]
    for chunk in (os.environ.get("PATH", ""), login_shell_path(), os.pathsep.join(fallbacks)):
        for p in chunk.split(os.pathsep):
            if p and "\0" not in p and os.path.isabs(p) and p not in parts:   # a NUL breaks every spawn
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
    holds a path separator, so an explicit path is never a match.) Case-blind, as the Mac's file system finds
    `Npx` too (#623 review L-1)."""
    entry = _PINNED.get((command or "").lower())
    return entry[0] if entry else None


def pinned_command(command: str) -> tuple[str, str | None]:
    """(absolute pinned binary, its bin dir) when that exact binary is installed; else
    (command, None). Never downloads: the supervisor decides when to fetch (0.1.61 §B1). Case-blind (#623 L-1)."""
    entry = _PINNED.get((command or "").lower())
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
    moved = [str(v) for v in (server.get("secrets") or {}).values() if v]     # SEC1: moved secrets, as written
    values += moved + [urllib.parse.unquote(v) for v in moved]                  # and as a server may echo them
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
