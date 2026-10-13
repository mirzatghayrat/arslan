"""What Arslan's terminal may run, and what crosses a boundary (0.1.48; categories 0.1.61 §A2).

`classify(command)` returns every finding in a command, each with a category:

  floor        never, even with a click: wiping disks or the home folder, shutting down, fork
               bombs, sudo, reading passwords out of the keychain, Arslan's own data, keys and
               database, an app on the never-list.
  opaque       code that is downloaded or decoded, or built while the command runs, and then
               run; a command Arslan could not read (past a parse ceiling, or a command word
               known only at run time).
  other_agent  a write into another agent's settings (Hermes, Codex, Claude, Cursor, OpenClaw).
  system       changes how the Mac behaves: launchd, preferences, crontab, power, network,
               keychain items, shell start files.
  destructive  a recursive or forced delete, discarding work, dropping data, killing processes.
  send         sends something off the Mac: uploads, mail, messages, git push, publishing,
               ssh/scp, nc/socat/telnet, a script that POSTs or mails.
  screen       a screenshot.
  apps         tells another app what to do: osascript `tell`, Shortcuts, a script in Terminal.
  local        everything else. It runs inside the sandbox, which holds every file write.

Only what the sandbox cannot hold asks (command_permissions decides how). The destructive
and hard-floor detection is Hermes Agent's (MIT, vendored in arslan/vendor/hermes, unedited);
`HERMES_CATEGORIES` places each of its descriptions, and a guard test fails when a Hermes
update adds one this table does not place. The outward, app and credential rules are Arslan's.

Text is not a command (§A9): a heredoc body is data for the program that reads it, scanned as
shell only when that program is a shell; quoted arguments are data for the delete, install,
sudo and SQL rules unless a shell (`bash -c`, `eval`) or a database client runs them. Code
written inline for an interpreter is read for three things only: sending, other apps, hidden
code (`_script_findings`).

`assess` (run / ask / forbid) and `ask_rules` are the 0.1.48 view of the same findings: Careful
mode's cards, the "don't ask again" rules (`legacy_rule`), the island and the task checks use it.
Everything here is a function of the command text; the sandbox holds the rest.
"""
from __future__ import annotations

import contextvars
import functools
import logging
import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

from arslan.vendor.hermes import approval_detection as hermes

logger = logging.getLogger(__name__)
MAX_COMMAND_CHARS = 8000

_POS = hermes._CMDPOS           # command position: start, after ; | && $( ` and sudo/env wrappers

#: In the order a card is chosen: the first asking category of a command is its headline.
CATEGORIES = ("floor", "opaque", "other_agent", "system", "destructive", "send", "screen", "apps",
              "local")
#: What asks in Standard (§A2): exactly what the sandbox cannot hold.
ASKING = frozenset({"opaque", "other_agent", "system", "destructive", "send", "screen", "apps"})

# ── Hermes' descriptions, placed (§A2) ────────────────────────────────────────
#: Every description Hermes' detector can report, and the category it means here. The guard
#: test (tests/server/test_terminal_categories.py) reads Hermes' own tables and fails on any
#: description missing from this one, so a re-vendored detector cannot add an unplaced finding.
HERMES_CATEGORIES: dict[str, str] = {
    # hardline: the floor
    "recursive delete of root filesystem": "floor",
    "recursive delete of system directory": "floor",
    "recursive delete of home directory": "floor",
    "format filesystem (mkfs)": "floor",
    "dd to raw block device": "floor",
    "redirect to raw block device": "floor",
    "fork bomb": "floor",
    "kill all processes": "floor",
    "system shutdown/reboot": "floor",
    "init 0/6 (shutdown/reboot)": "floor",
    "systemctl poweroff/reboot": "floor",
    "telinit 0/6 (shutdown/reboot)": "floor",
    "command parser limit exceeded": "floor",
    "sudo password guessing via stdin (sudo -S)": "floor",
    "sudo with privilege flag (stdin/askpass/shell/list)": "floor",
    "sudo with combined-flag privilege escalation": "floor",
    "format filesystem": "floor",
    "write to block device": "floor",
    "format filesystem (Format-Volume)": "floor",
    "wipe disk (Clear-Disk)": "floor",
    "disk partitioning (diskpart)": "floor",
    "format drive (format.com)": "floor",
    "wipe free space (cipher /w)": "floor",
    # deleting, discarding work, dropping data, killing processes
    "delete in root path": "destructive",
    "recursive delete": "destructive",
    "recursive delete (long flag)": "destructive",
    "recursive delete (flags after operands)": "destructive",
    "Windows cmd destructive delete": "destructive",
    "Windows PowerShell destructive delete": "destructive",
    "PowerShell destructive delete (Remove-Item)": "destructive",
    "Windows destructive delete (recursive/quiet switch)": "destructive",
    "delete volume shadow copies (vssadmin)": "destructive",
    "delete backups (wbadmin)": "destructive",
    "xargs with rm": "destructive",
    "find -exec/-execdir rm": "destructive",
    "find dynamic shell word may expand to destructive flag": "destructive",
    "find -delete": "destructive",
    "SQL DROP": "destructive",
    "SQL DELETE without WHERE": "destructive",
    "SQL TRUNCATE": "destructive",
    "git reset --hard (destroys uncommitted changes)": "destructive",
    "git clean with force (deletes untracked files)": "destructive",
    "git branch force delete": "destructive",
    "git branch force delete (long flags)": "destructive",
    "git branch force delete (long flags, force-first)": "destructive",
    "force kill processes": "destructive",
    "force kill processes (killall -KILL)": "destructive",
    "force kill processes (killall -s KILL)": "destructive",
    "kill processes by regex (killall -r)": "destructive",
    "force kill processes (taskkill /F)": "destructive",
    "force kill processes (Stop-Process -Force)": "destructive",
    "kill hermes/gateway process (self-termination)": "destructive",
    "kill process via pgrep/pidof expansion (self-termination)": "destructive",
    "kill process via backtick pgrep/pidof expansion (self-termination)": "destructive",
    # sending
    "git force push (rewrites remote history)": "send",
    "git force push short flag (rewrites remote history)": "send",
    "cloud metadata endpoint access (instance credentials)": "send",
    # fetched or decoded code, run
    "pipe remote content to shell": "opaque",
    "execute remote script via process substitution": "opaque",
    "execute remote content via command substitution": "opaque",
    "pipe decoded content to shell (possible command obfuscation)": "opaque",
    "pipe xxd-decoded content to shell (possible command obfuscation)": "opaque",
    "pipe tr-transformed output to shell (possible command obfuscation)": "opaque",
    "pipe openssl-decoded content to shell (possible command obfuscation)": "opaque",
    "PowerShell encoded command execution": "opaque",
    "pipe remote content to PowerShell (iwr | iex)": "opaque",
    "execute remote content via Invoke-Expression": "opaque",
    # how the Mac (or a daemon outside the sandbox) behaves
    "overwrite system config": "system",
    "overwrite system file via tee": "system",
    "overwrite system file via redirection": "system",
    "copy/move file into system config path": "system",
    "copy/move file into sensitive credential/SSH/shell-rc path": "system",
    "in-place edit of sensitive credential/SSH/shell-rc path": "system",
    "in-place edit of sensitive credential/SSH/shell-rc path (long flag)": "system",
    "in-place edit of sensitive credential/SSH/shell-rc path (perl/ruby)": "system",
    "in-place edit of system config": "system",
    "in-place edit of system config (long flag)": "system",
    "stop/restart system service": "system",
    "recursive chown to root": "system",
    "recursive chown to root (long flag)": "system",
    "docker with remote daemon redirect (-H/--host)": "system",
    "docker with daemon redirect (--context: alternate daemon)": "system",
    "docker context use (switches default daemon for future commands)": "system",
    "podman with remote daemon redirect (--url/--connection/--identity)": "system",
    "podman remote mode (-r/--remote: remote daemon)": "system",
    "docker/podman daemon redirect via environment (DOCKER_HOST/CONTAINER_HOST)": "system",
    "docker compose restart/stop/kill/down (container lifecycle)": "system",
    "docker restart/stop/kill (container lifecycle)": "system",
    "grant Everyone access (icacls)": "system",
    "reset ACLs recursively (icacls /reset)": "system",
    "modify boot configuration (bcdedit /set)": "system",
    "registry delete (reg delete)": "system",
    "registry value delete (Remove-ItemProperty -Force)": "system",
    "force stop service (Stop-Service -Force)": "system",
    "stop/delete service (sc)": "system",
    "access to SSH keys (Windows path)": "system",
    # another agent's settings
    "in-place edit of Hermes config/env": "other_agent",
    "in-place edit of Hermes config/env (long flag)": "other_agent",
    "in-place edit of Hermes config/env (perl/ruby)": "other_agent",
    "access to Hermes secrets (Windows path)": "other_agent",
    # inside the sandbox: just runs
    "script execution via -e/-c flag": "local",
    "script execution via heredoc": "local",
    "shell command via -c/-lc flag": "local",
    "shell execution via heredoc": "local",
    "chmod +x followed by immediate execution": "local",
    "world/other-writable permissions": "local",
    "recursive world/other-writable (long flag)": "local",
    "package manager uninstall": "local",
    "overwrite project env/config via tee": "local",
    "overwrite project env/config via redirection": "local",
    "overwrite project env/config file": "local",
    "disk copy": "local",
    "dynamic shell word may expand to arbitrary program execution flag": "local",
    "command parser limit or malformed executable payload": "local",
    "stop/restart hermes gateway (kills running agents)": "local",
    "hermes update (restarts gateway, kills running agents)": "local",
    "start gateway outside systemd (use 'systemctl --user restart hermes-gateway')": "local",
    "stop/restart hermes launchd service (kills running agents)": "local",
    "stop/restart hermes gateway via shell-spliced verb (kills running agents)": "local",
}
#: Descriptions Hermes builds at run time from a prefix.
HERMES_PREFIX_CATEGORIES: dict[str, str] = {"arbitrary program execution via ": "local"}


def hermes_category(description: str) -> str | None:
    """Where a Hermes description is placed; None for one this table does not know."""
    if description in HERMES_CATEGORIES:
        return HERMES_CATEGORIES[description]
    return next((c for p, c in HERMES_PREFIX_CATEGORIES.items() if description.startswith(p)), None)


_UNPLACED: set[str] = set()


def _placed(description: str) -> str:
    """A description's category; one the table does not know asks (destructive) and is logged
    once, so a re-vendored Hermes the guard test missed is visible, never silent."""
    category = hermes_category(description)
    if category is None:
        category = "destructive"
        if description not in _UNPLACED:
            _UNPLACED.add(description)
            logger.warning("terminal_policy: Hermes description %r has no category; it asks", description)
    return category


# Hermes' delete and SQL findings whose quoted arguments are data (§A9).
_HERMES_MASKED = frozenset({
    "delete in root path", "recursive delete", "recursive delete (long flag)",
    "recursive delete (flags after operands)", "xargs with rm", "find -exec/-execdir rm", "find -delete",
    "sudo with privilege flag (stdin/askpass/shell/list)", "sudo with combined-flag privilege escalation",
    "package manager uninstall"})
_HERMES_SQL = frozenset({"SQL DROP", "SQL DELETE without WHERE", "SQL TRUNCATE"})
_SQL_CLIENTS = frozenset({"sqlite3", "psql", "mysql", "mariadb", "duckdb", "clickhouse-client", "sqlcmd"})
_SHELLS = frozenset({"bash", "sh", "zsh", "dash", "ksh"})
_MALFORMED = hermes._MALFORMED_EXEC_DESCRIPTION

# ── Arslan's own rules (rule, pattern, why) — the rule is what "don't ask again" remembers ──
_FORBID = [
    ("keychain-secrets", _POS + r"security\s+(?:[^\n]*\s)?(?:find-(?:generic|internet)-password[^\n]*\s-w\b|"
                                r"find-(?:generic|internet)-password[^\n]*\s-g\b|dump-keychain|export\b)",
     "reads passwords out of the keychain"),
    ("arslan-keys", r"(?:\.arslan/secret_key|\.arslan-updater\.key|arslan-signing-backup)",
     "touches Arslan's own key files"),
    # Arslan has no terminal to type an admin password into, and should not act as root:
    # a command that needs sudo is one to hand to the user.
    ("sudo", r"(?:^|[\n;&|`(]|\$\()\s*sudo\b", "needs administrator rights; run it yourself"),
    # macOS roots Hermes' Linux-oriented floor does not name.
    ("macos-roots", _POS + r"rm\s+(?:-[^\s]*\s+)*(?:-[^\s]*[rR][^\s]*\s+)(?:-[^\s]*\s+)*"
                          r"[\"']?/(?:System|Library|Applications|Users|private|Volumes)/?[\"']?(?:\s|$|[;&|)])",
     "recursive delete of a macOS system folder"),
]
_ASK = [
    ("apple-events", _POS + r"osascript\b", "controls other apps (it could send, delete or buy)"),
    ("shortcuts", _POS + r"shortcuts\s+run\b", "runs one of your Shortcuts"),
    ("send-mail", _POS + r"(?:mail|mailx|sendmail|msmtp|mutt|himalaya\s+(?:send|write|reply|forward))\b",
     "sends email"),
    ("send-message", _POS + r"(?:imsg\s+send|xurl\b[^\n]*(?:post|tweet|/2/tweets))",
     "sends a message or posts"),
    ("upload", None, "sends data to a website"),
    ("remote-shell", None, "connects to another machine"),
    ("git-push", None, "publishes to a remote repository"),
    ("publish", _POS + r"(?:npm\s+publish|pnpm\s+publish|yarn\s+publish|twine\s+upload|cargo\s+publish|"
                       r"gh\s+(?:pr|issue|release|repo|gist)\s+(?:create|delete|merge|close|edit|comment)|"
                       r"gh\s+api\b[^\n]*-X\s*(?:POST|PUT|PATCH|DELETE))",
     "publishes or changes something online"),
    ("install", _POS + r"(?:brew\s+(?:install|reinstall|upgrade|tap)|pip3?\s+install|pipx\s+install|"
                       r"npm\s+(?:install|i)\s+(?:-g|--global)|gem\s+install|cargo\s+install)\b",
     "installs software"),
    ("login-items", None, "changes how your Mac starts or behaves"),
    ("delete", _POS + r"(?:rm|rmdir|unlink|trash|srm)\s", "deletes files"),
    # 0.1.61 §A2: what the sandbox cannot hold, named by Arslan.
    ("force-delete", None, "deletes files without asking for each (rm -f), or for good (srm)"),
    ("git-discard", None, "throws away changes git has not saved"),
    ("kill-force", None, "force-quits programs"),
    ("network-tool", None, "opens a raw connection to another machine"),
    ("system-settings", None, "changes a system setting (power, network, privacy, keychain items)"),
    ("start-files", None, "changes your shell or login start files"),
    ("other-agent", None, "changes another agent's settings"),
    ("screen-capture", None, "takes a screenshot"),
    ("terminal-app", None, "runs a script in Terminal, outside the sandbox"),
]
#: Rules matched with quoted arguments masked (§A9: text is not a command).
_MASKED_RULES = frozenset({"delete", "install", "sudo"})
_FORBID_C = [(k, re.compile(p, re.I), w) for k, p, w in _FORBID]
_ASK_C = [(k, re.compile(p, re.I), w) for k, p, w in _ASK if p is not None]
_WHY = {k: w for k, _, w in _FORBID + _ASK}
_WHY.update({"fetched-code": "runs code it downloads or decodes",
             "built-code": "runs code it builds while it runs",
             "unreadable": "Arslan could not read this command — run it?"})
_ARSLAN_DATA = re.compile(
    r"(?P<folder>Application\s*Support[\"']?/+[\"']?Arslan(?![\w.-]))"   # the data folder (and Hands')
    r"|(?:~|\$\{?HOME\}?)/+\.arslan"                             # ~/.arslan, ~/.arslan-updater.key
    r"|(?<![\w.-])arslan\.db\b", re.I)                           # the database, wherever it is named
#: Right after the data folder: `/skills/…`, imported skills (§C3), which commands may read and
#: run. The sandbox opens that folder read-only; writing it stays the floor (`_writes_arslan_data`).
_SKILLS_TAIL = re.compile(r"""["']?/+["']?skills(?P<rest>(?:["']?/[^\s;|&()<>`]*)?)(?=[\s;|&()<>`"']|$)""",
                          re.I)
_UP_LEVEL = re.compile(r"(?:^|/)\.\.(?:/|$|[\"'])")


@dataclass(frozen=True)
class Finding:
    category: str           # one of CATEGORIES
    rule: str               # the rule a "don't ask again" answer remembers ("upload", "hermes:…")
    why: str                # words for the card
    app: str = ""           # apps: the app or Shortcut as the text names it ("" = not known)
    kind: str = ""          # apps: "app" | "shortcut" | "app_risky" | "money"


@dataclass(frozen=True)
class Classification:
    command: str
    findings: tuple[Finding, ...]

    @property
    def floor(self) -> Finding | None:
        return next((f for f in self.findings if f.category == "floor"), None)

    @property
    def asking(self) -> tuple[Finding, ...]:
        """The findings that ask in Standard, most severe category first."""
        order = {c: i for i, c in enumerate(CATEGORIES)}
        return tuple(sorted((f for f in self.findings if f.category in ASKING),
                            key=lambda f: order[f.category]))

    @property
    def category(self) -> str:
        """The headline: floor, else the most severe asking category, else local."""
        if self.floor is not None:
            return "floor"
        asking = self.asking
        return asking[0].category if asking else "local"


@dataclass(frozen=True)
class Assessment:
    level: str              # "run" | "ask" | "forbid"
    rule: str = ""          # what "don't ask again" remembers; "" for run
    reason: str = ""


# ── what cannot be read asks (§A9; review I3, M3) ─────────────────────────────

