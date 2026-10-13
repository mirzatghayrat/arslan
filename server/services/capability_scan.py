"""Looking for known dangerous patterns in what a capability brings (0.1.57 §6).

Deterministic and honest about its reach: it finds KNOWN dangerous ways of writing things —
hidden instructions in a skill, a script that phones home or runs a shell, code that fetches
and runs more code, or writes to where macOS starts programs — and it cannot prove anything is
safe. That is why everything installed still runs in the sandbox. A "high" finding blocks the
install; a "note" is shown on the card and in the dossier.

What is read: a skill's SKILL.md, scripts and references; a package's OWN files (not the
whole dependency tree — HTTP clients there phone home by design and would drown the signal).
0.1.61: a skill's whole folder is read (`scan_skill_folder`) and a scan speaks in verdicts —
"dangerous" (a high finding: the skill is off until the user has read why) and "caution" (notes:
on, with a note). What could not be read is named in a note, so nothing unread is ever "clean".

"Dangerous" costs the user a click, so it needs the real act. In a script that is a write, a read or a
send. In text (SKILL.md and the other prose) it is only one of three things: invisible or bidirectional
characters, words that tell the model to ignore its earlier instructions USED as an order (not quoted,
not forbidden), and a store of secrets sent to a destination. Everything else a rule finds in text —
advice, a pointer, an install line, an act written out in a document, a credential handed to an API —
is a note, and so is the same words in a script's comments or in a file's name. A text rule never fires
inside a prohibition ("never send the key"). The runtime cards, the sandbox and the agent-settings
protection are the gate for what a skill makes Arslan do; this scan is the heads-up at import.
"""
from __future__ import annotations

import os
import re
import string
import time
import unicodedata
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

MAX_FILE_BYTES = 400_000
MAX_FILES = 400
MAX_FINDINGS = 20
#: A folder scan reads at most this much in all (64 MB: the largest archive Arslan downloads). 400
#: files of 400 KB would be 160 MB; what does not fit is named in the `not_scanned` note.
MAX_SCAN_BYTES = 64 * 1024 * 1024
#: A folder is walked this deep; a deeper one is named, not entered (a chain of ~900 folders raised
#: RecursionError in os.walk). And at most this many files of one folder are looked at; the rest are counted.
MAX_DEPTH = 32
MAX_WALKED = 50_000
#: A folder scan stops after this many seconds in all; every file it has not reached is named as not read.
#: A regex holds the GIL, so a scan is a stall of the whole server for as long as it runs.
MAX_SCAN_SECONDS = 3.0

#: The kinds of file the rules read: `text` (SKILL.md and prose references) and `data` (a skill's other files that hold
#: text: yaml, json, html, csv... and any file that is neither) are read line by line as words; a skill's scripts
#: (`skill_code`), a package's files (`code`) and its package.json (`manifest`) as code.
_PROSE = ("text", "data")
#: How much of a file is looked at to tell words from a program from other binary data.
SNIFF_BYTES = 8192
_BOM = chr(0xFEFF)


@dataclass(frozen=True)
class Rule:
    id: str
    level: str          # high | note
    #: What it reads. `text`: prose, and also a skill script's full-line comments and every file's name, at note level;
    #: `prose`: prose only; `skill_code` (a skill's script), `package` (a package's file), `code` (both), `manifest`.
    where: str
    pattern: re.Pattern
    #: Looks at each match before it counts: (the line, the match) -> counts? A rule with none counts
    #: its first match. Two rules may share an id and differ in level: the id says what was found,
    #: the level how much it matters in the place it was found.
    accept: Callable[[_Line, re.Match], bool] | None = None
    #: A cheap pattern the line must hold before `pattern` is tried. Most lines hold none of what a rule looks
    #: for, and a rule that starts at every `cp` or `>` of a hostile line would otherwise read on from each.
    needs: re.Pattern | None = None
    #: A match inside a prohibition ("never send the key") does not count.
    guard: bool = False


def _r(rule_id, level, where, pattern, flags=re.I, accept=None, needs=None, guard=False):
    return Rule(rule_id, level, where, re.compile(pattern, flags), accept, re.compile(needs, flags) if needs else None, guard)


# ── the line a rule reads ────────────────────────────────────────────────────────────────────
#: Quotation marks, each as the span of one quoted passage. A passage is read from its opening mark
#: to the next closing one, so `"a" ignore "b"` has two passages and the word between is not in one.
#: A mark whose closer is another character looks for it 300 characters ahead and no further: a run of
#: openers with no closer was read to the end of the line from each (a 400 KB line took 40 to 100 s).
_QUOTES = tuple(re.compile(p) for p in (
    r'"[^"\n]*"', "\u201c[^\u201d\n]{0,300}+\u201d", "\u201e[^\u201c\u201d\n]{0,300}+[\u201c\u201d]", "\u2018[^\u2019\n]{0,300}+\u2019",
    "\u00ab[^\u00bb\n]{0,300}+\u00bb", "\u300c[^\u300d\n]{0,300}+\u300d", "\u300e[^\u300f\n]{0,300}+\u300f", r"`[^`\n]*`",
    r"(?<![\w'])'[^'\n]*'(?![\w'])"))                     # a single quote that is not an apostrophe
_YAML_VALUE = re.compile(r"""^(\s*(?:-\s+)?(?:[\w.-]+\s*:\s*)?)(["'])(.*)\2\s*(?:#.*)?$""")
_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
#: A JSON string: the quotes that make it one are syntax, so the words inside are not a quotation (a quotation inside it is).
_JSON_STRING = re.compile(r'"(?:[^"\\\n]|\\.)*+"')
# A line break is `\n`, `\r\n` or `\r` — what an editor shows (see `_lines`). `str.splitlines()` also breaks at \x0b,
# \x0c, \x1c-\x1e, \x85, U+2028 and U+2029, which split "ignore<VT>all previous instructions" into two lines no rule
# reads whole (and moved every line number after it). They are whitespace to a pattern's `\s`.
#: A full line of comment in a script: `#` (other than the shebang) or `//`.
_COMMENT = re.compile(r"\s*(?:#|//)")


class _Line:
    """One line of a text, as the rules read it. `fenced`: inside a ``` block. `front`: inside the
    frontmatter, where a quoted value is a YAML string, not a quotation. `comment`: a full line of comment
    in a script, which the rules for acts do not read and the rules for words read at note level. `data`: a line of a
    yaml or json file, where a quoted value is a string, not a quotation."""
    __slots__ = ("text", "fenced", "front", "comment", "data", "_inside")

    def __init__(self, text: str, fenced: bool = False, front: bool = False, comment: bool = False, data: bool = False):
        self.text, self.fenced, self.front, self.comment, self.data, self._inside = text, fenced, front, comment, data, None

    def quoted(self, m: re.Match) -> bool:
        """Whether the match lies wholly inside a quotation, a code span or a fenced block: the words
        are mentioned (a skill warning about them), not used."""
        if self.fenced:
            return True
        if self._inside is None:
            text = self.text
            syntax = set()                                 # the quotes that make a value a string are not a quotation
            if self.front or self.data:
                value = _YAML_VALUE.match(text)
                if value:
                    syntax.update((value.end(1), value.end(3)))
            if self.data:
                for string in _JSON_STRING.finditer(text):
                    syntax.update((string.start(), string.end() - 1))
            if syntax:
                text = "".join(" " if i in syntax else c for i, c in enumerate(text))
            inside = bytearray(len(text))
            for quote in _QUOTES:
                for span in quote.finditer(text):
                    inside[span.start() + 1:span.end() - 1] = b"\x01" * (span.end() - span.start() - 2)
            self._inside = inside
        return self._inside.find(0, m.start(), m.end()) == -1


