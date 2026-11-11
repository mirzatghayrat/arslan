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
          module cannot read (`unreadable`: unbalanced quoting, over the parser limit, `eval`,
          something downloaded or decoded piped into a shell, an inline script that reaches
          out, starts programs or drives apps, and since S2a-3 step 3 anything else with no
          named rule that shell_grammar's reader does not understand). The tool loop runs a
          command whose only rule is `unreadable` in the sandbox, offline, with no card, where it can
          (command_gate); otherwise it asks. Since S2a-3 step 5, only for a command that runs outside the
          sandbox (`outside=True`) and only where no named rule matched: a program that asks macOS to act for
          it (`outside-reach`: open, at, batch, launchctl, shortcuts, networksetup and tccutil past their
          read-only forms, security create- and unlock-). Inside, the sandbox's profile refuses those services.
  run     layer ③, everything else. The tool loop runs it in the workspace sandbox without a
          card when the sandbox can start (`command_sandbox.available()`); otherwise, or when
          the sandbox is switched off, it asks (target `unsandboxed:*`).

The rules are Arslan's own; the hard floor (layer ①) is adapted from Hermes Agent's (MIT;
NousResearch/hermes-agent), keeping what applies to macOS. Commands are read through
server/services/shell_text.py (S2b-1), Arslan's copy of Hermes' text handling: the command-start
pass, the variants with a newline at every real command start, and the quote masks. Hermes'
MIT license is in THIRD_PARTY_NOTICES.md ("Terminal command reading").

Operand-aware tuple rules may loosen the original flattened-tuple verdict only
when _fully_accounted accepts every option in that program's own table. Unknown
options, unsplittable clusters, missing values and unplaceable global options
use the original bounded flattened matcher for that command. Argument spelling
and case are preserved; only command words are normalized. Coverage gaps can
therefore cost a confirmation, but cannot remove the original protection.

Folder cancellation also checks retained prefixes in a supplied working folder. It is a guard against mistakes and
against instructions smuggled in through web pages, not a sandbox: the sandbox (S2a-1) is what
holds a layer ③ command, and a command outside it runs with the user's own permissions.
"""
from __future__ import annotations

import functools
import os
import posixpath
import re
import shlex
import stat
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
# SMART-8: a delete reaching into a Trash. Finder emptying it needs Apple Events, which both profiles deny, and
# mac_applescript refuses it itself (`hands_service`). A permanent delete from the Trash is the user's own act;
# allowed deletes go to the Trash (`delete_to_trash`), so Arslan never takes them out of it. It reads commands: a
# launcher (`/bin/rm`, `command rm`, `FOO=1 rm`, `timeout 5 rm`) is read through, and prose or a read-only `find` that
# only names the Trash is not refused. Forms this can't prove (a glob or variable naming the folder) stay on the
# delete card, which no grant answers (#686 review).
_DELETER = r"(?:rm|rmdir|unlink|srm)\b"
_FORBID.append(
    ("trash", r"(?:" + _CMD + _DELETER + r"[^\n;&|]*\.Trash(?:es)?(?:[/\"'\s)`*]|$)"
              r"|" + _CMD + r"find\b[^\n;&|]*\.Trash(?:es)?\b[^\n;&|]*\s(?:-delete\b|-exec(?:dir)?\s+(?:[^\s]*/)?"
              + _DELETER + r")"
              # a delete after changing into a Trash (`cd ~/.Trash && rm -rf *`)
              + r"|" + _CMD + r"(?:builtin" + _H + r"+)?(?:cd|chdir|pushd)\b[^\n;&|]*\.Trash(?:es)?\b.*?(?:\b"
              + _DELETER + r"|\s-delete\b))",
     "deletes from or empties the Trash; that's yours to do", False))
# The program itself, not a longer name that starts with it (osascript.sh, osascriptx); a
# redirection may follow it directly (osascript<<EOF, osascript>/dev/null).
_END = r"(?=$|[\s;&|)`'\"<>])"
# HTTP methods that change something, and HTTPie / xh sending data: a method word, or a request
# item (`key=value`, `key:=json`, `field@file`), a form, or a body on stdin.
_WRITE = r"(?:POST|PUT|PATCH|DELETE)"
# One shell word: plain characters, a backslash escape, or a quoted part (`"Cache-Control:public, max-age=3600"`).
_WORD = r"""(?:\\.|[^\s"'\\]|"[^"\n]*"|'[^'\n]*')"""


def _opts(stop: str) -> str:
    """A cloud CLI's options before its next word (`-m`, `--profile "work account"`, `--region=eu-west-1`): each an
    option and at most one value that is neither an option nor the word `stop` names, then the blanks before it
    (#693 review). Linear: an option starts with `-` and a value can't, so each word is read one way only."""
    word = _WORD + r"+(?<![;&|])"                           # `;`, `&` or `|` ending it ends the command
    return r"(?:" + _H + r"+-" + word + r"(?:" + _H + r"+(?!-|(?:" + stop + r")" + _END + r")" + word + r")?)*" + _H + r"+"
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
                   r"|\.(?:aws|gnupg|kube|azure|gsutil)(?=/|\b)|\.config/rclone(?=/|\b)"
                   r"|\.docker/config\.json|\.(?:netrc|npmrc|pypirc|git-credentials|gitconfig|rclone\.conf|s3cfg|boto)"
                   r"(?![\w.-])|Library/(?:LaunchAgents|LaunchDaemons|StartupItems|Keychains)(?=/|\b)"
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
                      r")", "sends data to a website or a cloud"),
    # Cloud storage uploads (Astra on #688/#689, via ⓪Plan, 2026-11-03), `aws s3` among them: the verb, not the
    # direction (a download asks too). Options may come before each word (`aws --profile p s3 --region r cp`).
    ("upload", _CMD + r"(?:gcloud" + _opts(r"alpha|beta|storage") + r"(?:(?:alpha|beta)" + _opts(r"storage") + r")?"
                      r"storage" + _opts(r"cp|mv|rsync") + r"(?:cp|mv|rsync)"
                      r"|gsutil" + _opts(r"cp|copy|mv|move|ren|rename|rsync") + r"(?:cp|copy|mv|move|ren|rename|rsync)"
                      r"|aws" + _opts(r"s3|s3api") + r"(?:s3" + _opts(r"cp|mv|sync|rm") + r"(?:cp|mv|sync|rm)"
                      r"|s3api" + _opts(r"put-object|upload-part") + r"(?:put-object|upload-part))"
                      r"|gh" + _opts(r"release") + r"release" + _opts(r"upload") + r"upload"
                      r"|azcopy" + _opts(r"copy|cp|c|sync|sc|s") + r"(?:copy|cp|c|sync|sc|s)"
                      r"|az" + _opts(r"storage") + r"storage" + _opts(r"blob|file|fs") + r"(?:blob|file|fs" + _opts(r"file")
                      + r"file)" + _opts(r"upload|upload-batch|sync") + r"(?:upload(?:-batch)?|sync)"
                      r"|rclone" + _opts(r"copy|copyto|move|moveto|sync|bisync|rcat|copyurl")
                      + r"(?:copy|copyto|move|moveto|sync|bisync|rcat|copyurl)"
                      r"|s3cmd" + _opts(r"put|sync|cp|mv") + r"(?:put|sync|cp|mv))(?:" + _END + r"|(?=\$))",
     "sends data to a website or a cloud"),
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
    # bash opens the connection itself, with no program named (zsh has no such path).
    ("remote-shell", r"[<>]&?\s*/dev/(?:tcp|udp)/", "connects to another machine"),
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
#: Rules a card answers for this one time only: nothing to remember, and no stored answer stands.
ONCE_ONLY_RULES = frozenset({key for key, _, _ in _ASK}) | {"delete-outside", "outside-reach", UNREADABLE}

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
# shlex's own punctuation, and a newline: outside quotes it ends the launcher's command, inside them it is part of
# the argument, and so a line of the command it runs.
_LAUNCHER_PUNCTUATION = "();<>|&\n"


def _launcher_args(text: str) -> tuple[str, ...]:
    """Every quoted argument of a launcher, up to the end of its command (`concurrently 'a' 'b'` runs both). An
    argument may span lines (`watch 'ls<newline>x'`): read only to the first line, it had no closing quote and
    wasn't read at all."""
    out: list[str] = []
    for match in _LAUNCHER.finditer(text):
        lexer = shlex.shlex(text[match.end():], posix=True, punctuation_chars=_LAUNCHER_PUNCTUATION)
        lexer.whitespace, lexer.whitespace_split = " \t\r", True
        try:
            for token in lexer:
                if token in _ARG_END or ("\n" in token and not token.strip(_LAUNCHER_PUNCTUATION)):
                    break
                if any(ch.isspace() for ch in token):
                    out.append(token)          # it was quoted: a command line, not one word
        except ValueError:
            continue                           # unclosed quotes are `unreadable` already
    return tuple(out)


@functools.lru_cache(maxsize=64)        # assess, the limit check and ask_rules all ask
def _forms(text: str) -> tuple[str, ...]:
    """The forms the rules are matched against: as written, normalized, and the variants with a
    newline at every real (quote-aware) command start (`shell_text`). `_POS` anchors at a newline,
    not at `;` `&&` `|` `(`, so without the variants only the first command of a chain was checked:
    `ls && git push` ran with no card. Also the arguments of every launcher in any of them (one in a `-c` payload:
    `sh -c 'watch "…"'`), read the same way. Every form is read by every rule, and none is chosen over another: the
    verdict is the most cautious one any form gives, so a form added here can only add caution."""
    if shell_text.too_complex(text):
        return (text,)
    found = (text, shell_text.normalize(text), *shell_text.variants(text))
    forms = list(found)
    for arg in dict.fromkeys(arg for form in found for arg in _launcher_args(form)):
        # Shorter each time, so the reading ends: a marked form can be longer than the text, and so its argument.
        forms += _forms(arg) if len(arg) < len(text) else (arg,)
    return tuple(dict.fromkeys(forms))


def _detection_texts(text: str) -> tuple[str, ...]:
    """`_forms`, or when any form of it (the `-c` argument it hides, say) is past the parser limit, the forms still read
    cheaply: every one under the limits as it is, and every one past a limit as what the forbid rules read of it in
    linear passes (`shell_text.over_limit_forms`), the same squeezed passes the ruling's blank-run exception reads. So a
    form past a limit is still read — main reads it with every rule — and no form the parser would scan is read raw.
    `_unparseable` then says the command can't be read, and a forbid holds past the limit, so asking can't let one run.
    Two forms are left out of the readable set, both read squeezed instead: the text as written when its own blank run
    is past the limit (every rule's command position reads such a run in time far beyond its length), and any other form
    past a limit, read through its own linear passes rather than raw."""
    forms = _forms(text)
    if not _over_limit(forms):
        return forms
    out: list[str] = [] if shell_text.blank_run_over_limit(text) else [text]     # the text as written (the fork-bomb)
    for form in forms:
        out += shell_text.over_limit_forms(form) if shell_text.too_complex(form) else [form]
    return tuple(dict.fromkeys(out))


@functools.lru_cache(maxsize=64)        # assess, ask_rules and the card all ask, several times a call
def _parsed(text: str) -> shell_grammar.PrefixReading:
    """The reader's one pass over `text` (LOOP1 d2), the whole text as given: whether it understands the text and
    why not, and the commands the named rules read. Every reader here reads this one pass, and nothing reads the text
    through the grammar again; the card's steps read it too (`reading`, d2b).
    `shell_grammar.read` refuses exactly where this pass does: the folders it follows as well never change what is
    read (its docstring), so `refused` is its "not understood" with the same why, and an understood command's
    commands are its own. One it does not understand keeps the path it had: its named rules read the commands
    before the refusal (additive only, never a grant), beside the rules on the raw text."""
    return shell_grammar.read_prefix(text)


def reading(text: str) -> shell_grammar.PrefixReading:
    """The one pass, for card_purpose (LOOP1 d2b): an understood command's card reads its steps from the commands and
    redirections the rules read, so the title never reads the text another way."""
    return _parsed(text)


def _command_words(text: str) -> tuple[tuple[str, ...], ...]:
    """Only additive checks may use a parsed prefix; it never grants permission."""
    return _parsed(text).commands


def asks_once(words: tuple[str, ...], writes: tuple[str, ...] = (), *, reach: bool = False) -> int:
    """How strongly one command of an understood text, on its own words and the files its redirections write, is what
    its card asks about: 2 when it matches a rule the card answers this time only (a named rule in ONCE_ONLY_RULES,
    `delete-outside`, a write to a protected file); 1 when `reach` (the text's policy asks `outside-reach` itself,
    under the `outside` the gate used) and it is a step that reaches outside; else 0. card_purpose leads the title
    with the highest, so the title never hides what asked (LOOP1 d2b, ③Hands' condition 1; #828 review: a step that
    only reaches outside never takes the lead from a named rule's step, and only leads where outside-reach is asked).
    For the title only: no verdict reads it."""
    if (words and _named_rules(words) & ONCE_ONLY_RULES) or any(_PROTECTED_PATH_C.match(w) for w in writes):
        return 2
    return int(bool(reach and words and _reaches_outside((words,))))


def _operands(args: tuple[str, ...], values: frozenset[str] = frozenset()) -> tuple[str, ...]:
    """Operands after options, preserving each word, including empty words and `--`."""
    out = []
    options = True
    skip = False
    for word in args:
        if skip:
            skip = False
        elif options and word == "--":
            options = False
        elif options and word.startswith("-") and word != "-":
            skip = word in values
        else:
            out.append(word)
    return tuple(out)


def _verb(args: tuple[str, ...], values: frozenset[str] = frozenset()) -> tuple[str, ...]:
    """Skip leading options with separate, attached or clustered values."""
    i = 0
    while i < len(args) and args[i].startswith("-") and args[i] != "-":
        word = args[i]
        i += 1
        if word == "--":
            return args[i:]
        if word in values:
            i += 1
        elif not word.startswith("--"):
            for offset, letter in enumerate(word[1:], 2):
                if "-" + letter in values:
                    i += offset == len(word)
                    break
    return args[i:]


_GIT_VALUES = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env"})
# Option arities belong to a program: curl -O, wget -H and gsutil -m are flags.
_OPTION_VALUES = {
    "curl": frozenset({"-o", "-H", "-A", "-u", "-e", "-X", "-d", "-F", "-T",
                       "--output", "--header", "--user-agent", "--user", "--referer", "--url",
                       "--request", "--data", "--data-ascii", "--data-binary", "--data-raw",
                       "--data-urlencode", "--form", "--form-string", "--upload-file", "--json"}),
    "wget": frozenset({"-o", "-O", "-U", "-e", "--output-file", "--output-document",
                       "--user-agent", "--execute", "--header", "--user", "--password",
                       "--referer", "--method", "--post-data", "--post-file", "--body-data", "--body-file"}),
    "gsutil": frozenset({"-o", "-h", "-u", "-i"}),
    "gcloud": frozenset({"--project", "--configuration", "--account", "--billing-project",
                         "--impersonate-service-account", "--flags-file", "--format", "--verbosity"}),
    "aws": frozenset({"--profile", "--region", "--endpoint-url", "--output", "--query",
                      "--ca-bundle", "--cli-read-timeout", "--cli-connect-timeout", "--color"}),
    "az": frozenset({"--subscription", "--output", "-o", "--query"}),
    "azcopy": frozenset({"--output-type", "--output-level", "--log-level"}),
    "rclone": frozenset({"--config", "--log-file", "--log-level", "--transfers", "--checkers", "--retries", "--bwlimit"}),
    "s3cmd": frozenset({"-c", "--config", "--access_key", "--secret_key", "--host", "--host-bucket", "--encoding"}),
    "gh": frozenset({"-R", "--repo", "--hostname", "-X", "--method", "-f", "-F", "--field",
                     "--raw-field", "--input", "-H", "--header", "--cache", "-q", "--jq", "-t", "--template"}),
    "http": frozenset({"--pretty", "--style", "--print", "-p", "--output", "-o", "--raw",
                       "--auth", "-a", "--session", "--session-read-only", "--proxy", "--timeout"}),
    "https": frozenset({"--pretty", "--style", "--print", "-p", "--output", "-o", "--raw",
                        "--auth", "-a", "--session", "--session-read-only", "--proxy", "--timeout"}),
    "xh": frozenset({"--pretty", "--style", "--print", "-p", "--output", "-o", "--raw",
                     "--auth", "-a", "--session", "--session-read-only", "--proxy", "--timeout"}),
    "xhs": frozenset({"--pretty", "--style", "--print", "-p", "--output", "-o", "--raw",
                      "--auth", "-a", "--session", "--session-read-only", "--proxy", "--timeout"}),
}
_DELETE_PROGRAMS = frozenset({"rm", "rmdir", "unlink", "srm", "trash"})


# Tables are deliberately finite and program-specific. An omitted option uses
# the legacy floor, including on programs whose supported table is empty.
_OPTION_VALUES.update({
    "git": _GIT_VALUES | {"-m", "--message", "--author", "--format"},
    "security": frozenset({"-p", "-a", "-s", "-c", "-C", "-D", "-j", "-l", "-r", "-P", "-t"}),
    "xurl": frozenset({"--auth", "--username"}),
    "npm": frozenset({"--registry", "--prefix"}),
    "pnpm": frozenset({"--registry", "--dir", "-C"}),
    "yarn": frozenset({"--cwd", "--registry"}),
    "cargo": frozenset({"--manifest-path", "--target-dir", "--color"}),
    "twine": frozenset({"--repository", "-r", "--config-file"}),
    "docker": frozenset({"--config", "--context", "-c", "--host", "-H"}),
    "terraform": frozenset({"-chdir"}),
    "kubectl": frozenset({"--context", "--namespace", "-n", "--kubeconfig"}),
    "vercel": frozenset({"--cwd", "--token", "-t", "--scope"}),
    "osascript": frozenset({"-e", "-l", "-s"}),
    "open": frozenset({"-a", "-b"}),
    "himalaya": frozenset({"--account", "-a", "--config", "-c"}),
    "ssh": frozenset({"-p", "-i", "-o", "-F", "-J", "-l"}),
    "scp": frozenset({"-P", "-i", "-o", "-F", "-J"}),
    "sftp": frozenset({"-P", "-i", "-o", "-F", "-b"}),
    "autossh": frozenset({"-M", "-p", "-i", "-o"}),
    "rsync": frozenset({"-e", "--rsh", "--exclude", "--include"}),
    "kill": frozenset({"-s"}), "pkill": frozenset({"-u", "-U", "-P"}),
    "killall": frozenset({"-u", "-t"}),
    "screencapture": frozenset({"-T", "-t", "-R", "-w"}),
    "find": frozenset({"-name", "-path", "-type"}),
})
_OPTION_FLAGS = {
    "curl": "-s -S -O -I -L -v -f --head --silent --show-error --location",
    "wget": "-H -q -v -c --quiet --verbose --spider",
    "gsutil": "-m -q -D -v", "gcloud": "-q --quiet --no-user-output-enabled",
    "aws": "--debug --no-cli-pager --no-sign-request --no-verify-ssl",
    "az": "--verbose --debug --only-show-errors", "azcopy": "--help --version",
    "rclone": "-q -v --dry-run", "s3cmd": "-v -q -d --verbose --dry-run",
    "gh": "--help --version --paginate --silent --include -i",
    "http": "-v -q -f --form --multipart --verbose --quiet --check-status --ignore-stdin",
    "https": "-v -q -f --form --multipart --verbose --quiet --check-status --ignore-stdin",
    "xh": "-v -q -f --form --multipart --verbose --quiet --check-status --ignore-stdin",
    "xhs": "-v -q -f --form --multipart --verbose --quiet --check-status --ignore-stdin",
    "security": "-v -q -i -h --help -w -g", "xurl": "-v --verbose --help",
    "git": "--no-pager --bare --global --system --list -l --get --get-all --show-origin",
    "rm": "-f -r -R -i -I -v -d -P -W --force --recursive",
    "rmdir": "-p -v", "unlink": "", "srm": "-f -r -R -v -s -m -z", "trash": "-v",
    "dd": "", "diskutil": "", "newfs_apfs": "-v", "newfs_hfs": "-v -J",
    "kill": "-1 -9 -KILL -SIGKILL", "shutdown": "-h -r -k", "reboot": "-q", "halt": "-q",
    "poweroff": "", "sudo": "-n -S", "osascript": "-i", "shortcuts": "", "imsg": "",
    "mail": "", "mailx": "", "mutt": "", "sendmail": "-t -i", "msmtp": "-t -i",
    "himalaya": "--debug --trace", "ssh-copy-id": "", "sshpass": "", "mosh": "",
    "ftp": "", "telnet": "", "socat": "", "ssh": "-v -q -N -T", "scp": "-r -q -v -p",
    "sftp": "-q -v", "autossh": "-f -N", "nc": "-z -v -n -u", "ncat": "-z -v -n -u",
    "netcat": "-z -v -n -u", "rsync": "-a -v -z -r --dry-run",
    "npm": "--dry-run --silent", "pnpm": "--dry-run --silent", "yarn": "--silent",
    "cargo": "-q -v --quiet --verbose --dry-run", "twine": "--verbose --non-interactive",
    "docker": "-D --debug", "terraform": "-help -version", "kubectl": "--help",
    "vercel": "--prod --yes -y --debug -d", "killall": "-9 -v -q", "pkill": "-9 -f -x",
    "launchctl": "", "defaults": "", "crontab": "-l -r", "tccutil": "",
    "networksetup": "-setairportpower", "systemsetup": "-settimezone",
    "pmset": "-g -a -b -c", "spctl": "--status --master-disable --master-enable",
    "scutil": "--set --get", "open": "-n -g -j -R -W -F -e -t",
    "screencapture": "-x -i -c -C", "pbpaste": "",
    "tee": "-a -i", "cp": "-R -r -f -i -p -v", "mv": "-f -i -n -v",
    "ln": "-s -f -n", "install": "", "ditto": "", "truncate": "", "touch": "",
    "chmod": "-R", "chown": "-R", "chflags": "-R", "xattr": "-w -d -r",
    "sed": "", "perl": "", "ruby": "", "find": "-delete -exec -execdir -print",
}
_OPTION_FLAGS = {program: frozenset(flags.split()) for program, flags in _OPTION_FLAGS.items()}
# Only these programs have leading options that this reader can place before a
# subcommand. Other verb programs must fall back if a global option is present.
_GLOBAL_OPTIONS = {
    program: _OPTION_VALUES.get(program, frozenset()) | _OPTION_FLAGS[program]
    for program in ("gsutil", "gcloud", "aws", "az", "azcopy", "rclone", "s3cmd", "gh",
                    "git", "security", "xurl", "npm", "pnpm", "yarn", "cargo", "twine",
                    "docker", "terraform", "kubectl", "vercel", "himalaya")
}
# Security's subcommand options are not global flags; git's commit options are
# likewise not meaningful ahead of its command word.
_GLOBAL_OPTIONS["security"] = frozenset({"-p", "-q", "-v", "-i", "-h", "--help"})
_GLOBAL_OPTIONS["git"] = _GIT_VALUES | {"--no-pager", "--bare"}
# Global flags can select an implicit operation as well as modify a command.
# Keep that meaning separate from the words left after global-option stripping.
_OPERATION_FLAGS = {program: frozenset({"--prod"}) if program == "vercel" else frozenset()
                    for program in _GLOBAL_OPTIONS}
_VERB_PROGRAMS = frozenset(_GLOBAL_OPTIONS) | {
    "diskutil", "shortcuts", "imsg", "launchctl", "defaults", "tccutil",
}


def _fully_accounted(program: str, args: tuple[str, ...]) -> bool:
    """A single admission gate for every tuple rule; never guess an arity."""
    values = _OPTION_VALUES.get(program, frozenset())
    flags = _OPTION_FLAGS.get(program, frozenset())
    globals_ = _GLOBAL_OPTIONS.get(program, frozenset())
    before_command = program in _VERB_PROGRAMS
    i = 0
    while i < len(args):
        word = args[i]
        i += 1
        if word == "--":
            return True
        if not word.startswith("-") or word == "-":
            before_command = False
            continue
        option, equals, _ = word.partition("=")
        if option in values or word in flags or word.startswith("--"):
            if option not in values and (word not in flags or equals):
                return False
            options = (option,)
            consumes = option in values and not equals
        else:
            options = []
            consumes = False
            for offset, letter in enumerate(word[1:], 2):
                option = "-" + letter
                if option not in values and option not in flags:
                    return False
                options.append(option)
                if option in values:
                    consumes = offset == len(word)
                    break
        if before_command and any(option not in globals_ for option in options):
            return False
        if consumes:
            if i == len(args):
                return False
            i += 1
    return True


def _legacy_named_rules(words: tuple[str, ...]) -> set[str]:
    """The original bounded flattened-tuple matcher, used only on coverage gaps."""
    command = " ".join(words)
    if shell_text.too_complex(command):
        command = shell_text.over_limit_forms(command)[0]
    found = {key for key, pattern, _, masked in _FORBID_C
             if not masked and key != "arslan-keys" and pattern.match(command)}
    found.update(key for key, pattern, _ in _ASK_C if pattern.match(command))
    if ((_DELETE_LINE.match(command) or _FIND_DELETE.match(command))
            and _deletes_outside((command,))):
        found.add("delete-outside")
    return found


def _options(args: tuple[str, ...], values: frozenset[str]):
    """Yield options with their values, or an empty option for a positional word.

    Long assignments and attached short values never consume the next word.
    A separate value is data even when it resembles an operation or option.
    """
    i = 0
    ended = False
    while i < len(args):
        word = args[i]
        i += 1
        if not ended and word == "--":
            ended = True
        elif ended or not word.startswith("-") or word == "-":
            yield "", word
        elif word.startswith("--"):
            option, equals, value = word.partition("=")
            if not equals and option in values and i < len(args):
                value, i = args[i], i + 1
            yield option, value
        else:
            for offset, letter in enumerate(word[1:], 2):
                option = "-" + letter
                value = ""
                if option in values:
                    value = word[offset:]
                    if not value and i < len(args):
                        value, i = args[i], i + 1
                    yield option, value
                    break
                yield option, value


def _security_verb(args: tuple[str, ...]) -> tuple[str, ...]:
    # -p consumes a prompt; -q/-v/-i are flags. Help never selects an operation.
    i = 0
    while i < len(args) and args[i].startswith("-"):
        word = args[i]
        if word == "--":
            return args[i + 1:]
        if word == "--help":
            return ()
        i += 1
        if not word.startswith("--"):
            for offset, letter in enumerate(word[1:], 2):
                if letter == "h":
                    return ()
                if letter == "p":
                    i += offset == len(word)
                    break
    return args[i:]


def _dispatch_args(program: str, args: tuple[str, ...]) -> tuple[tuple[str, ...], frozenset[str]]:
    values = _OPTION_VALUES.get(program, frozenset())
    operations = frozenset(option for option, _ in _options(args, values)
                           if option in _OPERATION_FLAGS[program])
    return _verb(args, values), operations


def _named_rules(words: tuple[str, ...]) -> set[str]:
    """Named operations on parsed argv, never on a flattened or reparsed command.

    Each program decides which words are verbs, flags, option values or paths.
    The old text rules remain an independent conservative floor.
    """
    program, args = words[0].lower(), words[1:]
    if not _fully_accounted(program, args):
        return _legacy_named_rules(words)
    operations = frozenset()
    if program in _GLOBAL_OPTIONS and program not in {"security", "git"}:
        args, operations = _dispatch_args(program, args)
    lower = tuple(w.lower() for w in args)
    first = lower[0] if lower else ""
    found: set[str] = set()

    def add(rule: str, matches: bool) -> None:
        if matches:
            found.add(rule)

    if program == "sudo":
        found.add("sudo")
    if program == "security":
        operation = _security_verb(args)
        subcommand = operation[0].lower() if operation else ""
        add("keychain-secrets", subcommand in {"dump-keychain", "export"} or
            subcommand in {"find-generic-password", "find-internet-password"} and
            any(w in {"-w", "-g"} for w in _security_flags(operation[1:])))
        add("keychain-write", bool(re.fullmatch(r"(?:add-|delete-|set-)[\w-]+|import", subcommand)))
    if program in _DELETE_PROGRAMS:
        targets = _operands(args)
        add("delete-outside", not targets or any(_outside_target(w) for w in targets))
        add("trash", any(re.search(r"(?:^|/)\.Trash(?:es)?(?:/|$)", w, re.I) for w in targets))
        if program == "rm":
            add("wipe-root", any(re.fullmatch(r"/(?:(?:\.\.?)?/)*(?:\.\.?)?\**", w) for w in targets))
            add("wipe-home", any(re.fullmatch(r"(?:~|\$\{?HOME\}?)(?:/?|/\*)?", w, re.I) for w in targets))
            add("macos-roots", any(re.fullmatch(_ROOTS, w, re.I) for w in targets))
    if program == "find":
        actions = {"-delete", "-exec", "-execdir"}.intersection(args)
        deleting = "-delete" in actions or any(
            args[i] in {"-exec", "-execdir"} and args[i + 1].lower() in _DELETE_PROGRAMS
            for i in range(len(args) - 1))
        starts = args[:next((i for i, w in enumerate(args) if w.startswith("-") or w in {"!", "("}), len(args))]
        add("delete-outside", deleting and (not starts or any(_outside_target(w) for w in starts)))
        add("trash", deleting and any(re.search(r"(?:^|/)\.Trash(?:es)?(?:/|$)", w, re.I) for w in starts))
    add("raw-disk", program == "dd" and any(re.match(r"of=/dev/r?disk\d", w, re.I) for w in args)
        or program == "diskutil" and bool(re.fullmatch(r"erase\w*|zeroDisk|secureErase|randomDisk|partitionDisk|reformat", first, re.I))
        or bool(re.fullmatch(r"newfs_\w+", program)))
    if program == "kill":
        add("kill-all", "-1" in args)
        add("force-kill", any(w in {"-9", "-kill", "-sigkill"} for w in lower))
    add("shutdown", program in {"shutdown", "reboot", "halt", "poweroff"})
    add("apple-events", program == "osascript")
    add("shortcuts", program == "shortcuts" and first == "run")
    add("send-mail", program in {"mail", "mailx", "sendmail", "msmtp", "mutt"}
        or program == "himalaya" and first in {"send", "write", "reply", "forward"})
    add("send-message", program == "imsg" and first == "send"
        or program == "xurl" and first in {"post", "tweet", "/2/tweets"})
    add("upload", _uploads(program, args))
    add("remote-shell", program in {"ssh", "ssh-copy-id", "sshpass", "autossh", "mosh", "scp", "sftp", "ftp", "telnet", "socat"}
        or program in {"nc", "ncat", "netcat"} and not any(w.startswith("-") and "z" in w for w in args)
        or program == "rsync" and any(":" in w for w in _operands(args)))
    if program == "git":
        verb = _verb(args, _GIT_VALUES)
        add("git-push", bool(verb) and verb[0].lower() == "push")
        add("protected-write", bool(verb) and verb[0].lower() == "config"
            and bool({"--global", "--system"}.intersection(verb[1:]))
            and not any(w in {"-l", "--list"} or w.startswith(("--get", "--show-")) for w in verb[1:]))
    add("publish", program in {"npm", "pnpm", "yarn", "cargo"} and first == "publish"
        or program == "twine" and first == "upload"
        or program == "gh" and (len(lower) >= 2 and first in {"pr", "issue", "release", "repo", "gist"}
                                and lower[1] in {"create", "delete", "merge", "close", "edit", "comment"}
                                or first == "api" and _api_writes(args[1:]))
        or program == "docker" and (first == "push" or lower[:2] == ("image", "push"))
        or program == "terraform" and first in {"apply", "destroy"}
        or program == "kubectl" and first in {"apply", "create", "delete", "replace", "patch", "scale", "rollout"}
        or program == "vercel" and (not args or first in {"deploy", "--prod"} or "--prod" in operations))
    add("force-kill", program in {"killall", "pkill"})
    add("login-items", program == "launchctl" and first in {"load", "bootstrap", "enable", "submit"}
        or program == "defaults" and first == "write" or program == "crontab" and first != "-l")
    add("system-settings", program == "tccutil" and first == "reset"
        or program in {"networksetup", "systemsetup"} and bool(re.fullmatch(r"-set\w*", first))
        or program == "pmset" and first != "-g" or program == "spctl" or program == "scutil" and first == "--set")
    if program == "open":
        add("open-app", any(re.fullmatch(_SCRIPT_APPS, args[i + 1], re.I)
                            for i, w in enumerate(args[:-1]) if re.fullmatch(r"-[a-zA-Z]*[ab]", w))
            or any(re.match(r"[a-z][\w+.-]*:", w, re.I) or
                   re.search(r"\.(?:app|command|tool|sh|terminal|workflow|scpt|applescript|shortcut)$", w, re.I)
                   for w in _operands(args, frozenset({"-a", "-b"}))))
    add("screen-clipboard", program in {"screencapture", "pbpaste"})
    if program in {"tee", "cp", "mv", "ln", "install", "ditto", "rsync", "truncate", "touch",
                   "chmod", "chown", "chflags", "xattr", "dd", "sed", "perl", "ruby"}:
        add("protected-write", any(re.match(_PROTECTED_PATH, w.split("=", 1)[-1], re.I) for w in args))
    return found


def _security_flags(args: tuple[str, ...]) -> tuple[str, ...]:
    # These options consume a value, even when that value looks like another option.
    flags = []
    skip = False
    for word in args:
        if skip:
            skip = False
        elif word == "--":
            break
        elif word.startswith("-"):
            flags.append(word)
            skip = word in {"-a", "-s", "-c", "-C", "-D", "-j", "-l", "-r", "-p", "-P", "-t"}
    return tuple(flags)


def _api_writes(args: tuple[str, ...]) -> bool:
    return any(option in {"-f", "-F", "--field", "--raw-field", "--input"} or
               option in {"-X", "--method"} and bool(value) and value.upper() != "GET"
               for option, value in _options(args, _OPTION_VALUES["gh"]))


def _uploads(program: str, args: tuple[str, ...]) -> bool:
    if program in {"curl", "wget"}:
        methods = {"-X", "--request"} if program == "curl" else {"--method"}
        for option, value in _options(args, _OPTION_VALUES[program]):
            if program == "curl" and (re.match(r"--(?:data|form|upload-file|json)(?:-|$)", option)
                                       or option in {"-d", "-F", "-T"}):
                return True
            if program == "wget" and option in {"--post-data", "--post-file", "--body-data", "--body-file"}:
                return True
            if option in methods and value.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
                return True
        return False
    if program in {"http", "https", "xh", "xhs"}:
        options = tuple(_options(args, _OPTION_VALUES[program]))
        operands = tuple(value for option, value in options if not option)
        return bool(operands and operands[0].upper() in {"POST", "PUT", "PATCH", "DELETE"}) or any(
            option in {"--form", "--multipart", "--raw", "-f"} for option, _ in options) or any(
            re.match(r"[A-Za-z_][\w.\-\[\]]*(?::=|=|@)(?!=)", w) for w in operands[1:])
    values = _OPTION_VALUES.get(program, frozenset())
    verb = _verb(args, values)
    if program == "gcloud" and verb and verb[0].lower() in {"alpha", "beta"}:
        verb = _verb(verb[1:], values)
    paths = {"gcloud": {"storage": {"cp", "mv", "rsync"}},
             "aws": {"s3": {"cp", "mv", "sync", "rm"}, "s3api": {"put-object", "upload-part"}},
             "gh": {"release": {"upload"}}}
    if program in paths and verb:
        rest = _verb(verb[1:], values)
        return bool(rest and rest[0].lower() in paths[program].get(verb[0].lower(), ()))
    if program == "az" and verb and verb[0].lower() == "storage":
        rest = _verb(verb[1:], values)
        if rest and rest[0].lower() in {"blob", "file", "fs"}:
            tail = _verb(rest[1:], values)
            if rest[0].lower() == "fs" and tail and tail[0].lower() == "file":
                tail = _verb(tail[1:], values)
            return bool(tail and tail[0].lower() in {"upload", "upload-batch", "sync"})
    verbs = {"gsutil": {"cp", "copy", "mv", "move", "ren", "rename", "rsync"},
             "azcopy": {"copy", "cp", "c", "sync", "sc", "s"},
             "rclone": {"copy", "copyto", "move", "moveto", "sync", "bisync", "rcat", "copyurl"},
             "s3cmd": {"put", "sync", "cp", "mv"}}
    return bool(verb and verb[0].lower() in verbs.get(program, ()))


def _over_limit(forms: tuple[str, ...]) -> bool:
    return any(shell_text.too_complex(form) for form in forms)


def _masked_texts(texts: tuple[str, ...]) -> tuple[str, ...]:
    """Quoted prose masked out for the positionless forbid rules, except under a shell carrier
    (sh -c, eval, source), whose quoted argument is code (Hermes' hardline matcher). A text with no quote has nothing
    to mask."""
    return tuple(t if not ("'" in t or '"' in t) or shell_text.has_shell_carrier(t) else shell_text.mask_quoted_prose(t)
                 for t in texts)


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
    if _over_limit(_forms(text)):
        return "too complex to read before running"
    if shell_text.grep_unreadable(shell_text.mask_quoted_newlines(text)) or not _quotes_close(text):
        return "its quoting does not close, so what runs cannot be read"
    return ""


def _inline_scripts(text: str):
    """Each inline script's own code: the rest of its line (`python3 -c "…"`) and, for a heredoc, its body."""
    for match in _INLINE_SCRIPT.finditer(text):
        # its line starts at the program, past the blank lines `_POS` reads through: from the match start, a blank line
        # before the program (`ls<newline><newline>python3 -c …`) was the script's whole line
        end = text.find("\n", match.start() + len(match.group()) - len(match.group().lstrip()))
        line = text[match.start():] if end == -1 else text[match.start():end]
        body = _HEREDOC.match(text, text.find("<<", match.start())) if "<<" in line else None
        yield line + ("\n" + body.group(0) if body else "")


def _scripts(texts: tuple[str, ...]):
    """Every inline script in every form. A form with a newline at each command start ends a script's line where its
    command does; a form with fewer lines reads more of it; a `-c` payload read with its own newlines can have more
    lines than the whole command but holds only part of it. Any of them can be the one that shows what the script
    reaches, so none is chosen over the others: the most cautious reading of them all is the verdict."""
    return (script for form in texts for script in _inline_scripts(form))


def _hidden_code(texts: tuple[str, ...]) -> str:
    """Why what this command runs cannot be read from its text, or "" (layer ②'s `unreadable`)."""
    if _matches(_FETCHED_CODE, texts):
        return "it runs code it downloads, decodes or builds"
    if any(_SCRIPT_REACH.search(script) for script in _scripts(texts)):
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


def _deletes_outside(texts: tuple[str, ...]) -> bool:
    for text in texts:
        for match in _DELETE_LINE.finditer(text):
            if re.search(r"\bxargs\b", match.group(0), re.I):
                return True                     # xargs adds what it reads to the targets: unknown
            try:
                words = shlex.split(match.group(2), comments=False, posix=True)
            except ValueError:
                return True                     # the text cannot say what it deletes
            targets = [w for w in words if not w.startswith("-") or w == "-"]
            if not targets or any(_outside_target(w) for w in targets):
                return True
        for match in _FIND_DELETE.finditer(text):
            starts = match.group(1).split()
            if not starts or starts[0].startswith("-") or _outside_target(starts[0]):
                return True
    return False


_DELETE_OUTSIDE = ("delete-outside", "deletes files outside the working folder")   # in ONCE_ONLY_RULES above
# S2a-3 step 5: outside the sandbox, a program that hands work to a macOS service (LaunchServices, atrun, launchd,
# the Shortcuts, network configuration and privacy daemons, securityd) acts past the command. Asked only there, only
# where no named rule matched, and read from the reader's commands. In ONCE_ONLY_RULES above.
OUTSIDE_REACH = ("outside-reach", "asks macOS to act for it outside the sandbox")
_REACH_PROGRAMS = frozenset({"open", "at", "batch", "launchctl", "shortcuts", "networksetup", "tccutil"})
# A small allow set of the forms that only read, which run outside too: at's -l listing, launchctl's list and print
# verbs, shortcuts list, networksetup's -get/-list/-print/-show/-is queries, and help (a bare name prints usage, except
# at and batch, which read a job from stdin). crontab needs no entry: every form but -l is login-items already.
_REACH_READ_ONLY = {
    "at": frozenset({"-l"}),
    "launchctl": frozenset({"", "list", "print", "print-cache", "print-disabled", "blame", "error", "help", "version",
                            "getenv", "managerpid", "manageruid", "managername"}),
    "shortcuts": frozenset({"", "list", "help", "-h", "--help"}),
    "tccutil": frozenset({"", "-h", "--help", "--version"}),
}
# #798 review: a help or version word reads only when it is the whole command; with more after it, a verb there may
# still act. networksetup takes one query, so every option word on it must be one. The other read-only verbs (at -l,
# launchctl list/print…, shortcuts list) are judged on the first word only: their later words are labels, folders and
# job numbers, and no table here says which of those a real program would also act on.
_REACH_HELP = frozenset({"help", "version", "-h", "--help", "-help", "--version", "-version"})
_NETWORKSETUP_READS = re.compile(r"-(?:get|list|print|show|is)\w*|-help|-version")


def _reaches_outside(commands: tuple[tuple[str, ...], ...]) -> bool:
    for words in commands:
        if not words:
            continue
        program, args = words[0].rsplit("/", 1)[-1].lower(), words[1:]
        verb = args[0].lower() if args else ""
        if program == "security":
            operation = _security_verb(args)
            if operation and operation[0].lower().startswith(("create-", "unlock-")):
                return True
        elif program not in _REACH_PROGRAMS:
            continue
        elif verb in _REACH_HELP and len(args) > 1:
            return True
        elif program == "networksetup":
            options = [word.lower() for word in args if word.startswith("-")]     # a bare name prints its usage
            if args and (not args[0].startswith("-") or not all(_NETWORKSETUP_READS.fullmatch(o) for o in options)):
                return True
        elif verb not in _REACH_READ_ONLY.get(program, frozenset()):
            return True
    return False


# S2a-3 step 4: the path rules again, for a command after a change of folder, with each relative path joined to every
# folder shell_grammar says it may run in. Text the reader doesn't understand is judged as before (step 3 wires that).
_MOVED_DELETERS = frozenset({"rm", "rmdir", "unlink", "trash", "srm"})
_MOVED_WRITERS = frozenset({"tee", "cp", "mv", "ln", "install", "ditto", "rsync", "truncate", "touch", "chmod", "chown",
                            "chflags", "xattr", "dd", "sed", "perl", "ruby"})
_MOVED_FINDERS = frozenset({"find"})
_PROTECTED_PATH_C = re.compile(_PROTECTED_PATH, re.I)


def _joined(folder: str, word: str) -> str:
    return word if word.startswith(("/", "~", "$")) else f"{folder.rstrip('/')}/{word}"


def _protected(folders: tuple[str, ...], word: str) -> bool:
    paths = [_joined(f, part) for f in folders if f for part in {word, word.split("=", 1)[-1]}]
    return any(_PROTECTED_PATH_C.match(p) or _PROTECTED_PATH_C.match(posixpath.normpath(p)) for p in paths)


# These names prove only the effects of the understood command text. Unknown options,
# assignments, wrappers and launchers never inherit their child's proof.
# Git is excluded: even status, log and diff can invoke configured helpers.
_FOLD_BUILTINS = frozenset({"cd", "pushd", "popd", "pwd", "echo", "printf", "true", "false", ":", "test", "[", "[["})
_FOLD_READ_OPTIONS = {
    "ls": frozenset({"-a", "-A", "-l", "-h", "-1", "-d", "-F", "-R"}),
    "cat": frozenset({"-n", "-b", "-s", "-v", "-e", "-t", "-u"}),
    "grep": frozenset({"-i", "-v", "-n", "-c", "-l", "-L", "-h", "-H", "-q", "-s", "-w", "-x", "-F", "-E"}),
    "head": frozenset({"-q", "-v"}),
    "tail": frozenset({"-q", "-v"}),
    "wc": frozenset({"-c", "-m", "-l", "-w", "-L"}),
}


def _fold_effect_safe(words: tuple[str, ...] | None) -> bool:
    if not words:
        return False
    name, *args = words
    # Do not mistake an arbitrary executable with a builtin's basename for that builtin.
    if name in _FOLD_BUILTINS:
        return True
    if name in _FOLD_READ_OPTIONS:
        options = _FOLD_READ_OPTIONS[name]
    else:
        return False
    operands = False
    for arg in args:
        # Expansion can supply an option; even quoted expansion has no known value here.
        if any(char in arg for char in "$`*?["):
            return False
        if arg == "--":
            operands = True
        elif not operands and arg.startswith("-") and arg != "-" and arg not in options:
            return False
    return True


def _fold_effects_allow(reading: shell_grammar.Reading, point: int) -> bool:
    dependencies = set(range(point))
    for start, end, other_start, other_end in reading.effect_scopes:
        if start <= point - 1 < end:
            dependencies.update(range(other_start, other_end))
    return all(_fold_effect_safe(reading.effects[event]) for event in dependencies)


def _valid_fold_anchor(cwd) -> str | None:
    """Accept an existing, exactly spelled absolute directory, with no linked component."""
    try:
        path = os.fspath(cwd)
        if (not isinstance(path, str) or not path.startswith("/") or "\0" in path
                or any(part in ("", ".", "..") for part in path.split("/")[1:])):
            return None
        if os.path.realpath(path, strict=True) != path:
            return None
        current = "/"
        for part in path.split("/")[1:]:
            # realpath does not canonicalize case on every case-insensitive filesystem.
            if part not in os.listdir(current):
                return None
            current = os.path.join(current, part)
            mode = os.lstat(current).st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
                return None
        return path
    except (OSError, ValueError, TypeError):
        return None


def _safe_fold_prefix(prefix: str, cwd: str | os.PathLike[str] | None, checked: dict[str, bool]) -> bool:
    """Assessment-local lstat walk: missing, linked or uncheckable prefixes stay unfolded."""
    if cwd is None:
        return False
    path = os.fspath(cwd)
    parts = []
    for part in prefix.split("/"):
        parts.append(part)
        key = "/".join(parts)
        path = os.path.join(path, part)
        if key not in checked:
            try:
                mode = os.lstat(path).st_mode
                checked[key] = not stat.S_ISLNK(mode) and stat.S_ISDIR(mode)
            except OSError:
                checked[key] = False
        if not checked[key]:
            return False
    return True


def _after_moves(text: str, cwd: str | os.PathLike[str] | None = None) -> tuple[bool, bool]:
    """(deletes outside the working folder, writes a protected file) once a change of folder is followed."""
    # Folder observations are additive only when the caller supplies a work folder.
    # With no anchor, preserve main's text-only verdict and named rules exactly.
    if cwd is None:
        return False, False
    # Parse without partial work-relative folds, then choose each candidate at assessment time.
    # No filesystem verdict is cached across assessments.
    reading = shell_grammar.read(text, fold_partial=False)
    checked: dict[str, bool] = {}
    anchor_checked = False
    anchor = None

    def guard(prefix: str, point: int) -> bool:
        nonlocal anchor_checked, anchor
        if not _fold_effects_allow(reading, point):
            return False
        # Complete returns need no retained-prefix evidence, but earlier effects can
        # replace the work anchor too, so they use the same effect veto.
        if not prefix:
            return True
        if not anchor_checked:
            anchor = _valid_fold_anchor(cwd) if cwd is not None else None
            anchor_checked = True
        return _safe_fold_prefix(prefix, anchor, checked)

    if reading.understood:
        reading = shell_grammar.read(text, fold_partial=False, fold_guard=guard)
        if not reading.understood:
            # Vetoed complete returns can grow the folder union past its cap.
            # Losing that extent must not discard all path evidence toward run.
            return True, True

    outside = protected = False
    for words, folders in zip(reading.commands, reading.folders):
        name, args = words[0].rsplit("/", 1)[-1].lower(), words[1:]
        if name not in _MOVED_DELETERS | _MOVED_FINDERS | _MOVED_WRITERS:
            continue
        moved = tuple(f for f in folders if f)
        if not moved:
            continue
        operands = [w for w in args if not w.startswith("-") or w == "-"]
        if name in _MOVED_DELETERS:
            outside |= not operands or any(_outside_target(_joined(f, w)) for f in moved for w in operands)
        elif name in _MOVED_FINDERS and "-delete" in args:
            start = args[0] if args and not args[0].startswith("-") else "."
            outside |= any(_outside_target(_joined(f, start)) for f in moved)
        elif name in _MOVED_WRITERS:
            protected |= any(_protected(moved, w) for w in operands)
    protected |= any(_protected(folders, target) for target, folders in reading.writes)
    return outside, protected


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
    named_rules = set().union(*(_named_rules(words) for words in _command_words(text)))
    for key, pattern, why, quote_masked in _FORBID_C:
        if quote_masked:
            masked = masked or _masked_texts(texts)
        named = not quote_masked and key != "arslan-keys"
        if (_matches(pattern, masked if quote_masked else texts)
                or (named and key in named_rules)):
            return Assessment("forbid", key, why)
    return None


_PROTECTED_NAME_C = re.compile(_PROTECTED_NAME + r"|/(?:private/)?etc/")


def _script_names_protected(texts: tuple[str, ...]) -> bool:
    """An inline script whose code names a protected file: a script reaches ~/.zshrc through
    expanduser or Path.home(), which no path pattern sees."""
    return any(_PROTECTED_NAME_C.search(script) for script in _scripts(texts))


def _layer_two(texts: tuple[str, ...], commands: tuple[tuple[str, ...], ...], *,
               text: str, cwd: str | os.PathLike[str] | None = None, outside: bool = False) -> list[tuple[str, str]]:
    named_rules = set().union(*(_named_rules(words) for words in commands))
    found = [(key, why) for key, pattern, why in _ASK_C
             if _matches(pattern, texts) or key in named_rules]
    moved_outside, moved_protected = _after_moves(text, cwd)
    if (_script_names_protected(texts) or moved_protected) and not any(k == "protected-write" for k, _ in found):
        found.append(("protected-write", describe("protected-write")))
    if _deletes_outside(texts) or moved_outside or "delete-outside" in named_rules:
        found.insert(0, _DELETE_OUTSIDE)
    # S2a-3 step 5: on the words themselves, never through `_named_rules` (its `_fully_accounted` fallback reads text)
    if outside and not found and _reaches_outside(commands):
        found.append(OUTSIDE_REACH)
    seen: set[str] = set()
    return [(k, w) for k, w in found if not (k in seen or seen.add(k))]


def assess(command: str, *, cwd: str | os.PathLike[str] | None = None, outside: bool = False) -> Assessment:
    """The layer and first rule; without cwd, folder observations never change the verdict. `outside`: the command
    runs outside the sandbox (S2a-3 step 5, `outside-reach`); False reads exactly as before it."""
    text = str(command or "")
    if not text.strip():
        return Assessment("forbid", "empty", "no command")
    if len(text) > MAX_COMMAND_CHARS:
        return Assessment("forbid", "too-long", "command is too long to review")
    texts = _detection_texts(text)
    forbidden = _forbid(text, texts)
    if forbidden is not None:
        return forbidden
    unparseable = _unparseable(text)
    if unparseable:
        return Assessment("ask", UNREADABLE, unparseable)
    found = _layer_two(texts, _command_words(text), text=text, cwd=cwd, outside=outside)
    if found:
        return Assessment("ask", found[0][0], found[0][1])     # the named rule first: its card says what it is
    hidden = _hidden_code(texts)
    if hidden:
        return Assessment("ask", UNREADABLE, hidden)
    not_read = _not_understood(text)
    if not_read:
        return Assessment("ask", UNREADABLE, not_read)
    return Assessment("run")


def _not_understood(text: str) -> str:
    """S2a-3 step 3 (design point 4): why shell_grammar's reader does not understand the command, or "". With no named
    rule, such a command is `unreadable`, so its card, the approvals, the Island and the risk grade all read one table.
    Named layer ② rules still read the raw text, so they come first. The same parse as the named rules' (`_parsed`)."""
    prefix = _parsed(text)
    return (prefix.why or "Arslan does not understand all of it") if prefix.refused else ""


def ask_rules(command: str, *, cwd: str | os.PathLike[str] | None = None, outside: bool = False) -> set[str]:
    """Every layer ② rule the command matches (and `unreadable`). `assess` names only the first,
    which is what the card shows; a card's target lists all of them (`rules:<rule>|<rule>`)."""
    verdict = assess(command, cwd=cwd, outside=outside)
    if verdict.level != "ask":
        return set()
    text = str(command or "")
    if _unparseable(text):
        return {UNREADABLE}
    texts = _detection_texts(text)
    named = {key for key, _why in _layer_two(texts, _command_words(text), text=text, cwd=cwd, outside=outside)}
    # With no named rule, what asks is unreadable: its code is hidden, or the reader does not understand it (`assess`).
    return named | ({UNREADABLE} if not named or _hidden_code(texts) else set())


# JXA and any other OSA language than AppleScript (`osascript -l JavaScript`). It can bridge to
# Objective-C, so U11's bare run is plain AppleScript only: wrapped, its Apple Events are blocked.
_OTHER_OSA_LANGUAGE = re.compile(_CMD + r"osascript\b[^\n;&|]*\s-l\s*[\"']?(?!applescript\b)\w", re.I)


# bash 3.2 scans a substitution without knowing here-documents, so text in one can end it early and the rest runs: a
# numbered list in a commit message can delete a folder (#723 review). `$((` is arithmetic and `<<<` a here-string.
_HEREDOC_IN_SUBSTITUTION = re.compile(r"""(?:\$\((?!\()|[<>]\()[^)]*(?<!<)<<-?\s*[\\'"]?\w""")


def heredoc_in_substitution(command: str) -> bool:
    """A here-document inside `$( )`, `<( )` or `>( )`. Misses one after a `)` in the same substitution, which text
    inside the body can't write."""
    return bool(_HEREDOC_IN_SUBSTITUTION.search(str(command or "")))


def other_osa_language(command: str) -> bool:
    """An osascript in a language other than AppleScript (JXA): it cannot reach an app from a command."""
    return _matches(_OTHER_OSA_LANGUAGE, _detection_texts(str(command or "")))


def risk_grade(command: str, *, outside: bool = False) -> str:
    """The LOW/MEDIUM/HIGH grade the confirmation layer speaks (run/ask/forbid)."""
    return {"run": "LOW", "ask": "MEDIUM", "forbid": "HIGH"}[assess(command, outside=outside).level]


# S6 (v0.1.64): the "don't ask again" rules of 0.1.48–0.1.62 (`legacy_rule` rows) are gone: migration 0092
# deleted them, nothing writes one, and their Settings list and `/settings/terminal-rules` went with them.

def describe(rule: str) -> str:
    """What a rule is about, in the words its card used when it asked."""
    for key, _, why in _ASK:
        if key == rule:
            return why
    if rule == _DELETE_OUTSIDE[0]:
        return _DELETE_OUTSIDE[1]
    if rule == OUTSIDE_REACH[0]:
        return OUTSIDE_REACH[1]
    return rule.split(":", 1)[1] if rule.startswith("hermes:") else rule