#: A command Arslan could not read: an error while reading it, or one past a parse ceiling. It
#: asks as the `opaque` card, which is once only: never run unread, and never the floor, which no
#: click can lift. Its words are the card's title.
UNREADABLE = Finding("opaque", "unreadable", _WHY["unreadable"])
#: The parse ceilings (review M3, N6). Reading a command costs more with every substitution that
#: runs: with their number, their depth, and the text they span; with every command it holds, and
#: every wrapper word in front of one. Measured with none (loaded machine): 300 backticks 2.7 s,
#: 64 deep 3.7 s, 16 deep around 7 KB 26 s, 1,990 `env` words 17 s, 2,655 `(a)` 18 s. Real commands
#: open a handful of substitutions, one or two deep, run a few commands and wrap them once or
#: twice. One budget holds them all (`_Budget`): the command, each payload it hands a shell or
#: `eval`, each command a script runs. Past any ceiling a command is not read (the R3 path).
_MAX_SUBSTITUTIONS = 64           # backticks, `$(`, `<(`, `>(`, `=(` that run; and the commands one script runs
_MAX_SUBSTITUTION_DEPTH = 16      # a substitution inside a substitution
_MAX_BACKTICK_WORK = 64 * 1024    # backticks × the length of the text: 64 in 1 KB, 8 in 8 KB
_MAX_NESTED_WORK = 32 * 1024      # Σ depth² over the characters inside substitutions: any length 1 deep, 128 at 16
_MAX_SEPARATORS = 1024            # unquoted `;` `&` `|`, newlines and parentheses
_MAX_WRAPPERS = 16                # wrapper words in one simple command (`env`, `nohup`, `nice`, `xargs` …)
_MAX_CODE_DEPTH = 3               # code handed to a shell within code handed to a shell (`bash -c`, `eval`)
_MAX_READING = 4 * MAX_COMMAND_CHARS   # a command with the values R13 fills in


class _Unreadable(Exception):
    """A parse ceiling, or a command word known only at run time: the command is not read, and asks
    (`UNREADABLE`) unless a floor shows: `floor` holds what the reading found before it stopped."""

    def __init__(self, reason: str, floor: tuple[Finding, ...] = ()):
        super().__init__(reason)
        self.floor = floor


class _Budget:
    """What one `classify` has read (review N6): the load of the command and of every payload and
    script command read with it, summed against the ceilings, and each payload's commands, read once
    (`read`, by text and depth) — a payload written twice is not read twice. `payloads` keeps the
    code every shell and `eval` was handed, for the run-time code rules (R11, R13)."""
    __slots__ = ("marks", "deepest", "ticks", "nested", "separators", "read", "payloads")

    def __init__(self) -> None:
        self.marks = self.deepest = self.ticks = self.nested = self.separators = 0
        self.read: dict[tuple[str, int], list[list[str]]] = {}
        self.payloads: dict[str, None] = {}


#: The budget of the read in progress; None outside one. A command read inside another (what a
#: script or an AppleScript hands the shell) shares it, and is not memoized.
_BUDGET: contextvars.ContextVar[_Budget | None] = contextvars.ContextVar("terminal_policy_budget",
                                                                         default=None)


def as_shell(command: str, argv=None) -> str:
    """One shell string from either form the tool accepts ({command} or legacy {command, argv})."""
    command = str(command or "").strip()
    if not command:
        return ""          # argv alone is not a command; joining would run `'' <argv>`
    if isinstance(argv, list) and argv:
        command = shlex.join([command, *[str(a) for a in argv]])
    return command


# ── classify ──────────────────────────────────────────────────────────────────

def classify(command: str) -> Classification:
    """Every finding in a command. It never raises (the tool loop has no catch around it): an
    error while reading, or a command past a parse ceiling, is the floor its text shows, else
    `UNREADABLE` alone (review I3, amended by N3).

    Memoized (review N6: the live path classifies one command six times or more, on the event
    loop): by the text and by everything else a reading depends on (`_environment`); the answer is
    immutable. A command read inside another shares that read's budget and is read afresh."""
    text = str(command or "")
    if _BUDGET.get() is not None:
        return _classify(text)
    try:
        environment = _environment()
    except Exception:  # noqa: BLE001 — no key, no memo: read it afresh
        return _classify(text)
    return _classify_memoized(text, environment)


@functools.lru_cache(maxsize=512)
def _classify_memoized(text: str, environment: tuple) -> Classification:
    return _classify(text)


def clear_cache() -> None:
    """Forget every memoized classification (a test that patches what a reading depends on)."""
    _classify_memoized.cache_clear()


def _environment() -> tuple:
    """Everything besides its text that a reading depends on: the home folder (other agents' and
    start files), Arslan's data and working folders, and the files Hands' never-list is read from
    (the user's settings and the shipped policy), by path, modification time and size."""
    from server.services import hands_service
    key: list = [str(Path.home()), _data_dir_literal(), tuple(_data_roots())]
    for path in (hands_service._dir() / "settings.json", hands_service._policy_path()):
        try:
            stat = os.stat(path)
            key.append((str(path), stat.st_mtime_ns, stat.st_size))
        except OSError:
            key.append((str(path), None, None))
    return tuple(key)


def _classify(text: str) -> Classification:
    if not text.strip():
        return Classification(text, (Finding("floor", "empty", "no command"),))
    if len(text) > MAX_COMMAND_CHARS:
        return Classification(text, (Finding("floor", "too-long", "command is too long to review"),))
    if _BUDGET.get() is not None:       # read inside another command: what stops it stops that one
        return _unique(text, _read(text))
    try:
        findings = _read(text)
    except _Unreadable as ceiling:
        logger.info("terminal_policy: past a parse ceiling (%s), a command asks unread", ceiling)
        return Classification(text, tuple(dict.fromkeys(_floor_of_unread(text) + ceiling.floor))
                              or (UNREADABLE,))
    except Exception:  # noqa: BLE001 — never raise, never run it unread
        logger.warning("terminal_policy: could not read a command (%d characters); it asks unread",
                       len(text), exc_info=True)
        return Classification(text, _floor_of_unread(text) or (UNREADABLE,))
    return _unique(text, findings)


def _unique(text: str, findings: list[Finding]) -> Classification:
    seen: set[tuple] = set()
    unique = []
    for f in findings:
        key = (f.category, f.rule, f.app, f.kind)
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return Classification(text, tuple(unique))


#: For a command that could not be read: every quote, bracket, brace, backtick and separator is taken
#: as a command start (a run of them is one start, or `\s*` after `_CMDPOS` goes quadratic).
_FLAT_STARTS = re.compile(r"(?:\s*[;&|(){}`\n\"']\s*)+")
_FLAT_SUDO = re.compile(r"(?<![\w.-])(?:sudo|doas)(?![\w.-])", re.I)
_FLAT_KEYCHAIN = re.compile(r"(?<![\w.-])security\s+(?:dump-keychain|export|find-(?:generic|internet)-password\b"
                            r"[^\n]*\s-[a-zA-Z]*[wg])", re.I)
_FLAT_DISK = re.compile(r"(?<![\w.-])diskutil\s+(?:apfs\s+)?(?:erase\w*|zerodisk|randomdisk|secureerase|reformat"
                        r"|partitiondisk|deletecontainer|deletevolume)\b", re.I)


def _floor_of_unread(text: str) -> tuple[Finding, ...]:
    """The floor a command that could not be read shows in its text (review N3: padding a floor
    command past a ceiling must not turn "never" into a card asking "run it?"). Linear passes of
    the raw text, every quote and bracket taken as a command start: it over-reads on purpose, and
    the floor only refuses. The text is searched as written (`$'…'` decoded) and with the values
    R13 reads filled in (`${a:-rm} ${b:--rf} ~` is `rm -rf ~`). Never raises."""
    subjects = [text]
    try:
        subjects = [_decode_ansi_c(text)]
        reading = _readings(subjects[0])
        if reading != subjects[0]:
            subjects.append(reading)
    except Exception:  # noqa: BLE001 — what could be built is searched
        pass
    found: list[Finding] = []
    for subject in subjects:
        found += _floor_shown(subject)
    return tuple(dict.fromkeys(found))


def _floor_shown(text: str) -> list[Finding]:
    try:
        normalized = hermes._normalize_command_for_detection(text)
        flat = _FLAT_STARTS.sub("\n", normalized)
        found: list[Finding] = []
        for subject in (normalized.lower(), flat.lower()):
            hard = next((d for p, d, _ in hermes.HARDLINE_PATTERNS_COMPILED if p.search(subject)), "")
            if hard:
                found.append(Finding("floor", "hardline", hard))
                break
        found += [Finding("floor", k, w) for k, p, w in _FORBID_C if p.search(flat)]
        if _FLAT_SUDO.search(flat) or _SCRIPT_ADMIN.search(text):
            found.append(Finding("floor", "sudo", _WHY["sudo"]))
        if _FLAT_KEYCHAIN.search(flat):
            found.append(Finding("floor", "keychain-secrets", _WHY["keychain-secrets"]))
        if _FLAT_DISK.search(flat):
            found.append(Finding("floor", "disk-erase", "erases a disk"))
        if _touches_arslan_data(text):
            found.append(Finding("floor", "arslan-data", "touches Arslan's own data, keys or database"))
        return found
    except Exception:  # noqa: BLE001 — the unread card still asks
        return []


_ANSI_C_SIMPLE = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "e": "\x1b", "E": "\x1b", "f": "\f",
                  "v": "\v", "\\": "\\", "'": "'", '"': '"', "?": "?"}


def _decode_ansi_c(text: str) -> str:
    """Every `$'…'` outside quotes decoded as zsh decodes it (`\\'`, `\\\\`, `\\n`, `\\xHH`, `\\uHHHH`,
    `\\NNN` …) and written as a plain single-quoted word: `$'\\x67it' push` is `'git' push`, and
    `$'don\\'t'` no longer leaves the scanners in a quote that never closes (item 9). In double quotes
    `$'` is literal; a `$(…)` opens a fresh quoting level. Never raises."""
    if "$'" not in text:
        return text
    out: list[str] = []
    quotes: list[str | None] = [None]
    i, n = 0, len(text)
    while i < n:
        ch, quote = text[i], quotes[-1]
        if quote == "'":
            quotes[-1] = None if ch == "'" else quote
        elif ch == "\\":
            out.append(text[i:i + 2])
            i += 2
            continue
        elif quote is None and text.startswith("$'", i):
            value, i = _ansi_c_value(text, i + 2)
            out.append("'" + value.replace("'", "'\\''") + "'")
            continue
        elif ch == '"':
            quotes[-1] = None if quote == '"' else '"'
        elif ch == "'" and quote is None:
            quotes[-1] = "'"
        elif text.startswith("$(", i):
            quotes.append(None)
            out.append("$(")
            i += 2
            continue
        elif ch == ")" and quote is None and len(quotes) > 1:
            quotes.pop()
        out.append(ch)
        i += 1
    return "".join(out)


def _ansi_c_value(text: str, at: int) -> tuple[str, int]:
    """The decoded value of the `$'…'` whose content starts at `at`, and where the text resumes."""
    value: list[str] = []
    i, n = at, len(text)
    while i < n and text[i] != "'":
        if text[i] != "\\" or i + 1 >= n:
            value.append(text[i])
            i += 1
            continue
        c = text[i + 1]
        if c in _ANSI_C_SIMPLE:
            value.append(_ANSI_C_SIMPLE[c])
            i += 2
            continue
        digits, base, j = "", 16, i + 2
        if c in "xuU":
            width = {"x": 2, "u": 4, "U": 8}[c]
            while j < n and len(digits) < width and text[j] in "0123456789abcdefABCDEF":
                digits += text[j]
                j += 1
        elif c in "01234567":
            base, j = 8, i + 1
            while j < n and len(digits) < 3 and text[j] in "01234567":
                digits += text[j]
                j += 1
        try:
            value.append(chr(int(digits, base)) if digits else "\\" + c)
        except (ValueError, OverflowError):
            value.append("\\" + c)
        i = j if digits else i + 2
    return "".join(value), min(i + 1, n)


def _read(text: str) -> list[Finding]:
    """The findings of `classify`. Raises `_Unreadable` past a parse ceiling, and for a command word
    known only at run time (R13 d) once the whole command is read, with the floor it found. The
    command is read as zsh runs it (`_without_zsh_modifiers`), whose rewrites only take out or
    split: no text a floor pattern needs goes (`f()` stays, so `:(){ :|:& };:` is still the fork
    bomb); with the values R13 fills in read beside it (`_readings`)."""
    budget = _BUDGET.get()
    if budget is None:
        token = _BUDGET.set(_Budget())
        try:
            return _read(text)
        finally:
            _BUDGET.reset(token)
    text = _decode_ansi_c(text)
    shell, bodies = split_heredocs(text)
    _charge(shell)
    inner = _with_inner_backticks(shell)
    _charge(inner[len(shell):])
    shell = _without_zsh_modifiers(_readings(inner))
    commands = _commands(shell)
    findings: list[Finding] = []
    findings += _floor_findings(text, shell, commands)
    findings += _hermes_findings(shell, raw=text, commands=commands)
    findings += _arslan_findings(shell, commands, bodies)
    findings += _script_findings(commands, bodies)
    findings += _fetched_code_findings(shell)
    findings += _code_findings([shell, *budget.payloads])
    # A code word built by a substitution (`eval "$(…)"`) is that code's own card (R13 c).
    if (any(getattr(argv, "dynamic", False) for argv in commands)
            and not {f.rule for f in findings} & {"built-code", "fetched-code"}):
        raise _Unreadable("a command word known only at run time",
                          floor=tuple(f for f in findings if f.category == "floor"))
    return findings


def assess(command: str) -> Assessment:
    """The 0.1.48 view: forbid (the floor), ask (any other finding: the first, as the card names
    it), or run."""
    found = classify(command)
    floor = found.floor
    if floor is not None:
        return Assessment("forbid", floor.rule, floor.why)
    if found.findings:
        first = found.findings[0]
        return Assessment("ask", first.rule, first.why)
    return Assessment("run")


def ask_rules(command: str) -> set[str]:
    """Every rule the command matches, unless it reaches the floor (then none: nothing to answer)."""
    found = classify(command)
    if found.floor is not None:
        return set()
    return {f.rule for f in found.findings}


def standing_allows(command: str, allowed: set[str]) -> bool:
    """Whether the user's "don't ask again" answers cover this command: every rule it matches
    must be one of them. `osascript …; curl -d @file …` is "apple-events" to `assess`, but a
    standing answer for apple-events must not wave the upload through."""
    rules = ask_rules(command)
    return bool(rules) and not rules & _NEVER_REMEMBERED and rules <= allowed


def risk_grade(command: str) -> str:
    """The LOW/MEDIUM/HIGH grade the confirmation layer speaks (run/ask/forbid)."""
    return {"run": "LOW", "ask": "MEDIUM", "forbid": "HIGH"}[assess(command).level]


# ── heredocs and commands ─────────────────────────────────────────────────────

class _Level:
    """One level of shell text being scanned: the top, a `$(…)`/`<(…)` substitution, arithmetic,
    `${…}` or a backtick span; the quote open in it, its bracket depth, and where its current simple
    command started."""
    __slots__ = ("kind", "quote", "depth", "start")

    def __init__(self, kind: str, start: int, depth: int = 0):
        self.kind, self.quote, self.depth, self.start = kind, None, depth, start


#: What opens a level, longest first: (text, kind, bracket depth). In double quotes only the `$`
#: forms and the backtick open one.
_OPENERS = (("$((", "arith", 2), ("$(", "sub", 0), ("${", "brace", 1), ("$[", "bracket", 1), ("`", "tick", 0))
_UNQUOTED_OPENERS = (("((", "arith", 2), ("<(", "sub", 0), (">(", "sub", 0), ("=(", "sub", 0))
_CLOSERS = {"arith": "()", "bracket": "[]", "brace": "{}"}