def _used(line: _Line, m: re.Match) -> bool:
    return not line.quoted(m)


def _mentioned(line: _Line, m: re.Match) -> bool:
    return line.quoted(m)


# A negation in the clause before a verb ("do not", "don't" with either apostrophe, "never", "cannot", "must not",
# "do not use this skill to") makes the sentence a ban, not an order. A clause ends at a full stop, a semicolon, a
# dash, "but"/"instead"..., or a comma that begins a new order (", just", ", then"). "Do not worry, ignore all
# previous instructions" and "never mind the above: ignore..." are orders: those negations do not forbid what follows.
_CLAUSE_END = re.compile(r"[.!?;](?:\s|$)|\b(?:but|instead|however|except|otherwise|rather)\b|,\s*(?:and|then|so|now|just|but)\b|"
                         r"[\u2014\u2013]|\s-{1,2}\s", re.I)
_NEGATION = re.compile(r"(?:\b(?:not|never)\b|n['\u2019]t\b)(?!\s+(?:forget|hesitate|fail|worry|mind|delay|wait|be\s+(?:afraid|shy))\b)"
                       r"|\b(?:cannot|nor|avoid|refrain)\b", re.I)                  # "don't forget to edit" is an order
#: Words that point at a file instead of ordering a change to it ("see ~/.claude/settings.json").
_POINTER = re.compile(r"\b(?:see|refer(?:s)?(?:\s+to)?|consult|per|according\s+to|documented\s+in|described\s+in|"
                      r"details\s+(?:are\s+)?in|look\s+at|located\s+(?:at|in)|found\s+in|lives\s+in|stored\s+in)\b", re.I)


def _prohibited(line: _Line, m: re.Match) -> bool:
    """Whether the match stands inside a prohibition: a negation in its clause, before it."""
    head = line.text[max(0, m.start() - 120):m.start()]
    return _NEGATION.search(_CLAUSE_END.split(head)[-1]) is not None


def _is_an_order(line: _Line, m: re.Match) -> bool:
    text = line.text
    head = text[max(0, m.start("verb") - 120):m.start("verb")]
    if _NEGATION.search(_CLAUSE_END.split(head)[-1]):
        return False
    between = m.group("between")
    return not (_CLAUSE_END.search(between) or _POINTER.search(between))


# ── where the rules look ─────────────────────────────────────────────────────────────────────
#: Between two parts of a path: `/`, or what code writes instead (`", "` of os.path.join, `" / "` of pathlib).
_SEP = r"""(?:/|['"]\s*[,/]\s*['"])"""
#: Other agents' homes (§A2), as whole folders: Hermes, Codex, Claude Code, Cursor, OpenClaw and the shared `.agents`;
#: the file `.claude.json`; and the Claude desktop app's folder. Arslan never writes any of them.
_AGENT_SETTINGS = (r"(?:\.(?:hermes|codex|claude|cursor|openclaw|agents)" + _SEP + r"|\.claude\.json"
                   + r"|Library/Application(?:\s|\\ )+Support/Claude)")
#: The same, as a person writes them in an instruction: the files an agent keeps its settings in (a skill is told
#: where its own folder is, "~/.claude/skills/<name>", and that is no order to change anything).
_AGENT_SETTINGS_TEXT = (r"(?:~|\$\{?HOME\}?)/\.(?:hermes/|claude/settings|claude\.json|codex/config|"
                        r"cursor/mcp\.json|openclaw/)")
#: Where a shell or macOS starts programs: a start file by its exact name (`.zshrc.bak` is a copy, not a start
#: file), or a launchd folder.
_START_FILE = r"\.(?:bash_profile|bash_login|bashrc|profile|zshrc|zshenv|zprofile|zlogin)(?![\w-])(?!\.\w)"
_STARTUP = r"(?:" + _START_FILE + r"|LaunchAgents|LaunchDaemons)"
_SSH_KEY = r"\.ssh" + _SEP + r"(?:id_[a-z0-9_*?]++(?!\.pub|-cert)|\*)"      # a private key (not id_x.pub), or all of them
_AUTHORIZED_KEYS = r"\.ssh" + _SEP + r"authorized_keys"
#: What may stand before the named part of a path: `~/`, `$HOME/`, `/Users/x/`, `../` — whole parts, at most 8.
_HEAD = r"['\"]?/?(?:[\w.${}~@%+=:-]{1,60}+['\"]?/){0,8}"
#: Up to n more arguments of a command, one token each (a token is at most 200 characters; none is read twice).
_ARGS = r"(?:[ \t]++\S{1,200}+){0,%d}?[ \t]++"
#: A `>` that closes an HTML tag (`<code>`, `</b>`) is not a redirect: up to ten characters of tag name before it.
_CLOSES_A_TAG = "".join(f"(?<!<[a-z0-9]{{{k}}})(?<!</[a-z0-9]{{{k}}})" for k in range(1, 11))
#: What may follow the destination of a copy: options, redirects (`2>/dev/null`, `>/dev/null`, `2>&1`; `&>/dev/null` ends
#: the command at its `&`) and a comment — not another argument, which would make the path the source
#: ("cp ~/.claude/settings.json backup.json").
_TAIL = (r"(?:[ \t]++(?:-\S{1,60}+|\d{0,2}>>?&?[ \t]*+\S{1,60}+)){0,6}+"
         r"[ \t]*+(?:#[^\n]{0,200}+)?(?:$|[;&|)])")


