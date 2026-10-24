"""What Arslan's terminal may run, and when it asks first (0.1.48; three layers since v0.1.63 S2a-2).

Three answers for any shell command:

  forbid  layer ①, never, inside the sandbox or out: wiping the disk, the home folder or a
          system folder, writing a raw disk, shutting the Mac down, fork bombs, killing every
          process, reading passwords out of the keychain, touching Arslan's own key files,
          anything that needs sudo.
  ask     layer ②, this time only (the card offers nothing to remember, and a stored "Always"
          does not answer it): sending or publishing something, deleting outside the working
          folder, killing other programs, changing how the Mac starts or behaves, the keychain
          or system settings, controlling other apps (osascript, Shortcuts), opening an app or
          a link outside the sandbox, reading the screen or the clipboard — and a command this
          module cannot read (`unreadable`: anything outside the grammar shell_grammar reads,
          which also covers unbalanced quoting, `eval` and inline code of another interpreter;
          too many commands to read; reading that takes too long; something downloaded or
          decoded piped into a shell; an inline script that reaches out).
  run     layer ③, everything else. Since S2a-3 that has to be earned: only a command whose
          whole text shell_grammar understands gets here. The tool loop runs it in the
          workspace sandbox without a card when the sandbox can start
          (`command_sandbox.available()`); otherwise, or when the sandbox is switched off, it
          asks (target `unsandboxed:*`).

The rules are Arslan's own; the hard floor (layer ①) is adapted from Hermes Agent's (MIT;
NousResearch/hermes-agent), keeping what applies to macOS. Commands are read through
server/services/shell_text.py (S2b-1), Arslan's copy of Hermes' text handling: the command-start
pass, the variants with a newline at every real command start, and the quote masks. Hermes'
MIT license is in THIRD_PARTY_NOTICES.md ("Terminal command reading").

Everything here is a pure function of the command text. It is a guard against mistakes and
against instructions smuggled in through web pages, not a sandbox: the sandbox (S2a-1) is what
holds a layer ③ command, and a command outside it runs with the user's own permissions.
"""
from __future__ import annotations

import asyncio
import collections
import re
import shlex
import threading
from dataclasses import dataclass

from server.services import shell_grammar, shell_text

MAX_COMMAND_CHARS = 8000

_POS = shell_text.CMDPOS        # command position: start, after ; | && $( ` and sudo/env wrappers

# ── layer ①: forbid ──────────────────────────────────────────────────────────

# A path a recursive delete must never reach, wrapped in a matching quote pair or bare with a
# terminator, so `rm -rf "/"` and `$(rm -rf /)` are caught (Hermes' `_hardline_rm_path`).
def _rm_path(alternatives: str) -> str:
    return rf"(?:[\"'](?:{alternatives})[\"']|(?:{alternatives})(?:\s|$|[)`;|&]))"


_RM = _POS + r"rm\s+(?:-[^\s]*\s+)*"
# The macOS roots: Hermes' Linux list where macOS has the folder (/etc, /usr, /var, /bin, /sbin,
# /private behind them) and the macOS ones (0.1.48's `macos-roots`), each with an optional glob.
_ROOTS = "|".join(f"/{name}(?:/\\*)?" for name in (
    "etc", "usr", "var", "bin", "sbin", "private", "System", "Library", "Applications", "Users", "Volumes", "opt"))