def split_heredocs(text: str) -> tuple[str, list[tuple[str, str]]]:
    """(the command with every heredoc body that is data removed, [(program, body)]).

    A heredoc opens where the shell opens one: at the top or in a substitution, quoted or not
    (`git commit -m "$(cat <<'EOF' …)"`, review N7); never in quotes, a comment, arithmetic
    (`$((a<<b))`, `$[a<<b]`), `${…}` or a backtick span (item 8). Its delimiter is the shell word
    after `<<` with the quotes taken out (`E'OF'` and `E\\OF` are `EOF`, `"EOF"x` is `EOFx`), and
    the body ends at the first line that is exactly the delimiter (tabs stripped for `<<-`).

    A body is data for the program that reads it (`cat > README.md <<EOF` writes text, `python3 -
    <<EOF` reads code, `sqlite3 db <<SQL` reads SQL) and is taken out, so no shell rule and no
    ceiling sees it. It stays shell when a shell reads it: any word of its command is a shell, past
    wrappers and options (`nice -n 5 zsh <<EOF`), or one follows in its pipeline (`cat <<EOF | env
    zsh`). With an unquoted delimiter the shell still expands the body's `$(…)`, backticks and
    `${…}`: they stay, each on a line of its own as an argument of `:` (expanded, not run as a
    command word). A body with no closing line stays shell as well."""
    out: list[str] = []
    bodies: list[tuple[str, str]] = []
    levels = [_Level("top", 0)]
    pending: list[tuple[int, int, str, bool, bool, int]] = []    # (at, end, delimiter, quoted, tabs, command start)
    keep = i = 0
    n = len(text)
    while i < n:
        level, ch = levels[-1], text[i]
        if level.quote in ("'", "$'"):                           # single quotes: only their end counts
            if ch == "\\" and level.quote == "$'":
                i += 2
                continue
            if ch == "'":
                level.quote = None
            i += 1
            continue
        if ch == "\\":
            i += 2
            continue
        opened = next(((kind, len(o), depth) for o, kind, depth in _OPENERS if text.startswith(o, i)), None)
        if level.quote == '"':
            if ch == '"':
                level.quote = None
            elif opened:
                levels.append(_Level(opened[0], i + opened[1], opened[2]))
                i += opened[1]
                continue
            i += 1
            continue
        if level.kind == "tick" and ch == "`":
            levels.pop()
            i += 1
            continue
        if ch in "'\"":
            level.quote = "$'" if ch == "'" and i and text[i - 1] == "$" else ch
            i += 1
            continue
        if ch == "#" and level.kind in ("top", "sub") and (i == 0 or text[i - 1].isspace()
                                                          or text[i - 1] in ";&|()<>"):
            stop = text.find("\n", i)                           # a comment: up to its newline
            i = n if stop < 0 else stop
            continue
        opened = opened or next(((kind, len(o), depth) for o, kind, depth in _UNQUOTED_OPENERS
                                 if text.startswith(o, i)), None)
        if opened:
            levels.append(_Level(opened[0], i + opened[1], opened[2]))
            i += opened[1]
            continue
        if level.kind in _CLOSERS:                              # arithmetic, `${…}`: their brackets only
            pair = _CLOSERS[level.kind]
            level.depth += (ch == pair[0]) - (ch == pair[1])
            if level.depth <= 0:
                levels.pop()
            i += 1
            continue
        if level.kind == "tick":
            i += 1
            continue
        if ch == "(":                                           # the top or a substitution: shell
            level.depth += 1
            level.start = i + 1
        elif ch == ")":
            if level.depth:
                level.depth -= 1
            elif level.kind == "sub":
                levels.pop()
        elif ch in ";&|":
            level.start = i + 1
        elif text.startswith("<<", i) and not text.startswith("<<<", i) and (i == 0 or text[i - 1] != "<"):
            operator = _heredoc_operator(text, i)
            if operator is not None:
                pending.append((i, *operator, level.start))
                i = operator[0]
                continue
        elif ch == "\n":
            level.start = i + 1
            if pending:
                out.append(text[keep:i + 1])
                keep = i = _take_bodies(text, i, pending, out, bodies)
                pending = []
                continue
        i += 1
    out.append(text[keep:])
    return "".join(out), bodies


def _heredoc_operator(text: str, at: int) -> tuple[int, str, bool, bool] | None:
    """For the `<<` at `at`: (where its delimiter ends, the delimiter with its quotes taken out,
    whether any part of it was quoted, whether `<<-` strips tabs); None without a delimiter."""
    i = at + 2
    tabs = text.startswith("-", i)
    i += tabs
    while i < len(text) and text[i] in " \t":
        i += 1
    word, quoted, start = [], False, i
    while i < len(text) and text[i] not in " \t\n;&|()<>":
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            word.append(text[i + 1])
            quoted, i = True, i + 2
        elif ch in "'\"":
            close = text.find(ch, i + 1)
            close = len(text) if close < 0 else close
            word.append(text[i + 1:close])
            quoted, i = True, close + 1
        else:
            word.append(ch)
            i += 1
    return (i, "".join(word), quoted, tabs) if i > start else None


def _take_bodies(text: str, newline: int, pending, out: list[str], bodies: list[tuple[str, str]]) -> int:
    """The bodies of the heredocs opened on the line ending at `newline`, in order: each is data
    (taken out, `bodies`) or shell (kept in `out`). Returns where the text resumes."""
    pos = newline + 1
    for at, end_of_operator, delimiter, quoted, tabs, command_start in pending:
        start, end, after, closed = pos, len(text), len(text), False
        cursor = pos
        while cursor < len(text):
            stop = text.find("\n", cursor)
            stop = len(text) if stop < 0 else stop
            line = text[cursor:stop]
            if (line.lstrip("\t") if tabs else line) == delimiter:
                end, after, closed = cursor, min(stop + 1, len(text)), True
                break
            cursor = stop + 1
        head, rest, body = text[command_start:at], text[end_of_operator:newline], text[start:end]
        if _shell_reads_heredoc(head, rest):
            out.append(text[start:after])
        else:
            bodies.append((_heredoc_program(head), body))
            if not quoted:                      # the shell expands these before the program reads it
                out.extend(f": {expansion}\n" for expansion in _expansions(body))
            if not closed:                      # no closing line: shell as well, never only data
                out.append(text[start:after])
        pos = after
    return pos


def _words(text: str) -> list[str]:
    try:
        return shlex.split(text, posix=True)
    except ValueError:
        return text.split()


def _is_shell(word: str) -> bool:
    return os.path.basename(word.lstrip("=")).lower() in _SHELLS


def _shell_reads_heredoc(head: str, rest: str) -> bool:
    """Whether a shell reads a heredoc's body: a word of its command is a shell, before or after the
    `<<` (`nice -n 5 zsh <<EOF`, `<<EOF zsh`), or a shell follows in its pipeline (`| env zsh`)."""
    pipeline = re.split(r"\|\||&&|;|(?<![<>])&(?!>)", rest, maxsplit=1)[0]
    pieces = pipeline.split("|")
    return any(_is_shell(word) for word in _words(head) + _words(pieces[0])) or any(
        _is_shell(word) for piece in pieces[1:] for word in _words(piece))


def _heredoc_program(head: str) -> str:
    """The program a heredoc feeds: the first word of its command past assignments, wrappers with
    their options and values, zsh modifiers and `repeat N` (`nice -n 5 python3 -` feeds python3)."""
    wrappers = hermes._COMMAND_WRAPPER_WORDS | _RUNS_NEXT | _ZSH_MODIFIER_WORDS
    repeat_count = False
    for word in _words(head):
        if repeat_count:
            repeat_count = False
            continue
        name = os.path.basename(word.lstrip("=")).lower()
        if (re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", word) or name in wrappers or word.startswith("-")
                or re.fullmatch(r"\d+(?:\.\d+)?[smhd]?", word)):
            continue
        if name == "repeat":
            repeat_count = True
            continue
        return name
    return ""


def _expansions(body: str) -> list[str]:
    """The `$(…)`, backtick and `${…}` spans in an unquoted-delimiter heredoc body, which the shell
    runs (a `\\$` or `` \\` `` there is literal)."""
    found, i = [], 0
    while i < len(body):
        end = None
        if body[i] == "\\":
            i += 2
            continue
        if body.startswith("$(", i):
            end = hermes._scan_dollar_paren_end(body, i)
        elif body[i] == "`":
            end = hermes._scan_backtick_end(body, i)
        elif body.startswith("${", i):
            close = _closing_brace(body, i + 2)
            end = None if close is None else close + 1
        if end is not None:
            found.append(body[i:end])
            i = end
        else:
            i += 1
    return found


#: zsh precommand modifiers and keywords (run_command runs `/bin/zsh -c`): `noglob`, `nocorrect`, `-`
#: and `coproc` run the command after them, `=git` is git's own path, `repeat N` runs it N times (and
#: runs N's own substitutions), and `f() cmd` makes `cmd` a function body (review I2, N2).
_ZSH_MODIFIER = re.compile(r"(?:noglob|nocorrect|coproc|-)[ \t]+|=(?=[\w./~])")
_ZSH_REPEAT = re.compile(r"repeat[ \t]+")
_FUNCTION_HEAD = re.compile(r"(?:function[ \t]+)?[\w.:-]+[ \t]*\([ \t]*\)")
_ZSH_MODIFIER_WORDS = frozenset({"noglob", "nocorrect", "coproc", "-"})
_MAX_REWRITES = 16


def _without_zsh_modifiers(shell: str) -> str:
    """The command with what zsh reads before a command word taken out, so every rule, Hermes' text
    patterns too, sees the command that runs: `noglob sudo ls` is `sudo ls`, `exec noglob git push`
    is `exec git push`, `repeat $(rm -rf ~) true` is `: $(rm -rf ~)` then `true` (zsh expands the
    count), `f() git push` is `git push`, `{git push}` is `{git push` then `}` (review I2, N2, items
    12–13). Read at every command word, a wrapper's too, until nothing changes."""
    for _ in range(_MAX_REWRITES):
        rewritten = _rewrite_command_words(shell)
        if rewritten == shell:
            return shell
        shell = rewritten
    raise _Unreadable("zsh modifiers past the rewrite ceiling")


def _rewrite_command_words(shell: str) -> str:
    edits: set[tuple[int, int, str]] = set()
    starts = set(hermes._iter_shell_command_starts(shell))
    spans = list(hermes._iter_shell_command_word_spans(shell))
    for _start, end, word in spans:         # a case pattern is no command; after its `)` one starts (item 10)
        if hermes._deobfuscate_shell_word_for_detection(word) == "case":
            for start, close in _case_patterns(shell, end):
                pattern = re.sub(r"\s*\|\s*", "|", shell[start:close - 1].strip()).replace(": ", "")
                if not re.search(r"\s", pattern):                 # each alternative an argument of `:`
                    for at in [start] + [j for kind, i, j, quote in
                                         hermes._scan_shell(shell, start, close - 1, subst="uq", brace=True)
                                         if kind == "char" and quote is None and shell[i] == "|"]:
                        at = hermes._skip_shell_whitespace(shell, at)
                        if not shell.startswith(": ", at):
                            edits.add((at, at, ": "))
                if shell[close:close + 1] != "\n":
                    edits.add((close, close, "\n"))
    for at in starts | {start for start, _end, _word in spans}:
        if _follows_redirect(shell, at):    # Hermes starts a command after `2>&`: `2>&- -d` is no `- -d`
            continue
        end = at
        while True:
            if (match := _ZSH_MODIFIER.match(shell, end)) is not None:
                edits.add((end, match.end(), ""))
                end = match.end()
            elif (match := _FUNCTION_HEAD.match(shell, end)) is not None:
                if shell[match.end():match.end() + 1] != "\n":     # `f()` stays: `:(){ :|:& };:` is read
                    edits.add((match.end(), match.end(), "\n"))
                end = match.end()
            elif (match := _ZSH_REPEAT.match(shell, end)) is not None:
                count_end = _word_end(shell, match.end())
                if count_end == match.end():
                    break                   # the count is expanded, not run: `: C` then the command
                edits |= {(end, match.end(), ": "), (count_end, count_end, "\n")}
                end = hermes._skip_shell_whitespace(shell, count_end)
            else:
                break
    for at in starts:                       # `{git push}`: zsh closes the group at a `}` with no space
        if at and shell[at - 1] == "{":
            close = _closing_brace(shell, at)
            if close is not None and not shell[close - 1].isspace() and shell[close - 1] != ";":
                edits.add((close, close, "\n"))
    kept, cursor = [], 0
    for edit in sorted(edits):
        if edit[0] >= cursor:
            kept.append(edit)
            cursor = edit[1]
    return hermes._splice(shell, kept) if kept else shell


def _case_patterns(shell: str, at: int) -> list[tuple[int, int]]:
    """(where each pattern starts, just after its `)`) in the `case` whose subject starts at `at`
    (`case a in a) sudo ls;; esac`): a pattern is no command (`*.md)` is no glob run as one), and a
    command starts after its `)`. A pattern with a blank in it is left as it is (zsh refuses it,
    and it is read as the command it looks like). The clauses end at `;;`, `;&` or `;|`."""
    _start, pos, _subject = hermes._read_shell_word(shell, at)
    _start, pos, word = hermes._read_shell_word(shell, pos)
    patterns: list[tuple[int, int]] = []
    if word != "in":
        return patterns
    while True:
        pos = hermes._skip_shell_whitespace(shell, pos)
        if pos >= len(shell) or re.match(r"esac(?![\w-])", shell[pos:pos + 5]):
            return patterns
        pos += shell[pos] == "("
        close = _pattern_close(shell, pos)
        if close is None:
            return patterns
        patterns.append((pos, close + 1))
        pos = _clause_end(shell, close + 1)
        if pos is None:
            return patterns


def _pattern_close(shell: str, at: int) -> int | None:
    depth = 0
    for kind, i, _j, quote in hermes._scan_shell(shell, at, subst="uq", brace=True):
        if kind != "char" or quote is not None:
            continue
        if shell[i] == "(":
            depth += 1
        elif shell[i] == ")":
            if not depth:
                return i
            depth -= 1
        elif shell[i] in ";\n" and not depth:
            return None
    return None


def _clause_end(shell: str, at: int) -> int | None:
    depth = 0
    for kind, i, _j, quote in hermes._scan_shell(shell, at, subst="uq", brace=True, comments=True):
        if kind != "char" or quote is not None:
            continue
        if shell[i] == "(":
            depth += 1
        elif shell[i] == ")":
            depth = max(depth - 1, 0)
        elif shell[i] == ";" and not depth and shell[i + 1:i + 2] in (";", "&", "|"):
            return i + 2
    return None


def _with_inner_backticks(shell: str) -> str:
    """The command with each backtick body that holds an escaped backtick or `$` added again,
    unescaped, on a line of its own: ``echo "`echo \\`sudo ls\\``"`` runs `sudo ls` (item 10)."""
    added, pending, seen = [], [shell], set()
    while pending and len(added) < _MAX_SUBSTITUTIONS:
        text = pending.pop()
        for kind, i, j, _quote in hermes._scan_shell(text, subst="uq"):
            if kind != "subst" or j is None:
                continue
            if text[i] == "`":
                body = text[i + 1:j - 1]
                inner = body.replace("\\\\", "\0").replace("\\`", "`").replace("\\$", "$").replace("\0", "\\")
                if inner != body and inner not in seen:
                    seen.add(inner)
                    added.append(inner)
                    pending.append(inner)
            elif text.startswith("$(", i):
                pending.append(text[i + 2:j - 1])
    return shell + "".join(f"\n{line}" for line in added)


def _word_end(text: str, at: int) -> int:
    """Where the shell word at `at` ends: unquoted whitespace or `;&|<>` outside parentheses and
    backticks. `$((1))` is one word (`hermes._read_shell_word` ends it one `)` early)."""
    depth, tick = 0, False
    for kind, i, _j, quote in hermes._scan_shell(text, at):
        if kind != "char" or quote is not None:
            continue
        ch = text[i]
        if ch == "`":
            tick = not tick
        elif tick:
            continue
        elif ch == "(":
            depth += 1
        elif ch == ")":
            if not depth:
                return i
            depth -= 1
        elif not depth and (ch.isspace() or ch in ";&|<>"):
            return i
    return len(text)


def _closing_brace(text: str, at: int) -> int | None:
    """The `}` that closes the brace group whose body starts at `at` (`${…}` is not a group)."""
    depth = 0
    for kind, i, _j, quote in hermes._scan_shell(text, at, subst="uq", brace=True):
        if kind != "char" or quote is not None:
            continue
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            if not depth:
                return i
            depth -= 1
    return None


def _charge(*texts: str) -> None:
    """Add what reading the texts costs to the read's one budget, and raise `_Unreadable` once it
    passes a ceiling (review M3, N6): the command, then each payload before `_commands` reads it,
    then each command a script runs — a cost split over many payloads is still one cost. Outside a
    read the texts are measured alone."""
    budget = _BUDGET.get() or _Budget()
    for text in texts:
        marks, depth, backticks, nested, separators = _substitution_load(text)
        budget.marks += marks
        budget.deepest = max(budget.deepest, depth)
        budget.ticks += backticks * len(text)
        budget.nested += nested
        budget.separators += separators
        wrappers = _most_wrappers(text)
        if wrappers > _MAX_WRAPPERS:
            raise _Unreadable(f"{wrappers} wrapper words in one command")
    if budget.marks > _MAX_SUBSTITUTIONS:
        raise _Unreadable(f"{budget.marks} substitutions")
    if budget.deepest > _MAX_SUBSTITUTION_DEPTH:
        raise _Unreadable(f"substitutions {budget.deepest} deep")
    if budget.ticks > _MAX_BACKTICK_WORK:
        raise _Unreadable(f"backticks over {budget.ticks} characters")
    if budget.nested > _MAX_NESTED_WORK:
        raise _Unreadable(f"nested substitutions weighing {budget.nested}")
    if budget.separators > _MAX_SEPARATORS:
        raise _Unreadable(f"{budget.separators} separators")


def _check_nested(commands: list[str], what: str) -> None:
    """The commands a script hands the system are each read in full (`classify`, in this read's
    budget): at most `_MAX_SUBSTITUTIONS` of them."""
    if len(commands) > _MAX_SUBSTITUTIONS:
        raise _Unreadable(f"{what} runs {len(commands)} commands")


def _substitution_load(text: str) -> tuple[int, int, int, int, int]:
    """(the backticks and substitutions that run — `$(`, and unquoted `<(`, `>(`, `=(` —, how deep
    the substitutions nest, the backticks, Σ depth² over the characters inside substitutions, the
    separators: unquoted `;` `&` `|`, newlines and parentheses), in one pass that never raises.
    Nothing in single quotes runs; in double quotes `$(` does, and each substitution opens a fresh
    quoting level until its `)` (a `(` opened inside it closes first). Approximate on purpose: it
    only bounds the reading, it never decides a card."""
    marks = deepest = backticks = nested = separators = 0
    quotes: list[str | None] = [None]           # the quote open at each substitution level
    parens = [0]                                # the `(` open at each level, closed before it
    i, n = 0, len(text)
    while i < n:
        ch, quote = text[i], quotes[-1]
        nested += (len(quotes) - 1) ** 2
        if quote == "'":
            if ch == "'":
                quotes[-1] = None
        elif ch == "\\":
            i += 1                              # the next character is escaped
        elif ch == "'" and quote is None:
            quotes[-1] = "'"
        elif ch == '"':
            quotes[-1] = None if quote == '"' else '"'
        elif ch == "`":
            marks += 1
            backticks += 1
        elif text.startswith("$(", i) or (quote is None and ch in "<>=" and text.startswith("(", i + 1)):
            marks += 1
            quotes.append(None)
            parens.append(0)
            deepest = max(deepest, len(quotes) - 1)
            i += 1
        elif quote is None and ch == "(":
            parens[-1] += 1
            separators += 1
        elif quote is None and ch == ")":
            separators += 1
            if parens[-1]:
                parens[-1] -= 1
            elif len(quotes) > 1:
                quotes.pop()
                parens.pop()
        elif quote is None and ch in ";&|\n":
            separators += 1
        i += 1
    return marks, deepest, backticks, nested, separators


