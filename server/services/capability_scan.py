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
"Dangerous" costs the user a click, so it needs the real act: a script that writes, reads or sends, or
words USED as an order. The same words quoted, advice, a pointer, an install line in a document are a
note. The runtime cards, the sandbox and the agent-settings protection are the gate for what a skill
makes Arslan do; this scan is the heads-up at import.
"""
from __future__ import annotations

import os
import re
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


@dataclass(frozen=True)
class Rule:
    id: str
    level: str          # high | note
    where: str          # text (instructions) | skill_code (a skill's script) | package (a package's file) | code (both) | manifest | any
    pattern: re.Pattern
    #: Looks at each match before it counts: (the line, the match) -> counts? A rule with none counts
    #: its first match. Two rules may share an id and differ in level: the id says what was found,
    #: the level how much it matters in the place it was found.
    accept: Callable[[_Line, re.Match], bool] | None = None
    #: A cheap pattern the line must hold before `pattern` is tried. Most lines hold none of what a rule looks
    #: for, and a rule that starts at every `cp` or `>` of a hostile line would otherwise read on from each.
    needs: re.Pattern | None = None


def _r(rule_id, level, where, pattern, flags=re.I, accept=None, needs=None):
    return Rule(rule_id, level, where, re.compile(pattern, flags), accept, re.compile(needs, flags) if needs else None)


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
_FENCE = re.compile(r"^\s{0,3}(?:`{3,}|~{3,})")


class _Line:
    """One line of a text, as the rules read it. `fenced`: inside a ``` block. `front`: inside the
    frontmatter, where a quoted value is a YAML string, not a quotation."""
    __slots__ = ("text", "fenced", "front", "_inside")

    def __init__(self, text: str, fenced: bool = False, front: bool = False):
        self.text, self.fenced, self.front, self._inside = text, fenced, front, None

    def quoted(self, m: re.Match) -> bool:
        """Whether the match lies wholly inside a quotation, a code span or a fenced block: the words
        are mentioned (a skill warning about them), not used."""
        if self.fenced:
            return True
        if self._inside is None:
            text = self.text
            if self.front:
                value = _YAML_VALUE.match(text)
                if value:                                  # the quotes that make the value a string are not a quotation
                    text = "".join(" " if i in (value.end(1), value.end(3)) else c for i, c in enumerate(text))
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
# "do not use this skill to") makes the sentence a ban, not an order. A clause ends at a full stop,
# a semicolon, "but"/"instead"..., or a comma that begins a new order (", just", ", then").
_CLAUSE_END = re.compile(r"[.!?;](?:\s|$)|\b(?:but|instead|however|except|otherwise|rather)\b|,\s*(?:and|then|so|now|just|but)\b",
                         re.I)
_NEGATION = re.compile(r"(?:\b(?:not|never)\b|n['\u2019]t\b)(?!\s+(?:forget|hesitate|fail)\b)|\b(?:cannot|nor|avoid|refrain)\b",
                       re.I)                  # "don't forget to edit" is an order
#: Words that point at a file instead of ordering a change to it ("see ~/.claude/settings.json").
_POINTER = re.compile(r"\b(?:see|refer(?:s)?(?:\s+to)?|consult|per|according\s+to|documented\s+in|described\s+in|"
                      r"details\s+(?:are\s+)?in|look\s+at|located\s+(?:at|in)|found\s+in|lives\s+in|stored\s+in)\b", re.I)


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
#: Other agents' settings files (§A2): Hermes, Claude Code, Codex, Cursor, OpenClaw.
_AGENT_SETTINGS = (r"(?:\.hermes" + _SEP + r"|\.claude" + _SEP + r"settings|\.claude\.json|\.codex" + _SEP + r"config"
                   + r"|\.cursor" + _SEP + r"mcp\.json|\.openclaw" + _SEP + r")")
#: The same, as a person writes them in an instruction.
_AGENT_SETTINGS_TEXT = (r"(?:~|\$\{?HOME\}?)/\.(?:hermes/|claude/settings|claude\.json|codex/config|"
                        r"cursor/mcp\.json|openclaw/)")
#: Where a shell or macOS starts programs.
_STARTUP = r"(?:\.bash_profile|\.bashrc|\.zshrc|\.zprofile|LaunchAgents|LaunchDaemons)"
_SSH_KEY = r"\.ssh" + _SEP + r"id_[a-z0-9_*?]++(?!\.pub|-cert)"           # a private key: not id_x.pub
_AUTHORIZED_KEYS = r"\.ssh" + _SEP + r"authorized_keys"
#: What may stand before the named part of a path: `~/`, `$HOME/`, `/Users/x/`, `../` — whole parts, at most 8.
_HEAD = r"['\"]?/?(?:[\w.${}~@%+=:-]{1,60}+['\"]?/){0,8}"
#: Up to n more arguments of a command, one token each (a token is at most 200 characters; none is read twice).
_ARGS = r"(?:[ \t]++\S{1,200}+){0,%d}?[ \t]++"


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
        r"(?<![-=])(?:>>?[ \t]{0,16}|\btee[ \t]++(?:-a[ \t]++)?)" + _HEAD + path,
        r"\b(?:cp|mv|ln|install|rsync|ditto)\b" + _ARGS % 12 + _HEAD + path + r"[^\s'\"]{0,120}['\"]?[ \t]*(?:$|[;&|)])",
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

#: A command that reads, copies or uploads what it is given, with a private key among its arguments (not
#: after `-i`, `--key` or `--identity-file`, which only USE the key); and a reader in code.
_SSH_READERS = (r"\b(?:cat|less|more|head|tail|strings|xxd|od|hexdump|base64|openssl|pbcopy|cp|mv|tar|zip|ditto|install|"
                r"tee|dd|gpg|scp|rsync|sftp|curl|wget|nc|ncat|socat)\b")
_SSH_READ = (_SSH_READERS + _ARGS % 12 + r"(?<!-i[ \t])(?<!--key[ \t])(?<!--identity-file[ \t])" + _HEAD + _SSH_KEY)
_SSH_ARCHIVE = r"\b(?:tar|zip|cp|rsync|ditto|scp|7z)\b" + _ARGS % 8 + _HEAD + r"\.ssh/?['\"]?(?=\s|$)"

#: A secret handed over, and the sign that it is how an API is called ("in the x-api-key header", "to the login").
_SEND_SECRET = (r"\b(?:send|post|upload|forward|transmit|exfiltrat\w*)\s+(?:the\s+|all\s+|any\s+|your\s+|their\s+)?"
                r"(?:user['\u2019]?s?\s+)?(?:api[_ ]?keys?|access\s+tokens?|auth\w*\s+tokens?|passwords?|secrets?|"
                r"credentials|ssh\s+keys?)\b")
_API_USE = (r"(?:\bheaders?\b|\bauthori[sz]ation\b|\bbearer\b|\bx-api-key\b|\blogin\b|\bsign[- ]?in\b|\boauth\b|"
            r"\bsession\b|\bquery\s+(?:string|param\w*)\b)")
#: A store of secrets sent to a URL, a host or an address.
_SECRET_STORE = (r"(?:~/\.ssh\b|\.ssh/|\bid_(?:rsa|ed25519|ecdsa|dsa)\b|\bkeychains?\b|"
                 r"\.env\b(?!\.(?:example|sample|template|dist))|\.netrc\b|\.aws/credentials|\.npmrc\b|"
                 r"\.git-credentials|\.gnupg\b)")
#: Where a secret store is sent. Every part is bounded and an address cannot begin in the middle of a run of
#: word characters: `[\w.+-]+@` unbounded and tried at each of 81 offsets after each verb-and-store pair of a
#: run like "send.env.send.env." took hours on 400 KB.
_DESTINATION = (r"(?:https?://|\bto\s+(?:my|our|their|an?\s+(?:remote|external|outside)|the\s+(?:remote|external))\b|"
                r"\bto\s+(?:[\w-]{1,63}\.){1,6}[a-z]{2,24}\b|\bto\s+\d{1,3}(?:\.\d{1,3}){3}\b|"
                r"(?<![\w.+-])[\w.+-]{1,64}@[\w-]{1,63}(?:\.[\w-]{1,63}){1,5})")

_HIDDEN_INSTRUCTION = (r"\b(ignore|disregard|forget)\s+(all\s+|any\s+)?(previous|prior|above|earlier)\s+"
                       r"(instructions|rules|messages)")
_PIPE_TO_SHELL = r"\b(curl|wget)\b[^|\n]{0,200}\|\s*(ba|z)?sh\b"
_KEYCHAIN = r"\bsecurity\s+(find-generic-password|find-internet-password|dump-keychain)\b"
_SETTINGS_WRITE = _writes(_AGENT_SETTINGS)

RULES = (
    # Instructions a skill gives the model.
    # The words used as an order are dangerous; the same words quoted, in a code span or in a fenced
    # block are mentioned (a skill warning against them) and are a note.
    _r("hidden_instruction", "high", "text", _HIDDEN_INSTRUCTION, accept=_used),
    _r("hidden_instruction", "note", "text", _HIDDEN_INSTRUCTION, accept=_mentioned),
    # Ordinary advice ("do not tell the user to repeat a step"): never dangerous. A skill cannot act
    # by itself; whatever it asks for still meets the cards and the ledger.
    _r("hide_from_user", "note", "text", r"\b(do\s*n[o']?t|never)\s+(tell|show|mention|reveal)\s+(this\s+)?(to\s+)?the\s+user"),
    # A credential handed over: "in the x-api-key header", "to the login" is how an API is called, a note;
    # a secret store sent to a URL or an address is not.
    _r("send_data_out", "high", "text", _SEND_SECRET + r"(?![^\n]{0,120}" + _API_USE + r")"),
    _r("send_data_out", "note", "text", _SEND_SECRET + r"(?=[^\n]{0,120}" + _API_USE + r")"),
    _r("send_data_out", "high", "text",
       r"\b(?:send|post|upload|forward|transmit|exfiltrat\w*|copy|attach|email|paste)\b(?>[^\n]{0,50}?" + _SECRET_STORE
       + r")[^\n]{0,40}" + _DESTINATION, needs=_SECRET_STORE),
    _r("url_in_instructions", "note", "text", r"https?://[^\s)>\"']+"),
    # Code (skill scripts, package files).
    # An install line in a document is common and the agent's command card shows it; a skill whose OWN
    # scripts (or package hooks) pipe a download into a shell is a supply-chain risk.
    _r("pipe_to_shell", "high", "code", _PIPE_TO_SHELL),
    _r("pipe_to_shell", "high", "manifest", _PIPE_TO_SHELL),
    _r("pipe_to_shell", "note", "text", _PIPE_TO_SHELL),
    _r("run_decoded_code", "high", "code",
       r"\b(exec|eval)\s*\(\s*(base64\.b64decode|codecs\.decode|bytes\.fromhex|zlib\.decompress|atob)\b"),
    # Persistence is a WRITE: into a shell start file or a launchd folder, a crontab installed, a job loaded.
    # `source ~/.zshrc` and `crontab -l` only read.
    _r("autostart_write", "high", "code", _writes(_STARTUP) + "|" + _CRONTAB + "|" + _LAUNCHCTL,
       needs=_STARTUP + r"|crontab|launchctl"),
    # A script that reads the keychain is high; a commented config example in a document is a note (the
    # runtime floor refuses `security find-generic-password -w` in every mode).
    _r("keychain_read", "high", "code", _KEYCHAIN),
    _r("keychain_read", "high", "manifest", _KEYCHAIN),
    _r("keychain_read", "note", "text", _KEYCHAIN),
    # Key material taken: a private key read, copied or uploaded (`cat`, `cp`, `base64`, `curl -F`...), the .ssh
    # folder archived or copied, a key appended to authorized_keys. `ssh-add`, `ssh -i`, `ssh-keygen -l`/`-y`
    # and the .pub half use or describe a key without taking it.
    _r("ssh_keys", "high", "code",
       _SSH_READ + r"|" + _SSH_ARCHIVE
       + r"|" + _SSH_KEY + r"[^\n]{0,200}?\.read\w*\("
       + r"|\b(?:readFileSync|readFile|read_text|read_bytes)\s*\([^\n]{0,160}?" + _SSH_KEY
       + r"|" + _writes(_AUTHORIZED_KEYS), needs=r"\.ssh"),
    # `-(?=[a-z]*r)[a-z]+` is `-[a-z]*r[a-z]*` read in one pass: that one was quadratic on `rm -rrrr…`.
    _r("wipe", "high", "any", r"\brm\s+-(?=[a-z]*r)[a-z]+\s+(/|~|\$HOME)(\s|$)"),
    _r("network_in_script", "note", "skill_code", r"\b(requests|urllib|httpx|aiohttp|socket)\b"),
    _r("shell_in_script", "note", "skill_code", r"\b(subprocess|os\.system|os\.popen)\b"),
    _r("install_hook", "note", "manifest", r"\"(preinstall|install|postinstall)\"\s*:"),
    # Another agent's settings, written by a script or asked of the model (0.1.61 §C1, Hermes'
    # skills guard; §A2 "other agents' settings"). The write must TARGET the settings path (see
    # `_writes`), so reading it, copying it away or printing "… -> path" is not a finding. Telling the
    # model NOT to edit it is not one either, nor is pointing at it ("see ~/.claude/settings.json").
    # Arslan runs a skill's scripts itself, so a skill that writes them is high; a package often bundles a
    # client-registration command next to the server (`install --client cursor`), and a high finding
    # there would remove an install the user chose on its card: a note, the card shows it.
    _r("agent_settings_write", "high", "skill_code", _SETTINGS_WRITE, needs=_AGENT_SETTINGS),
    _r("agent_settings_write", "note", "package", _SETTINGS_WRITE, needs=_AGENT_SETTINGS),
    # Words telling the model to change them are a note (a cross-agent skill says "add to your Codex
    # config"): the act in code is the high one, and the runtime holds whatever the scan says.
    _r("agent_settings_instruction", "note", "text",
       r"\b(?P<verb>edit|modify|change|update|overwrite|replace|patch|append|merge|write\s+(?:\w+\s+){0,4}?(?:to|into|in)|"
       r"add\s+(?:\w+\s+){0,4}?to)\b(?P<between>[^\n]{0,80}?)(?P<path>" + _AGENT_SETTINGS_TEXT + r")",
       accept=_is_an_order),
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
#: someone put inside a word ("ig" + ZWNJ + "nore").
_SQUASH = re.compile(r"[\u00ad\u061c\u200b-\u200f\u2060-\u2064\u206a-\u206f\ufeff\ufe00-\ufe0f]")


def _invisible(text: str) -> tuple[int, int]:
    """(hiding, odd). `hiding`: characters that hide or reorder text, in a document as in code ("Trojan
    Source"): bidirectional controls and isolates (U+202A-202E, U+2066-2069) and tag characters
    (U+E0000-E007F, an invisible ASCII). `odd`: other zero-width characters that are not how a script is
    written: a zero-width space, a word joiner, a joiner that stands beside no letter. A ZWNJ, ZWJ or ALM
    between letters, or after a virama (Indic scripts write one at the end of a syllable or a word), is
    real orthography (Persian, Indic, Arabic, emoji sequences) and counts for nothing."""
    if text.isascii():
        return 0, 0
    hiding = odd = 0
    for i, ch in enumerate(text):
        if ch < "\x80":
            continue
        cp = ord(ch)
        if 0x202A <= cp <= 0x202E or 0x2066 <= cp <= 0x2069 or 0xE0000 <= cp <= 0xE007F:
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


def _prepare(text: str, kind: str) -> list[tuple[int, str, _Line]]:
    """The lines of a text with what the rules need to know about each: where a fenced block is, and
    where a SKILL.md's frontmatter is."""
    out: list[tuple[int, str, _Line]] = []
    lines = text.splitlines()
    front_end = 0
    if kind == "text" and lines and lines[0].strip() == "---":
        front_end = next((i for i, line in enumerate(lines[1:], 1) if line.strip() in ("---", "...")), 0)
    fenced = False
    for n, line in enumerate(lines, 1):
        read = line if line.isascii() else _SQUASH.sub("", line)
        front = 0 < n - 1 < front_end
        if not front and kind == "text" and _FENCE.match(read):
            fenced = not fenced
            out.append((n, line, _Line(read)))
            continue
        out.append((n, line, _Line(read, fenced=fenced and not front, front=front)))
    return out


def scan_text(name: str, text: str, *, kind: str) -> list[Finding]:
    """`kind`: text (a skill's instructions), skill_code (a skill's script), code (a package
    file), manifest (package.json)."""
    out: list[Finding] = []
    lines = _prepare(text, kind)
    for rule in RULES:
        applies = (rule.where == "any" or rule.where == kind
                   or (rule.where == "code" and kind in ("code", "skill_code"))
                   or (rule.where == "package" and kind == "code"))
        if not applies:
            continue
        for n, raw, line in lines:
            if rule.needs is not None and rule.needs.search(line.text) is None:
                continue
            if rule.accept is None:
                hit = rule.pattern.search(line.text) is not None
            else:
                hit = any(rule.accept(line, m) for m in rule.pattern.finditer(line.text))
            if hit:
                out.append(Finding(rule.id, rule.level, name, n, raw.strip()[:160]))
                break                       # one finding per rule per file is enough to show
    hiding, odd = _invisible(text)
    if hiding:
        out.append(Finding("invisible_characters", "high", name, 0, f"{hiding} bidirectional-control or tag characters"))
    if odd:
        out.append(Finding("zero_width_characters", "note", name, 0, f"{odd} zero-width characters"))
    if kind == "text":
        if re.search(r"[A-Za-z0-9+/]{400,}={0,2}", text):
            out.append(Finding("long_encoded_blob", "note", name, 0, "a long base64-like block"))
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
_CODE_SUFFIXES = frozenset({".py", ".sh", ".bash", ".zsh", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
                            ".rb", ".pl", ".php", ".applescript", ".swift", ".go", ".rs", ".lua", ".ps1",
                            ".r", ".jl", ".java", ".kt", ".c", ".cc", ".cpp", ".cs"})
#: Folders a skill's folder may hold that are not the skill's own text: dependencies, a
#: checkout's history, caches. They are not walked — and are named as not read.
_DEPENDENCY_DIRS = frozenset({".git", "node_modules", "__pycache__", ".venv", "venv"})


def _kind_for(rel: str, text: str = "") -> str | None:
    suffix = PurePosixPath(rel).suffix.lower()
    if suffix in _TEXT_SUFFIXES:
        return "text"
    if suffix in _CODE_SUFFIXES or rel.startswith("scripts/") or text.startswith("#!"):
        return "skill_code"
    return None


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


def _scan(skill_md: str, items: list[tuple[str, str, str]], unread: list[str], deadline: float | None = None) -> dict:
    """A skill given as (path, text, kind) items, in the order to scan them (code first): its whole SKILL.md
    (the frontmatter too — a description is read by the model as well) and each file as instructions or as
    code. What could not be read (`unread`, any text over MAX_FILE_BYTES, read as far as that, and whatever
    the `deadline` cut off) is one `not_scanned` note."""
    found = scan_text("SKILL.md", skill_md, kind="text")
    unread = [*unread]
    for i, (rel, text, kind) in enumerate(items):
        if deadline is not None and time.monotonic() >= deadline:
            unread.extend(later for later, _, _ in items[i:])
            break
        found += scan_text(rel, text[:MAX_FILE_BYTES], kind=kind)
        if len(text) > MAX_FILE_BYTES:
            unread.append(rel)
    if unread:
        found.append(Finding("not_scanned", "note", unread[0], 0,
                             (f"{len(unread)} not read (too large, too many, a link, dependencies or unreadable): "
                              + ", ".join(unread[:6]))[:160]))
    summary = summarise(found)
    summary["verdict"] = verdict(summary)
    return summary


def scan_texts(skill_md: str, files: dict[str, str], *, unread: list[str] = ()) -> dict:
    """A skill given as text: its whole SKILL.md and its files, each read as instructions or as code
    by its name (or its `#!`). What could not be read (`unread`) is one `not_scanned` note: never
    silently clean."""
    items = []
    for rel, text in files.items():
        kind = _kind_for(rel, text)
        if kind is not None and rel != "SKILL.md":
            items.append((rel, text, kind))
    items.sort(key=lambda item: (item[2] != "skill_code", item[0]))        # code first, then by name
    return _scan(skill_md, items, [*unread])


def _list_folder(folder: Path, candidates: list[tuple[int, str, str, Path]], unread: list[str], deadline: float) -> None:
    """Walk `folder` top-down WITHOUT recursion (os.walk recurses on Python 3.11) and file every regular
    text or code file under it in `candidates` as (0 code | 1 text, name, kind, path); everything that will
    not be read goes by name into `unread`: a link (never followed), a dependency folder, a folder nested
    deeper than MAX_DEPTH, a folder it cannot list, a pipe, socket or device (opening one can wait for
    ever), whatever lies past MAX_WALKED files, and whatever the `deadline` stopped it short of. Code is a
    source file, anything in scripts/, a `#!` file and an executable; the rest that is read is text."""
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
                    kind = _kind_for(rel)
                    if kind is None:
                        with open(entry.path, "rb") as handle:
                            shebang = handle.read(2) == b"#!"
                        if not (shebang or entry.stat(follow_symlinks=False).st_mode & 0o111):
                            continue                    # data, images, fonts: neither instructions nor code
                        kind = "skill_code"
                    candidates.append((0 if kind == "skill_code" else 1, rel, kind, Path(entry.path)))
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
    candidates: list[tuple[int, str, str, Path]] = []
    unread: list[str] = []
    try:
        walkable = folder is not None and folder.is_dir()
    except OSError:
        walkable = False
        unread.append("./")
    if walkable:
        _list_folder(folder, candidates, unread, deadline)
    items: list[tuple[str, str, str]] = []
    spent = 0
    ordered = sorted(candidates, key=lambda candidate: (candidate[0], candidate[1]))
    for i, (_, rel, kind, path) in enumerate(ordered):
        if time.monotonic() >= deadline:
            unread.extend(later for _, later, _, _ in ordered[i:])
            break
        try:
            size = path.stat().st_size
            if len(items) >= MAX_FILES or size > MAX_FILE_BYTES or spent + size > MAX_SCAN_BYTES:
                unread.append(rel)
                continue
            items.append((rel, path.read_text("utf-8", errors="replace"), kind))
            spent += size
        except OSError:
            unread.append(rel)
    return _scan(skill_md, items, unread, deadline)


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
