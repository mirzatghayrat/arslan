"""Fail when a change ADDS Chinese on a line that should be English (card LANG1).

The rule is docs/sessions.md §6 (user, 2026-10-28): everything written to
GitHub is English. About 250 files on main already hold Chinese written before
that date, and it is not rewritten, so this check never reads whole files. It
reads only the lines a change adds (`git diff <base>...<head>`), and a line
fails when it holds a Han character that none of the exceptions below covers.

Old Chinese is not new: when every run of Han characters on an added line also
appears on a line the same diff removes, the line is an edit or a move of
pre-rule text (an English note appended to an old Chinese table row, say) and
passes.

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
   - a path glob in ALLOWLIST_FILE, one per line, each with a `# reason`.

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
HAN = re.compile("[㐀-䶿一-鿿豈-﫿\U00020000-\U0002fa1f]")
# Chinese sentence punctuation: full-width comma, full stop, exclamation and
# question marks, semicolon, colon, and the ideographic comma.
SENTENCE_PUNCT = re.compile("[，。！？；：、]")
ENGLISH_WORD = re.compile(r"[A-Za-z]{3,}")

# Quoted spans. A straight single quote only opens or closes when it is not
# part of a word, so the apostrophes in "don't … it's" are not a span.
QUOTED = re.compile(
    r'"[^"\n]*"'
    r"|(?<![A-Za-z0-9])'[^'\n]*'(?![A-Za-z0-9])"
    r"|`[^`\n]*`"
    "|“[^”\n]*”"  # curly double quotes
    "|‘[^’\n]*’"  # curly single quotes
    "|「[^」\n]*」"  # corner brackets
    "|『[^』\n]*』"  # white corner brackets
)
# Session names: a circled digit (⓪, ①–⑳) followed by a short Han name.
SESSION_NAME = re.compile("[⓪①-⑳][㐀-䶿一-鿿]{1,6}")

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


def is_comment(path: str, line: str) -> bool:
    prefixes = COMMENT_PREFIXES.get(_suffix(path), ())
    return bool(prefixes) and line.lstrip().startswith(prefixes)


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


def is_old_chinese(line: str, removed: str) -> bool:
    """Every Han run on the line also appears in the text the diff removed."""
    return all(run in removed for run in HAN_RUN.findall(line))


def line_fails(path: str, line: str, removed: str = "") -> bool:
    if not HAN.search(line) or MARKER in line:
        return False
    if removed and is_old_chinese(line, removed):
        return False
    kind = path_kind(path)
    if kind == "translation":
        return False
    comment = is_comment(path, line)
    if kind == "data" and not comment:
        return False
    return not quoted_english_ok(line, code_line=_suffix(path) in CODE_SUFFIXES and not comment)


@dataclass(frozen=True)
class Added:
    path: str
    line: int
    text: str


_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def parse_diff(diff: str) -> tuple[list[Added], str]:
    """Added lines of a `git diff -U0` with their new-file line numbers, and
    every removed line (from all files, so a move between files counts)."""
    added: list[Added] = []
    removed: list[str] = []
    path: str | None = None
    lineno = 0
    in_header = False  # "--- "/"+++ " are headers only here; in a hunk they are content
    for raw in diff.split("\n"):
        if raw.startswith("diff --git "):
            in_header, path = True, None
        elif in_header and raw.startswith("+++ "):
            target = raw[4:]
            path = target[2:] if target.startswith("b/") else None  # /dev/null: a deletion
        elif in_header and not raw.startswith("@@"):
            continue
        elif raw.startswith("@@"):
            in_header = False
            m = _HUNK.match(raw)
            lineno = int(m.group(1)) if m else 0
        elif raw.startswith("+") and path is not None:
            added.append(Added(path, lineno, raw[1:]))
            lineno += 1
        elif raw.startswith("-"):
            removed.append(raw[1:])
    return added, "\n".join(removed)


def load_allowlist(text: str) -> tuple[list[str], list[str]]:
    """(patterns, errors). Every entry needs a `# reason` after the glob."""
    patterns, errors = [], []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        glob, sep, reason = line.partition("#")
        if not sep or not reason.strip() or not glob.strip():
            errors.append(f"{ALLOWLIST_FILE}:{n}: an entry is '<path glob>  # <reason>'")
            continue
        patterns.append(glob.strip())
    return patterns, errors


def failures(added: list[Added], allowlist: list[str], removed: str = "") -> list[Added]:
    return [a for a in added if not _matches(a.path, allowlist) and line_fails(a.path, a.text, removed)]


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", "-c", "core.quotePath=false", *args],
        check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
    ).stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True, help="the commit the change is measured against")
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args(argv)

    allow_path = pathlib.Path(ALLOWLIST_FILE)
    allowlist, errors = load_allowlist(allow_path.read_text(encoding="utf-8") if allow_path.is_file() else "")
    for e in errors:
        print(e, file=sys.stderr)
    if errors:
        return 2

    try:
        diff = _git("diff", "-U0", "--no-color", "--no-ext-diff", "-M", f"{args.base}...{args.head}")
    except subprocess.CalledProcessError as exc:
        print(f"git diff failed: {exc.stderr.strip()}", file=sys.stderr)
        return 2

    added, removed = parse_diff(diff)
    found = failures(added, allowlist, removed)
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