def _most_wrappers(text: str) -> int:
    """The most wrapper words any one simple command of `text` holds, quoted words as data, in one
    linear pass (review N6: 1,990 `env` read in 17 s). A redirection (`2>&1`) ends no command."""
    most = count = 0
    for token in _SHELL_TOKEN.finditer(text):
        word = token.group()
        if word in _COMMAND_ENDS:
            count = 0
        elif os.path.basename(word.strip("'\"").lstrip("=")).lower() in _WRAPPER_NAMES:
            count += 1
            most = max(most, count)
    return most


#: Programs that run the command written after their own options: what they run is read too.
_RUNS_NEXT = frozenset({"xargs", "watch", "caffeinate", "arch", "ionice", "stdbuf", "unbuffer", "chronic",
                        "flock", "parallel", "npx", "bunx", "pnpx", "uvx"})
#: Package runners, and the subcommand after which they run a command (`uv run twine upload`).
_RUNNER_RUNS = {"uv": {"run"}, "poetry": {"run"}, "pdm": {"run"}, "pipx": {"run"}, "npm": {"exec"},
                "pnpm": {"exec", "dlx"}, "yarn": {"dlx"}, "pipenv": {"run"}, "bundle": {"exec"},
                "mise": {"exec", "x"}, "rye": {"run"}, "pixi": {"run"}, "hatch": {"run"}, "conda": {"run"},
                "asdf": {"exec"}, "direnv": {"exec"}}
_FIND_RUNS = ("-exec", "-execdir", "-ok", "-okdir")
#: The words that run the command after them, which a command may stack (`env env … git push`).
_WRAPPER_NAMES = hermes._COMMAND_WRAPPER_WORDS | _RUNS_NEXT | {"noglob", "nocorrect", "coproc", "repeat"}
_SHELL_TOKEN = re.compile(r"""'[^']*'|"(?:\\.|[^"\\])*"|\d*[<>]&|&>>?|[^\s;&|()<>`'"]+|[;&|()`\n<>]""")
_COMMAND_ENDS = frozenset({";", "&", "|", "(", ")", "`", "\n"})


def _commands(text: str, depth: int = 0) -> list[list[str]]:
    """The argv of every simple command in `text`, quote-aware (Hermes' own tokenizer): wrappers
    (`sudo`, `env`, `nohup`) appear with the command they run and as that command alone; what a
    shell runs (`bash -c '…'`, `eval '…'`) and what `xargs`, `find -exec`, `watch` … run appear as
    their own commands. Each command is read to where it ends (`;` `|` `&`, or the `)` or backtick
    closing the substitution it is in): from `git`, the rest of `echo "$(git push)"` ends in the
    enclosing quote, which shlex refused, and the command was dropped (review C1). Code handed to a
    shell is read `_MAX_CODE_DEPTH` levels down; deeper, the command asks unread.

    A payload is charged to the read's budget before it is read, and each (text, depth) is read
    once per `classify` (review N6). A command word known only at run time marks its argv
    `dynamic` (R13 d): `_read` then asks unread."""
    budget = _BUDGET.get()
    if budget is not None and (text, depth) in budget.read:
        return list(budget.read[text, depth])
    if depth:
        _charge(text)
    out: list[list[str]] = []

    def add(tokens: list[str], stdin_code: str | None = None) -> None:
        out.append(tokens)
        name = _name(tokens)
        payload = (" ".join(tokens[1:]) if name == "eval"
                   else hermes._bash_exec_payload(tokens[1:])[1] if name in _SHELLS else None)
        payload = payload or stdin_code
        if payload:
            if depth >= _MAX_CODE_DEPTH:
                raise _Unreadable(f"code nested more than {_MAX_CODE_DEPTH} deep")
            if budget is not None:
                budget.payloads[payload] = None
            out.extend(_commands(payload, depth + 1))

    for segment in _top_level_segments(text):
        quiet = _quiet_ranges(segment)
        for start, raw, bounded in _spans(segment):
            rest = bounded[len(raw):] if bounded.startswith(raw) else bounded
            tokens = hermes._shell_segment_tokens(rest, 0)
            if tokens is None:              # quoting the shell would refuse: read it word by word
                tokens = rest.split()
            # The command word is read as written (`$(which git)` is one word, which the tokenizer
            # split); no closer sticks to the last word any more (`(git push)` is `git push`), and
            # stripping one would cut a substitution argument short (`bash -c "$(curl …)"`).
            word, dynamic = _command_word(raw)
            argv = _Argv(t for t in [word, *tokens] if t)
            if not argv:                # `''` alone: no command word, nothing runs (an empty argv raised)
                continue
            argv.dynamic = dynamic and not any(a <= start < b for a, b in quiet)
            add(argv, _here_string_code(bounded))
            for inner in _run_by(argv):
                if _name(argv) == "find":   # `-exec "$cmd" {} \;` runs a command known only then
                    inner = _Argv(inner)
                    inner.dynamic = _command_word(inner[0])[1]
                add(inner)
    if budget is not None:
        budget.read[text, depth] = out
    return list(out)


class _Argv(list):
    """One command's words. `dynamic`: its command word is known only at run time (R13 d)."""
    dynamic = False


def _spans(segment: str):
    """Hermes' command words in `segment`, each as (start, the word as written, its command's text
    as written), clipped at the backtick that closes the backtick span the word sits in: Hermes
    reads ``a` `b` `` as the word in ``echo `a` `b` ``, and its command on into the next span."""
    ticks = _tick_spans(segment)
    for start, end, _word in hermes._iter_shell_command_word_spans(segment):
        bounded = _command_text(segment, start)
        close = next((b for a, b in ticks if a < start < b), None)
        if close is not None:
            end = min(end, close)
            bounded = bounded[:close - start].rstrip()
        yield start, segment[start:end], bounded


def _tick_spans(text: str) -> list[tuple[int, int]]:
    """(opening, closing) backtick of each backtick span in `text`: outside them single quotes hide
    a backtick; inside, the first one no backslash escapes closes the span."""
    spans: list[tuple[int, int]] = []
    quote, i, n = None, 0, len(text)
    while i < n:
        ch = text[i]
        if quote == "'":
            if ch == "'":
                quote = None
        elif ch == "\\":
            i += 1
        elif ch == "'" and quote is None:
            quote = "'"
        elif ch == '"':
            quote = None if quote == '"' else '"'
        elif ch == "`":
            end = hermes._scan_backtick_end(text, i)
            if end is None:
                break
            spans.append((i, end - 1))
            i = end
            continue
        i += 1
    return spans


def _command_text(segment: str, start: int) -> str:
    """The simple command starting at `start`: to the first unquoted `;` `&` `|`, newline or comment,
    or the `)` or backtick closing the substitution it sits in. A `(` opened inside the command
    (`<(…)`, `>(…)`, `=(…)`, a glob qualifier `*(.)`) closes inside it: its `)` does not end the
    command, which dropped every later argument (review N1)."""
    depth, end = 0, len(segment)
    for kind, i, _j, quote in hermes._scan_shell(segment, start, subst="uq", brace=True, comments=True):
        if kind == "comment":
            end = i
            break
        if kind != "char" or quote is not None:
            continue
        ch = segment[i]
        if ch == "(":
            depth += 1
        elif ch == ")" and depth:
            depth -= 1
        elif ch in ";&|\n)`" and not depth and not _redirect_amp(segment, i):
            end = i
            break
    return segment[start:end].strip()


def _redirect_amp(text: str, i: int) -> bool:
    """Whether the `&` at `i` belongs to a redirection (`2>&1`, `>&2`, `<&3`, `>&-`, `&>f`, `&>>f`),
    which ends no command (item 14)."""
    return text[i] == "&" and ((i > 0 and text[i - 1] in "<>") or text[i + 1:i + 2] == ">")


def _follows_redirect(text: str, at: int) -> bool:
    j = at - 1
    while j >= 0 and text[j] in " \t":
        j -= 1
    return j >= 0 and _redirect_amp(text, j)


def _top_level_segments(text: str):
    """Hermes' top-level command segments, except that a redirection's `&` splits nothing:
    `curl URL 2>&1 -d @f` is one command, not `curl URL 2>` and `1 -d @f` (item 14)."""
    start = 0
    for kind, i, j, quote in hermes._scan_shell(text, comments=True):
        if kind == "comment" or (kind == "char" and quote is None and text[i] in ";&|\n"
                                 and not _redirect_amp(text, i)):
            if start < i:
                yield text[start:i]
            start = j
    if start < len(text):
        yield text[start:]


def _run_by(argv: list[str]) -> list[list[str]]:
    """The commands `argv` runs on its own: `find … -exec CMD … ;` and, for the programs in
    `_RUNS_NEXT`, each of the first few non-option words with what follows it (an option's value
    may come first; a wrong start only reads a harmless extra word as a command)."""
    name = _name(argv)
    if name == "find":
        out, i = [], 0
        while i < len(argv):
            if argv[i] in _FIND_RUNS:
                j = i + 1
                while j < len(argv) and argv[j] not in (";", "+", "\\;"):
                    j += 1
                if j > i + 1:
                    out.append(argv[i + 1:j])
                i = j
            i += 1
        return out
    if name in _RUNS_NEXT:
        return [argv[i:] for i in range(1, len(argv)) if not argv[i].startswith("-")][:4]
    if name in _RUNNER_RUNS:                        # review M2: `uv run`, `npm exec`, `pnpm dlx` …
        at = next((i for i in range(1, len(argv)) if argv[i] in _RUNNER_RUNS[name]), None)
        return [] if at is None else [argv[i:] for i in range(at + 1, len(argv))
                                      if not argv[i].startswith("-")][:4]
    return []


def _name(argv: list[str]) -> str:
    return os.path.basename(argv[0]).lower() if argv else ""


def _detection_texts(text: str) -> tuple[str, ...]:
    """The forms Arslan's own rules are matched against: as written (quoted newlines masked: they
    are data), normalized, and Hermes' variants with a newline at every real (quote-aware) command
    start. `_POS` anchors at a newline, not at `;` `&&` `|` `(`, so without the variants only the
    first command of a chain was checked: `ls && git push` ran with no card."""
    return (hermes._mask_quoted_newlines(text), *hermes._command_detection_variants(text))


def _masked(texts: tuple[str, ...]) -> tuple[str, ...]:
    """The same texts with quoted arguments blanked, except where a shell runs them."""
    return tuple(t if hermes._contains_shell_carrier(t) else hermes._mask_quoted_prose(t) for t in texts)


def _matches(pattern, texts) -> bool:
    return any(pattern.search(t) for t in texts)


# ── what is known only at run time: names, values, code (R11, R13) ────────────

_NAME_AT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_DEFAULT_AT = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(:?[-=+])")
_PLAIN_AT = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_VALUE = r"""(?:'[^'\n]*'|"[^"\\$`\n]*"|[^\s;&|()<>'"`$\\]*)"""
_ASSIGNMENTS_AT = re.compile(r"[ \t]*(?:export[ \t]+)?((?:[A-Za-z_][A-Za-z0-9_]*=" + _VALUE + r"[ \t]+)*"
                             r"[A-Za-z_][A-Za-z0-9_]*=" + _VALUE + r")[ \t]*(?:;|&&|\n)")
_ONE_ASSIGNMENT = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=(" + _VALUE + ")")
_SAFE_VALUE = re.compile(r"[A-Za-z0-9_./:@%+,-]*")


def _readings(text: str) -> str:
    """The command as the rules read it when words come from variables (R13 a, b), else `text`.

    (a) `${name<op>word}` (op `:-` `-` `:=` `=` `:+` `+`) is `word` — or, since the variable may be
    set (zsh sets `ZSH_NAME`; the home is always set), the variable itself: `${name}`, or nothing
    for `:+`/`+`. Both readings are read, one after the other, so `git ${x:-push}` is a push and
    `${ZSH_NAME:-true} -c 'git push'` keeps a command word known only at run time.
    (b) `$name` and `${name}` are the value a literal one-word assignment opening the command
    gives them (`_known_values`: `x=git; $x push`, `export x=git && ${x} push`)."""
    if "$" not in text:
        return text
    known = _known_values(text)
    as_name = _with_values(text, known, as_word=False)
    as_word = _with_values(text, known, as_word=True)
    reading = as_name if as_name == as_word else as_name + "\n" + as_word
    if len(reading) > _MAX_READING:
        raise _Unreadable("the values read into the command make it too long")
    return reading


def _known_values(text: str) -> dict[str, str]:
    """(R13 b) The variables the command sets first, to a literal word: only the assignments that
    open it (assignments alone, `export` too, joined by `;`, `&&` or a newline: they always run),
    and only names the rest of the command never sets again (`for x`, `read x`, `x+=`, `${x:=…}` …)
    — anything else leaves the variable unknown, and a command word built from it asks."""
    known: dict[str, str] = {}
    pos = 0
    while (opening := _ASSIGNMENTS_AT.match(text, pos)) is not None:
        for name, value in _ONE_ASSIGNMENT.findall(opening.group(1)):
            value = value[1:-1] if value[:1] in ("'", '"') else value
            if _SAFE_VALUE.fullmatch(value):
                known[name] = value
            else:
                known.pop(name, None)
        pos = opening.end()
    rest = text[pos:]
    for name in list(known):
        if (re.search(r"""(?:^|[\s;&|(){}`'"])""" + name + r"""(?:\+?=|\[|(?=[\s;&|()`'"]|$))""", rest)
                or re.search(r"\$\{" + name + r":{0,2}=", rest)):
            del known[name]
    return known


def _with_values(text: str, known: dict[str, str], *, as_word: bool) -> str:
    """`text` with each default form read as its word (`as_word`) or as its variable, and each known
    variable as its value. Nothing in single quotes expands; `$(…)` and `${…}` quote afresh. One
    linear pass: a default form read as its word drops its `${name<op>` and its `}`."""
    out: list[str] = []
    levels: list[list] = [[None, "top", 0]]             # [quote, kind, open brackets]
    i, n = 0, len(text)
    while i < n:
        level, ch = levels[-1], text[i]
        if level[0] == "'":
            level[0] = None if ch == "'" else "'"
            out.append(ch)
            i += 1
            continue
        if ch == "\\":
            out.append(text[i:i + 2])
            i += 2
            continue
        if ch == "$":
            default = _DEFAULT_AT.match(text, i)
            if default is not None and as_word:
                levels.append([None, "default", 0])
                i = default.end()
                continue
            if default is not None:
                close = _closing_brace(text, default.end())
                if close is None:                           # zsh refuses it: nothing runs
                    out.append(text[i:])
                    break
                name, op = default.groups()
                out.append("" if op.endswith("+") else known.get(name, "${" + name + "}"))
                i = close + 1
                continue
            plain = _PLAIN_AT.match(text, i)
            if plain is not None and plain.group(1) in known:
                out.append(known[plain.group(1)])
                i = plain.end()
                continue
            name = _NAME_AT.match(text, i + 1)
            if name is not None and name.group() in known and text[name.end():name.end() + 1] not in ("[", ":"):
                out.append(known[name.group()])             # not `$x[1]` or `$x:t`: zsh reads those apart
                i = name.end()
                continue
            if text.startswith(("$(", "${"), i):
                levels.append([None, "sub" if text[i + 1] == "(" else "brace", 0])
                out.append(text[i:i + 2])
                i += 2
                continue
        elif ch == '"':
            level[0] = None if level[0] == '"' else '"'
        elif ch == "'" and level[0] is None:
            level[0] = "'"
        elif level[0] is None and ch in "({":
            level[2] += 1
        elif level[0] is None and ch in ")}":
            if level[2]:
                level[2] -= 1
            elif (ch == ")") == (level[1] == "sub") and level[1] != "top":
                levels.pop()
                if level[1] == "default":
                    i += 1
                    continue
        out.append(ch)
        i += 1
    return "".join(out)


#: Set-up commands whose output a shell runs as it starts (R13 c): `eval "$(brew shellenv)"` needs
#: no card. Exactly these, by name and subcommand.
_SET_UP = (("ssh-agent",), ("brew", "shellenv"), ("pyenv", "init"), ("pyenv", "virtualenv-init"),
           ("rbenv", "init"), ("nodenv", "init"), ("goenv", "init"), ("jenv", "init"), ("direnv", "hook"),
           ("direnv", "export"), ("fnm", "env"), ("mise", "activate"), ("mise", "env"), ("starship", "init"),
           ("zoxide", "init"), ("opam", "env"))
_WHICH = re.compile(r"(?:\$\(|`)[ \t]*(?:which|command[ \t]+-v)[ \t]+([A-Za-z0-9_.+-]+)[ \t]*(?:\)|`)")
_ASSIGNMENT_AT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\[[^\]]*\])?\+?=")
_GLOB = re.compile(r"[*?]|\[.*\]|\{[^{}]*(?:,|\.\.)[^{}]*\}")