def _writes(path: str) -> str:
    """A write that TARGETS `path` (a regex): a redirect or tee into it, cp/mv/ln/install/rsync with it as the
    destination, a download written to it, an in-place edit, `dd of=`, a write mode or call after it, or a
    write call that names it as its destination. Reading it, copying it away, naming it in a message or
    pointing an arrow at it ("-> path", "=> path") is not a write.

    Linear in the line, on purpose. A command is followed argument by argument (a token is read once), the
    path is reached through whole path parts, and every other quantifier is bounded: a greedy `[^\\s'"]*` or
    `[^\\n]{0,200}` re-read the line from every `>`, `cp` or `tee` in it, so one 400 KB line (a minified bundle, or
    a hostile file) held the scan for minutes."""
    return "(?:" + "|".join((
        r"(?<![-=])(?:" + _CLOSES_A_TAG + r">>?[ \t]{0,16}|\btee[ \t]++(?:-a[ \t]++)?)" + _HEAD + path,
        r"\b(?:cp|mv|ln|install|rsync|ditto)\b" + _ARGS % 12 + _HEAD + path + r"[^\s'\";&|)]{0,120}+['\"]?" + _TAIL,
        r"\b(?:curl|wget)\b" + _ARGS % 16 + r"(?:-[A-Za-z]*[oO][ \t]*+|--output(?:-document)?(?:=|[ \t]++))" + _HEAD + path,
        r"\b(?:sed|perl)\b(?:[ \t]++-\S{1,60}+){0,4}?[ \t]++(?:-[A-Za-z]*i|--in-place)\S{0,20}+" + _ARGS % 8 + _HEAD + path,
        r"\bdd\b" + _ARGS % 6 + r"of=" + _HEAD + path,
        path + r"[^\n]{0,200}?(?:['\"]\)?\s*,\s*['\"][wa]b?\+?['\"]|\.write_(?:text|bytes)\(|\.open\(\s*['\"][wa])",
        r"\b(?:writeFile(?:Sync)?|appendFile(?:Sync)?|writeTextFile|createWriteStream|Bun\.write)\s*\([^\n]{0,160}?" + path,
        r"\b(?:shutil\.(?:copy2?|copyfile|move)|os\.(?:replace|rename)|copyFile(?:Sync)?|rename(?:Sync)?)\s*"
        r"\([^\n,]{0,160},[^\n]{0,80}?" + path,
    )) + ")"


#: What starts a crontab or a launchd job, as a command: `crontab -e` / `-r` / `-` / `< file` / a file, and
#: `launchctl load` / `bootstrap`. `crontab -l` only lists.
_CRONTAB = (r"\bcrontab\s+(?:-u\s+\S+\s+)?(?:-[er]\b|-(?=\s*(?:$|[;&|)]))|<|[~/.$][^\s]*|"
            r"[\w.-]+\.(?:txt|cron|crontab|tab)\b)")
_LAUNCHCTL = r"\blaunchctl\s+(?:load|bootstrap|submit)\b"
_AUTOSTART = _writes(_STARTUP) + "|" + _CRONTAB + "|" + _LAUNCHCTL

#: A command that reads, copies or uploads what it is given, with a private key among its arguments (not
#: after `-i`, `--key` or `--identity-file`, which only USE the key); and a reader in code.
_SSH_READERS = (r"\b(?:cat|less|more|head|tail|strings|xxd|od|hexdump|base64|openssl|pbcopy|cp|mv|tar|zip|ditto|install|"
                r"tee|dd|gpg|scp|rsync|sftp|curl|wget|nc|ncat|socat)\b")
#: `--exclude .ssh` and `-x .ssh` leave the folder out of an archive.
_NOT_AN_EXCLUDE = r"(?<!--exclude[ \t])(?<!--exclude-dir[ \t])(?<!--ignore[ \t])(?<!-x[ \t])"
_SSH_READ = (_SSH_READERS + _ARGS % 12 + r"(?<!-i[ \t])(?<!--key[ \t])(?<!--identity-file[ \t])" + _NOT_AN_EXCLUDE + _HEAD + _SSH_KEY)
#: The .ssh folder as a whole taken: archived, or copied/uploaded AWAY (something follows it, the destination).
#: A copy INTO the folder takes nothing out of it.
_SSH_ARCHIVE = (r"\b(?:tar|zip|7z)\b" + _ARGS % 12 + _NOT_AN_EXCLUDE + _HEAD + r"\.ssh/?['\"]?(?=\s|$|[;&|)])"
                r"|\b(?:cp|rsync|ditto|scp)\b" + _ARGS % 8 + _NOT_AN_EXCLUDE + _HEAD + r"\.ssh/?['\"]?[ \t]++[^\s;&|)]")
_SSH = (_SSH_READ + r"|" + _SSH_ARCHIVE
        + r"|" + _SSH_KEY + r"[^\n]{0,200}?\.read\w*\("
        + r"|\b(?:readFileSync|readFile|read_text|read_bytes)\s*\([^\n]{0,160}?" + _SSH_KEY
        + r"|" + _writes(_AUTHORIZED_KEYS))

#: A secret handed over: an API key, a token, a password.
_SEND_SECRET = (r"\b(?:send|post|upload|forward|transmit|exfiltrat\w*)\s+(?:the\s+|all\s+|any\s+|your\s+|their\s+)?"
                r"(?:user['\u2019]?s?\s+)?(?:api[_ ]?keys?|access\s+tokens?|auth\w*\s+tokens?|passwords?|secrets?|"
                r"credentials|ssh\s+keys?)\b")
#: A store of secrets: the ssh folder and keys, the keychain, .env, an agent's auth file...
_SECRET_STORE = (r"(?:~/\.ssh\b|\.ssh/|\bid_(?:rsa|ed25519|ecdsa|dsa)\b|\bkeychains?\b|"
                 r"\.env\b(?!\.(?:example|sample|template|dist))|\.netrc\b|\.aws/credentials|\.npmrc\b|"
                 r"\.git-credentials|\.gnupg\b|\bauth(?:-profiles)?\.json\b|\.credentials\.json\b)")
#: Where a secret store is sent. Every part is bounded and an address cannot begin in the middle of a run of
#: word characters: `[\w.+-]+@` unbounded and tried at each of 81 offsets after each verb-and-store pair of a
#: run like "send.env.send.env." took hours on 400 KB.
_DESTINATION = (r"(?:https?://|\bto\s+(?:my|our|their|an?\s+(?:remote|external|outside)|the\s+(?:remote|external))\b|"
                r"\bto\s+(?:[\w-]{1,63}\.){1,6}[a-z]{2,24}\b|\bto\s+\d{1,3}(?:\.\d{1,3}){3}\b|"
                r"(?<![\w.+-])[\w.+-]{1,64}@[\w-]{1,63}(?:\.[\w-]{1,63}){1,5})")
_SEND_STORE = (r"\b(?:send|post|upload|forward|transmit|exfiltrat\w*|copy|attach|email|paste)\b(?>[^\n]{0,50}?" + _SECRET_STORE
               + r")[^\n]{0,40}" + _DESTINATION)

#: The determiner may be "the", "your", "all", "all of the"...; the noun a rule, an instruction, a direction, a prompt...
_HIDDEN_INSTRUCTION = (r"\b(ignore|disregard|forget)\s+(?:(?:all|any|every)\s+(?:of\s+)?)?(?:(?:the|your|my|these|those)\s+)?"
                       r"(?:previous|prior|above|earlier|preceding)\s+(?:instructions?|rules?|messages?|directions?|directives?|prompts?|guidelines?)")
