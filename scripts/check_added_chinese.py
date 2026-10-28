"""Fail when a change ADDS Chinese on a line that should be English (card LANG1).

The rule is docs/sessions.md §6 (user, 2026-10-28): everything written to
GitHub is English. About 250 files on main already hold Chinese written before
that date, and it is not rewritten, so this check never reads whole files. It
reads only the lines a change adds (`git diff <base>...<head>`), and a line
fails when it holds a Han character that none of the exceptions below covers.

Old Chinese is not new: when every run of Han characters on an added line also
appears on a line the same diff removes from the same file (or from the file it
was renamed from), the line is an edit or a move of pre-rule text (an English
note appended to an old Chinese table row, say) and passes.

Exceptions, in the order they are tried:

1. Translation files and tables, and the multilingual docs site
   (TRANSLATION_PATHS): every added line passes.
2. Data that has to match Chinese input, and tests, evals and fixtures whose
   input is Chinese (DATA_PATHS): code and data lines pass; a comment line
   (by file type: `#`, `//`, `/*`, `*`, `<!--`) is still held to rule 3,
   because comments are English everywhere.
3. Quoted Chinese inside an English sentence: the line passes when every Han
   character sits inside a quoted span ("", '', ``, “”, ‘’, 「」, 『』) or a
   session name such as ④参谋, and what is left outside the quotes still has
   an English word (3+ ASCII letters). On a code line (not a comment) in a
   code file, a quoted span holding Chinese sentence punctuation (，。！？；：、)
   does not count as a quote: a Chinese sentence in a string literal is copy
   or a prompt, and belongs in a translation table.
4. Escape hatches for a case no exception names:
   - the marker `lang-check: allow` anywhere on the line (in a comment of the
     file's own syntax, ideally with a reason after it);
   - a path glob in ALLOWLIST_FILE, one per line, each with a `# reason`; an
     entry that would cover most of the repository (`**`, `**/*.md`,
     `docs/**`) is an error. Every line an escape hatch lets through is
     printed in the log.
   CI runs the base commit's copy of this script and of the allowlist first,
   so a change cannot loosen the check it is judged by: a new exception or
   allowlist entry lands in its own PR before the Chinese it allows.

Commit messages and PR text are not files and are not checked here.

    python3 scripts/check_added_chinese.py --base origin/main [--head HEAD]

Exit 0 when nothing fails, 1 when an added line fails, 2 on a usage, git or
allowlist error. Under GitHub Actions each failure is also printed as an
`::error file=…,line=…::` annotation so it shows on the PR's diff.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import re
import subprocess
import sys
from dataclasses import dataclass

ALLOWLIST_FILE = ".github/lang-check-allow.txt"
MARKER = "lang-check: allow"

# CJK Unified Ideographs (+ Extension A, compatibility, and the supplementary
# planes B–F). Kana and Hangul are not Chinese and are not checked.
HAN = re.compile("[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0002fa1f]")
# Chinese sentence punctuation: full-width comma, full stop, exclamation and
# question marks, semicolon, colon, and the ideographic comma.
SENTENCE_PUNCT = re.compile("[\uff0c\u3002\uff01\uff1f\uff1b\uff1a\u3001]")
ENGLISH_WORD = re.compile(r"[A-Za-z]{3,}")

# Quoted spans. A straight single quote only opens or closes when it is not
# part of a word, so the apostrophes in "don't … it's" are not a span.
QUOTED = re.compile(
    r'"[^"\n]*"'
    r"|(?<![A-Za-z0-9])'[^'\n]*'(?![A-Za-z0-9])"
    r"|`[^`\n]*`"
    "|\u201c[^\u201d\n]*\u201d"  # curly double quotes
    "|\u2018[^\u2019\n]*\u2019"  # curly single quotes
    "|\u300c[^\u300d\n]*\u300d"  # corner brackets
    "|\u300e[^\u300f\n]*\u300f"  # white corner brackets
)
# Session names: a circled digit (⓪, ①–⑳) followed by a Han name of at most
# three characters, such as ④参谋. A longer run is not a name.
SESSION_NAME = re.compile("[\u24ea\u2460-\u2473][\u3400-\u4dbf\u4e00-\u9fff]{1,3}(?![\u3400-\u4dbf\u4e00-\u9fff])")

# §6 "translation files and tables" and "the multilingual docs-site".
TRANSLATION_PATHS = (
    "web/src/locales/**",
    "desktop/src-tauri/native_menu_messages.json",
    "desktop/src-tauri/native_messages.json",
    "desktop/src-tauri/recovery_messages.json",
    "desktop/src-tauri/locales/**",
    "**/*.xcstrings",
    "**/*.lproj/**",
    "server/services/runtime_messages.py",
    "server/services/provider_error_messages.py",
    "server/services/project_templates.py",
    "README.*.md",
    "docs-site/**",
)
# §6 "data that has to match Chinese input" and "tests, evals and fixtures
# whose input is Chinese". Markdown here is prose (a README in evals/ is a
# doc), so it is only data inside a fixtures directory.
DATA_PATHS = (
    "arslan/companion/content_policy.py",
    "desktop/hands/policy.json",
    "tests/**",
    "**/__tests__/**",
    "**/*.test.ts",
    "**/*.test.tsx",
    "desktop/bridge/Tests/**",
    "evals/**",
    "scripts/kernel_bench/**",
    "**/fixtures/**",
)

_HASH = ("#",)
_SLASH = ("//", "/*", "*")
COMMENT_PREFIXES = {
    **{s: _HASH for s in (".py", ".pyi", ".sh", ".zsh", ".bash", ".toml", ".yml", ".yaml", ".cfg", ".ini")},
    **{s: _SLASH for s in (".ts", ".tsx", ".js", ".jsx", ".cjs", ".mjs", ".rs", ".swift", ".m", ".h", ".c", ".go", ".kt", ".java", ".scss")},
    ".css": ("/*", "*"),
    ".sql": ("--",),
    ".md": ("<!--",),
    ".html": ("<!--",),
    ".xml": ("<!--",),
    ".svg": ("<!--",),
}
# Files where a line that is not a comment is code or data, not prose.
CODE_SUFFIXES = (set(COMMENT_PREFIXES) - {".md", ".html", ".xml", ".svg"}) | {".json"}


def glob_regex(pattern: str) -> re.Pattern[str]:
    """A path glob where `*` stays inside one directory and `**` crosses them."""
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def _matches(path: str, patterns) -> bool:
    return any(glob_regex(p).match(path) for p in patterns)


def _suffix(path: str) -> str:
    return pathlib.PurePosixPath(path).suffix.lower()


def path_kind(path: str) -> str:
    """'translation', 'data' or 'english' for a repo-relative path."""
    if _matches(path, TRANSLATION_PATHS):
        return "translation"
    if _matches(path, DATA_PATHS):
        if _suffix(path) == ".md" and "/fixtures/" not in f"/{path}":
            return "english"
        return "data"
    return "english"


def is_comment(path: str, line: str, *, docstrings: bool = True) -> bool:
    """A whole-line comment, or (Python, when asked) a line that opens a docstring."""
    suffix = _suffix(path)
    prefixes = COMMENT_PREFIXES.get(suffix, ())
    if docstrings and suffix in (".py", ".pyi"):
        prefixes += ('"""', "'''")
    return bool(prefixes) and line.lstrip().startswith(prefixes)