def _command_word(raw: str) -> tuple[str, bool]:
    """The program a command word names, and whether it is known only at run time (R13 d). Hermes
    reads `\\git` and `g"it"` as `git`. A word the shell computes — `$x`, `"$cmd"`, `$(…)`, a backtick
    span, a glob — is read by the literal name after a `/` that follows its last expansion
    (`"$VIRTUAL_ENV/bin/python"` is python), as X for `$(which X)` / `$(command -v X)` /
    `` `which X` ``, and as the set-up a shell runs for `$(brew shellenv)` and its kind; anything
    else is dynamic."""
    word = hermes._deobfuscate_shell_word_for_detection(raw)
    last = _last_expansion_end(raw)
    if last is None or _ASSIGNMENT_AT.match(raw):      # `arr[1]=$(date)` assigns: no command word
        return word, False
    bare = raw[1:-1] if len(raw) > 1 and raw[0] == raw[-1] == '"' else raw
    which = _WHICH.fullmatch(bare)
    if which is not None:
        return which.group(1), False
    if (bare.startswith("$(") and _paren_end(bare, 1) == len(bare) and _sets_up_environment(bare[2:-1])
            or bare.startswith("`") and hermes._scan_backtick_end(bare, 0) == len(bare)
            and _sets_up_environment(bare[1:-1])):
        return word, False
    tail = raw[last:].replace('"', "").replace("'", "").replace("\\", "")
    name = tail.rpartition("/")[2]
    return word, not ("/" in tail and name and not _GLOB.search(name))


def _last_expansion_end(word: str) -> int | None:
    """Where the last part of `word` the shell computes ends (a parameter, a substitution, a glob
    outside quotes), or None when it computes none."""
    last, quote, i, n = None, None, 0, len(word)
    while i < n:
        ch = word[i]
        if quote == "'":
            quote = None if ch == "'" else "'"
            i += 1
            continue
        if ch == "\\":
            i += 2
            continue
        end = None
        if ch == '"':
            quote = None if quote == '"' else '"'
        elif ch == "'" and quote is None:
            quote = "'"
        elif ch == "$" and word.startswith("$(", i):
            end = _paren_end(word, i + 1) or n
        elif ch == "$" and word.startswith("${", i):
            close = _closing_brace(word, i + 2)
            end = n if close is None else close + 1
        elif ch == "$" and word.startswith("$[", i):
            close = word.find("]", i)
            end = n if close < 0 else close + 1
        elif ch == "$" and i + 1 < n and (word[i + 1].isalnum() or word[i + 1] in "_#?@*!$-"):
            name = _NAME_AT.match(word, i + 1)
            end = name.end() if name is not None and not word[i + 1].isdigit() else i + 2
        elif ch == "`":
            end = hermes._scan_backtick_end(word, i) or n
        elif quote is None and ch in "<>=" and i == 0 and word.startswith("(", 1):
            end = _paren_end(word, 1) or n
        elif quote is None and (ch in "*?" or (ch == "[" and "]" in word[i + 1:])
                                or (ch == "{" and _GLOB.match(word, i))):
            end = i + 1
        if end is not None:
            last = i = max(end, i + 1)
            continue
        i += 1
    return last


def _paren_end(text: str, at: int) -> int | None:
    """Just past the `)` closing the `(` at `at`, or None. Quotes are read per level: in double
    quotes only `$(` opens one, and its quotes are its own."""
    levels = [[None, 0]]                                # [quote, open parentheses]
    i, n = at + 1, len(text)
    while i < n:
        level, ch = levels[-1], text[i]
        if level[0] == "'":
            if ch == "'":
                level[0] = None
        elif ch == "\\":
            i += 1
        elif ch == "`":
            end = hermes._scan_backtick_end(text, i)
            if end is None:
                return None
            i = end
            continue
        elif text.startswith("$(", i):
            levels.append([None, 0])
            i += 2
            continue
        elif level[0] == '"':
            if ch == '"':
                level[0] = None
        elif ch in "'\"":
            level[0] = ch
        elif ch == "(":
            level[1] += 1
        elif ch == ")":
            if level[1]:
                level[1] -= 1
            elif len(levels) > 1:
                levels.pop()
            else:
                return i + 1
        i += 1
    return None


_QUIET = {"arith": "()", "bracket": "[]", "brace": "{}", "array": "()"}
_OPENED = {"(": "sub", "{": "brace", "[": "bracket"}


def _quiet_ranges(text: str) -> list[tuple[int, int]]:
    """Where `text` holds no command: arithmetic (`$((…))`, `((…))`, `$[…]`), `${…}` and an array
    `name=(…)`, minus the substitutions opened inside them, which run (`$(( $(git push) ))`).
    Hermes takes `$a` in `$(( $a + 1 ))` for a command word; R13 (d) must not ask for it."""
    ranges: list[tuple[int, int]] = []
    levels: list[list] = [["top", None, 0]]            # [kind, quote, open brackets]
    begun: int | None = None
    i, n = 0, len(text)
    while i < n:
        level, ch = levels[-1], text[i]
        kind, quote, step = level[0], level[1], 1
        if quote == "'":
            if ch == "'":
                level[1] = None
        elif ch == "\\":
            step = 2
        elif text.startswith("$((", i):
            levels.append(["arith", None, 2])
            step = 3
        elif text.startswith(("$(", "${", "$["), i):
            opened = _OPENED[text[i + 1]]
            levels.append([opened, None, 0 if opened == "sub" else 1])
            step = 2
        elif ch == "`":
            if kind == "tick":
                levels.pop()
            else:
                levels.append(["tick", None, 0])
        elif quote == '"':
            if ch == '"':
                level[1] = None
        elif ch in "'\"":
            level[1] = ch
        elif kind in _QUIET:
            level[2] += (ch == _QUIET[kind][0]) - (ch == _QUIET[kind][1])
            if level[2] <= 0:
                levels.pop()
        elif text.startswith("((", i):
            levels.append(["arith", None, 2])
            step = 2
        elif ch == "=" and text.startswith("(", i + 1) and i and (text[i - 1].isalnum() or text[i - 1] in "_]+"):
            levels.append(["array", None, 1])
            step = 2
        elif ch in "<>=" and text.startswith("(", i + 1):
            levels.append(["sub", None, 0])
            step = 2
        elif ch == "(":
            level[2] += 1
        elif ch == ")":
            if level[2]:
                level[2] -= 1
            elif kind == "sub":
                levels.pop()
        i += step
        if levels[-1][0] in _QUIET and begun is None:
            begun = i
        elif levels[-1][0] not in _QUIET and begun is not None:
            ranges.append((begun, i))
            begun = None
    if begun is not None:
        ranges.append((begun, n))
    return ranges


_REDIRECTION = re.compile(r"\d*(?:<<<|<<-?|<>|<&|>&|>>|>\||&>>|&>|<|>)")


def _raw_words(text: str) -> list[str]:
    """One simple command's words as written — quotes and substitutions kept, `<(…)` one word — with
    each redirection operator a word of its own (`<`, `3<`, `<<<`, `2>&` …)."""
    words: list[str] = []
    i, n = 0, len(text)
    while i < n:
        if text[i] in " \t\n":
            i += 1
            continue
        if text.startswith(("<(", ">("), i):
            end = _paren_end(text, i + 1) or n
            end = max(end, _word_end(text, end)) if end < n and not text[end].isspace() else end
        elif (operator := _REDIRECTION.match(text, i)) is not None:
            end = operator.end()
        else:
            end = max(_word_end(text, i), i + 1)
        words.append(text[i:end])
        i = end
    return words


def _split_redirections(words: list[str]) -> tuple[list[str], list[tuple[str, str]]]:
    """(the words without their redirections, [(operator, target)] for each input redirection:
    `<`, `N<`, `<>`, `<&`, a here-string `<<<`). A heredoc's `<<` and its delimiter are left out."""
    plain: list[str] = []
    inputs: list[tuple[str, str]] = []
    i = 0
    while i < len(words):
        if _REDIRECTION.fullmatch(words[i]):
            operator, target = words[i], words[i + 1] if i + 1 < len(words) else ""
            if "<" in operator and not operator.rstrip("-").endswith("<<") or operator.endswith("<<<"):
                inputs.append((operator, target))
            i += 2
            continue
        plain.append(words[i])
        i += 1
    return plain, inputs


def _unquote(word: str) -> str:
    """A simple word's text as the program sees it (`"-c"`, `'git push'`, `git\\ push`)."""
    try:
        parts = shlex.split(word, posix=True)
    except ValueError:
        return word
    return parts[0] if len(parts) == 1 else word


def _program(word: str) -> str:
    return os.path.basename(_unquote(word).lstrip("=")).lower()


def _outer_substitutions(text: str) -> list[str]:
    """The bodies of the substitutions the shell runs in `text` as written, outermost: `$(…)` and
    backtick spans outside single quotes; `<(…)`, `>(…)` and zsh's `=(…)` outside any quotes (an
    array's `name=(…)` is no substitution). Arithmetic `$((…))` is no body, the ones in it are."""
    bodies: list[str] = []
    quote, i, n = None, 0, len(text)
    while i < n:
        ch = text[i]
        if quote == "'":
            quote = None if ch == "'" else "'"
            i += 1
            continue
        if ch == "\\":
            i += 2
            continue
        if ch == '"':
            quote = None if quote == '"' else '"'
        elif ch == "'" and quote is None:
            quote = "'"
        elif text.startswith("$((", i):
            i += 3
            continue
        elif text.startswith("$(", i) or (quote is None and ch in "<>=" and text.startswith("(", i + 1)
                                          and not (ch == "=" and i and (text[i - 1].isalnum() or text[i - 1] in "_]"))):
            end = _paren_end(text, i + 1)
            bodies.append(text[i + 2:(end or n + 1) - 1])
            if end is None:
                break
            i = end
            continue
        elif ch == "`":
            end = hermes._scan_backtick_end(text, i)
            bodies.append(text[i + 1:(end or n + 1) - 1])
            if end is None:
                break
            i = end
            continue
        i += 1
    return bodies


_DURATION = re.compile(r"\d+(?:\.\d+)?[smhd]?")
_ASSIGNMENT_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=", re.S)


def _unwrapped(plain: list[str]) -> list[str]:
    """The words from the command a run of wrappers runs (R11: `nice -n 5 bash`, `caffeinate -i
    bash`, `arch -arch arm64 bash` run bash): wrapper words, options, numbers, assignments and the
    value after an option are read past; a code reader never counts as a value."""
    if not plain or _program(plain[0]) not in _WRAPPER_NAMES:
        return plain
    i, after_option = 0, False
    while i < len(plain):
        word, name = _unquote(plain[i]), _program(plain[i])
        if name in _CODE_READERS or hermes._interpreter_family(name) is not None:
            break
        if (name in _WRAPPER_NAMES or word.startswith(("-", "+")) or _DURATION.fullmatch(word)
                or _ASSIGNMENT_WORD.match(word) or after_option):
            after_option = word.startswith(("-", "+"))
            i += 1
            continue
        break
    return plain[i:]


_STDIN = "<stdin>"                  # `_script_operand`: the program reads its code from stdin
_STDIN_PATH = re.compile(r"-|/dev/stdin|/dev/fd/\d+")


def _script_operand(plain: list[str]) -> str | None:
    """Where a code reader takes its code when no `-c`/`-e` hands it any: the script word as written,
    `_STDIN`, or None (inline code, `python -m`, or not a code reader). Code readers: the shells,
    `source`/`.`, osascript and the interpreters Hermes knows."""
    name = _program(plain[0])
    args = [_unquote(word) for word in plain[1:]]
    if name in ("source", "."):
        return plain[1] if len(plain) > 1 else None
    i = 0
    if name in _SHELLS:
        while i < len(args):
            arg = args[i]
            if arg == "--":
                return plain[i + 2] if i + 1 < len(args) else _STDIN
            if arg in hermes._BASH_OPTIONS_WITH_ARG:
                i += 2
                continue
            if arg.startswith(("-", "+")) and len(arg) > 1:
                letters = "" if arg.startswith("--") else arg[1:]
                if "c" in letters:
                    return None
                if "s" in letters:
                    return _STDIN
                i += 1 + ("o" in letters or "O" in letters)
                continue
            return _STDIN if arg == "-" else plain[i + 1]
        return _STDIN
    if name == "osascript":
        while i < len(args):
            if args[i] == "-e":
                return None
            if args[i] in ("-l", "-s"):
                i += 2
                continue
            if not args[i].startswith("-") or args[i] == "-":
                return _STDIN if args[i] == "-" else plain[i + 1]
            i += 1
        return _STDIN
    family = hermes._interpreter_family(name)
    if family is None or hermes._interpreter_exec_flag(family, args):
        return None
    with_value = hermes._INTERPRETER_WITH_ARG.get(family, set())
    while i < len(args):
        arg = args[i]
        if arg == "-":
            return _STDIN
        if family == "python" and arg.startswith("-m"):
            return None
        if not arg.startswith("-"):
            return plain[i + 1]
        i += 2 if arg in with_value else 1
    return _STDIN


def _reads_stdin_code(plain: list[str]) -> bool:
    """A code reader that runs what it is fed (a pipe, `<`, a here-string): `bash`, `bash -s`,
    `env bash` (read past its wrapper by `_commands`), `python3`, `python3 -`, `python3 /dev/stdin`,
    `source /dev/stdin`, `osascript` with no script of its own."""
    script = _script_operand(plain) if plain else None
    return script == _STDIN or (script is not None and _STDIN_PATH.fullmatch(_unquote(script)) is not None)


def _code_word(plain: list[str]) -> str | None:
    """The word holding the code a shell's `-c` or an interpreter's `-c`/`-e` is handed, as written."""
    name = _program(plain[0])
    args = [_unquote(word) for word in plain[1:]]
    if name in _SHELLS:
        i = 0
        while i < len(args):
            arg = args[i]
            if arg == "--" or not arg.startswith(("-", "+")):
                return None
            if arg in hermes._BASH_OPTIONS_WITH_ARG:
                i += 2
                continue
            letters = arg[1:]
            if arg.startswith("--") or not set(letters) <= hermes._BASH_SHORT_OPTION_LETTERS:
                i += 1
                continue
            skip = int("O" in letters or "o" in letters)
            if "c" in letters:
                at = i + 1 + skip
                return plain[at + 1] if at < len(args) else None
            i += 1 + skip
        return None
    family = hermes._interpreter_family(name)
    flag = hermes._interpreter_exec_flag(family, args) if family else None
    if flag is None:
        return None
    at = next((i for i, arg in enumerate(args) if arg == flag or arg.startswith(flag)), None)
    if at is None:
        return None
    return plain[at + 1] if args[at] != flag else (plain[at + 2] if at + 1 < len(args) else None)


def _here_string_code(command: str) -> str | None:
    """The code a shell reads from a literal here-string (`bash <<< "git push"`, `source /dev/stdin
    <<< …`): read like `bash -c`. One built by a substitution is `_code_findings`' to judge."""
    if "<<<" not in command:
        return None
    plain, inputs = _split_redirections(_raw_words(command))
    plain = _unwrapped(plain)
    if not plain or _program(plain[0]) not in _SHELLS | {"source", "."} or not _reads_stdin_code(plain):
        return None
    words = [target for operator, target in inputs if operator.endswith("<<<")]
    if not words or _outer_substitutions(words[-1]):
        return None
    return _unquote(words[-1])


def _runs_its_input(piece: str) -> bool:
    """A pipe target that runs what it is fed (R11), past wrappers: `| bash`, `| env bash`, `| nice
    -n 5 bash`, `| command bash`, `| source /dev/stdin`, `| python3 /dev/stdin`, `| python3 -W ignore`."""
    for segment in _top_level_segments(piece):
        for _start, _raw, bounded in _spans(segment):
            plain, _inputs = _split_redirections(_raw_words(bounded))
            if _reads_stdin_code(_unwrapped(plain)):
                return True
    return False


def _sets_up_environment(body: str) -> bool:
    """(R13 c) A substitution that is exactly one set-up command on `_SET_UP` (or `conda
    shell.<shell> hook`): nothing nested, no pipe, no variable."""
    pipelines = _pipelines(body)
    if len(pipelines) != 1 or len(pipelines[0]) != 1 or _outer_substitutions(body):
        return False
    plain, _inputs = _split_redirections(_raw_words(pipelines[0][0]))
    words = [_unquote(word) for word in plain]
    if not words or any("$" in word or "`" in word for word in words):
        return False
    words[0] = os.path.basename(words[0])
    if words[0] == "conda":
        return len(words) > 2 and re.fullmatch(r"shell\.\w+", words[1]) is not None and words[2] == "hook"
    return any(tuple(words[:len(entry)]) == entry for entry in _SET_UP)


def _fetches_or_decodes(body: str) -> bool:
    return any(_fetches(argv) or _decodes(argv) for argv in _commands(body))


def _code_findings(texts: list[str]) -> list[Finding]:
    """Code a shell or an interpreter runs that nobody can read in the command (R11, R13 c), in the
    command and in each payload it hands a shell: from a download or a decode (opaque,
    `fetched-code`), or — for `eval`, `source`/`.` and a shell — built while it runs (opaque,
    `built-code`), unless every substitution building it is a set-up on `_SET_UP`. An
    AppleScript built while it runs asks as an app it names only then."""
    found: list[Finding] = []
    for text in texts:
        for segment in _top_level_segments(text):
            for _start, raw, bounded in _spans(segment):
                name = _name([hermes._deobfuscate_shell_word_for_detection(raw) or "-"])
                if (name in _CODE_READERS or name in _WRAPPER_NAMES
                        or hermes._interpreter_family(name) is not None):
                    found += _code_use(bounded)
    return list(dict.fromkeys(found))


_CODE_READERS = _SHELLS | {"eval", "source", ".", "osascript"}


def _code_use(command: str) -> list[Finding]:
    plain, inputs = _split_redirections(_raw_words(command))
    plain = _unwrapped(plain)
    if not plain:
        return []
    name = _program(plain[0])
    builds = name in _SHELLS or name in ("eval", "source", ".")
    if name == "eval":
        sources = plain[1:]
    elif name == "osascript" and "-e" in (lines := [_unquote(word) for word in plain]):
        sources = [plain[i + 1] for i, word in enumerate(lines[:-1]) if word == "-e"]
    elif (code := _code_word(plain)) is not None:
        sources = [code]
    else:
        script = _script_operand(plain)
        if script is None:
            return []
        reads_input = script == _STDIN or _STDIN_PATH.fullmatch(_unquote(script)) is not None
        sources = [target for _operator, target in inputs] if reads_input else [script]
    bodies = [body for source in sources for body in _outer_substitutions(source)]
    if not bodies:
        return []
    if any(_fetches_or_decodes(body) for body in bodies):
        return [Finding("opaque", "fetched-code", _WHY["fetched-code"])]
    if builds and not all(_sets_up_environment(body) for body in bodies):
        return [Finding("opaque", "built-code", _WHY["built-code"])]
    if name == "osascript":
        return [Finding("apps", "apple-events", "runs AppleScript that can control an app it names only at "
                                                "run time", kind="app")]
    return []