_SHELL = r"(?:ba|z|da|k)?sh"
#: A download run as it arrives: piped into a shell (also `| sudo bash`, `| env bash`, `| /bin/sh`), or given to one
#: as an argument: `sh -c "$(curl ...)"`, `eval "$(curl ...)"`, `bash <(curl ...)`, `source <(curl ...)`.
_PIPE_TO_SHELL = (r"\b(?:curl|wget)\b[^|\n]{0,200}\|[ \t]*(?:sudo(?:[ \t]+-\S{1,20}+){0,3}+[ \t]+|env(?:[ \t]+(?:\w{1,40}=\S{0,60}+|-\S{1,20}+)){0,6}+[ \t]+)?"
                  r"(?:/(?:usr/)?(?:local/)?bin/)?" + _SHELL + r"\b"
                  r"|\b(?:" + _SHELL + r"|eval)[ \t]+(?:-c[ \t]+)?[\"']?\$\([ \t]*(?:curl|wget)\b"
                  r"|(?<![\w.])(?:" + _SHELL + r"|source|\.)[ \t]+<\([ \t]*(?:curl|wget)\b")
#: `security find-generic-password`: with -w or -g it prints the secret (an existence check does not);
#: `dump-keychain` dumps. `-q`... may stand before the command.
_KEYCHAIN = (r"\bsecurity\b(?:[ \t]++-\S{1,20}+){0,3}+[ \t]++(?P<cmd>find-generic-password|find-internet-password|dump-keychain)\b"
             r"(?P<rest>[^\n;|]{0,200})")
_PRINTS_IT = re.compile(r"(?<![\w-])-(?=[A-Za-z]*[wg])[A-Za-z]++(?![\w-])")
_DISCARDED = re.compile(r"(?:&>|>)[ \t]*/dev/null\b")
#: A recursive remove of the root or the home folder, with the flags in any order and the target quoted, with a
#: slash or a star after it: `rm -rf ~/`, `rm -rf "$HOME"`, `rm -rf /*`, `rm -r -f /`, `rm --recursive --force /`.
#: The recursive flag is read in one pass: `-[a-z]*r[a-z]*` was quadratic on `rm -rrrr...`.
_WIPE = (r"\brm\s++(?:(?:-[a-z]++|--[a-z-]++)\s++){0,3}?(?:-(?=[a-z]*r)[a-z]++|--recursive)\s++"
         r"(?:(?:-[a-z]++|--[a-z-]*+)\s++){0,3}?[\"']?(?:/|~|\$\{?HOME\}?)/?\*?[\"']?(?=\s|$|[;&|)`'\"]|[.,:](?:\s|$))")
_SETTINGS_WRITE = _writes(_AGENT_SETTINGS)


def _prints_the_secret(line: _Line, m: re.Match) -> bool:
    """A keychain command that hands the secret over: `-w` or `-g`, output not thrown away; or a dump."""
    if m.group("cmd").lower() == "dump-keychain":
        return True
    rest = m.group("rest")
    return _PRINTS_IT.search(rest) is not None and _DISCARDED.search(rest) is None


def _only_checks_it(line: _Line, m: re.Match) -> bool:
    return not _prints_the_secret(line, m)


RULES = (
    # ── Words: SKILL.md and the other prose. A script's full-line comments and every file's name are read by the
    # `text` rules too, at note level. A match inside a prohibition ("never ...") does not count (`guard`).
    # The words used as an order are dangerous; the same words quoted, in a code span or in a fenced
    # block are mentioned (a skill warning against them) and are a note.
    _r("hidden_instruction", "high", "text", _HIDDEN_INSTRUCTION, accept=_used, needs=r"ignore|disregard|forget", guard=True),
    _r("hidden_instruction", "note", "text", _HIDDEN_INSTRUCTION, accept=_mentioned, needs=r"ignore|disregard|forget", guard=True),
    # Ordinary advice ("do not tell the user to repeat a step"): never dangerous. A skill cannot act
    # by itself; whatever it asks for still meets the cards and the ledger. (No guard: the rule IS a negation.)
    _r("hide_from_user", "note", "text", r"\b(do\s*n[o'\u2019]?t|never)\s+(tell|show|mention|reveal)\s+(this\s+)?(to\s+)?the\s+user",
       needs=r"user"),
    # A credential handed to an API ("in the x-api-key header", "to the login", "over TLS") is how an API is called,
    # and is a note wherever it goes; a secret STORE sent to a URL, a host or an address is not.
    _r("send_data_out", "note", "text", _SEND_SECRET, needs=r"send|post|upload|forward|transmit|exfiltrat", guard=True),
    _r("send_data_out", "high", "text", _SEND_STORE, needs=_SECRET_STORE, guard=True),
    _r("url_in_instructions", "note", "prose", r"https?://[^\s)>\"']+", needs=r"http"),
    # ── Acts: a script (and a package file) does them; the same act written out in text is a note.
    # An install line in a document is common and the agent's command card shows it; a skill whose OWN
    # scripts (or package hooks) pipe a download into a shell is a supply-chain risk.
    _r("pipe_to_shell", "high", "code", _PIPE_TO_SHELL, needs=r"curl|wget"),
    _r("pipe_to_shell", "high", "manifest", _PIPE_TO_SHELL, needs=r"curl|wget"),
    _r("pipe_to_shell", "note", "text", _PIPE_TO_SHELL, needs=r"curl|wget", guard=True),
    _r("run_decoded_code", "high", "code",
       r"\b(exec|eval)\s*\(\s*(base64\.b64decode|codecs\.decode|bytes\.fromhex|zlib\.decompress|atob)\b", needs=r"exec|eval"),
    # Persistence is a WRITE: into a shell start file or a launchd folder, a crontab installed, a job loaded.
    # `source ~/.zshrc` and `crontab -l` only read.
    _r("autostart_write", "high", "code", _AUTOSTART, needs=_STARTUP + r"|crontab|launchctl"),
    _r("autostart_write", "note", "text", _AUTOSTART, needs=_STARTUP + r"|crontab|launchctl", guard=True),
    # A script that prints the keychain's secret is high; a commented config example in a document, or a check that
    # an item exists, is a note (the runtime floor refuses `security find-generic-password -w` in every mode).
    _r("keychain_read", "high", "code", _KEYCHAIN, accept=_prints_the_secret, needs=r"security"),
    _r("keychain_read", "high", "manifest", _KEYCHAIN, accept=_prints_the_secret, needs=r"security"),
    _r("keychain_read", "note", "code", _KEYCHAIN, accept=_only_checks_it, needs=r"security"),
    _r("keychain_read", "note", "manifest", _KEYCHAIN, accept=_only_checks_it, needs=r"security"),
    _r("keychain_read", "note", "text", _KEYCHAIN, needs=r"security", guard=True),
    # Key material taken: a private key read, copied or uploaded (`cat`, `cp`, `base64`, `curl -F`...), the .ssh
    # folder archived or copied away, a key appended to authorized_keys. `ssh-add`, `ssh -i`, `ssh-keygen -l`/`-y`
    # and the .pub half use or describe a key without taking it.
    _r("ssh_keys", "high", "code", _SSH, needs=r"\.ssh"),
    _r("ssh_keys", "note", "text", _SSH, needs=r"\.ssh", guard=True),
    _r("wipe", "high", "code", _WIPE, needs=r"rm"),
    _r("wipe", "high", "manifest", _WIPE, needs=r"rm"),
    _r("wipe", "note", "text", _WIPE, needs=r"rm", guard=True),
    _r("network_in_script", "note", "skill_code", r"\b(requests|urllib|httpx|aiohttp|socket)\b"),
    _r("shell_in_script", "note", "skill_code", r"\b(subprocess|os\.system|os\.popen)\b"),
    _r("install_hook", "note", "manifest", r"\"(preinstall|install|postinstall)\"\s*:", needs=r"install"),
    # Another agent's folder, written by a script or asked of the model (0.1.61 §C1, Hermes'
    # skills guard; §A2 "other agents' settings"). The write must TARGET the path (see `_writes`), so reading it,
    # copying it away or printing "… -> path" is not a finding. Telling the model NOT to edit it is not one
    # either, nor is pointing at it ("see ~/.claude/settings.json").
    # Arslan runs a skill's scripts itself, so a skill that writes them is high; a package often bundles a
    # client-registration command next to the server (`install --client cursor`), and a high finding
    # there would remove an install the user chose on its card: a note, the card shows it.
    _r("agent_settings_write", "high", "skill_code", _SETTINGS_WRITE, needs=_AGENT_SETTINGS),
    _r("agent_settings_write", "note", "package", _SETTINGS_WRITE, needs=_AGENT_SETTINGS),
    _r("agent_settings_write", "note", "text", _SETTINGS_WRITE, needs=_AGENT_SETTINGS, guard=True),
    # Words telling the model to change a settings file are a note (a cross-agent skill says "add to your Codex
    # config"): the act in code is the high one, and the runtime holds whatever the scan says.
    _r("agent_settings_instruction", "note", "text",
       r"\b(?P<verb>edit|modify|change|update|overwrite|replace|patch|append|merge|write\s+(?:\w+\s+){0,4}?(?:to|into|in)|"
       r"add\s+(?:\w+\s+){0,4}?to)\b(?P<between>[^\n]{0,80}?)(?P<path>" + _AGENT_SETTINGS_TEXT + r")",
       accept=_is_an_order, needs=r"edit|modify|change|update|overwrite|replace|patch|append|merge|write|add"),
)