_TRAILING = {"#": re.compile(r"#.*"), "//": re.compile(r"//.*")}


def trailing_comment(path: str, line: str) -> str | None:
    """The comment after code on the line, found outside quoted spans."""
    prefixes = COMMENT_PREFIXES.get(_suffix(path), ())
    lead = "#" if "#" in prefixes else "//" if "//" in prefixes else None
    if lead is None:
        return None
    m = _TRAILING[lead].search(QUOTED.sub(lambda q: " " * len(q.group(0)), line))
    return line[m.start():] if m else None


def quoted_english_ok(line: str, *, code_line: bool) -> bool:
    """True when every Han character is quoted (or a session name) inside English."""
    rest = SESSION_NAME.sub(" ", line)

    def strip(match: re.Match[str]) -> str:
        span = match.group(0)
        if code_line and HAN.search(span) and SENTENCE_PUNCT.search(span):
            return span  # a Chinese sentence in a string literal: not a quote
        return " "

    rest = QUOTED.sub(strip, rest)
    return not HAN.search(rest) and bool(ENGLISH_WORD.search(rest))


HAN_RUN = re.compile(HAN.pattern + "+")


def is_old_chinese(line: str, removed: list[str]) -> bool:
    """One removed line of the same file holds every Han run of this line as a
    whole run: an edit around old Chinese, not new Chinese. A run that is only a
    substring (a new phrase cut from an old paragraph) does not count."""
    runs = set(HAN_RUN.findall(line))
    return any(runs <= set(HAN_RUN.findall(r)) for r in removed)


