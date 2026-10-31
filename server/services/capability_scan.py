"""Looking for known dangerous patterns in what a capability brings (0.1.57 §6).

Deterministic and honest about its reach: it finds KNOWN dangerous ways of writing things —
hidden instructions in a skill, a script that phones home or runs a shell, code that fetches
and runs more code, or writes to where macOS starts programs — and it cannot prove anything is
safe. That is why everything installed still runs in the sandbox. A "high" finding blocks the
install; a "note" is shown on the card and in the dossier.

What is read: a skill's SKILL.md, scripts and references; a package's OWN files (not the
whole dependency tree — HTTP clients there phone home by design and would drown the signal).
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path

MAX_FILE_BYTES = 400_000
MAX_FILES = 400
MAX_FINDINGS = 20


@dataclass(frozen=True)
class Rule:
    id: str
    level: str          # high | note
    where: str          # text (instructions) | code
    pattern: re.Pattern


def _r(rule_id, level, where, pattern, flags=re.I):
    return Rule(rule_id, level, where, re.compile(pattern, flags))


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
    _r("wipe", "high", "any", r"\brm\s+-[a-z]*r[a-z]*f?\s+(/|~|\$HOME)(\s|$)"),
    _r("network_in_script", "note", "skill_code", r"\b(requests|urllib|httpx|aiohttp|socket)\b"),
    _r("shell_in_script", "note", "skill_code", r"\b(subprocess|os\.system|os\.popen)\b"),
    _r("install_hook", "note", "manifest", r"\"(preinstall|install|postinstall)\"\s*:"),
)

#: UNI1b-3 (the user's 3A, 2026-11-01): what the scan blocks in a skill's text, and nothing else hidden. Unicode Tag
#: characters (U+E0000-E007F, text no reader sees: the hidden-text smuggling vector), but those of the three RGI
#: subdivision flags; and the bidi controls, U+202A-202E (embeddings and overrides) and U+2066-2069
#: (isolates), which make text read in another order than it is stored (Trojan Source) and which GitHub warns about
#: as bidirectional text. Every other character that shows nothing (a zero-width space, a soft hyphen, a word
#: joiner, a run of variation selectors) is counted and marked wherever the skill is shown (UNI1b's
#: `untrusted.hidden_summary`), never blocked, as GitHub's hidden-character warning does. Explicit code points,
#: never the Unicode database (#586 review F5).
_BLOCKED = ((0x202A, 0x202E), (0x2066, 0x2069), (0xE0000, 0xE007F))
HIDDEN_RULE = "tag_or_bidi_characters"


def _invisible(text: str) -> int:
    """How many Tag characters (outside an RGI flag) and bidi controls the text holds, each one counted."""
    from server.orchestrator import untrusted
    text = untrusted.TAG_FLAG.sub("", text)
    return sum(1 for ch in text if any(lo <= ord(ch) <= hi for lo, hi in _BLOCKED))


_SHOWS_NOTHING: re.Pattern | None = None


def _keyword_text(text: str) -> str:
    """#563 review (cross-PR): what the keyword rules read. Every character that shows nothing is taken out first:
    UNI1b's table (zero-width space, word joiner, soft hyphen, variation selectors, tags, the blank braille
    pattern...), ZWNJ and ZWJ, the direction marks and the bidi controls. Until UNI1b-3 a zero-width space that
    split a keyword (`cu`, U+200B, `rl ... | sh`) was blocked on its own; now it is only counted, so the rules read
    the word it splits. Only for matching: the text is stored as it is, and what it hides is still counted."""
    global _SHOWS_NOTHING
    if _SHOWS_NOTHING is None:
        from server.orchestrator import untrusted
        ranges = (*untrusted._HIDDEN, (0x200C, 0x200F), (0x061C, 0x061C), *_BLOCKED[:2])
        _SHOWS_NOTHING = re.compile("[" + "".join(f"{re.escape(chr(lo))}-{re.escape(chr(hi))}" for lo, hi in ranges)
                                    + "]")
    return _SHOWS_NOTHING.sub("", text)


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
    words = _keyword_text(text)
    for rule in RULES:
        applies = (rule.where == "any" or rule.where == kind
                   or (rule.where == "code" and kind in ("code", "skill_code")))
        if not applies:
            continue
        for n, line in _lines(words):
            if rule.pattern.search(line):
                out.append(Finding(rule.id, rule.level, name, n, line.strip()[:160]))
                break                       # one finding per rule per file is enough to show
    if kind in ("text", "skill_code"):
        # #607 review K3 (⓪Plan): a skill's scripts too. Trojan Source in code is what the bidi rule is for, and
        # GitHub warns about it there. A package's own files are not held to it.
        hidden = _invisible(text)
        if hidden:
            out.append(Finding(HIDDEN_RULE, "high", name, 0, f"{hidden} tag or bidi control characters"))
    if kind == "text":
        if re.search(r"[A-Za-z0-9+/]{400,}={0,2}", words):
            out.append(Finding("long_encoded_blob", "note", name, 0, "a long base64-like block"))
    return out


def summarise(findings: list[Finding]) -> dict:
    """The level from every finding, then at most MAX_FINDINGS of them, the high ones first: notes can never
    push a high finding off the list, or the level down to "notes" (#539 review 1)."""
    level = "blocked" if any(f.level == "high" for f in findings) else ("notes" if findings else "clean")
    shown = sorted(findings, key=lambda f: f.level != "high")[:MAX_FINDINGS]
    return {"level": level, "findings": [asdict(f) for f in shown]}


def scan_skill(skill_md: str, scripts: dict[str, str], references: dict[str, str]) -> dict:
    """`skill_md` is the whole SKILL.md as fetched, its frontmatter's name and description included: under the
    user's D2 every skill's name and description reach the model unframed (#539 review 4)."""
    found = scan_text("SKILL.md", skill_md, kind="text")
    for name, text in references.items():
        found += scan_text(name, text, kind="text")
    for name, text in scripts.items():
        found += scan_text(name, text, kind="skill_code")
    return summarise(found)


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