# ── the floor ─────────────────────────────────────────────────────────────────

_DISK_ERASE = frozenset({"erasedisk", "erasevolume", "zerodisk", "randomdisk", "secureerase", "reformat",
                         "partitiondisk"})


def _floor_findings(text: str, shell: str, commands: list[list[str]]) -> list[Finding]:
    found = []
    hard = _hardline(shell)
    if hard:
        found.append(Finding("floor", "hardline", hard))
    texts = _detection_texts(shell)
    masked = _masked(texts)
    for key, pattern, why in _FORBID_C:
        if _matches(pattern, masked if key in _MASKED_RULES else texts):
            found.append(Finding("floor", key, why))
    if _touches_arslan_data(text) or _writes_arslan_data(commands):
        found.append(Finding("floor", "arslan-data", "touches Arslan's own data, keys or database"))
    for argv in commands:
        name = _name(argv)
        if name == "diskutil" and len(argv) > 1 and (
                argv[1].lower() in _DISK_ERASE
                or (argv[1].lower() == "apfs" and len(argv) > 2
                    and argv[2].lower() in {"deletecontainer", "deletevolume", "erasevolume"})):
            found.append(Finding("floor", "disk-erase", "erases a disk"))
        if name in ("sudo", "doas"):              # `env sudo …`, `nice sudo …`: the regex sees only a start
            found.append(Finding("floor", "sudo", _WHY["sudo"]))
        if name == "security" and _reads_keychain_secret(argv[1:]):
            found.append(Finding("floor", "keychain-secrets", _WHY["keychain-secrets"]))
    return found


def _reads_keychain_secret(args: list[str]) -> bool:
    """`security find-*-password` with -w or -g anywhere in a short-option cluster (`-wa`, `-gs x`),
    `dump-keychain`, `export`: the password or key itself is printed."""
    if not args:
        return False
    if args[0] in ("dump-keychain", "export"):
        return True
    return args[0] in ("find-generic-password", "find-internet-password") and any(
        a.startswith("-") and not a.startswith("--") and ({"w", "g"} & set(a[1:])) for a in args[1:])


def _hardline(text: str) -> str:
    """Hermes' hardline floor without its malformed-grep verdict (§A9: that one is local inside
    the sandbox). Mirrors `detect_hardline_command`; a parity test keeps them equal."""
    if hermes._command_parser_limit_exceeded(text):
        return hermes._PARSER_LIMIT_DESCRIPTION
    for variant in hermes._command_detection_variants(text):
        lowered = variant.lower()
        masked: str | None = None
        for pattern_re, description, quote_masked in hermes.HARDLINE_PATTERNS_COMPILED:
            if quote_masked and masked is None:
                masked = (lowered if hermes._contains_shell_carrier(variant)
                          else hermes._mask_quoted_prose(variant).lower())
            if pattern_re.search(masked if quote_masked else lowered):
                return description
    return ""


def _touches_arslan_data(text: str) -> bool:
    """Arslan's data folder, keys and database, in the spellings a text can show (§A2): `~`,
    `$HOME`, `${HOME}`, quoted or escaped, any case, and `config.data_dir()` literally — never
    ~/Arslan, the working folder. Read on the whole text, heredoc bodies and inline scripts
    included. One exception (§C3): reading or running an imported skill under `<data>/skills/`
    (no `..` in the rest of the path). A glob, a variable or a `cd` in two steps can still spell
    the folder unseen: the sandbox closes it to every command (`command_sandbox.default_protected`,
    and in 0.1.61 the wide profile too), and every command that runs without the sandbox asks."""
    normalized = hermes._normalize_command_for_detection(text)
    subjects = (normalized, text, _unspliced(normalized))
    for subject in subjects:
        for match in _ARSLAN_DATA.finditer(subject):
            if not (match.group("folder") and _reads_a_skill(subject, match.end())):
                return True
    literal = _data_dir_literal()
    if literal:
        for subject in subjects:
            for match in re.finditer(re.escape(literal) + r"(?=[/\s\"';|&)]|$)", subject):
                if not _reads_a_skill(subject, match.end()):
                    return True
    return False


def _unspliced(text: str) -> str:
    """The text with its quote marks taken out and `/./` folded, so a path spelled in quoted
    pieces (`Application' 'Support`, `Ars'l'an`, `"Application Support"/./Arslan`) reads as the
    path itself (review M4). For matching only: it joins words a shell would keep apart."""
    text = text.replace("'", "").replace('"', "")
    while "/./" in text:
        text = text.replace("/./", "/")
    return text


def _reads_a_skill(subject: str, at: int) -> bool:
    """Whether the data folder named just before `at` continues into `skills/` with no `..`."""
    tail = _SKILLS_TAIL.match(subject, at)
    return tail is not None and not _UP_LEVEL.search(tail.group("rest"))


def _data_roots() -> list[str]:
    """Arslan's data folder (production's and `config.data_dir()`), lowercased: the Mac's disk
    ignores case."""
    roots = [str(Path.home() / "Library" / "Application Support" / "Arslan")]
    literal = _data_dir_literal()
    if literal:
        roots.append(literal)
    return [r.lower() for r in roots]


def _writes_arslan_data(commands: list[list[str]]) -> bool:
    """A command that plainly writes inside Arslan's data folder — the skills folder included, which
    the text check above lets commands read (§C3). A write the text does not show (a script
    opening the file itself) is stopped by the sandbox: the skills folder is read-only to commands."""
    roots = _data_roots()
    for path in _write_targets(commands):
        target = os.path.normpath(str(path)).lower()
        if any(target == root or target.startswith(root + "/") for root in roots):
            return True
    return False


def _data_dir_literal() -> str:
    """`config.data_dir()` as a path, when it is not the working folder or above it (a development
    data dir can be anywhere; production's is Application Support/Arslan, matched above)."""
    try:
        from server import config
        from server.services import settings_service
        data = Path(config.data_dir()).expanduser().resolve()
        work = settings_service.default_workspace().expanduser().resolve()
    except Exception:  # noqa: BLE001 — the patterns above still hold
        return ""
    if len(data.parts) <= 2 or data == work or data in work.parents:
        return ""
    return str(data)


# ── Hermes' findings ──────────────────────────────────────────────────────────

def _hermes_findings(shell: str, *, raw: str, commands: list[list[str]]) -> list[Finding]:
    """Every Hermes finding for the command, where `detect_dangerous_command` stops at the first,
    each placed by HERMES_CATEGORIES. Whether a database client runs is read once, from the
    command's own commands (each variant re-read cost a full read: review N6)."""
    if hermes._is_verification_artifact_cleanup(shell):
        return []
    found: list[str] = []
    sql_client = any(_name(argv) in _SQL_CLIENTS for argv in commands)
    for variant in hermes._command_detection_variants(shell):
        lowered = hermes._lower_preserving_flags(variant)
        carrier = hermes._contains_shell_carrier(variant)
        masked = hermes._lower_preserving_flags(hermes._mask_quoted_prose(variant))
        for pattern_re, description in hermes.DANGEROUS_PATTERNS_COMPILED:
            if description in hermes._QUOTE_MASKED_DANGEROUS_DESCRIPTIONS:
                subject = masked
            elif description in _HERMES_MASKED and not carrier:
                subject = masked
            elif description in _HERMES_SQL and not (carrier or sql_client):
                subject = masked
            else:
                subject = lowered
            if pattern_re.search(subject) and description not in found:
                found.append(description)
    for description, _payload in hermes._execution_flag_findings(hermes._normalize_command_for_detection(shell)):
        if description not in found:
            found.append(description)
    _, malformed_grep = hermes._grep_safe_detection_variant(hermes._mask_quoted_newlines(shell))
    if malformed_grep and _MALFORMED not in found:
        found.append(_MALFORMED)
    if _MALFORMED in found and _parses(raw):
        found.remove(_MALFORMED)          # §A9: quoting that is valid in the shell is not malformed
    if hermes._is_shell_token_spliced_gateway_lifecycle(shell):
        found.append(hermes._GATEWAY_LIFECYCLE_SPLICE_DESCRIPTION)
    return [Finding(_placed(d), f"hermes:{d}", d) for d in found]


def _parses(text: str) -> bool:
    """The raw command (heredoc bodies aside) tokenizes as the shell would: no open quote."""
    shell, _ = split_heredocs(text)
    try:
        shlex.split(shell, comments=True, posix=True)
    except ValueError:
        return False
    return True


# ── Arslan's findings ─────────────────────────────────────────────────────────

_SEND_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
#: curl's request data: the body of a POST, or with `-G` the query of a GET (a read).
_CURL_DATA = ("--data", "--data-ascii", "--data-binary", "--data-raw", "--data-urlencode")
_CURL_SENDING = ("--form", "--form-string", "--upload-file", "--json")
_CURL_VALUE_SHORT = frozenset("dFTXHAbceEhKmortuUwxyYzCPQ")
#: curl's long options that take no value: the word after one is never its value.
_CURL_FLAGS = frozenset({"--silent", "--show-error", "--location", "--fail", "--fail-with-body", "--compressed",
                         "--insecure", "--verbose", "--include", "--globoff", "--get", "--head",
                         "--no-progress-meter"})
_WGET_SENDING = ("--post-data", "--post-file", "--body-data", "--body-file")
_REMOTE = frozenset({"ssh", "scp", "sftp", "ftp", "mosh", "ssh-copy-id"})
_RAW_NET = frozenset({"nc", "ncat", "netcat", "socat", "telnet"})
_START_FILES = (".zshrc", ".bashrc", ".zprofile", ".profile", ".bash_profile", ".zshenv", ".gitconfig",
                ".npmrc")
#: Other agents' settings (§A2): readable, never written without their own card.
OTHER_AGENTS: dict[str, str] = {".hermes": "Hermes", ".codex": "Codex", ".claude": "Claude",
                                ".claude.json": "Claude", ".cursor": "Cursor", ".openclaw": "OpenClaw",
                                ".agents": "the shared agents folder",
                                "Library/Application Support/Claude": "Claude"}


def _arslan_findings(shell: str, commands: list[list[str]], bodies) -> list[Finding]:
    texts = _detection_texts(shell)
    masked = _masked(texts)
    found: list[Finding] = []
    for key, _pattern, why in _ASK:
        if key == "apple-events":
            found += _osascript_findings(commands, bodies)
        elif key == "shortcuts":
            found += [Finding("apps", "shortcuts", why, app=_shortcut_name(argv), kind="shortcut")
                      for argv in commands if _name(argv) == "shortcuts" and argv[1:2] == ["run"]]
        elif key == "upload":
            if any(_uploads(argv) for argv in commands):
                found.append(Finding("send", key, why))
        elif key == "remote-shell":
            if any(_name(argv) in _REMOTE or (_name(argv) == "rsync" and _rsync_remote(argv)) for argv in commands):
                found.append(Finding("send", key, why))
        elif key == "publish":
            pattern = next(p for k, p, _ in _ASK_C if k == key)
            if _matches(pattern, texts) or any(_publishes(argv) for argv in commands):
                found.append(Finding("send", key, why))
        elif key == "git-push":
            if any(_git_subcommand(argv)[0] == "push" for argv in commands if _name(argv) == "git"):
                found.append(Finding("send", key, why))
        elif key == "login-items":
            if any(_changes_startup(argv) for argv in commands):
                found.append(Finding("system", key, why))
        elif key == "force-delete":
            if any(_force_deletes(argv) for argv in commands):
                found.append(Finding("destructive", key, why))
        elif key == "git-discard":
            if any(_git_discards(argv) for argv in commands if _name(argv) == "git"):
                found.append(Finding("destructive", key, why))
        elif key == "kill-force":
            if any(_kills_hard(argv) for argv in commands):
                found.append(Finding("destructive", key, why))
        elif key == "network-tool":
            if any(_name(argv) in _RAW_NET for argv in commands):
                found.append(Finding("send", key, why))
        elif key == "system-settings":
            if any(_changes_system(argv) for argv in commands):
                found.append(Finding("system", key, why))
        elif key == "start-files":
            if any(_is_start_file(p) for p in _write_targets(commands)):
                found.append(Finding("system", key, why))
        elif key == "other-agent":
            for agent in dict.fromkeys(a for a in map(other_agent_of, _write_targets(commands)) if a):
                found.append(Finding("other_agent", key, f"changes {agent}'s settings", app=agent))
        elif key == "screen-capture":
            if any(_name(argv) == "screencapture" for argv in commands):
                found.append(Finding("screen", key, why))
        elif key == "terminal-app":
            for app in dict.fromkeys(a for a in map(_terminal_app, commands) if a):
                found.append(Finding("apps", key, why if app in ("Terminal", "iTerm") else
                                     "starts a program outside the sandbox", app=app, kind="app"))
        else:
            pattern = next(p for k, p, _ in _ASK_C if k == key)
            if _matches(pattern, masked if key in _MASKED_RULES else texts):
                category = {"install": "local", "delete": "local"}.get(key, "send")
                found.append(Finding(category, key, why))
    for program, body in bodies:                       # SQL a database client reads (§A9)
        if program in _SQL_CLIENTS:
            for pattern_re, description in hermes.DANGEROUS_PATTERNS_COMPILED:
                if description in _HERMES_SQL and pattern_re.search(body):
                    found.append(Finding("destructive", f"hermes:{description}", description))
    return found


def _options(argv: list[str]) -> list[str]:
    return [a for a in argv[1:] if a.startswith("-")]


def _uploads(argv: list[str]) -> bool:
    """curl or wget sending data: curl's data flags are case-sensitive (`-f`, `-sSf`, `-D -` read),
    and `-G` turns the data into the query of a GET, a read (review M5)."""
    name, args = _name(argv), argv[1:]
    if name == "wget":
        return any(a.startswith(_WGET_SENDING) or (a.startswith("--method=") and a[9:].upper() in _SEND_METHODS)
                   for a in args) or any(a == "--method" and i + 1 < len(args) and args[i + 1].upper() in _SEND_METHODS
                                         for i, a in enumerate(args))
    if name != "curl":
        return False
    transfers: list[list[str]] = [[]]
    for arg in args:                        # `-:` / `--next`: the next URL has options of its own (review N4)
        if arg in ("-:", "--next"):
            transfers.append([])
        else:
            transfers[-1].append(arg)
    return any(_curl_transfer_sends(transfer) for transfer in transfers)


def _curl_transfer_sends(args: list[str]) -> bool:
    """One curl transfer sends: a form or a file upload, a sending method, or data — unless `-G`
    makes the data the query of a GET, and even then when the data names a file (`-d @f`): its
    contents leave in the URL."""
    get = data = files = sends = False
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--":
            break
        if arg.startswith("--"):
            option, equals, value = arg.partition("=")
            if option == "--get":
                get = get or _curl_option_stands(args, i)
            elif option in _CURL_DATA:
                data = True
                value = value if equals else (args[i + 1] if i + 1 < len(args) else "")
                files = files or _curl_data_names_a_file(option, value)
            elif option in _CURL_SENDING:
                sends = True
            elif option == "--request":
                method = value if equals else (args[i + 1] if i + 1 < len(args) else "")
                sends = sends or method.upper() in _SEND_METHODS
                i += 1 if equals else 2
                continue
            i += 1
            continue
        if arg.startswith("-") and len(arg) > 1:
            letters, skip = arg[1:], 1
            for j, letter in enumerate(letters):
                if letter == "G":
                    get = get or _curl_option_stands(args, i)
                elif letter == "d":
                    data = True
                    value = letters[j + 1:] or (args[i + 1] if i + 1 < len(args) else "")
                    files = files or _curl_data_names_a_file("--data", value)
                elif letter in "FT":
                    sends = True
                elif letter == "X":
                    method = letters[j + 1:] or (args[i + 1] if i + 1 < len(args) else "")
                    sends = sends or method.upper() in _SEND_METHODS
                if letter in _CURL_VALUE_SHORT:
                    skip = 1 if j + 1 < len(letters) else 2      # its value: the rest, or the next word
                    break
            i += skip
            continue
        i += 1
    return sends or (data and (not get or files))


def _curl_data_names_a_file(option: str, value: str) -> bool:
    """`-d @f`, `--data-binary @f`; `--data-urlencode @f` or `name@f` (an `@` before any `=`).
    `--data-raw` takes its value as it is."""
    if option == "--data-raw":
        return False
    if option == "--data-urlencode":
        at, equals = value.find("@"), value.find("=")
        return at >= 0 and (equals < 0 or at < equals)
    return value.startswith("@")


def _curl_option_stands(args: list[str], i: int) -> bool:
    """Whether `args[i]` is an option of its own and not the value of the option before it
    (`-H -G`, `--data-urlencode -G`): `-G` counts only then, so it never hides a POST."""
    if i == 0:
        return True
    before = args[i - 1]
    # A short option taking the next word as its value (`-H -G`) never reaches here: the caller
    # skips that word. A long one does (`--data-urlencode -G`).
    return not before.startswith("--") or "=" in before or before in _CURL_FLAGS


def _rsync_remote(argv: list[str]) -> bool:
    return any(a.startswith("rsync://") or re.match(r"^(?:[^/\s:@]+@)?[^/\s:]+:", a)
               for a in argv[1:] if not a.startswith("-"))