_RAW_DISK = r"/dev/r?disk\d"
# (rule, pattern, why, quote_masked): a positionless rule (no command word to anchor: a redirect,
# a function definition) is matched with quoted prose masked out, so `echo "x > /dev/disk2"` is data.
_FORBID = [
    ("keychain-secrets", _POS + r"security\s+(?:[^\n]*\s)?(?:find-(?:generic|internet)-password[^\n]*\s-w\b|"
                                r"find-(?:generic|internet)-password[^\n]*\s-g\b|dump-keychain|export\b)",
     "reads passwords out of the keychain", False),
    ("arslan-keys", r"(?:\.arslan/secret_key|\.arslan-updater\.key|arslan-signing-backup)",
     "touches Arslan's own key files", False),
    # Arslan has no terminal to type an admin password into, and should not act as root:
    # a command that needs sudo is one to hand to the user.
    ("sudo", r"(?:^|[\n;&|`(]|\$\()\s*sudo\b", "needs administrator rights; run it yourself", False),
    # Any root-anchored path that collapses to "/" ("/", "//", "/.", "/../..", a trailing glob), or
    # `rm -rf / *` (Hermes' rule, unchanged).
    ("wipe-root", _RM + _rm_path(r"/(?:(?:\.\.?)?/)*(?:\.\.?)?\**|/ \*"), "recursive delete of the whole disk", False),
    ("wipe-home", _RM + _rm_path(r"(?:~|\$\{?HOME\}?)(?:/?|/\*)?"), "recursive delete of your home folder", False),
    ("macos-roots", _RM + _rm_path(_ROOTS), "recursive delete of a macOS system folder", False),
    ("raw-disk", _POS + r"(?:dd\b[^\n]*\bof=" + _RAW_DISK
                 + r"|diskutil\s+(?:erase\w*|zeroDisk|secureErase|randomDisk|partitionDisk|reformat)\b"
                 + r"|newfs_\w+)", "erases or overwrites a disk", False),
    ("raw-disk", r">\s*" + _RAW_DISK, "overwrites a disk", True),
    ("fork-bomb", r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", "a fork bomb (freezes the Mac)", True),
    ("kill-all", _POS + r"kill\s+(?:-[^\s]+\s+)*-1\b", "kills every process", False),
    ("shutdown", _POS + r"(?:shutdown|reboot|halt|poweroff)\b", "shuts down or restarts the Mac", False),
]

# ── layer ②: this time only ──────────────────────────────────────────────────

# 0.1.62 F4a (R2): how osascript and `shortcuts run` are reached in command position however
# they are written: through `command` (not `command -v`, which only looks it up), `exec` (with
# -a NAME, -c, -l), or `xargs` with its options, named by a path or not. Built so it never
# backtracks: every alternative starts differently, and no blank between words crosses a line
# break (`_H`), so many lines of launchers are tried line by line (an overlapping first version
# took ~3x longer per xargs option; one that let `exec` match in two places and across lines took
# cubic time). Its own command position for that reason: Hermes' `_CMDPOS` also consumes `exec`
# and lets blanks cross lines. An xargs option that takes a value is case-sensitive (-r and -p
# are flags; -R and -P take values) and has the value attached (-n1, -I{}) or after blanks (-n 1,
# -I {}; the command-start pass splits {} across a line). S2a-2: every layer ② rule is reached
# this way (`_CMD`), so `/usr/bin/git push`, `command git push` and `xargs curl -d` ask too.
_H = r"[^\S\n]"
_ONCE_POS = (r"(?:^|[\n`]|\$\()" + _H + r"*(?:sudo" + _H + r"+(?:-\S+" + _H + r"+)*)?"
             r"(?:\w+=\S*" + _H + r"+)*"
             r"(?:(?:[^\s=]*/)?env" + _H + r"+(?:-\S+" + _H + r"+)*(?:\w+=\S*" + _H + r"+)*)?"
             r"(?:(?:nohup|setsid|time|nice|caffeinate|timeout" + _H + r"+\S+|xcrun|arch" + _H + r"+-\S+)"
             + _H + r"+)*")
_XARGS_VALUE = r"(?:\{\s*\}|[^\s{-]\S*)"
_XARGS_OPT = (r"(?:--\S+|(?-i:-[IJLPRSEdins])(?:" + _H + r"+" + _XARGS_VALUE + r"|\S+)"
              r"|(?-i:-[^\sIJLPRSEdins-])\S*)")
_LAUNCHED = (r"(?:command" + _H + r"+(?:-p" + _H + r"+)?"
             r"|builtin" + _H + r"+command" + _H + r"+"
             r"|exec" + _H + r"+(?:-a" + _H + r"+\S+" + _H + r"+|-[cl]+" + _H + r"+)*"
             r"|xargs(?:" + _H + r"+" + _XARGS_OPT + r")*" + _H + r"+)*"
             r"(?:[^\s=]*/)?")         # a path, never a VAR=value assignment
_CMD = _ONCE_POS + _LAUNCHED
# The program itself, not a longer name that starts with it (osascript.sh, osascriptx); a
# redirection may follow it directly (osascript<<EOF, osascript>/dev/null).
_END = r"(?=$|[\s;&|)`'\"<>])"
# HTTP methods that change something, and HTTPie / xh sending data: a method word, or a request
# item (`key=value`, `key:=json`, `field@file`), a form, or a body on stdin.
_WRITE = r"(?:POST|PUT|PATCH|DELETE)"
_HTTPIE = r"(?:https?|xhs?)"
# Apps that run what they are given (`open -a`/`-b`): terminals, script and automation apps.
_SCRIPT_APPS = (r"(?:terminal|iterm2?|warp|kitty|alacritty|wezterm|hyper|ghostty|script\s+editor|automator"
                r"|shortcuts(?:\s+events)?|system\s+events|com\.apple\.(?:terminal|scripteditor2|automator|shortcuts)"
                r"|com\.googlecode\.iterm2|dev\.warp\.\S+)")
# Files that make something run later, or hold the user's keys (②Main's review of S2a-2): shell startup
# files, SSH (authorized_keys, config), the credential folders, launch agents, and other agents' settings. In the sandbox a write to
# them fails; outside it (a grant to leave the sandbox, or no sandbox at all) it would not, so a write asks,
# this time only. Reads are not here: ssh, git push and gh read them outside the sandbox (S2a-1).
_PROTECTED_NAME = (r"(?:\.ssh(?=/|\b)|\.(?:zshrc|zshenv|zprofile|zlogin|zlogout|bashrc|bash_profile|bash_login"
                   r"|bash_logout|profile|inputrc|cshrc|tcshrc|kshrc)(?![\w.-])|\.config/(?:fish|gh|gcloud)(?=/|\b)"
                   r"|\.(?:aws|gnupg|kube|azure)(?=/|\b)|\.docker/config\.json|\.(?:netrc|npmrc|pypirc|git-credentials"
                   r"|gitconfig)(?![\w.-])|Library/(?:LaunchAgents|LaunchDaemons|StartupItems|Keychains)(?=/|\b)"
                   # other agents' settings start programs (hooks, MCP servers) the next time they run
                   r"|\.(?:cursor|codex|claude|gemini|hermes|continue)/|\.claude\.json\b"
                   r"|Library/Application Support/Claude/)")
_PROTECTED_PATH = (r"[\"']?(?:(?:~|\$HOME|\$\{HOME\}|/Users/[^/\s'\"]+)/" + _PROTECTED_NAME
                   + r"|/(?:private/)?etc/|/Library/(?:LaunchAgents|LaunchDaemons|StartupItems)(?=/|\b))")
_ASK = [
    # F4a: first, so a card for a script that also uploads names the app it drives
    ("apple-events", _CMD + r"osascript" + _END, "controls other apps (it could send, delete or buy)"),
    ("shortcuts", _CMD + r"shortcuts" + _H + r"+run" + _END, "runs one of your Shortcuts"),
    # sends something out
    ("send-mail", _CMD + r"(?:mail|mailx|sendmail|msmtp|mutt|himalaya" + _H + r"+(?:send|write|reply|forward))" + _END,
     "sends email"),
    ("send-message", _CMD + r"(?:imsg" + _H + r"+send|xurl\b[^\n]*(?:post|tweet|/2/tweets))", "sends a message or posts"),
    ("upload", _CMD + r"(?:curl\b[^\n]*(?:\s(?-i:-[a-zA-Z]*[dFT])\b|\s--(?:data[a-z-]*|form[a-z-]*|upload-file|json)\b"
                      r"|\s(?-i:-[a-zA-Z]*X)\s*[\"']?" + _WRITE + r"\b|--request(?:=|\s+)[\"']?" + _WRITE + r"\b)"
                      r"|wget\b[^\n]*--(?:post[a-z-]*|method(?:=|\s+)[\"']?(?:" + _WRITE + r"))"
                      r"|" + _HTTPIE + r"(?:\s+-\S+)*\s+[\"']?" + _WRITE + r"\b"
                      r"|" + _HTTPIE + r"\b[^\n]*(?:\s--(?:form|multipart|raw)\b|\s-f\b|\s[A-Za-z_][\w.\-\[\]]*(?::=|=|@)(?!=))"
                      r"|aws" + _H + r"+s3" + _H + r"+(?:cp|mv|sync|rm)\b)", "sends data to a website or a cloud"),
    # a body piped in or redirected in: `cat d.json | http url`, `http url < d.json`
    ("upload", r"\|\s*(?:[^\s=|]*/)?" + _HTTPIE + _END, "sends data to a website or a cloud"),
    ("upload", _CMD + _HTTPIE + r"\b[^\n|;&]*\s<\s*[^\s<]", "sends data to a website or a cloud"),
    # `rsync a host:/b` too (0.1.48's `\S+:)\b` wanted a word character after the colon).
    # A raw socket (nc, telnet…) sends whatever it is given: `nc mail.example.com 25` is an email. A
    # port check (`nc -z`, `-zv`) sends nothing.
    ("remote-shell", _CMD + r"(?:ssh|ssh-copy-id|sshpass|autossh|mosh|scp|sftp|ftp|telnet|socat|(?:nc|ncat|netcat)(?!\s+-[a-zA-Z]*z))"
     + _END
     + r"|" + _CMD
     + r"rsync\b[^\n]*\S:", "connects to another machine"),
    ("git-push", _CMD + r"git\s+(?:[^\n]*\s)?push\b", "publishes to a remote repository"),
    ("publish", _CMD + r"(?:npm\s+publish|pnpm\s+publish|yarn\s+publish|twine\s+upload|cargo\s+publish"
                       r"|gh\s+(?:pr|issue|release|repo|gist)\s+(?:create|delete|merge|close|edit|comment)"
                       r"|gh\s+api\b[^\n]*(?:\s-[a-zA-Z]*X\s*[\"']?" + _WRITE + r"\b|\s--method(?:=|\s+)[\"']?(?!GET\b)\w"
                       r"|\s(?:-f|-F|--field|--raw-field|--input)(?:[\s=]|$|\S))"
                       r"|docker\s+(?:image\s+)?push|terraform\s+(?:apply|destroy)"
                       r"|kubectl\s+(?:apply|create|delete|replace|patch|scale|rollout)"
                       r"|vercel(?:\s+(?:deploy|--prod)|\s*$|\s*[;&|]))",
     "publishes or changes something online"),
    # deletes or stops things
    ("force-kill", _CMD + r"(?:kill" + _H + r"+(?:-[^\s]+" + _H + r"+)*-(?:9|KILL|SIGKILL)\b|killall|pkill)" + _END,
     "force-quits other programs"),
    # changes how the Mac behaves
    ("login-items", _CMD + r"(?:launchctl\s+(?:load|bootstrap|enable|submit)|defaults\s+write|crontab(?!\s+-l\b))" + _END,
     "changes how your Mac starts or behaves"),
    ("keychain-write", _CMD + r"security\s+(?:add-\w+|delete-\w+|import|set-\w+)\b", "changes your keychain"),
    ("system-settings", _CMD + r"(?:tccutil\s+reset|networksetup\s+-set\w*|systemsetup\s+-set\w*|pmset(?!\s+-g\b)"
     + r"|spctl|scutil\s+--set)\b", "changes system settings (network, privacy, power, security)"),
    # reaches outside the sandbox through the system (S2a's open question): what `open` starts runs outside
    # the sandbox (LaunchServices). A document opened in its viewer is harmless (`open -a Preview x.pdf`);
    # a link, a file that runs (an app, a script, a workflow), or an app that runs scripts (a terminal,
    # Script Editor, Automator, Shortcuts, System Events: `open -a Terminal x.command`) is not.
    ("open-app", _CMD + r"open\s+(?:[^\n;&|]*\s)?(?:-[a-zA-Z]*[ab]\s+[\"']?" + _SCRIPT_APPS + r"\b"
                        r"|[\"']?[a-z][\w+.-]*:"
                        r"|[^\s;&|]*\.(?:app|command|tool|sh|terminal|workflow|scpt|applescript|shortcut)[\"']?(?:\s|$|[;&|)]))",
     "opens an app, a script or a link outside the sandbox"),
    ("screen-clipboard", _CMD + r"(?:screencapture|pbpaste)" + _END, "reads your screen or clipboard"),
    # a write into a protected file: a redirect, a program that writes its operands, or an in-place edit
    ("protected-write", r"(?:>>?|&>>?|>\|)\s*" + _PROTECTED_PATH + r"|" + _CMD
     + r"(?:tee|cp|mv|ln|install|ditto|rsync|truncate|touch|chmod|chown|chflags|xattr|dd|sed|perl|ruby)" + _END
     + r"[^\n;&|]*?(?:\s|=)" + _PROTECTED_PATH
     # ~/.gitconfig by git itself: core.hooksPath, an alias or core.sshCommand runs code later
     + r"|" + _CMD + r"git\s+config\s+(?:[^\n;&|]*\s)?--(?:global|system)\b"
     + r"(?![^\n;&|]*\s(?:--get[\w-]*|--list|-l|--show-\w+)\b)",
     "changes your shell startup, SSH, credential, login or agent settings files"),
]
#: Layer ② by group. The names are stable: the M1 driver answers cards by them
#: (scripts/kernel_bench/arslan_driver.py) and task_service reads the outbound ones.
SEND_OUT_RULES = frozenset({"send-mail", "send-message", "upload", "remote-shell", "git-push", "publish"})
#: What may have left something behind elsewhere when it fails (task_service.known_local_failure).
OUTBOUND_RULES = SEND_OUT_RULES | {"apple-events", "shortcuts"}
#: The two whose approved plain call may run with no sandbox at all (U11, task_service.unwrapped_once).
BARE_RULES = frozenset({"apple-events", "shortcuts"})
UNREADABLE = "unreadable"

# S2a-3 b (the user's decision, 2026-10-22): programs that ask macOS to act for them outside the sandbox,
# which the sandbox does not stop (launchd runs a job, LaunchServices opens an app, Shortcuts runs a
# shortcut, the at daemon runs a command later …). Two tiers. The distinctive names ask wherever they
# appear in the text, and wherever the reader found them as a command (quotes removed). The common words
# ask only where the reader found a command: anything it could not read asks already (`unreadable`). A
# command that matches a named rule keeps that name (U11 and the Inbox go by it); this one names the rest.
# DELETE-BY: revise when v0.1.64's default-deny sandbox stops these services from the sandbox itself.
OUTSIDE_REACH = ("outside-reach", "asks macOS to act for it outside the sandbox")
_OUTSIDE_NAMES = frozenset({"launchctl", "crontab", "shortcuts", "tccutil", "networksetup", "osascript", "killall"})
_OUTSIDE_COMMANDS = frozenset({"open", "at", "batch"})
_SECURITY_WRITES = r"(?:add-[\w-]+|delete-[\w-]+|import|set-[\w-]+|create-[\w-]+|unlock-[\w-]+|export)"
# Not a file named after one (shortcuts.txt, osascript.log): the word, not a name with an extension.
_OUTSIDE_ANYWHERE = re.compile(r"(?<![\w.-])(?:" + "|".join(sorted(_OUTSIDE_NAMES)) + r")(?![\w-]|\.\w)"
                               r"|(?<![\w.-])security\s+" + _SECURITY_WRITES + r"(?![\w-])", re.I)

#: Rules a card answers for this one time only: nothing to remember, and no stored answer stands.
ONCE_ONLY_RULES = frozenset({key for key, _, _ in _ASK}) | {"delete-outside", UNREADABLE, OUTSIDE_REACH[0]}

# An inline script (python -c, node -e, a heredoc …) that reaches out, starts programs, drives
# apps or hides its code: the text alone cannot say what it does (0.1.52's `_SCRIPT_REACH`). Not
# osascript: it is layer ② already (`apple-events`), and its approved plain call may run bare (U11).
_INLINE_SCRIPT = re.compile(
    _POS + r"(?:python[0-9.]*|node|nodejs|deno|bun|perl|ruby|php|lua|tclsh|swift)\b[^\n]*"
           r"(?:\s-[a-zA-Z]*[ceE]\b|<<|\s-(?:$|\s))", re.I)
_SCRIPT_REACH = re.compile("|".join((
    # Python modules that reach out, spawn programs or hide code (a URL inside data is fine)
    r"\b(?:requests|urllib\d?|httpx|aiohttp|http\.client|socket|smtplib|ftplib|paramiko|telnetlib|webbrowser"
    r"|subprocess|pty|ctypes|multiprocessing|importlib|base64|codecs|marshal|pickle)\b",
    # calls that run other programs or evaluate code
    r"\b(?:os\.(?:system|popen|exec\w*|spawn\w*)|popen\d?|__import__|eval|exec|compile|system|fetch)\s*\(",
    # other apps
    r"\b(?:osascript|applescript|nsapplescript|appscript|scriptingbridge)\b|\bshortcuts\s+run\b",
    # node, perl, ruby
    r"require\(\s*['\"](?:https?|http2|net|dgram|tls|child_process)['\"]|\b(?:XMLHttpRequest|WebSocket)\b",
    r"\bqx\b|\bopen3\b|\bLWP\b|IO::Socket|Net::\w+|`",
)), re.I)
_SHELLS = r"(?:ba|z|k|da|c|tc|fi)?sh"
# Code the command fetches, decodes or builds, then runs: eval; source/. of a process
# substitution; a download or decode piped into a shell or an interpreter; `sh <(curl …)`.
_FETCHED_CODE = re.compile("|".join((
    _POS + r"eval\b",
    _POS + r"(?:source|\.)\s+<\(",
    r"(?:curl|wget|fetch|nc|ncat|base64\s+(?:-d|-D|--decode)|xxd\s+-r|openssl\s+(?:enc|base64)\b[^\n|]*\s-d)\b[^\n|]*\|"
    r"\s*(?:sudo\s+)?(?:env\s+)?(?:" + _SHELLS + r"|python[0-9.]*|perl|ruby|node)\b",
    r"\b" + _SHELLS + r"\s+(?:-\S+\s+)*<\(\s*(?:curl|wget)\b",
    r"\b" + _SHELLS + r"\s+-c\s+[\"']?\$\(\s*(?:curl|wget)\b",
)), re.I)

_FORBID_C = [(k, re.compile(p, re.I | re.DOTALL), w, masked) for k, p, w, masked in _FORBID]
_ASK_C = [(k, re.compile(p, re.I), w) for k, p, w in _ASK]


@dataclass(frozen=True)
class Assessment:
    level: str              # "run" | "ask" | "forbid"
    rule: str = ""          # the layer ② rule, `unreadable`, or the forbid rule; "" for run
    reason: str = ""


# Programs that run the shell command they are given as one quoted argument, like `sh -c` (which
# Hermes' variants already read): `watch 'rm -rf ~'`, `script -q /dev/null -c '…'`, `tmux new '…'`.
# Their argument is read as a command too (②Main's review of S2a-2).
_LAUNCHER = re.compile(
    r"(?:^|[\n;&|(]\s*)(?:(?:npx|bunx|pnpm\s+dlx|yarn\s+dlx)\s+(?:-\S+\s+)*)?"
    r"(?:watch|script|concurrently|parallel|tmux\s+(?:new(?:-session|-window)?|split-window|send-keys|respawn-pane)"
    r"|screen)(?=\s)")
_ARG_END = frozenset({";", "&&", "||", "|", "&", "|&", ";;"})


def _launcher_args(text: str) -> tuple[str, ...]:
    """Every quoted argument of a launcher, up to the end of its command (`concurrently 'a' 'b'` runs both)."""
    out: list[str] = []
    for match in _LAUNCHER.finditer(text):
        rest = text[match.end():].split("\n", 1)[0]
        lexer = shlex.shlex(rest, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        try:
            for token in lexer:
                if token in _ARG_END:
                    break
                if any(ch.isspace() for ch in token):
                    out.append(token)          # it was quoted: a command line, not one word
        except ValueError:
            continue                           # unclosed quotes are `unreadable` already
    return tuple(out)


def _detection_texts(text: str) -> tuple[str, ...]:
    """The forms the rules are matched against: as written, normalized, and the variants with a
    newline at every real (quote-aware) command start (`shell_text`). `_POS` anchors at a newline,
    not at `;` `&&` `|` `(`, so without the variants only the first command of a chain was checked:
    `ls && git push` ran with no card."""
    inner = tuple(t for arg in _launcher_args(text) for t in _detection_texts(arg))
    return (text, shell_text.normalize(text), *shell_text.variants(text), *inner)


def _masked_texts(texts: tuple[str, ...]) -> tuple[str, ...]:
    """Quoted prose masked out for the positionless forbid rules, except under a shell carrier
    (sh -c, eval, source), whose quoted argument is code (Hermes' hardline matcher)."""
    return tuple(t if shell_text.has_shell_carrier(t) else shell_text.mask_quoted_prose(t) for t in texts)


def _matches(pattern, texts) -> bool:
    return any(pattern.search(t) for t in texts)


_HEREDOC = re.compile(r"<<-?\s*([\"']?)(\w+)\1[^\n]*\n.*?(?:\n\s*\2[^\S\n]*(?=\n|$)|\Z)", re.S)


def _quotes_close(text: str) -> bool:
    """Whether the command's own quoting closes. A heredoc's body is data, not shell (a "don't" in a
    script's prose is fine), so it is left out; a `#` comment ends its line."""
    shell = _HEREDOC.sub("<<HEREDOC\n", text)
    lexer = shlex.shlex(shell, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        for _token in lexer:
            pass
    except ValueError:
        return False
    return True


def _unparseable(text: str) -> str:
    """Why the command's text cannot be read at all, or "": then no other rule can be trusted."""
    if shell_text.too_complex(text):
        return "too complex to read before running"
    if shell_text.grep_unreadable(shell_text.mask_quoted_newlines(text)) or not _quotes_close(text):
        return "its quoting does not close, so what runs cannot be read"
    return ""


def _inline_scripts(text: str):
    """Each inline script's own code: the rest of its line (`python3 -c "…"`) and, for a heredoc, its body."""
    for match in _INLINE_SCRIPT.finditer(text):
        end = text.find("\n", match.start() + 1)
        line = text[match.start():] if end == -1 else text[match.start():end]
        body = _HEREDOC.match(text, text.find("<<", match.start())) if "<<" in line else None
        yield line + ("\n" + body.group(0) if body else "")


def _hidden_code(texts: tuple[str, ...]) -> str:
    """Why what this command runs cannot be read from its text, or "" (layer ②'s `unreadable`)."""
    if _matches(_FETCHED_CODE, texts):
        return "it runs code it downloads, decodes or builds"
    # Each command on its own line: the variant with a newline at every command start (the most lines), so a
    # script's "line" stops where its command does.
    split = max(texts, key=lambda t: t.count("\n"))
    if any(_SCRIPT_REACH.search(script) for script in _inline_scripts(split)):
        return "its script reaches out, starts programs or drives apps"
    return ""


# rm and its kin at a command start, and their operands; a target outside the working folder (the
# command's cwd), or one the text cannot pin down, asks.
_DELETE_LINE = re.compile(_ONCE_POS + _LAUNCHED + r"(rm|rmdir|unlink|trash|srm)" + _END + r"([^\n;&|)`]*)", re.I)
_FIND_DELETE = re.compile(_POS + r"find\s+([^\n;&|]*?)\s(?:-delete\b|-exec(?:dir)?\s+(?:[^\s]*/)?rm\b)", re.I)


def _outside_target(word: str) -> bool:
    word = word.strip()
    if not word:
        return False
    if word.startswith(("/", "~", "$")) or "$(" in word or "`" in word or "${" in word:
        return True
    if "{" in word and "}" in word:
        return True                     # a placeholder (`parallel 'rm {}'`): filled in from what it reads
    return ".." in word.replace("\\", "/").split("/")


# S2a-3 e (⓪Plan, the final M1 of v0.1.63): a relative operand is judged against the command's own folder,
# so a command that changes folder anywhere (cd, chdir, pushd, popd, also through builtin / command, in a
# subshell or a script; env -C / --chdir) leaves its deletes' targets unknown, and they ask. Even `cd sub`:
# the text alone cannot say where a name under CDPATH or a link leads.
_CHANGES_FOLDER = re.compile(
    r"(?:^|[\n;&|(`{'\"]|\$\()" + _H + r"*(?:(?:builtin|command)" + _H + r"+)?(?:cd|chdir|pushd|popd)" + _END
    + r"|\benv\b[^\n;&|]*\s(?:-[a-zA-Z]*C|--chdir)\b")


def _deletes_outside(texts: tuple[str, ...]) -> bool:
    moved = any(_CHANGES_FOLDER.search(text) for text in texts)
    for text in texts:
        for match in _DELETE_LINE.finditer(text):
            if re.search(r"\bxargs\b", match.group(0), re.I):
                return True                     # xargs adds what it reads to the targets: unknown
            if moved:
                return True                     # relative to a folder the command moved to: unknown
            try:
                words = shlex.split(match.group(2), comments=False, posix=True)
            except ValueError:
                return True                     # the text cannot say what it deletes
            targets = [w for w in words if not w.startswith("-") or w == "-"]
            if not targets or any(_outside_target(w) for w in targets):
                return True
        for match in _FIND_DELETE.finditer(text):
            starts = match.group(1).split()
            if moved or not starts or starts[0].startswith("-") or _outside_target(starts[0]):
                return True
    return False


_DELETE_OUTSIDE = ("delete-outside", "deletes files outside the working folder")   # in ONCE_ONLY_RULES above


def as_shell(command: str, argv=None) -> str:
    """One shell string from either form the tool accepts ({command} or legacy {command, argv})."""
    command = str(command or "").strip()
    if not command:
        return ""          # argv alone is not a command; joining would run `'' <argv>`
    if isinstance(argv, list) and argv:
        command = shlex.join([command, *[str(a) for a in argv]])
    return command


def _forbid(text: str, texts: tuple[str, ...]) -> Assessment | None:
    masked = None
    for key, pattern, why, quote_masked in _FORBID_C:
        if quote_masked:
            masked = masked or _masked_texts(texts)
        if _matches(pattern, masked if quote_masked else texts):
            return Assessment("forbid", key, why)
    return None


_PROTECTED_NAME_C = re.compile(_PROTECTED_NAME + r"|/(?:private/)?etc/")


def _script_names_protected(texts: tuple[str, ...]) -> bool:
    """An inline script whose code names a protected file: a script reaches ~/.zshrc through
    expanduser or Path.home(), which no path pattern sees."""
    split = max(texts, key=lambda t: t.count("\n"))
    return any(_PROTECTED_NAME_C.search(script) for script in _inline_scripts(split))


def _reaches_outside(texts: tuple[str, ...], reading: shell_grammar.Reading) -> bool:
    """S2a-3 b: a program that asks macOS to act for it outside the sandbox (see OUTSIDE_REACH)."""
    if _matches(_OUTSIDE_ANYWHERE, texts):
        return True
    for command in reading.commands:
        name = command[0].rsplit("/", 1)[-1]
        if name in _OUTSIDE_NAMES or name in _OUTSIDE_COMMANDS:
            return True
        if name == "security" and len(command) > 1 and re.fullmatch(_SECURITY_WRITES, command[1]):
            return True
    return False


def _layer_two(texts: tuple[str, ...]) -> list[tuple[str, str]]:
    found = [(key, why) for key, pattern, why in _ASK_C if _matches(pattern, texts)]
    if _script_names_protected(texts) and not any(k == "protected-write" for k, _ in found):
        found.append(("protected-write", describe("protected-write")))
    if _deletes_outside(texts):
        found.insert(0, _DELETE_OUTSIDE)
    seen: set[str] = set()
    return [(k, w) for k, w in found if not (k in seen or seen.add(k))]


@dataclass(frozen=True)
class _Analysis:
    verdict: Assessment
    rules: frozenset[str] = frozenset()      # every layer ② rule it matches (and `unreadable`), for ask_rules


def _analyse(text: str) -> _Analysis:
    if not text.strip():
        return _Analysis(Assessment("forbid", "empty", "no command"))
    if len(text) > MAX_COMMAND_CHARS:
        return _Analysis(Assessment("forbid", "too-long", "command is too long to review"))
    # S2a-3: read first. The reader is linear and stops at MAX_COMMANDS; past it, or past the text
    # parser's own limit, only the text as written and normalized is matched (building the detection
    # variants is quadratic in the number of commands: ②Main measured ~37 s for one command).
    reading = shell_grammar.read(text)
    heavy = reading.capped or shell_text.too_complex(text)
    texts = (text, shell_text.normalize(text)) if heavy else _detection_texts(text)
    if reading.commands:
        # Every command the reader found the shell would start, one per line, wrappers read through: the
        # rules judge the inner command too (`find . -exec rm -rf / \;`, `nohup git push`), not only the
        # text as written, where it does not stand at a command position.
        texts = (*texts, "\n".join(shlex.join(command) for command in reading.commands))
    forbidden = _forbid(text, texts)
    if forbidden is not None:
        return _Analysis(forbidden)
    unparseable = _unparseable(text)
    if unparseable:
        return _Analysis(Assessment("ask", UNREADABLE, unparseable), frozenset({UNREADABLE}))
    found = _layer_two(texts)
    if not found and _reaches_outside(texts, reading):
        found = [OUTSIDE_REACH]
    hidden = _hidden_code(texts) or (reading.why if not reading.understood else "")
    rules = frozenset(key for key, _why in found) | ({UNREADABLE} if hidden else frozenset())
    if found:
        # The named rule first: its card says what it is. A command the reader did not understand keeps
        # `unreadable` among its rules too (the card's target lists every rule), and asks this time only.
        return _Analysis(Assessment("ask", found[0][0], found[0][1]), rules)
    if hidden:
        return _Analysis(Assessment("ask", UNREADABLE, hidden), rules)
    return _Analysis(Assessment("run"))


# One analysis per command text: the tool loop, the card, the approvals and the Island all ask about
# the same command, and each used to read it again (on the event loop). Pure in the text, so caching
# changes nothing but the cost. A timed-out reading (assess_async) is stored here too, so every later
# caller gets the same answer instead of reading it again on the loop.
_CACHE_SIZE = 512
_cache: collections.OrderedDict[str, _Analysis] = collections.OrderedDict()
_cache_lock = threading.Lock()

#: How long the tool loop waits for a command to be read before it counts as not understood (S2a-3 c).
#: Reading takes about a millisecond; the caps keep the slowest well under this.
READ_TIMEOUT_S = 2.0
TIMED_OUT = Assessment("ask", UNREADABLE, "it takes too long to read before running")


def _store(text: str, analysis: _Analysis, *, replace: bool) -> _Analysis:
    with _cache_lock:
        if not replace and text in _cache:
            _cache.move_to_end(text)
            return _cache[text]
        _cache[text] = analysis
        _cache.move_to_end(text)
        while len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)
        return analysis


def _analysis(text: str) -> _Analysis:
    with _cache_lock:
        hit = _cache.get(text)
        if hit is not None:
            _cache.move_to_end(text)
            return hit
    return _store(text, _analyse(text), replace=False)


def assess(command: str) -> Assessment:
    """The layer a command is in, with its first rule (the one its card names)."""
    return _analysis(str(command or "")).verdict


async def assess_async(command: str, *, timeout_s: float = READ_TIMEOUT_S) -> Assessment:
    """`assess` off the event loop, within `timeout_s` (S2a-3 c): one that takes longer is not
    understood, and that answer is the one every later caller gets for this text."""
    text = str(command or "")
    with _cache_lock:
        hit = _cache.get(text)
    if hit is not None:
        return hit.verdict
    try:
        return (await asyncio.wait_for(asyncio.to_thread(_analysis, text), timeout_s)).verdict
    except asyncio.TimeoutError:
        return _store(text, _Analysis(TIMED_OUT, frozenset({UNREADABLE})), replace=True).verdict


def ask_rules(command: str) -> set[str]:
    """Every layer ② rule the command matches (and `unreadable`). `assess` names only the first,
    which is what the card shows; a card's target lists all of them (`rules:<rule>|<rule>`)."""
    analysis = _analysis(str(command or ""))
    return set(analysis.rules) if analysis.verdict.level == "ask" else set()


# JXA and any other OSA language than AppleScript (`osascript -l JavaScript`). It can bridge to
# Objective-C, so U11's bare run is plain AppleScript only: wrapped, its Apple Events are blocked.
_OTHER_OSA_LANGUAGE = re.compile(_CMD + r"osascript\b[^\n;&|]*\s-l\s*[\"']?(?!applescript\b)\w", re.I)


def other_osa_language(command: str) -> bool:
    """An osascript in a language other than AppleScript (JXA): it cannot reach an app from a command."""
    return _matches(_OTHER_OSA_LANGUAGE, _detection_texts(str(command or "")))


def risk_grade(command: str) -> str:
    """The LOW/MEDIUM/HIGH grade the confirmation layer speaks (run/ask/forbid)."""
    return {"run": "LOW", "ask": "MEDIUM", "forbid": "HIGH"}[assess(command).level]


# ── "don't ask again", remembered by rule (0.1.48–0.1.62) ────────────────────
# Since S2a-2 no command card offers "Always", and the stored `legacy_rule` rows are not read by
# any decision (layer ② is this-time-only; layer ③ needs no card in the sandbox). Settings still
# lists them; S6 deletes this and the old panel when it lands (v0.1.64 if S6 moves).

async def always_allowed(db) -> set[str]:
    """Rules the user said not to ask about again (0.1.61: `legacy_rule` rows in the permission
    store), for Settings' list only. Unreadable means none."""
    from server.services import permission_store
    try:
        return {r.target for r in await permission_store.list_rules(db, "legacy_rule")}
    except Exception:  # noqa: BLE001 — a standing permission is never inferred from an error
        return set()


async def forget(db, rule: str) -> None:
    from server.services import permission_store
    await permission_store.delete_rule_by(db, "legacy_rule", rule)
    await db.commit()


# Rules S2a-2 retired (in the sandbox they run with no card): stored `legacy_rule` rows still carry
# them, and Settings lists those in the words their cards used. Goes with `always_allowed` (S6).
_RETIRED = {"delete": "deletes files", "install": "installs software"}


def describe(rule: str) -> str:
    """What a rule is about, in the words its card used when it asked."""
    for key, _, why in _ASK:
        if key == rule:
            return why
    if rule == _DELETE_OUTSIDE[0]:
        return _DELETE_OUTSIDE[1]
    if rule == OUTSIDE_REACH[0]:
        return OUTSIDE_REACH[1]
    if rule in _RETIRED:
        return _RETIRED[rule]
    return rule.split(":", 1)[1] if rule.startswith("hermes:") else rule
