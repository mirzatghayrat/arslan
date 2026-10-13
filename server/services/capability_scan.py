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
"""
from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

MAX_FILE_BYTES = 400_000
MAX_FILES = 400
MAX_FINDINGS = 20
#: A folder scan reads at most this much in all (64 MB: the largest archive Arslan downloads). 400
#: files of 400 KB would be 160 MB; what does not fit is named in the `not_scanned` note.
MAX_SCAN_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class Rule:
    id: str
    level: str          # high | note
    where: str          # text (instructions) | code
    pattern: re.Pattern


def _r(rule_id, level, where, pattern, flags=re.I):
    return Rule(rule_id, level, where, re.compile(pattern, flags))


#: Other agents' settings files (§A2): Hermes, Claude Code, Codex, Cursor, OpenClaw.
_AGENT_SETTINGS = r"(?:\.hermes/|\.claude/settings|\.claude\.json|\.codex/config|\.cursor/mcp\.json|\.openclaw/)"

RULES = (
    # Instructions a skill gives the model.
    _r("hidden_instruction", "high", "text",
       r"\b(ignore|disregard|forget)\s+(all\s+|any\s+)?(previous|prior|above|earlier)\s+(instructions|rules|messages)"),
    _r("hide_from_user", "high", "text",
       r"\b(do\s*n[o']?t|never)\s+(tell|show|mention|reveal)\s+(this\s+)?(to\s+)?the\s+user"),
    _r("send_data_out", "high", "text",
       # The secret right after the verb ("send the user's API key"): API docs say "POST
       # /v1/messages/count_tokens", which a looser rule flagged (anthropics/skills claude-api).
       r"\b(send|post|upload|forward|transmit|exfiltrat\w*)\s+(the\s+|all\s+|any\s+|your\s+|their\s+)?"
       r"(user'?s?\s+)?(api[_ ]?keys?|access\s+tokens?|auth\w*\s+tokens?|passwords?|secrets?|credentials|ssh\s+keys?)\b"),
    _r("url_in_instructions", "note", "text", r"https?://[^\s)>\"']+"),
    # Code (skill scripts, package files).
    _r("pipe_to_shell", "high", "any", r"\b(curl|wget)\b[^|\n]{0,200}\|\s*(ba|z)?sh\b"),
    _r("run_decoded_code", "high", "code",
       r"\b(exec|eval)\s*\(\s*(base64\.b64decode|codecs\.decode|bytes\.fromhex|zlib\.decompress|atob)\b"),
    _r("autostart_write", "high", "code",
       r"(LaunchAgents|LaunchDaemons|\.bash_profile|\.bashrc|\.zshrc|\.zprofile|crontab\s+-)"),
    _r("keychain_read", "high", "any", r"\bsecurity\s+(find-generic-password|find-internet-password|dump-keychain)\b"),
    _r("ssh_keys", "high", "code", r"\.ssh/(id_[a-z0-9]+|authorized_keys)"),
    # `-(?=[a-z]*r)[a-z]+` is `-[a-z]*r[a-z]*` read in one pass: that one was quadratic on `rm -rrrr…`.
    _r("wipe", "high", "any", r"\brm\s+-(?=[a-z]*r)[a-z]+\s+(/|~|\$HOME)(\s|$)"),
    _r("network_in_script", "note", "skill_code", r"\b(requests|urllib|httpx|aiohttp|socket)\b"),
    _r("shell_in_script", "note", "skill_code", r"\b(subprocess|os\.system|os\.popen)\b"),
    _r("install_hook", "note", "manifest", r"\"(preinstall|install|postinstall)\"\s*:"),
    # Another agent's settings, written by a script or asked of the model (0.1.61 §C1, Hermes'
    # skills guard; §A2 "other agents' settings"). The write must TARGET the settings path — a
    # redirect, tee, cp/mv with it last, sed -i, open(…, "w"|"a"), write_text — so reading it,
    # copying it away or printing "… -> path" is not a finding. Telling the model NOT to edit it
    # is not one either.
    #
    # Every quantifier is bounded (a path prefix 120 characters, the rest of a command 200): a
    # greedy `[^\s'"]*` or `[^\n]*` re-read the line from every `>`, `cp` or `tee` in it, so one
    # 400 KB line (a minified bundle, or a hostile file) held the scan for 15 minutes.
    _r("agent_settings_write", "high", "code",
       r"(?:>>?\s*|\btee\s+(?:-a\s+)?)['\"]?[^\s'\"]{0,120}" + _AGENT_SETTINGS
       + r"|\b(?:cp|mv)\b[^\n]{0,200}\s['\"]?[^\s'\"]{0,120}" + _AGENT_SETTINGS
       + r"[^\s'\"]{0,120}['\"]?\s*(?:$|[;&|)])"
       + r"|\bsed\s+-i\S*\s[^\n]{0,200}" + _AGENT_SETTINGS
       + r"|" + _AGENT_SETTINGS
       + r"[^\n]{0,200}?(?:['\"]\)?\s*,\s*['\"][wa]b?\+?['\"]|\.write_(?:text|bytes)\(|\.open\(\s*['\"][wa])"),
    _r("agent_settings_instruction", "high", "text",
       r"(?<!\bnot\s)(?<!n't\s)(?<!never\s)"
       r"\b(edit|modify|change|update|overwrite|write\s+to|add\s+(?:it\s+|this\s+\w+\s+)?to)\b[^\n]{0,80}"
       r"(~/\.hermes/|~/\.claude/settings|~/\.claude\.json|~/\.codex/config|~/\.cursor/mcp\.json|~/\.openclaw/)"),
)

_INVISIBLE = {"Cf"}          # format characters: zero-width, bidi overrides
#: Format characters that only shape text: the byte-order mark, a soft hyphen and the
#: left-to-right/right-to-left marks (U+FEFF, U+00AD, U+200E, U+200F).
_SHAPING = frozenset("\ufeff\u00ad\u200e\u200f")


def _invisible(text: str) -> int:
    """Format characters that can hide text (zero-width, bidi overrides, tags). 0.1.61: whole
    folders and other agents' skills are read now, so a zero-width joiner between two emoji
    (a woman technologist, a rainbow flag: U+200D only joins them) and the shaping marks are
    not counted."""
    count = 0
    for i, ch in enumerate(text):
        if unicodedata.category(ch) not in _INVISIBLE or ch in _SHAPING:
            continue
        if ch == "\u200d" and 0 < i < len(text) - 1:
            before, after = text[i - 1], text[i + 1]
            if (unicodedata.category(before) in ("So", "Sk") or before == "\ufe0f") \
                    and unicodedata.category(after) == "So":
                continue
        count += 1
    return count


@dataclass
class Finding:
    rule: str
    level: str
    file: str
    line: int
    excerpt: str


def _lines(text: str):
    for n, line in enumerate(text.splitlines(), 1):
        yield n, line


def scan_text(name: str, text: str, *, kind: str) -> list[Finding]:
    """`kind`: text (a skill's instructions), skill_code (a skill's script), code (a package
    file), manifest (package.json)."""
    out: list[Finding] = []
    for rule in RULES:
        applies = (rule.where == "any" or rule.where == kind
                   or (rule.where == "code" and kind in ("code", "skill_code")))
        if not applies:
            continue
        for n, line in _lines(text):
            if rule.pattern.search(line):
                out.append(Finding(rule.id, rule.level, name, n, line.strip()[:160]))
                break                       # one finding per rule per file is enough to show
    if kind == "text":
        hidden = _invisible(text)
        if hidden:
            out.append(Finding("invisible_characters", "high", name, 0, f"{hidden} invisible characters"))
        if re.search(r"[A-Za-z0-9+/]{400,}={0,2}", text):
            out.append(Finding("long_encoded_blob", "note", name, 0, "a long base64-like block"))
    return out


def summarise(findings: list[Finding]) -> dict:
    """The level is read from EVERY finding; the list kept is cut to MAX_FINDINGS with the high
    ones first, so a pile of notes can never push a high finding out (0.1.61: whole folders)."""
    level = "blocked" if any(f.level == "high" for f in findings) else ("notes" if findings else "clean")
    kept = sorted(findings, key=lambda f: f.level != "high")[:MAX_FINDINGS]
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
    turned on after reading its findings stays on while nothing new turns up (Ruling C)."""
    def key(scan):
        return sorted((f.get("rule"), f.get("file"), f.get("excerpt")) for f in (scan or {}).get("findings") or [])
    return key(a) == key(b)