def line_fails(path: str, line: str, removed: list[str] | None = None, *, honour_marker: bool = True) -> bool:
    if not HAN.search(line) or (honour_marker and MARKER in line):
        return False
    if removed and is_old_chinese(line, removed):
        return False
    kind = path_kind(path)
    if kind == "translation":
        return False
    # In tests and data a line that opens with a triple quote is usually
    # multi-line input (a model reply, a fixture), not a docstring.
    comment = is_comment(path, line, docstrings=kind != "data")
    if _suffix(path) in (".py", ".pyi"):
        # A triple quote would read as `""` plus an open quote.
        line = line.replace('"""', " ").replace("'''", " ")
    if kind == "data" and not comment:
        # Data passes; a comment after the data is still English.
        tail = trailing_comment(path, line)
        return bool(tail and HAN.search(tail)) and not quoted_english_ok(tail, code_line=False)
    return not quoted_english_ok(line, code_line=_suffix(path) in CODE_SUFFIXES and not comment)


@dataclass(frozen=True)
class Added:
    path: str
    line: int
    text: str


_ESCAPES = {"a": "\a", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v", '"': '"', "\\": "\\"}


def _unquote(name: str) -> str:
    """A path as git prints it on a `+++ ` line. Git C-quotes a name holding `"`,
    a backslash or a control character, and ends a name holding a space with a tab."""
    if not name.startswith('"'):
        return name[:-1] if name.endswith("\t") else name
    raw, i, body = bytearray(), 1, name.rstrip("\t")
    while i < len(body) - 1:
        c = body[i]
        if c == "\\" and i + 1 < len(body) - 1:
            nxt = body[i + 1]
            if nxt in "01234567":
                raw.append(int(body[i + 1:i + 4], 8))
                i += 4
                continue
            raw += _ESCAPES.get(nxt, nxt).encode()
            i += 2
            continue
        raw += c.encode()
        i += 1
    return raw.decode("utf-8", errors="replace")


_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def parse_diff(diff: str) -> tuple[list[Added], dict[str, list[str]]]:
    """Added lines of a `git diff -U0` with their new-file line numbers, and per
    file the lines removed from it. Only the same file's removed lines can make
    a line "old Chinese": a rename pairs the old and new path (`-M`), so a moved
    file still counts, but deleting one file excuses nothing in another."""
    added: list[Added] = []
    removed: dict[str, list[str]] = {}
    path: str | None = None
    lineno = 0
    in_header = False  # "--- "/"+++ " are headers only here; in a hunk they are content
    for raw in diff.split("\n"):
        if raw.startswith("diff --git "):
            in_header, path = True, None
        elif in_header and raw.startswith("+++ "):
            target = _unquote(raw[4:])
            path = target[2:] if target.startswith("b/") else None  # /dev/null: a deletion
        elif in_header and not raw.startswith("@@"):
            continue
        elif raw.startswith("@@"):
            in_header = False
            m = _HUNK.match(raw)
            lineno = int(m.group(1)) if m else 0
        elif path is None:
            continue
        elif raw.startswith("+"):
            added.append(Added(path, lineno, raw[1:]))
            lineno += 1
        elif raw.startswith("-"):
            removed.setdefault(path, []).append(raw[1:])
    return added, removed


_WILDCARD = re.compile(r"[*?\[]")


def too_broad(glob: str) -> bool:
    """An entry names one file, or has two directory levels before its first
    wildcard. `*`, `**`, `**/*.md` or `docs/**` would switch the check off for
    much of the repository, and the PR adding the entry would pass its own check."""
    m = _WILDCARD.search(glob)
    return m is not None and glob[: m.start()].count("/") < 2


def load_allowlist(text: str, source: str = ALLOWLIST_FILE) -> tuple[list[str], list[str]]:
    """(patterns, errors). Every entry needs a `# reason` and must not be too broad."""
    patterns, errors = [], []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        glob, sep, reason = line.partition("#")
        glob = glob.strip()
        if not sep or not reason.strip() or not glob:
            errors.append(f"{source}:{n}: an entry is '<path glob>  # <reason>'")
        elif too_broad(glob):
            errors.append(
                f"{source}:{n}: '{glob}' is too broad; name a file, or a directory two levels deep "
                "before any wildcard (for example docs/archive/**)"
            )
        else:
            patterns.append(glob)
    return patterns, errors


def check(added: list[Added], allowlist: list[str], removed: dict[str, list[str]]) -> tuple[list[Added], list[str]]:
    """(failing lines, one log line per line an escape hatch let through)."""
    found: list[Added] = []
    waived: list[str] = []
    for a in added:
        if not line_fails(a.path, a.text, removed.get(a.path, []), honour_marker=False):
            continue
        entry = next((p for p in allowlist if glob_regex(p).match(a.path)), None)
        if entry is not None:
            waived.append(f"{a.path}:{a.line}: allowed by the allowlist entry '{entry}'")
        elif MARKER in a.text:
            waived.append(f"{a.path}:{a.line}: allowed by the '{MARKER}' marker")
        else:
            found.append(a)
    return found, waived


def _git(*args: str, binary: bool = False):
    out = subprocess.run(["git", "-c", "core.quotePath=false", *args], check=True, capture_output=True).stdout
    return out if binary else out.decode("utf-8", errors="replace")


_DIFF = ("diff", "-U0", "--no-color", "--no-ext-diff", "--no-textconv")


def read_diff(base: str, head: str) -> str:
    """`git diff -U0 -M base...head`, plus, diffed as text, every file git calls
    binary only because of an attribute (`*.md -diff` in .gitattributes would
    otherwise hide a whole file type). A file is really binary, as git itself
    decides without attributes, when its first 8000 bytes hold a NUL."""
    diff = _git(*_DIFF, "-M", f"{base}...{head}")
    numstat = _git("diff", "--numstat", "-z", "--no-renames", f"{base}...{head}")
    forced = []
    for entry in numstat.split("\0"):
        fields = entry.split("\t", 2)
        if len(fields) == 3 and fields[0] == "-":
            try:
                blob = _git("cat-file", "blob", f"{head}:{fields[2]}", binary=True)
            except subprocess.CalledProcessError:
                continue  # deleted at head
            if b"\0" not in blob[:8000]:
                forced.append(f":(literal){fields[2]}")
    if forced:
        diff += "\n" + _git(*_DIFF, "--text", f"{base}...{head}", "--", *forced)
    return diff


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True, help="the commit the change is measured against")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--allowlist", default=ALLOWLIST_FILE,
                        help="the allowlist file (CI passes the base commit's copy on its first run)")
    args = parser.parse_args(argv)

    allow_path = pathlib.Path(args.allowlist)
    allowlist, errors = load_allowlist(
        allow_path.read_text(encoding="utf-8") if allow_path.is_file() else "", args.allowlist)
    for e in errors:
        print(e, file=sys.stderr)
    if errors:
        return 2

    try:
        diff = read_diff(args.base, args.head)
    except subprocess.CalledProcessError as exc:
        print(f"git failed: {(exc.stderr or '').strip()}", file=sys.stderr)
        return 2

    added, removed = parse_diff(diff)
    found, waived = check(added, allowlist, removed)
    if waived:
        print(f"{len(waived)} added line(s) with Chinese passed by an escape hatch:")
        for w in waived:
            print(f"  {w}")
    annotate = os.environ.get("GITHUB_ACTIONS") == "true"
    for f in found:
        print(f"{f.path}:{f.line}: {f.text.strip()[:160]}")
        if annotate:
            print(f"::error file={f.path},line={f.line}::Added Chinese outside the exceptions in docs/sessions.md §6")
    if found:
        print(
            f"\n{len(found)} added line(s) hold Chinese where English is expected (docs/sessions.md §6).\n"
            "Write them in English. To quote exact Chinese, put it in quotes inside an English sentence.\n"
            f"For a case no exception covers, add '{MARKER}' to the line, or a path glob with a reason to {ALLOWLIST_FILE}."
        )
        return 1
    print(f"checked {len(added)} added line(s): no Chinese outside the exceptions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