#: Format characters that only shape text: the byte-order mark, a soft hyphen and the left-to-right and
#: right-to-left marks (U+FEFF, U+00AD, U+200E, U+200F); and the script-format controls Arabic and Syriac
#: are written with (number signs, end of ayah).
_SHAPING = frozenset("\ufeff\u00ad\u200e\u200f")
_SCRIPT_FORMATS = frozenset("\u0600\u0601\u0602\u0603\u0604\u0605\u06dd\u070f\u0890\u0891\u08e2")
#: Joiners that real writing needs between letters: ZWNJ (Persian, Indic), ZWJ (Indic, emoji), ALM (Arabic).
_JOINERS = frozenset("\u200c\u200d\u061c")
#: What may stand beside such a joiner for it to be orthography: a letter, a mark (a virama, a variation
#: selector), a digit or an emoji.
_WORDY = frozenset({"Lu", "Ll", "Lt", "Lm", "Lo", "Mn", "Mc", "Me", "Nd", "Nl", "No", "So", "Sk"})
#: Taken away from a line before the rules read it: a pattern is matched through the zero-width characters
#: someone put inside a word ("ig" + ZWNJ + "nore"), a combining grapheme joiner or a Hangul filler.
_SQUASH = re.compile(r"[\u00ad\u034f\u061c\u115f\u1160\u200b-\u200f\u2060-\u2064\u206a-\u206f\u3164\ufe00-\ufe0f\ufeff\uffa0]")
#: Bidirectional marks and controls, and the tag block (an invisible copy of ASCII).
_BIDI_MARKS = frozenset(chr(c) for c in (0x200E, 0x200F, 0x061C, *range(0x202A, 0x202F), *range(0x2066, 0x206A)))
_TAG_CHARS = re.compile(f"[{chr(0xE0000)}-{chr(0xE007F)}]")
#: The three flags that are written as a tag sequence (England, Scotland, Wales): a black flag, the tags of
#: "gbeng", "gbsct" or "gbwls", a cancel tag. Nothing else can ride in them.
_RGI_FLAGS = re.compile(chr(0x1F3F4) + "(?:" + "|".join("".join(chr(0xE0000 + ord(c)) for c in word) for word in ("gbeng", "gbsct", "gbwls"))
                        + ")" + chr(0xE007F))


def _beside_rtl(text: str, i: int) -> bool:
    """Whether the nearest letter on either side of text[i] — past spaces and other bidirectional marks — is
    written right to left (Hebrew, Arabic, Syriac...)."""
    for step in (-1, 1):
        j, looked = i + step, 0
        while 0 <= j < len(text) and looked < 6:
            ch = text[j]
            if ch != " " and ch not in _BIDI_MARKS:
                if unicodedata.bidirectional(ch) in ("R", "AL"):
                    return True
                break
            j, looked = j + step, looked + 1
    return False


def _invisible(text: str, code: bool = False) -> tuple[int, int]:
    """(hiding, odd). `hiding`: characters that hide or reorder text, in a document as in code ("Trojan
    Source"): bidirectional controls and isolates (U+202A-202E, U+2066-2069) and tag characters
    (U+E0000-E007F, an invisible ASCII). `odd`: other zero-width characters that are not how a script is
    written: a zero-width space, a word joiner, a joiner that stands beside no letter. A ZWNJ, ZWJ or ALM
    between letters, or after a virama (Indic scripts write one at the end of a syllable or a word), is
    real orthography (Persian, Indic, Arabic, emoji sequences) and counts for nothing; so are the three flags
    written as tag sequences, and — in text, not in `code` — an embedding or an isolate beside Hebrew or Arabic
    letters (U+202D and U+202E, the overrides, always count)."""
    if text.isascii():
        return 0, 0
    if _TAG_CHARS.search(text):
        text = _RGI_FLAGS.sub("", text)
    hiding = odd = 0
    for i, ch in enumerate(text):
        if ch < "\x80":
            continue
        cp = ord(ch)
        if 0x202A <= cp <= 0x202E or 0x2066 <= cp <= 0x2069 or 0xE0000 <= cp <= 0xE007F:
            if not code and cp not in (0x202D, 0x202E) and cp < 0xE0000 and _beside_rtl(text, i):
                continue
            hiding += 1
        elif unicodedata.category(ch) != "Cf" or ch in _SHAPING or ch in _SCRIPT_FORMATS:
            continue
        elif ch in _JOINERS:
            before, after = text[i - 1] if i else "", text[i + 1:i + 2]
            between_letters = (before and after and unicodedata.category(before) in _WORDY
                               and unicodedata.category(after) in _WORDY)
            if not (between_letters or (before and unicodedata.combining(before) == 9)):     # 9: a virama
                odd += 1
        else:
            odd += 1
    return hiding, odd