def scan_texts(skill_md: str, files: dict[str, str], *, unread: list[str] = ()) -> dict:
    """A skill given as text: its whole SKILL.md (the frontmatter too — a description is read by the
    model as well) and its files, each read as instructions or as code by its name (or its `#!`).
    What could not be read (`unread`, and any file here over MAX_FILE_BYTES, read as far as that) is
    one `not_scanned` note: never silently clean."""
    found = scan_text("SKILL.md", skill_md, kind="text")
    unread = [*unread]
    for rel, text in sorted(files.items()):
        kind = _kind_for(rel, text)
        if kind is not None and rel != "SKILL.md":
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


def _is_link(path: Path) -> bool:
    """Whether `path` is a link, or cannot even be asked (a name the disk refuses): not read either way."""
    try:
        return path.is_symlink()
    except OSError:
        return True


def scan_skill_folder(folder: Path | None, skill_md: str) -> dict:
    """A skill's folder (§C1): its SKILL.md and every text or code file under it — at most
    MAX_FILES files of at most MAX_FILE_BYTES each, MAX_SCAN_BYTES in all. Links are never followed
    and dependency folders never walked; those, a pipe or device (opening one can wait for ever), a
    folder or file that cannot be opened, and whatever is over the limits are named in a note.
    A disk error never escapes: what cannot be read is named, never silently clean."""
    files: dict[str, str] = {}
    unread: list[str] = []
    spent = 0

    def relative(path) -> str:
        try:
            return Path(path).relative_to(folder).as_posix()
        except ValueError:
            return str(path)

    def unlistable(error: OSError) -> None:         # os.walk skips a folder it cannot list: say so
        unread.append(relative(error.filename) + "/" if error.filename else "./")

    try:
        walkable = folder is not None and folder.is_dir()
    except OSError:
        walkable = False
        unread.append("./")
    if walkable:
        for dirpath, dirnames, filenames in os.walk(folder, followlinks=False, onerror=unlistable):
            here = Path(dirpath)
            walked = []
            for name in sorted(dirnames):
                if name in _DEPENDENCY_DIRS or _is_link(here / name):
                    unread.append(relative(here / name) + "/")
                else:
                    walked.append(name)
            dirnames[:] = walked
            for name in sorted(filenames):
                path = here / name
                rel = relative(path)
                if rel == "SKILL.md":
                    continue
                try:
                    if path.is_symlink() or not path.is_file():
                        unread.append(rel)
                        continue
                    kind = _kind_for(rel)
                    if kind is None:
                        with path.open("rb") as handle:
                            if handle.read(2) != b"#!":
                                continue                # data, images, fonts: neither instructions nor code
                    size = path.stat().st_size
                    if len(files) >= MAX_FILES or size > MAX_FILE_BYTES or spent + size > MAX_SCAN_BYTES:
                        unread.append(rel)
                        continue
                    files[rel] = path.read_text("utf-8", errors="replace")
                    spent += size
                except OSError:
                    unread.append(rel)
    return scan_texts(skill_md, files, unread=unread)


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