#: (program, subcommand) pairs that publish or change something online (§A2 send), read as argv.
_PUBLISH_SUBCOMMANDS = {
    "docker": {"push"}, "podman": {"push"}, "uv": {"publish"}, "poetry": {"publish"}, "twine": {"upload"},
    "gem": {"push"}, "cargo": {"publish"}, "npm": {"publish"}, "pnpm": {"publish"}, "yarn": {"publish"},
    "bun": {"publish"}, "netlify": {"deploy"}, "fly": {"deploy"}, "flyctl": {"deploy"},
    "firebase": {"deploy"}, "wrangler": {"deploy", "publish"}, "vercel": {"deploy"},
}
_GH_SENDS = {"pr": {"create", "merge", "close", "edit", "comment", "review", "ready", "reopen"},
             "issue": {"create", "close", "edit", "comment", "delete", "reopen", "transfer", "lock"},
             "release": {"create", "delete", "edit", "upload"},
             "repo": {"create", "delete", "edit", "fork", "rename", "archive"},
             "gist": {"create", "delete", "edit"}, "secret": {"set", "delete"}, "variable": {"set", "delete"}}
_HTTPIE = frozenset({"http", "https", "xh", "xhs"})


def _publishes(argv: list[str]) -> bool:
    """Publishing, deploying or uploading by a tool the regex above does not name: `gh api` with
    fields or a sending method (it POSTs when given fields), `gh release upload`, `docker push`,
    `uv publish`, `python -m twine upload`, `vercel --prod`, HTTPie with a sending method or data,
    `aws s3`/`gsutil`/`rclone` copying TO a remote, `git send-email`."""
    name, args = _name(argv), argv[1:]
    positional = [a for a in args if not a.startswith("-")]
    if name.startswith("python") and args[:2] == ["-m", "twine"]:
        return "upload" in args[2:]
    if name == "git":
        return _git_subcommand(argv)[0] == "send-email"
    if name == "gh":
        if positional[:1] == ["api"]:
            for i, a in enumerate(args):
                if a in ("-f", "-F", "--field", "--raw-field", "--input") or a.startswith(("--field=", "--raw-field=")):
                    return True
                method = (a.split("=", 1)[1] if a.startswith("--method=") else a[2:] if a.startswith("-X") and len(a) > 2
                          else args[i + 1] if a in ("-X", "--method") and i + 1 < len(args) else "")
                if method.upper() in _SEND_METHODS:
                    return True
            return False
        return len(positional) > 1 and positional[1] in _GH_SENDS.get(positional[0], set())
    if name == "vercel":
        return "--prod" in args or positional[:1] == ["deploy"]
    if name in _PUBLISH_SUBCOMMANDS:
        return bool(positional) and positional[0] in _PUBLISH_SUBCOMMANDS[name]
    if name in _HTTPIE:
        if positional and positional[0].upper() in _SEND_METHODS:
            return True
        return any(a in ("-f", "--form", "--multipart", "--raw") for a in args) or any(
            re.match(r"^[^/=:@\s]+(?::=@|:=|=@|=|@)", a) for a in positional[1:] if "://" not in a)
    if name == "aws":
        return positional[:1] == ["s3"] and len(positional) > 2 and positional[1] in ("cp", "mv", "sync") \
            and positional[-1].startswith("s3://")
    if name == "gsutil":
        return bool(positional) and positional[0] in ("cp", "mv", "rsync") and positional[-1].startswith("gs://")
    if name == "rclone":
        return bool(positional) and positional[0] in ("copy", "copyto", "move", "moveto", "sync") \
            and re.match(r"^[A-Za-z0-9_.-]+:", positional[-1]) is not None
    return False


def _git_subcommand(argv: list[str]) -> tuple[str, list[str]]:
    """(the git subcommand, its arguments), past git's own options (`-C dir`, `-c k=v`, …)."""
    args, i = argv[1:], 0
    while i < len(args):
        if args[i] in ("-C", "-c", "--git-dir", "--work-tree", "--namespace"):
            i += 2
        elif args[i].startswith("-"):
            i += 1
        else:
            return args[i], args[i + 1:]
    return "", []


def _git_discards(argv: list[str]) -> bool:
    sub, rest = _git_subcommand(argv)
    if sub == "checkout":
        return bool({"--", ".", "-f", "--force"} & set(rest))
    if sub == "switch":
        return bool({"-f", "--force", "--discard-changes"} & set(rest))
    if sub == "restore":         # the working tree (the default, or --worktree), not only the index
        return ("--worktree" in rest or "-W" in rest) or not ({"--staged", "-S"} & set(rest))
    if sub == "stash":
        return bool(rest) and rest[0] in ("drop", "clear")
    return False


def _force_deletes(argv: list[str]) -> bool:
    name = _name(argv)
    if name == "srm":
        return True
    if name != "rm":
        return False
    for arg in argv[1:]:
        if arg == "--":
            break
        if arg == "--force" or (arg.startswith("-") and not arg.startswith("--") and "f" in arg[1:]):
            return True
    return False


def _kills_hard(argv: list[str]) -> bool:
    name = _name(argv)
    if name in ("pkill", "killall"):
        return not _signal_zero(argv[1:])
    if name != "kill":
        return False
    args = argv[1:]
    for i, arg in enumerate(args):
        if arg.upper() in ("-9", "-KILL", "-SIGKILL"):
            return True
        if arg == "-s" and i + 1 < len(args) and args[i + 1].upper() in ("9", "KILL", "SIGKILL"):
            return True
    return False


def _signal_zero(args: list[str]) -> bool:
    """`pkill -0 x`, `killall -s 0 x`, `--signal 0`: signal 0 only checks that a process exists
    (review M5). Any other signal named beside it, and it is a kill again."""
    zero = other = False
    for i, arg in enumerate(args):
        value = None
        if arg in ("-s", "--signal") and i + 1 < len(args):
            value = args[i + 1]
        elif arg.startswith("--signal="):
            value = arg.partition("=")[2]
        elif re.fullmatch(r"-(?:\d+|[A-Z][A-Z0-9+-]*)", arg):
            value = arg[1:]
        if value is not None:
            zero, other = zero or value == "0", other or value != "0"
    return zero and not other


def _changes_startup(argv: list[str]) -> bool:
    name, args = _name(argv), argv[1:]
    if name == "launchctl":         # list, print, blame, getenv … read
        return bool(args) and args[0] in ("load", "unload", "bootstrap", "bootout", "enable", "disable",
                                          "submit", "remove", "kickstart", "kill", "setenv", "unsetenv",
                                          "config", "limit")
    if name == "defaults":          # past -currentHost / -host <name>
        verbs = [a for i, a in enumerate(args) if not a.startswith("-") and (i == 0 or args[i - 1] != "-host")]
        return bool(verbs) and verbs[0] in ("write", "delete", "import", "rename")
    if name == "crontab":          # `crontab -l` reads; -e, -r, a file or stdin change it
        return not ("-l" in args and not {"-e", "-r", "-i"} & set(args))
    return False


def _changes_system(argv: list[str]) -> bool:
    name, args = _name(argv), argv[1:]
    if name in ("sfltool", "tccutil"):
        return True
    if name == "networksetup":
        return any(a.lower().startswith(("-set", "-create", "-remove", "-delete", "-add")) for a in args)
    if name == "systemsetup":
        return any(a.lower().startswith("-set") for a in args)
    if name == "pmset":            # `pmset -g …` reads
        return not (args and args[0].startswith("-g"))
    if name == "scutil":
        return "--set" in args
    if name == "security":
        return bool(args) and re.match(r"^(?:add|delete)-", args[0]) is not None
    return False


def _write_targets(commands: list[list[str]]) -> list[Path]:
    """Paths a command plainly writes: redirections, tee, the destination of cp/mv/install/ln,
    files edited in place, created, touched or removed."""
    out: list[str] = []
    for argv in commands:
        name, args = _name(argv), argv[1:]
        for i, arg in enumerate(args):
            if arg in (">", ">>", "&>", "&>>") and i + 1 < len(args):
                out.append(args[i + 1])
        plain = [a for a in args if not a.startswith("-") and a not in (">", ">>", "<", "&>", "&>>")]
        if name == "tee":
            out += plain
        elif name in ("cp", "mv", "install", "ln", "rsync") and plain:
            out.append(plain[-1])
        elif name in ("touch", "mkdir", "rm", "rmdir", "truncate", "chmod", "chown", "unlink"):
            out += plain
        elif name in ("sed", "perl", "ruby") and any(a.startswith("-i") or a == "--in-place" or
                                                     (a.startswith("-") and "i" in a[1:] and name != "sed")
                                                     for a in args):
            out += plain[1:]
    return [p for p in map(_expand, out) if p is not None]


def _expand(word: str) -> Path | None:
    """The absolute path a write target names, or None when the text shows none: a variable, a
    relative path, or a home the shell resolves only at run time or not at all (`~+`, `~-`,
    `~<no such user>`, where `expanduser` raises). None is not the floor: a target whose home
    cannot be resolved is not Arslan's data, so the write rules skip it and the rest of the
    command is read as usual (a spelling of the data folder anywhere in the text is still the
    floor; Seatbelt holds a write the text does not show, Ruling 11)."""
    word = re.sub(r"^(?:\$HOME|\$\{HOME\})(?=/|$)", "~", word)
    if not word or "$" in word:
        return None
    try:
        path = Path(word).expanduser()
    except RuntimeError:            # no such home: classify never raises (a raise ends the turn)
        return None
    return path if path.is_absolute() else None


def other_agent_of(path: Path) -> str:
    """The agent whose settings `path` is in, or ""."""
    home = Path.home()
    for rel, agent in OTHER_AGENTS.items():
        root = home / rel
        if path == root or root in path.parents:
            return agent
    return ""


def _is_start_file(path: Path) -> bool:
    home = Path.home()
    agents = home / "Library" / "LaunchAgents"
    return path in {home / name for name in _START_FILES} or path == agents or agents in path.parents


def _terminal_app(argv: list[str]) -> str:
    """`open -a Terminal script.sh` (the app by name, path or bundle id), `open -a iTerm x`,
    `open x.command|.tool|.terminal`: a script run in a terminal app, outside the sandbox. And
    `open path/to/Some.app` outside the installed-app folders: a program the command may have just
    built, which LaunchServices starts outside the sandbox (named by its bundle). "" otherwise."""
    if _name(argv) != "open":
        return ""
    args, app, files, i = argv[1:], "", [], 0
    while i < len(args):
        if args[i] in ("-a", "-b") and i + 1 < len(args):
            app, i = args[i + 1], i + 2
            continue
        if args[i] == "--args":
            break
        if not args[i].startswith("-"):
            files.append(args[i])
        i += 1
    terminal = {"terminal": "Terminal", "com.apple.terminal": "Terminal", "iterm": "iTerm", "iterm2": "iTerm",
                "com.googlecode.iterm2": "iTerm"}
    key = os.path.basename(app.rstrip("/")).lower().removesuffix(".app")
    if key in terminal and files:
        return terminal[key]
    if any(f.lower().endswith((".command", ".tool", ".terminal")) for f in files):
        return "Terminal"
    for f in files:
        bundle = f.rstrip("/")
        if bundle.lower().endswith(".app") and not bundle.startswith(
                ("/Applications/", "/System/", str(Path.home() / "Applications") + "/", "~/Applications/")):
            return os.path.basename(bundle)[:-4] or "an app"
    return ""


# ── apps: AppleScript and Shortcuts (§A2, §A11) ───────────────────────────────

_JXA_APP = re.compile(r"""\bApplication\(\s*['"]([^'"\n]{1,120})['"]\s*\)""")
_APPSCRIPT_APP = re.compile(r"""\bapp\(\s*['"]([^'"\n]{1,120})['"]\s*\)""")
_SCRIPT_STRING = re.compile(r'"(?:[^"\\\n]|\\.)*"')
#: Outside its strings, an AppleScript that says none of these tells no other app (display a
#: notification, say, delay…); one that does but names no app by a literal reaches an app it builds
#: at run time (`tell application x`, `run script`): it asks as an unknown app.
_SCRIPT_REACHES = re.compile(
    r"\b(?:tell|using\s+terms\s+from)\s+(?:application|app)\b|\bapplication\s+(?:id|process)\b"
    r"|\b(?:run|load)\s+script\b|\bdo\s+script\b|\bApplication\s*\(|\bapp\s*\(|\bObjC\b|\$\.NS"
    r"|\b(?:SBApplication|NSAppleScript|System\s+Events)\b", re.I)
#: Code an AppleScript hands to a shell (`do shell script "…"`, JXA `doShellScript('…')`) or to
#: Terminal/iTerm (`do script "…"`, `write text "…"`): read as the command it is.
_SCRIPT_SHELL = re.compile(
    r"""\b(?:do\s+shell\s+script|do\s+script|write\s+text)\s+"((?:[^"\\\n]|\\.)*)"|"""
    r"""\bdoShellScript\s*\(\s*(?:"((?:[^"\\\n]|\\.)*)"|'((?:[^'\\\n]|\\.)*)')""", re.I)
_SCRIPT_ADMIN = re.compile(r"\bwith\s+administrator\s+privileges\b|\badministratorPrivileges\s*:\s*true\b", re.I)
_SCRIPT_POWER = re.compile(r"\b(?:shut\s+down|restart|log\s+out)\b", re.I)
#: A step that clicks or types: the strings it names are the labels it acts on, not content.
_SCRIPT_UI = re.compile(r"\b(?:click|keystroke|key\s+code|perform\s+action|select\s+menu\s+item)\b", re.I)
_SCRIPT_SENDING_KEY = re.compile(r"\bkeystroke\s+(?:return|enter)\b|\bkey\s+code\s+(?:36|76)\b"
                                 r"|\bkeystroke\b[^\n]*&\s*return\b", re.I)
_SCRIPT_JS = re.compile(r'\bdo\s+JavaScript\s+"((?:[^"\\\n]|\\.)*)"', re.I)
#: §A1/§A11 money words, with the ones in ③Hands' word list for the languages Arslan speaks.
_SCRIPT_MONEY = re.compile(
    r"\b(?:pay|purchase|buy|order|checkout|check\s+out|transfer|pagar|comprar|transferir|bezahlen|kaufen|"
    r"überweisen|payer|acheter|virement)\b|付款|支付|购买|下单|转账|汇款|確認購入|支払|購入|振込", re.I)


def _osascript_findings(commands: list[list[str]], bodies) -> list[Finding]:
    found: list[Finding] = []
    scripts: list[str] = []
    for argv in commands:
        if _name(argv) != "osascript":
            continue
        lines = [argv[i + 1] for i, a in enumerate(argv[:-1]) if a == "-e"]
        if lines:
            scripts.append("\n".join(lines))
        elif not any(program == "osascript" for program, _ in bodies):
            found.append(Finding("apps", "apple-events", "runs an AppleScript file that can control any app",
                                 kind="app"))
    scripts += [body for program, body in bodies if program == "osascript"]
    for script in scripts:
        found += _applescript_findings(script)
    return found


def _applescript_findings(script: str) -> list[Finding]:
    """One AppleScript (or JXA) text: the apps it tells (by name, else one unknown app), the
    commands it hands to a shell or a terminal, and the floor for admin rights and shutting down."""
    found: list[Finding] = []
    steps = _SCRIPT_STRING.sub('""', script)
    if _SCRIPT_ADMIN.search(script):
        found.append(Finding("floor", "sudo", _WHY["sudo"]))
    if _SCRIPT_POWER.search(steps):
        found.append(Finding("floor", "shutdown", "shuts down, restarts or logs out the Mac"))
    payloads = [_unescape(next(g for g in m.groups() if g is not None)) for m in _SCRIPT_SHELL.finditer(script)]
    _check_nested(payloads, "an AppleScript")
    for payload in payloads:
        found += [f for f in classify(payload).findings if f.category != "local"]
    named = app_names(script)
    kind = _app_step_kind(script)
    if named:
        found += app_findings(named, script, kind=kind)
    elif _SCRIPT_REACHES.search(steps):
        found.append(Finding("apps", "apple-events", "runs AppleScript that can control an app it names "
                                                     "only at run time", kind=kind))
    else:
        found.append(Finding("local", "apple-events", "runs AppleScript that tells no other app"))
    return found


def _app_step_kind(script: str) -> str:
    """"money" for a step that pays or buys, "app_risky" for one that deletes, sends, submits or
    types Return in a UI script (③Hands' word list), else "app" (§A1: those two ask every time).
    Words inside AppleScript strings are content (`notes whose name contains "send"`), except
    the labels a UI step clicks or types (`click button "Pay"`) and code run by `do JavaScript`."""
    from server.services import hands_service
    steps = _SCRIPT_STRING.sub('""', script)
    text = script if _SCRIPT_UI.search(steps) else "\n".join([steps, *_SCRIPT_JS.findall(script)])
    if _SCRIPT_MONEY.search(text):
        return "money"
    if hands_service.risky_label(text) or (_SCRIPT_UI.search(steps) and _SCRIPT_SENDING_KEY.search(steps)):
        return "app_risky"
    return "app"


def app_names(script: str) -> list[str]:
    """The apps a script names: AppleScript `tell application "X"` (Hands' own reading),
    JavaScript `Application("X")`, appscript `app('X')`."""
    from server.services import hands_service
    names = list(hands_service.script_apps(script))
    for pattern in (_JXA_APP, _APPSCRIPT_APP):
        names += [m.group(1) for m in pattern.finditer(script) if m.group(1) not in names]
    return names


def app_findings(names: list[str], script: str, *, kind: str | None = None) -> list[Finding]:
    """One finding per app a script tells: the floor for an app on the never-list (Hands'
    `never_touched`, by name and bundle id); a money or risky step asks every time."""
    kind = kind or _app_step_kind(script)
    found = []
    for name in names:
        if _never_touched(name):
            found.append(Finding("floor", "never-app", f"Arslan never touches {name} (the never-list)",
                                 app=name))
        else:
            found.append(Finding("apps", "apple-events", f"uses {name}", app=name, kind=kind))
    return found