@dataclass
class Finding:
    rule: str
    level: str
    file: str
    line: int
    excerpt: str


def _shown(name: str) -> str:
    """A file name as the user is shown it: a control character, a line break or a bidirectional or other format
    character becomes a visible escape (`\\x1b`, `\\u202e`), so a name can neither repaint the screen nor pass for another."""
    if name.isprintable():
        return name
    bs = chr(92)
    return "".join(ch if ch.isprintable() else (f"{bs}x{ord(ch):02x}" if ord(ch) < 0x100 else f"{bs}u{ord(ch):04x}" if ord(ch) < 0x10000
                                                else f"{bs}U{ord(ch):08x}") for ch in name)


def _blank(line: str) -> bool:
    return not line.replace(_BOM, "").strip()


def _prepare(text: str, kind: str) -> list[tuple[int, str, _Line]]:
    """The lines of a text with what the rules need to know about each: where a fenced block is (one that is
    closed: an unclosed fence is not a code block), where a SKILL.md's frontmatter is (after a byte-order mark or blank
    lines too), and which lines of a script are comments."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    read = [line if line.isascii() else _SQUASH.sub("", line) for line in lines]
    front_from = front_to = -1
    fenced = [False] * len(lines)
    if kind == "text":
        if text.lstrip(string.whitespace + _BOM).startswith("---"):
            first = next((i for i, line in enumerate(lines) if not _blank(line)), -1)
            if first >= 0 and lines[first].replace(_BOM, "").strip() == "---":
                close = next((i for i in range(first + 1, len(lines)) if lines[i].strip() in ("---", "...")), -1)
                if close > first:
                    front_from, front_to = first, close
        opener = None                                   # (line, mark, length) of the fence that is open
        for i, line in enumerate(read if "```" in text or "~~~" in text else ()):
            if front_from <= i <= front_to:
                continue
            m = _FENCE.match(line)
            if m is None:
                continue
            mark = m.group(1)
            if opener is None:
                opener = (i, mark[0], len(mark))
            elif mark[0] == opener[1] and len(mark) >= opener[2] and not line[m.end():].strip():
                for j in range(opener[0] + 1, i):
                    fenced[j] = True
                opener = None
    out: list[tuple[int, str, _Line]] = []
    code = kind not in _PROSE
    for i, line in enumerate(lines):
        if not read[i] or read[i].isspace():
            continue                                    # a blank line holds nothing for a rule; the others keep their numbers
        comment = code and _COMMENT.match(read[i]) is not None and not (i == 0 and read[i].startswith("#!"))
        out.append((i + 1, line, _Line(read[i], fenced=fenced[i], front=front_from < i < front_to, comment=comment, data=kind == "data")))
    return out


def _reads(rule: Rule, kind: str) -> tuple[bool, bool]:
    """(whether the rule reads the lines of a file of this kind, whether it reads a script's comment lines). Prose is
    read by the `text` rules, and by the `prose` ones in a `text` file; a script's code lines by the rules for
    its kind; its full-line comments by the `text` rules (a skill's script only: a package's comments are its authors')."""
    where = rule.where
    if kind in _PROSE:
        return where == "text" or (where == "prose" and kind == "text"), False
    if where == "text":
        return False, kind == "skill_code"
    return (where == kind or (where == "code" and kind in ("skill_code", "code")) or (where == "package" and kind == "code")), False


def _hit(rule: Rule, line: _Line) -> bool:
    if rule.needs is not None and rule.needs.search(line.text) is None:
        return False
    if rule.accept is None and not rule.guard:
        return rule.pattern.search(line.text) is not None
    return any((rule.accept is None or rule.accept(line, m)) and not (rule.guard and _prohibited(line, m))
               for m in rule.pattern.finditer(line.text))


def scan_text(name: str, text: str, *, kind: str) -> list[Finding]:
    """`kind`: text (a skill's instructions), data (its other files that hold text: yaml, json, html...), skill_code
    (a skill's script), code (a package file), manifest (package.json)."""
    out: list[Finding] = []
    shown = _shown(name)
    lines = _prepare(text, kind)
    flat = text if text.isascii() else _SQUASH.sub("", text)
    pools = (lines, []) if kind in _PROSE else ([x for x in lines if not x[2].comment], [x for x in lines if x[2].comment])
    for rule in RULES:
        on_lines, on_comments = _reads(rule, kind)
        pool = pools[0] if on_lines else pools[1] if on_comments else ()
        if not pool or (rule.needs is not None and rule.needs.search(flat) is None):
            continue                        # nothing to read, or nothing in the whole text a match could start from
        for n, raw, line in pool:
            if _hit(rule, line):
                out.append(Finding(rule.id, "note" if line.comment else rule.level, shown, n, raw.strip()[:160]))
                break                       # one finding per rule per file is enough to show
    hiding, odd = _invisible(text, code=kind not in _PROSE)
    if hiding:
        # A skill's bidirectional or tag characters are dangerous (P6); a package's files are judged as before: a note.
        level = "high" if kind in ("text", "data", "skill_code") else "note"
        out.append(Finding("invisible_characters", level, shown, 0, f"{hiding} bidirectional-control or tag characters"))
    if odd:
        out.append(Finding("zero_width_characters", "note", shown, 0, f"{odd} zero-width characters"))
    if kind == "text":
        if re.search(r"[A-Za-z0-9+/]{400,}={0,2}", text):
            out.append(Finding("long_encoded_blob", "note", shown, 0, "a long base64-like block"))
    return out


_PLAIN_NAME = re.compile(r"[\w.-]*")


def scan_name(rel: str) -> list[Finding]:
    """A file's or folder's name, read by the `text` rules at note level: the model is shown the list of a skill's
    files, and a name can say anything. A name of letters, digits, dots and dashes cannot hold what a rule looks for."""
    base = rel.rstrip("/").rsplit("/", 1)[-1]
    if _PLAIN_NAME.fullmatch(base):
        return []
    shown = _shown(rel)
    line = _Line(_SQUASH.sub("", base).replace("\n", " ").replace("\r", " "))
    out = [Finding(rule.id, "note", shown, 0, shown[:160]) for rule in RULES if rule.where == "text" and _hit(rule, line)]
    hiding, odd = _invisible(base, code=False)
    if hiding:
        out.append(Finding("invisible_characters", "note", shown, 0, f"{hiding} bidirectional-control or tag characters"))
    if odd:
        out.append(Finding("zero_width_characters", "note", shown, 0, f"{odd} zero-width characters"))
    return out


def summarise(findings: list[Finding]) -> dict:
    """The level is read from EVERY finding; the list kept is cut to MAX_FINDINGS with the high ones
    first and then the note of what was not read, so a pile of notes can never push a high finding out,
    and the cut never hides that part of a skill was not read (0.1.61: whole folders)."""
    level = "blocked" if any(f.level == "high" for f in findings) else ("notes" if findings else "clean")
    ordered = sorted(findings, key=lambda f: (f.level != "high", f.rule != "not_scanned"))
    kept = ordered[:MAX_FINDINGS]
    unread = next((f for f in ordered if f.rule == "not_scanned"), None)
    if unread is not None and unread not in kept:
        kept[-1] = unread
    return {"level": level, "findings": [asdict(f) for f in kept]}


def scan_skill(body: str, scripts: dict[str, str], references: dict[str, str]) -> dict:
    found = scan_text("SKILL.md", body, kind="text")
    for name, text in references.items():
        found += scan_text(name, text, kind="text")
    for name, text in scripts.items():
        found += scan_text(name, text, kind="skill_code")
    return summarise(found)


# ── 0.1.61 §C1: a skill's whole folder, and the verdicts the skills list speaks ─────────────

_TEXT_SUFFIXES = frozenset({".md", ".markdown", ".txt", ".rst"})
#: Data files that hold text. They are read as words (a file that is neither code nor prose is read so, too, unless
#: it is binary), and a script that is named like one is read as code as well.
_DATA_SUFFIXES = frozenset({".yaml", ".yml", ".json", ".toml", ".html", ".htm", ".csv", ".xml", ".ini", ".cfg"})
_CODE_SUFFIXES = frozenset({".py", ".sh", ".bash", ".zsh", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
                            ".rb", ".pl", ".php", ".applescript", ".swift", ".go", ".rs", ".lua", ".ps1",
                            ".r", ".jl", ".java", ".kt", ".c", ".cc", ".cpp", ".cs",
                            ".command", ".bat", ".cmd", ".tool"})
_CODE_NAMES = frozenset({"makefile", "gnumakefile", "justfile"})
#: The first bytes of a program: ELF, Mach-O (32 and 64 bit, both byte orders), a universal binary or Java class, a PE ("MZ").
_PROGRAM_MAGIC = tuple(bytes.fromhex(h) for h in ("7f454c46", "feedface", "feedfacf", "cefaedfe", "cffaedfe", "cafebabe", "4d5a"))
_NUL = bytes(1)
#: Folders a skill's folder may hold that are not the skill's own text: dependencies, a
#: checkout's history, caches. They are not walked — and are named as not read.
_DEPENDENCY_DIRS = frozenset({".git", "node_modules", "__pycache__", ".venv", "venv"})


def _classify(rel: str, head: bytes, executable: bool) -> tuple[str, ...]:
    """What a file of a skill's folder is, from its name, its first bytes and its mode: the kinds to read it as —
    `skill_code` (a script), `text` (prose) or `data` (yaml, json, html... and any other file that holds text) — or
    `("program",)` for a program that is not read (a Mach-O, ELF or PE by its first bytes, or a binary file with the
    executable bit), or `()` for binary data that is neither words nor code (an image, a font, bytecode), which is
    skipped without a word. Code is a source file by its suffix, a Makefile, anything with the executable bit or a `#!`
    whatever its suffix, and a file in a scripts/ folder (at any depth, in any case); a text or data file that is code
    too is read both ways."""
    if _NUL in head:
        return ("program",) if executable or head.startswith(_PROGRAM_MAGIC) else ()
    path = PurePosixPath(rel)
    suffix = path.suffix.lower()
    words = "text" if suffix in _TEXT_SUFFIXES else "data"
    if suffix in _CODE_SUFFIXES or path.name.lower() in _CODE_NAMES:
        return ("skill_code",)
    in_scripts = suffix not in _TEXT_SUFFIXES and "scripts" in (part.lower() for part in path.parts[:-1])
    if executable or head.startswith(b"#!") or in_scripts:
        return ("skill_code", words) if suffix in _TEXT_SUFFIXES | _DATA_SUFFIXES else ("skill_code",)
    return (words,)


def verdict(scan: dict | None) -> str:
    """A skill's scan in the skills list's words (§C1): dangerous (a high finding: the skill is
    off until the user reads it), caution (notes: on, with a note), clean."""
    level = (scan or {}).get("level")
    return {"blocked": "dangerous", "notes": "caution"}.get(level, "clean")


def same_findings(a: dict | None, b: dict | None) -> bool:
    """Whether two scans found the same things (rule, file and line text) — so a skill the user
    turned on after reading its findings stays on while nothing new turns up (Ruling C). It compares the
    findings a scan KEEPS (at most MAX_FINDINGS, highs first, excerpts of 160 characters), not every hit:
    equal, not subset, because a different set is a different skill to read."""
    def key(scan):
        found = ((f.get("rule"), f.get("file"), f.get("excerpt")) for f in (scan or {}).get("findings") or [])
        return sorted(found, key=repr)                          # a missing file is None: repr orders it, < would raise
    return key(a) == key(b)


def _scan(skill_md: str, items: list[tuple[str, str, str]], unread: list[str], deadline: float | None = None,
          names: list[str] = ()) -> dict:
    """A skill given as (path, text, kind) items, in the order to scan them (code first): its whole SKILL.md
    (the frontmatter too — a description is read by the model as well) and each file as instructions or as
    code; and the `names` of its files and folders. What could not be read (`unread`, any text over MAX_FILE_BYTES, read
    as far as that, and whatever the `deadline` cut off) is one `not_scanned` note."""
    found = scan_text("SKILL.md", skill_md, kind="text")
    unread = [*unread]
    named = set(unread)                                  # a file read two ways (code and data) is named once
    for i, (rel, text, kind) in enumerate(items):
        if deadline is not None and time.monotonic() >= deadline:
            unread.extend(dict.fromkeys(later for later, _, _ in items[i:] if later not in named))
            break
        found += scan_text(rel, text[:MAX_FILE_BYTES], kind=kind)
        if len(text) > MAX_FILE_BYTES and rel not in named:
            named.add(rel)
            unread.append(rel)
    for rel in names:
        if deadline is not None and time.monotonic() >= deadline:
            break
        found += scan_name(rel)
    if unread:
        found.append(Finding("not_scanned", "note", _shown(unread[0]), 0,
                             (f"{len(unread)} not read, and a file that was not read can still run: "
                              + ", ".join(_shown(name) for name in unread[:6]))[:160]))
    summary = summarise(found)
    summary["verdict"] = verdict(summary)
    return summary


def scan_texts(skill_md: str, files: dict[str, str], *, unread: list[str] = ()) -> dict:
    """A skill given as text: its whole SKILL.md and its files, each read as instructions or as code
    by its name (or its `#!`). What could not be read (`unread`) is one `not_scanned` note: never
    silently clean."""
    items, names, unread = [], [*files, *unread], [*unread]
    for rel, text in files.items():
        if rel == "SKILL.md":
            continue
        kinds = _classify(rel, text[:SNIFF_BYTES].encode("utf-8", "replace"), False)
        if kinds == ("program",):
            unread.append(rel + " (a program)")
        else:
            items.extend((rel, text, kind) for kind in kinds)
    items.sort(key=lambda item: (item[2] != "skill_code", item[0]))        # code first, then by name
    return _scan(skill_md, items, unread, names=names)


def _list_folder(folder: Path, candidates: list[tuple[int, str, tuple[str, ...], Path]], unread: list[str], deadline: float,
                 names: list[str]) -> None:
    """Walk `folder` top-down WITHOUT recursion (os.walk recurses on Python 3.11) and file every regular
    file that holds words or code in `candidates` as (0 code | 1 words, name, kinds, path) — see `_classify`;
    everything that will not be read goes by name into `unread`: a link (never followed), a dependency folder, a
    folder nested deeper than MAX_DEPTH, a folder it cannot list, a pipe, socket or device (opening one can wait for
    ever), a program, whatever lies past MAX_WALKED files, and whatever the `deadline` stopped it short of. Every
    name it meets goes into `names`."""
    def relative(path) -> str:
        try:
            return Path(path).relative_to(folder).as_posix()
        except ValueError:
            return str(path)

    seen = 0
    pending = [(folder, 0)]
    while pending:
        if time.monotonic() >= deadline:                                 # out of time: name the folders left
            unread.extend(relative(left) + "/" for left, _ in reversed(pending))
            return
        top, depth = pending.pop()
        try:
            with os.scandir(top) as listing:
                entries = sorted(listing, key=lambda entry: entry.name)
        except OSError:
            unread.append(relative(top) + "/")
            continue
        below = []
        for k, entry in enumerate(entries):
            if k % 256 == 255 and time.monotonic() >= deadline:          # out of time inside a huge folder
                unread.extend(relative(rest.path) for rest in entries[k:])
                unread.extend(relative(left) + "/" for left, _ in [*below, *reversed(pending)])
                return
            rel = relative(entry.path)
            names.append(rel)
            try:
                if entry.is_symlink():
                    unread.append(rel + "/" if entry.is_dir() else rel)
                elif entry.is_dir(follow_symlinks=False):
                    if entry.name in _DEPENDENCY_DIRS or depth >= MAX_DEPTH:
                        unread.append(rel + "/")
                    else:
                        below.append((Path(entry.path), depth + 1))
                elif not entry.is_file(follow_symlinks=False):
                    unread.append(rel)
                elif rel != "SKILL.md":
                    seen += 1
                    if seen > MAX_WALKED:
                        unread.append(f"(over {MAX_WALKED} files: the rest not listed)")
                        return
                    with open(entry.path, "rb") as handle:
                        head = handle.read(SNIFF_BYTES)
                    kinds = _classify(rel, head, bool(entry.stat(follow_symlinks=False).st_mode & 0o111))
                    if kinds == ("program",):
                        unread.append(rel + " (a program)")
                    elif kinds:                         # () is an image, a font, bytecode: neither words nor code
                        candidates.append((0 if "skill_code" in kinds else 1, rel, kinds, Path(entry.path)))
            except OSError:
                unread.append(rel)
        pending.extend(reversed(below))


def scan_skill_folder(folder: Path | None, skill_md: str) -> dict:
    """A skill's folder (§C1): its SKILL.md and every text or code file under it — at most MAX_FILES
    files of at most MAX_FILE_BYTES each, MAX_SCAN_BYTES in all, SKILL.md first, then code (scripts, source
    files, executables), then the rest, so a few hundred references can never push the scripts out of the
    budget. What is not read (see `_list_folder`, and whatever is over the limits) is named in a note.
    A disk error never escapes: what cannot be read is named, never silently clean. And it never holds the
    server for long: after MAX_SCAN_SECONDS in all it stops, and every file it has not reached is named."""
    deadline = time.monotonic() + MAX_SCAN_SECONDS
    candidates: list[tuple[int, str, tuple[str, ...], Path]] = []
    unread: list[str] = []
    names: list[str] = []
    try:
        walkable = folder is not None and folder.is_dir()
    except OSError:
        walkable = False
        unread.append("./")
    if walkable:
        _list_folder(folder, candidates, unread, deadline, names)
    items: list[tuple[str, str, str]] = []
    spent = read = 0
    ordered = sorted(candidates, key=lambda candidate: (candidate[0], candidate[1]))
    for i, (_, rel, kinds, path) in enumerate(ordered):
        if time.monotonic() >= deadline:
            unread.extend(later for _, later, _, _ in ordered[i:])
            break
        try:
            size = path.stat().st_size
            if read >= MAX_FILES or size > MAX_FILE_BYTES or spent + size > MAX_SCAN_BYTES:
                unread.append(rel)
                continue
            text = path.read_text("utf-8", errors="replace")
            items.extend((rel, text, kind) for kind in kinds)
            read += 1
            spent += size
        except OSError:
            unread.append(rel)
    return _scan(skill_md, items, unread, deadline, names)


def _own_files(root: Path) -> list[Path]:
    """A package's own files under an install folder: the Python distribution named in
    requirements.in, or node_modules/<package>, or an unpacked bundle."""
    files: list[Path] = []
    req = root / "requirements.in"
    if req.is_file():
        name = req.read_text().split("==", 1)[0].strip()
        want = re.sub(r"[-_.]+", "_", name).lower()
        for record in root.glob("venv/lib/python*/site-packages/*.dist-info/RECORD"):
            dist = re.sub(r"[-_.]+", "_", record.parent.name.removesuffix(".dist-info").rsplit("-", 1)[0]).lower()
            if dist != want:
                continue
            site = record.parent.parent
            for line in record.read_text().splitlines():
                rel = line.split(",", 1)[0]
                if rel.endswith((".py", ".js", ".sh")) and ".." not in rel:
                    files.append(site / rel)
    lock = root / "package.json"
    if lock.is_file():
        import json
        try:
            deps = json.loads(lock.read_text()).get("dependencies") or {}
        except ValueError:
            deps = {}
        for dep in deps:
            folder = root / "node_modules" / dep
            files += [p for p in folder.rglob("*") if p.suffix in (".js", ".mjs", ".cjs", ".sh", ".json")
                      and "node_modules" not in p.relative_to(folder).parts]
    bundle = root / "bundle"
    if bundle.is_dir():
        files += [p for p in bundle.rglob("*") if p.suffix in (".js", ".mjs", ".cjs", ".py", ".sh", ".json")
                  and "node_modules" not in p.relative_to(bundle).parts]
    return files[:MAX_FILES]


def scan_install(root: Path) -> dict:
    found: list[Finding] = []
    for path in _own_files(root):
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
            text = path.read_text("utf-8", errors="replace")
        except OSError:
            continue
        name = str(path.relative_to(root))
        kind = "manifest" if path.name == "package.json" else "code"
        found += scan_text(name, text, kind=kind)
    return summarise(found)
