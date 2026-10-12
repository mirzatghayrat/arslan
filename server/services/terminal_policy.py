"""What Arslan's terminal may run, and what crosses a boundary (0.1.48; categories 0.1.61 §A2).

`classify(command)` returns every finding in a command, each with a category:

  floor        never, even with a click: wiping disks or the home folder, shutting down, fork
               bombs, sudo, reading passwords out of the keychain, Arslan's own data, keys and
               database, an app on the never-list.
  opaque       code that is downloaded or decoded and then run.
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
    text = str(command or "")
    if not text.strip():
        return Classification(text, (Finding("floor", "empty", "no command"),))
    if len(text) > MAX_COMMAND_CHARS:
        return Classification(text, (Finding("floor", "too-long", "command is too long to review"),))
    shell, bodies = split_heredocs(text)
    commands = _commands(shell)
    findings: list[Finding] = []
    findings += _floor_findings(text, shell, commands)
    findings += _hermes_findings(shell, raw=text)
    findings += _arslan_findings(shell, commands, bodies)
    findings += _script_findings(commands, bodies)
    seen: set[tuple] = set()
    unique = []
    for f in findings:
        key = (f.category, f.rule, f.app, f.kind)
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return Classification(text, tuple(unique))


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
    return bool(rules) and rules <= allowed


def risk_grade(command: str) -> str:
    """The LOW/MEDIUM/HIGH grade the confirmation layer speaks (run/ask/forbid)."""
    return {"run": "LOW", "ask": "MEDIUM", "forbid": "HIGH"}[assess(command).level]


# ── heredocs and commands ─────────────────────────────────────────────────────

_HEREDOC_OP = re.compile(r"<<(-?)[ \t]*(?:'([^'\n]+)'|\"([^\"\n]+)\"|\\?([A-Za-z_][\w.-]*))")
_PIPED_TO_SHELL = re.compile(r"\|\s*(?:\S*/)?(?:bash|sh|zsh|dash|ksh)\b")


def split_heredocs(text: str) -> tuple[str, list[tuple[str, str]]]:
    """(the command with every heredoc body that is data removed, [(program, body)]).

    A body is data for the program that reads it (`cat > README.md <<EOF` writes text, `python3
    - <<EOF` reads code, `sqlite3 db <<SQL` reads SQL), so shell rules never see it. A body read
    by a shell (`bash <<EOF`, or piped into one) stays: it is shell. The body ends at the first
    line that is exactly the delimiter (tabs stripped for `<<-`), or at the end, as in the shell."""
    out: list[str] = []
    bodies: list[tuple[str, str]] = []
    pos, n = 0, len(text)
    while pos < n:
        ops, newline = [], None
        for kind, i, _j, quote in hermes._scan_shell(text, pos):
            if kind != "char" or quote is not None:
                continue
            if text[i] == "\n":
                newline = i
                break
            if text.startswith("<<", i) and not text.startswith("<<<", i) and (i == 0 or text[i - 1] != "<"):
                match = _HEREDOC_OP.match(text, i)
                if match:
                    ops.append(match)
        if newline is None:
            out.append(text[pos:])
            break
        out.append(text[pos:newline + 1])
        line_end = newline
        pos = newline + 1
        for match in ops:
            delimiter = match.group(2) or match.group(3) or match.group(4)
            strip_tabs = match.group(1) == "-"
            start, end, after = pos, n, n
            cursor = pos
            while cursor < n:
                stop = text.find("\n", cursor)
                stop = n if stop < 0 else stop
                line = text[cursor:stop]
                if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                    end, after = cursor, min(stop + 1, n)
                    break
                cursor = stop + 1
            program = _heredoc_program(text, match.start())
            rest_of_line = text[match.end():line_end]
            if program in _SHELLS or _PIPED_TO_SHELL.search(rest_of_line):
                out.append(text[start:after])
            else:
                bodies.append((program, text[start:end]))
            pos = after
    return "".join(out), bodies


def _heredoc_program(text: str, at: int) -> str:
    """The program a heredoc at `at` feeds: the command word of its simple command."""
    line_start = text.rfind("\n", 0, at) + 1
    head = re.split(r"\|\||&&|[;&|(]|\$\(", text[line_start:at])[-1]
    try:
        words = shlex.split(head, posix=True)
    except ValueError:
        words = head.split()
    for word in words:
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", word) or word in hermes._COMMAND_WRAPPER_WORDS:
            continue
        return os.path.basename(word).lower()
    return ""


#: Programs that run the command written after their own options: what they run is read too.
_RUNS_NEXT = frozenset({"xargs", "watch", "caffeinate", "arch", "ionice", "stdbuf", "unbuffer", "chronic",
                        "flock", "parallel", "npx", "bunx", "pnpx", "uvx"})
_FIND_RUNS = ("-exec", "-execdir", "-ok", "-okdir")


def _commands(text: str, depth: int = 0) -> list[list[str]]:
    """The argv of every simple command in `text`, quote-aware (Hermes' own tokenizer): wrappers
    (`sudo`, `env`, `nohup`) appear with the command they run and as that command alone; what a
    shell runs (`bash -c '…'`, `eval '…'`) and what `xargs`, `find -exec`, `watch` … run appear as
    their own commands. Hermes' tokenizer reads to the end of the segment, so the closer of a
    subshell or substitution sticks to the last word (`(git push)` → `push)`): it is stripped."""
    out: list[list[str]] = []

    def add(tokens: list[str]) -> None:
        out.append(tokens)
        if depth < 3:
            payload = (" ".join(tokens[1:]) if _name(tokens) == "eval"
                       else hermes._bash_exec_payload(tokens[1:])[1] if _name(tokens) in _SHELLS else None)
            if payload:
                out.extend(_commands(payload, depth + 1))

    for segment in hermes._iter_top_level_shell_segments(text):
        for start, _end, word in hermes._iter_shell_command_word_spans(segment):
            tokens = hermes._shell_segment_tokens(segment, start)
            if not tokens:
                continue
            tokens = [hermes._deobfuscate_shell_word_for_detection(word),
                      *(t.rstrip(")`") for t in tokens[1:])]
            tokens = [t for t in tokens if t]
            if not tokens:              # `''` alone: no command word, nothing runs (an empty argv raised)
                continue
            add(tokens)
            for inner in _run_by(tokens):
                add(inner)
    return out


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
    for subject in (normalized, text):
        for match in _ARSLAN_DATA.finditer(subject):
            if not (match.group("folder") and _reads_a_skill(subject, match.end())):
                return True
    literal = _data_dir_literal()
    if literal:
        for subject in (normalized, text):
            for match in re.finditer(re.escape(literal) + r"(?=[/\s\"';|&)]|$)", subject):
                if not _reads_a_skill(subject, match.end()):
                    return True
    return False


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

def _hermes_findings(shell: str, *, raw: str) -> list[Finding]:
    """Every Hermes finding for the command, where `detect_dangerous_command` stops at the first,
    each placed by HERMES_CATEGORIES."""
    if hermes._is_verification_artifact_cleanup(shell):
        return []
    found: list[str] = []
    for variant in hermes._command_detection_variants(shell):
        lowered = hermes._lower_preserving_flags(variant)
        carrier = hermes._contains_shell_carrier(variant)
        masked = hermes._lower_preserving_flags(hermes._mask_quoted_prose(variant))
        sql_client = any(_name(argv) in _SQL_CLIENTS for argv in _commands(variant))
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
_CURL_SENDING = ("--data", "--data-ascii", "--data-binary", "--data-raw", "--data-urlencode", "--form",
                 "--form-string", "--upload-file", "--json")
_CURL_VALUE_SHORT = frozenset("dFTXHAbceEhKmortuUwxyYzCPQ")
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
    """curl or wget sending data: curl's data flags are case-sensitive (`-f`, `-sSf`, `-D -` read)."""
    name, args = _name(argv), argv[1:]
    if name == "wget":
        return any(a.startswith(_WGET_SENDING) or (a.startswith("--method=") and a[9:].upper() in _SEND_METHODS)
                   for a in args) or any(a == "--method" and i + 1 < len(args) and args[i + 1].upper() in _SEND_METHODS
                                         for i, a in enumerate(args))
    if name != "curl":
        return False
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--":
            break
        if arg.startswith("--"):
            option, equals, value = arg.partition("=")
            if option in _CURL_SENDING:
                return True
            if option == "--request":
                method = value if equals else (args[i + 1] if i + 1 < len(args) else "")
                if method.upper() in _SEND_METHODS:
                    return True
                i += 1 if equals else 2
                continue
            i += 1
            continue
        if arg.startswith("-") and len(arg) > 1:
            letters, skip = arg[1:], 1
            for j, letter in enumerate(letters):
                if letter in "dFT":
                    return True
                if letter == "X":
                    method = letters[j + 1:] or (args[i + 1] if i + 1 < len(args) else "")
                    if method.upper() in _SEND_METHODS:
                        return True
                if letter in _CURL_VALUE_SHORT:
                    skip = 1 if j + 1 < len(letters) else 2      # its value: the rest, or the next word
                    break
            i += skip
            continue
        i += 1
    return False


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
        return True
    if name != "kill":
        return False
    args = argv[1:]
    for i, arg in enumerate(args):
        if arg.upper() in ("-9", "-KILL", "-SIGKILL"):
            return True
        if arg == "-s" and i + 1 < len(args) and args[i + 1].upper() in ("9", "KILL", "SIGKILL"):
            return True
    return False


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
    for m in _SCRIPT_SHELL.finditer(script):
        payload = _unescape(next(g for g in m.groups() if g is not None))
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
    from server.services import hands_service
    kind = kind or _app_step_kind(script)
    found = []
    for name in names:
        if hands_service.never_touched(name):
            found.append(Finding("floor", "never-app", f"Arslan never touches {name} (the never-list)",
                                 app=name))
        else:
            found.append(Finding("apps", "apple-events", f"uses {name}", app=name, kind=kind))
    return found


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
        for command in _shell_outs(script, family):
            found += [f for f in classify(command).findings if f.category != "local"]
    return found


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
    """0.1.52's exemption, exactly as before; Task 3 removes it with its caller (tool_loop)."""
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
        return {r.target for r in await permission_store.list_rules(db, "legacy_rule")}
    except Exception:  # noqa: BLE001 — a standing permission is never inferred from an error
        return set()


#: Rules that can never be remembered: the floor.
_NEVER_REMEMBERED = frozenset({k for k, _, _ in _FORBID} | {"hardline", "empty", "too-long", "arslan-data",
                                                           "never-app", "disk-erase", "shutdown"})


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