def _never_touched(name: str) -> bool:
    """Hands' never-list. When it cannot be read (Hands' policy file is missing), the app is not
    refused unseen and the command is not unread: the app asks, as its own card (review I3)."""
    from server.services import hands_service
    try:
        return hands_service.never_touched(name)
    except Exception:  # noqa: BLE001 — fail closed to the app's card
        logger.warning("terminal_policy: Hands' never-list could not be read; %r asks as its app card", name,
                       exc_info=True)
        return False


def _shortcut_name(argv: list[str]) -> str:
    return argv[2] if len(argv) > 2 and not argv[2].startswith("-") else ""


# ── scripts: read for three things only (§A2) ────────────────────────────────

_RUNNERS = frozenset({"uv", "uvx", "pipx", "poetry", "pdm", "hatch", "conda"})
_SCRIPT_SENDS = re.compile(
    r"\b(?:requests|httpx|session|client|axios)\.(?:post|put|patch|delete)\s*\("
    r"|\b(?:requests|httpx)\.request\s*\(\s*['\"](?:POST|PUT|PATCH|DELETE)"
    r"|\b(?:urlopen|Request)\s*\([^)\n]*\bdata\s*="
    r"|\burlopen\s*\(\s*[^,()\n]+,\s*(?!timeout\b|context\b|cafile\b|capath\b|cadefault\b)[\w'\"(]"
    r"|\bmethod\s*[=:]\s*['\"](?:POST|PUT|PATCH|DELETE)['\"]"
    r"|\.request\s*\(\s*['\"](?:POST|PUT|PATCH|DELETE)['\"]"
    r"|\b(?:smtplib|ftplib|paramiko|telnetlib|nodemailer)\b"
    r"|\bXMLHttpRequest\b|\bWebSocket\b", re.I)
#: An HTTP client in the script, and any `.post(` / `.put(` / `.patch(` / `.delete(` call: a session
#: or client under any name (`s = requests.Session(); s.post(…)`, `import requests as r`).
_HTTP_CLIENT = re.compile(r"\b(?:requests|httpx|aiohttp|urllib3|axios|got|ky|superagent)\b", re.I)
_ANY_SEND_CALL = re.compile(r"\.(?:post|put|patch|delete)\s*\(", re.I)
_SOCKET_USE = re.compile(r"\bimport\s+socket\b|\bfrom\s+socket\s+import\b|\bsocket\.socket\s*\(|\bnet\.(?:connect|createConnection)\s*\(")
_SOCKET_SEND = re.compile(r"\.(?:connect|connect_ex|sendall|sendto)\s*\(|\bnet\.(?:connect|createConnection)\s*\(")
_SCRIPT_APPS = re.compile(r"\b(?:osascript|NSAppleScript|appscript|ScriptingBridge|SBApplication)\b|\bshortcuts\b[\"',\s]+run\b",
                          re.I)
_SCRIPT_HIDDEN = re.compile(
    r"\b(?:exec|eval|Function)\s*\((?=[^\n]*(?:b64decode|b32decode|b85decode|a85decode|base64|decompress|"
    r"unhexlify|fromhex|urlopen|urllib|requests\.get|httpx\.get|\.read\s*\(|fetch\s*\(|atob\s*\(|Buffer\.from|"
    r"decode_base64|\.decode\s*\())"
    r"|\b(?:marshal|pickle|cPickle|dill)\.loads?\s*\(", re.I)
#: A command a script hands to the system, written as a literal: `os.system('…')`, `os.popen`,
#: `subprocess.run([...])` / `('…', shell=True)`, Node's `execSync('…')`, Perl/Ruby `system("…")`
#: and backticks. Spawning programs runs inside the sandbox (§A2), but the command spawned is a
#: command: it is read like one, so `os.system('git push')` asks and `os.system('rm -rf ~')` is the floor.
_SHELL_OUT = re.compile(
    r"""(?:\bsystem|\bpopen|\bsubprocess\.\w+|\bgetoutput|\bgetstatusoutput|\bexecSync|\bexecFileSync|"""
    r"""\bexecFile|\bspawnSync|\bspawn|child_process\.exec|\bIO\.popen|\bOpen3\.\w+)\s*\(\s*"""
    r"""(?:(?P<q>['"])(?P<cmd>(?:\\.|(?!(?P=q)).){1,2000}?)(?P=q)|\[(?P<list>[^\]\n]{1,2000})\])""")
_SCRIPT_LITERAL = re.compile(r"""(['"])((?:\\.|(?!\1).)*)\1""")
_BACKTICK = re.compile(r"`([^`\n]{1,2000})`")


def _unescape(literal: str) -> str:
    """A string literal's text as the program sees it (the escapes a script or AppleScript uses)."""
    return literal.replace('\\"', '"').replace("\\'", "'").replace("\\\\", "\\")


def _shell_outs(script: str, family: str | None) -> list[str]:
    """The literal commands a script runs (see `_SHELL_OUT`); a list form is joined into one
    command line. Ruby and Perl backticks run a shell too."""
    out = []
    for m in _SHELL_OUT.finditer(script):
        if m.group("cmd") is not None:
            out.append(_unescape(m.group("cmd")))
        else:
            words = [_unescape(w) for _, w in _SCRIPT_LITERAL.findall(m.group("list"))]
            if words:
                out.append(shlex.join(words))
    if family in ("ruby", "perl"):
        out += _BACKTICK.findall(script)
    return out


def _script_findings(commands: list[list[str]], bodies) -> list[Finding]:
    """Code written inline for an interpreter — a `-c`/`-e` payload or a heredoc body — read for
    sending (an HTTP call that sends, mail, a raw socket, a command it shells out to), other apps
    and hidden code. Anything else a script does (reading the web, starting programs that stay
    inside, importing modules) runs inside the sandbox. Script files are not read."""
    scripts = [(" ".join(argv[1:]), hermes._interpreter_family(argv[0])) for argv in commands
               if hermes._interpreter_family(argv[0]) is not None and _name(argv) != "osascript"]
    scripts += [(body, hermes._interpreter_family(program) or program) for program, body in bodies
                if program in _RUNNERS or (hermes._interpreter_family(program) is not None and program != "osascript")]
    found: list[Finding] = []
    if any(_runs_fetched_code(argv) for argv in commands):          # review I1
        found.append(Finding("opaque", "fetched-code", _WHY["fetched-code"]))
    for script, family in scripts:
        if (_SCRIPT_SENDS.search(script) or (_HTTP_CLIENT.search(script) and _ANY_SEND_CALL.search(script))
                or (_SOCKET_USE.search(script) and _SOCKET_SEND.search(script))):
            found.append(Finding("send", "script-send", "a script sends data off the Mac"))
        if _SCRIPT_APPS.search(script):
            named = app_names(script)
            found += app_findings(named, script) if named else [
                Finding("apps", "script-apps", "a script controls other apps", kind=_app_step_kind(script))]
        if _SCRIPT_HIDDEN.search(script):
            found.append(Finding("opaque", "script-hidden", "a script runs code it decoded or downloaded"))
        outs = _shell_outs(script, family)
        _check_nested(outs, "a script")
        for command in outs:
            found += [f for f in classify(command).findings if f.category != "local"]
    return found


# ── code fetched or decoded, then run (§A2 opaque; review I1, M1) ─────────────

#: Programs whose output is what the web sent (`curl`, `wget`, HTTPie).
_FETCHERS = frozenset({"curl", "wget", "http", "https", "xh", "xhs"})


def _fetches(argv: list[str]) -> bool:
    return _name(argv) in _FETCHERS


def _decodes(argv: list[str]) -> bool:
    """`base64 -d`, `xxd -r`, `openssl … -d`: the decoders Hermes' decode-to-shell rules name."""
    name, args = _name(argv), argv[1:]
    if name in ("base64", "base32", "base16", "basenc"):
        return any(a in ("-d", "-D", "--decode") or (a.startswith("-") and not a.startswith("--") and "d" in a[1:].lower())
                   for a in args)
    if name == "xxd":
        return any(a.startswith("-") and not a.startswith("--") and "r" in a[1:] for a in args)
    return name == "openssl" and "-d" in args


def _runs_fetched_code(argv: list[str]) -> bool:
    """`bash -c "$(curl …)"`, `eval "$(curl …)"`, `python3 -c "$(curl …)"`: the code a shell or an
    interpreter is handed holds what a download or a decode printed, so it runs code nobody read.
    (A substitution in the code is filled in before the code is read, quoted or not.)"""
    name = _name(argv)
    if name == "eval":
        code = " ".join(argv[1:])
    elif name in _SHELLS:
        code = hermes._bash_exec_payload(argv[1:])[1] or ""
    else:
        family = hermes._interpreter_family(argv[0]) if argv else None
        code = " ".join(argv[1:]) if family and hermes._interpreter_exec_flag(family, argv[1:]) else ""
    return any(_fetches(inner) or _decodes(inner)
               for body in _substitution_bodies(code) for inner in _commands(body))


def _substitution_bodies(code: str) -> list[str]:
    """The text inside each `$(…)`, `<(…)` and backtick span of `code` (outermost)."""
    bodies, i = [], 0
    while i < len(code):
        end = None
        if code.startswith(("$(", "<("), i):
            end = hermes._scan_dollar_paren_end(code, i)
            if end is not None:
                bodies.append(code[i + 2:end - 1])
        elif code[i] == "`":
            end = hermes._scan_backtick_end(code, i)
            if end is not None:
                bodies.append(code[i + 1:end - 1])
        i = end if end is not None else i + 1
    return bodies


def _fetched_code_findings(shell: str) -> list[Finding]:
    """Fetched or decoded code piped into what runs it, in ways Hermes' shell-only patterns miss
    (review M1, R11): an interpreter or a shell with no script of its own (`curl … | python3`,
    `| env bash`, `| source /dev/stdin`) — at the top, and in every substitution, which a quote
    does not stop from running (`echo "$(curl … | python3)"`). Code read from `<(…)`, `<` or a
    here-string is `_code_findings`'."""
    pending, seen = [shell], set()
    while pending:
        text = pending.pop()
        if text in seen:
            continue
        seen.add(text)
        if _pipes_fetched_code(text):
            return [Finding("opaque", "fetched-code", _WHY["fetched-code"])]
        pending += _substitution_bodies(text)
    return []


def _pipes_fetched_code(text: str) -> bool:
    for pipeline in _pipelines(text):
        fed = False
        for piece in pipeline:
            if fed and _runs_its_input(piece):
                return True
            fed = fed or any(_fetches(argv) or _decodes(argv) for argv in _commands(piece))
    return False


def _pipelines(text: str) -> list[list[str]]:
    """Each pipeline in `text`, as its commands' text in order: split at `|` (`|&` too), and from
    the next pipeline at `;`, `&`, `&&`, `||` and newlines; quotes, comments and redirections such
    as `2>&1` respected."""
    pipelines: list[list[str]] = [[]]
    start = skip_to = 0
    for kind, i, j, quote in hermes._scan_shell(text, comments=True):
        if i < skip_to:
            continue
        if kind == "comment":
            pipelines[-1].append(text[start:i])
            pipelines.append([])
            start = skip_to = j
            continue
        if kind != "char" or quote is not None or text[i] not in ";&|\n":
            continue
        ch, nxt = text[i], text[i + 1:i + 2]
        if ch == "&" and ((i and text[i - 1] in "<>") or nxt == ">"):
            continue                                        # `2>&1`, `<&3`, `&>file`: a redirection
        pipelines[-1].append(text[start:i])
        if ch == "|" and nxt != "|":
            start = i + 1 + (nxt == "&")
        else:
            pipelines.append([])
            start = i + 1 + (nxt == ch and ch in "&|")
        skip_to = start
    pipelines[-1].append(text[start:])
    return [p for p in pipelines if any(piece.strip() for piece in p)]


# ── 0.1.52's script exemption, kept until its caller goes (Task 3 deletes this block) ────────
_LEGACY_ASK_C = [re.compile(p, re.I) for p in (
    _POS + r"osascript\b",
    _POS + r"shortcuts\s+run\b",
    _POS + r"(?:mail|mailx|sendmail|msmtp|mutt|himalaya\s+(?:send|write|reply|forward))\b",
    _POS + r"(?:imsg\s+send|xurl\b[^\n]*(?:post|tweet|/2/tweets))",
    _POS + r"(?:curl\b[^\n]*(?:\s-(?:[a-zA-Z]*[dFT])\b|\s--(?:data[a-z-]*|form|upload-file|json)\b|"
           r"-X\s*(?:POST|PUT|PATCH|DELETE)\b|--request\s+(?:POST|PUT|PATCH|DELETE)\b)|"
           r"wget\b[^\n]*--(?:post|method=(?:POST|PUT|DELETE)))",
    _POS + r"(?:ssh|scp|sftp|ftp|rsync\b[^\n]*\S+:)\b",
    _POS + r"git\s+(?:[^\n]*\s)?push\b",
    _POS + r"(?:npm\s+publish|pnpm\s+publish|yarn\s+publish|twine\s+upload|cargo\s+publish|"
           r"gh\s+(?:pr|issue|release|repo|gist)\s+(?:create|delete|merge|close|edit|comment)|"
           r"gh\s+api\b[^\n]*-X\s*(?:POST|PUT|PATCH|DELETE))",
    _POS + r"(?:brew\s+(?:install|reinstall|upgrade|tap)|pip3?\s+install|pipx\s+install|"
           r"npm\s+(?:install|i)\s+(?:-g|--global)|gem\s+install|cargo\s+install)\b",
    _POS + r"(?:launchctl\s+(?:load|bootstrap|enable|submit)|defaults\s+write|crontab\b)",
    _POS + r"(?:rm|rmdir|unlink|trash|srm)\s",
)]
_SCRIPT_RULES = frozenset({"hermes:script execution via -e/-c flag", "hermes:script execution via heredoc"})
_SCRIPT_REACH = re.compile("|".join((
    r"\b(?:requests|urllib\d?|httpx|aiohttp|http\.client|socket|smtplib|ftplib|paramiko|telnetlib|webbrowser"
    r"|subprocess|pty|ctypes|multiprocessing|importlib|base64|codecs|marshal|pickle)\b",
    r"\b(?:os\.(?:system|popen|exec\w*|spawn\w*)|popen\d?|__import__|eval|exec|compile|system|fetch)\s*\(",
    r"\b(?:osascript|applescript|nsapplescript|appscript|scriptingbridge)\b|\bshortcuts\s+run\b",
    r"require\(\s*['\"](?:https?|http2|net|dgram|tls|child_process)['\"]|\b(?:XMLHttpRequest|WebSocket)\b",
    r"\bqx\b|\bopen3\b|\bLWP\b|IO::Socket|Net::\w+|`",
)), re.I)


def runs_freely_in_sandbox(command: str) -> bool:
    """0.1.52's exemption, exactly as before; Task 3 removes it with its caller (tool_loop). It
    never raises, and never reads a command `classify` (memoized) could not read or found the
    floor in (review N6: Hermes' own detection is slow on the shapes the ceilings stop)."""
    try:
        found = classify(command)
        if found.floor is not None or UNREADABLE in found.findings:
            return False
        return _runs_freely(command)
    except Exception:  # noqa: BLE001 — the card comes back
        return False


def _runs_freely(command: str) -> bool:
    text = str(command or "")
    if not text.strip() or len(text) > MAX_COMMAND_CHARS or hermes.detect_hardline_command(text)[0]:
        return False
    dangerous, key, _description = hermes.detect_dangerous_command(text)
    if not dangerous or f"hermes:{key}" not in _SCRIPT_RULES:
        return False
    normalized = hermes._normalize_command_for_detection(text)
    if _SCRIPT_REACH.search(text) or _SCRIPT_REACH.search(normalized):
        return False
    texts = (text, normalized, *hermes._command_detection_variants(text))
    if any(pattern.search(t) for pattern in _LEGACY_ASK_C for t in texts):
        return False
    lowered = hermes._lower_preserving_flags(text)
    for pattern_re, description in hermes.DANGEROUS_PATTERNS_COMPILED:
        if f"hermes:{description}" not in _SCRIPT_RULES and pattern_re.search(lowered):
            return False
    return all(f"hermes:{d}" in _SCRIPT_RULES for d, _ in hermes._execution_flag_findings(normalized))

# ── "don't ask again", remembered by rule ─────────────────────────────────────

async def always_allowed(db) -> set[str]:
    """Rules the user said not to ask about again (0.1.61: `legacy_rule` rows in the permission
    store). Unreadable means none: ask."""
    from server.services import permission_store
    try:
        return {r.target for r in await permission_store.list_rules(db, "legacy_rule")} - _NEVER_REMEMBERED
    except Exception:  # noqa: BLE001 — a standing permission is never inferred from an error
        return set()


#: Rules that can never be remembered, and that no stored rule stands for (review N5): the floor; a
#: command nobody could read; code downloaded, decoded or built at run time (once-only cards).
_NEVER_REMEMBERED = frozenset({k for k, _, _ in _FORBID} | {"hardline", "empty", "too-long", "arslan-data",
                                                           "never-app", "disk-erase", "shutdown", "unreadable",
                                                           "fetched-code", "built-code"})


async def allow_always(db, rule: str) -> None:
    """Remember a rule. Forbidden rules and the empty rule can never be remembered."""
    from server.services import permission_store
    if not rule or rule in _NEVER_REMEMBERED:
        return
    await permission_store.add_rule(db, "legacy_rule", rule, label=describe(rule),
                                    created_from="card")
    await db.commit()


async def forget(db, rule: str) -> None:
    from server.services import permission_store
    await permission_store.delete_rule_by(db, "legacy_rule", rule)
    await db.commit()


def describe(rule: str) -> str:
    """What a remembered rule lets through, in the words the card used when it asked."""
    if rule in _WHY:
        return _WHY[rule]
    return rule.split(":", 1)[1] if rule.startswith("hermes:") else rule
