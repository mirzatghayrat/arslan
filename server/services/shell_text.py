"""How a shell command reads, for terminal_policy: where each command starts, what a quoted or `-c`
argument runs, and the spellings that hide a command word (r''m, r\\m, $IFS, `$(echo rm)`, ${x:-rm}).

0.1.63 S2b-1: Arslan's own copy, adapted from Hermes Agent's command detection
(NousResearch/hermes-agent, tools/approval_detection.py and tools/ansi_strip.py at commit
6b2fe92af66a95ea6a5caa309e05c5643cdd79de), trimmed to what Arslan's decisions read. Left out, because
no Arslan decision reads them: folding HERMES_HOME (Hermes' own install path, never set here) and the
interpreter -c/-e and "malformed payload" findings, which carry no payload (terminal_policy reads inline
scripts itself). The Windows-path variant is kept: dropping it would change verdicts (it only asks more).
Nothing else changed: S2b-1 compared it with the vendored original command by command (0 differences)
before S2b-2 removed that copy; tests/server/test_shell_text_reading.py pins the readings since.

Hermes Agent's MIT license, which covers the parts adapted from it, is in THIRD_PARTY_NOTICES.md
("Terminal command reading").
"""
from __future__ import annotations

import functools
import os
import re
import shlex
import unicodedata

# ── ANSI escapes (Hermes' ansi_strip.strip_ansi) ──────────────────────────────

_ANSI_ESCAPE_RE = re.compile(
    r"\x1b(?:\[[\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e]|\][\s\S]*?(?:\x07|\x1b\\)|[PX^_][\s\S]*?(?:\x1b\\)"
    r"|[\x20-\x2f]+[\x30-\x7e]|[\x30-\x7e])|\x9b[\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e]|\x9d[\s\S]*?(?:\x07|\x9c)"
    r"|[\x80-\x9f]", re.DOTALL)
_HAS_ESCAPE = re.compile(r"[\x1b\x80-\x9f]")


def _strip_ansi(text: str) -> str:
    if not text or not _HAS_ESCAPE.search(text):
        return text
    return _ANSI_ESCAPE_RE.sub("", text)


# ── adapted from Hermes ───────────────────────────────────────────────────────

_MAX_DETECTION_COMMAND_CHARS, _MAX_SEPARATOR_FREE_COMMAND_CHARS, _MAX_DETECTION_SEGMENTS = 128_000, 4_096, 25_000

# Start of a command: start of text, a newline, `$(` or a backtick, past sudo/env/exec/nohup/setsid/time.
# ; & | are made newlines by the quote-aware _mark_command_starts pass, so quoted data never counts.
_CMDPOS = (
    r'(?:^|[\n`]|\$\()' r'\s*'  # start position, optional whitespace
    r'(?:sudo\s+(?:-[^\s]+\s+)*)?' r'(?:env\s+(?:\w+=\S*\s+)*)?'  # optional sudo with flags, env VAR=VAL pairs
    r'(?:(?:exec|nohup|setsid|time)\s+)*' r'\s*'  # optional wrapper commands
)

# Commands that run a quoted argument: there quoted text is code, so the quote-masked rules read it raw.
_SHELL_CARRIER_NAMES = frozenset({"eval", "sh", "bash", "zsh", "ksh", "dash", "source", "."})

# The shells among them, shared by every -c payload scan so the list cannot drift (it let `dash -c` through).
_SHELL_NAMES = ("bash", "sh", "zsh", "ksh", "dash")


def _contains_shell_carrier(command: str) -> bool:
    """Return whether any command-position word is a shell-carrying command."""
    return any(
        os.path.basename(_deobfuscate_shell_word_for_detection(word)).lower() in _SHELL_CARRIER_NAMES
        for _, _, word in _iter_shell_command_word_spans(command)
    )


def _mask_quoted_prose(command: str) -> str:
    """Blank out quoted text (the quotes stay) for the positionless floor rules: a quoted argument is data,
    except `$(...)` and backticks inside double quotes, which run. An unclosed quote masks to the end."""
    return "".join(
        command[i:j] if quote is None or kind in ("quote", "subst") else " " * (j - i)
        for kind, i, j, quote in _scan_shell(command, subst="q", naive_backtick=True)
    )


# ---- Detection ----------------------------------------------------------------------------
def _normalize_command_for_detection(command: str) -> str:
    """Normalize a command before pattern matching so ANSI escapes, null bytes, Unicode fullwidth
    forms, and shell splicing tricks cannot bypass detection."""
    command = unicodedata.normalize('NFKC', _strip_ansi(command).replace('\x00', ''))
    # Join `\<newline>` first (`rm -rf \<newline>/` is `rm -rf /`): the escape strip below skips newlines.
    command = re.sub(r'\\\r?\n', '', command)
    # Fold the absolute home prefix to ~/ so the static patterns catch /Users/alice/.zshrc. Resolved at
    # detection time (not import time) so it tracks HOME set later. MUST run before the backslash strip.
    command = _rewrite_resolved_user_home(command)
    # Strip backslash-escapes (r\m -> rm) and empty-string literals (r''m -> rm).
    command = re.sub(r'\\([^\n])', r'\1', command)
    command = re.sub(r"''|\"\"", '', command)
    # Collapse $IFS / ${IFS...} (incl. `${IFS:0:1}`) to a space: IFS defaults to whitespace, so `rm${IFS}-rf${IFS}/`
    # runs as `rm -rf /`, and every pattern — incl. the hardline floor — anchors on literal \s between tokens.
    return re.sub(r'\$\{IFS\b[^}]*\}|\$IFS\b', ' ', command)


# Shell metacharacters, quotes, and whitespace that terminate a path token.
_PATH_TOKEN_STOP = r"""\s'"`;|&<>()"""

_PATH_TAIL = r"(?P<tail>(?:[/\\][^/\\" + _PATH_TOKEN_STOP + r"]*)+)"


@functools.lru_cache(maxsize=64)
def _home_prefix_fold_regex(path: str):
    """A regex for *path* as an absolute directory prefix with a non-empty tail, or None for a degenerate
    path (fewer than two components), so a stray HOME cannot rewrite unrelated prefixes."""
    components = [c for c in re.split(r"[/\\]+", path) if c] if path else []
    if len(components) < 2:
        return None
    # Optional leading root separator; a Windows drive letter is a component.
    return re.compile(r"[/\\]*" + r"[/\\]+".join(re.escape(c) for c in components) + _PATH_TAIL)


def _fold_home_prefixes(command: str, paths, replacement: str) -> str:
    """Fold each resolved home prefix in *command* to *replacement* (no trailing separator; the tail
    supplies it). Longest first so a deeper home folds before a shorter overlapping one that would clobber it."""
    for path in dict.fromkeys(sorted((p for p in paths if p), key=len, reverse=True)):
        pattern = _home_prefix_fold_regex(path)
        if pattern is not None:
            command = pattern.sub(lambda m: replacement + m.group("tail").replace("\\", "/"), command)
    return command


def _rewrite_resolved_user_home(command: str) -> str:
    """User home (expanduser / realpath / $HOME) -> ``~/``; no-op when unset, degenerate, or unresolvable."""
    try:
        # expanduser, realpath, and an explicit HOME — Windows expanduser uses USERPROFILE, not HOME.
        home = os.path.expanduser("~")
        paths = [home, os.path.realpath(home), os.environ.get("HOME", "")]
    except Exception:
        return command
    return _fold_home_prefixes(command, paths, "~")

_PARAM_REPLACEMENT_RE = re.compile(r"\$\{[^}/\s]+/[^}/]*/(?P<replacement>[^}]*)\}")

_PARAM_DEFAULT_RE = re.compile(r"\$\{[^}:}\s]+:-(?P<default>[^}]*)\}")

_SIMPLE_SHELL_LITERAL_RE = re.compile(r"^[A-Za-z0-9_./:@%+=,-]+$")

_ENV_ASSIGNMENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*")

_COMMAND_WRAPPER_WORDS = {"sudo", "env", "exec", "nohup", "setsid", "time", "command", "builtin",
                          "nice", "timeout", "stdbuf", "ionice", "chrt", "taskset", "chroot"}

_SUDO_OPTIONS_WITH_ARG = {"-c", "--close-from", "-g", "--group", "-h", "--host", "-p", "--prompt", "-u", "--user"}

# Adapted from embwl0x's command-position work in #76063. Option operands are
# data, not executable positions; option spelling remains case-sensitive.
_COMMAND_WRAPPER_OPTIONS_WITH_ARG = {
    "chroot": {"--groups", "--userspec"},
    "sudo": _SUDO_OPTIONS_WITH_ARG,
    "env": {"-a", "--argv0", "-C", "--chdir", "-S", "--split-string", "-u", "--unset"},
    "exec": {"-a"}, "nice": {"-n", "--adjustment"},
    "time": {"-f", "--format", "-o", "--output"},
    "timeout": {"-k", "--kill-after", "-s", "--signal"},
    "stdbuf": {"-e", "--error", "-i", "--input", "-o", "--output"},
    "ionice": {"-c", "--class", "-n", "--classdata"},
}

_COMMAND_WRAPPER_NON_EXECUTING_OPTIONS = {
    "command": {"-v", "-V"}, "chrt": {"-p", "--pid"},
    "ionice": {"-p", "--pid", "--pgid", "--uid"}, "taskset": {"-p", "--pid"},
}

_COMMAND_WRAPPER_POSITIONAL_ARGS = {"chroot": 1, "chrt": 1, "taskset": 1, "timeout": 1}

_SHELL_COMMAND_TRANSITIONS = {"if", "then", "else", "elif", "do", "while", "until", "!"}

_SHELL_REDIRECTION_RE = re.compile(r"(?:[0-9]+)?(?:>>|<<|<>|>&|<&|>\||[<>])")

_READ_TOOL_EXEC_FLAGS = {
    "sort": {"--compress-program"}, "rg": {"--pre", "--hostname-bin"}, "ag": {"--pager"},
    "man": {"--pager", "--html", "-P", "-H"},
}

# Required-argument options are ownership boundaries: an option-looking next token is data, not another option. These
# sets mirror the invocation grammar of the supported binaries (ripgrep 14, GNU sort, man-db, and ag 2.2).
_READ_TOOL_LONG_OPTIONS_WITH_ARG = {
    "rg": {
        "--after-context", "--before-context", "--color", "--colors", "--context", "--context-separator",
        "--dfa-size-limit", "--encoding", "--engine", "--field-context-separator", "--field-match-separator",
        "--file", "--generate", "--glob", "--hostname-bin", "--hyperlink-format", "--iglob", "--ignore-file",
        "--max-columns", "--max-count", "--max-depth", "--max-filesize", "--path-separator", "--pre", "--pre-glob",
        "--regex-size-limit", "--regexp", "--replace", "--sort", "--sortr", "--threads", "--type", "--type-add",
        "--type-clear", "--type-not",
    },
    "sort": {
        "--batch-size", "--buffer-size", "--compress-program", "--field-separator", "--files0-from", "--key",
        "--output", "--parallel", "--random-source", "--sort", "--temporary-directory",
    },
    "man": {
        "--config-file", "--encoding", "--extension", "--locale", "--manpath", "--pager", "--preprocessor",
        "--prompt", "--recode", "--sections", "--systems",
    },
    "ag": {
        "--ackmate-dir-filter", "--color-line-number", "--color-match", "--color-path", "--depth",
        "--filename-pattern", "--file-search-regex", "--ignore", "--ignore-dir", "--max-count", "--pager",
        "--path-to-ignore", "--width", "--workers",
    },
}

_READ_TOOL_SHORT_OPTIONS_WITH_ARG = {
    "rg": frozenset("efEmjgdtTABCMr"), "sort": frozenset("koStT"), "man": frozenset("CRLmMSserEPp"),
    "ag": frozenset("gGmpW"),
}

_GREP_OPTIONS_WITH_ARG = {
    "--after-context", "--before-context", "--binary-files", "--context", "--directories", "--devices", "--exclude",
    "--exclude-dir", "--exclude-from", "--include", "--label", "--max-count", "--regexp", "--file",
}

_GREP_SHORT_OPTIONS_WITH_ARG = {"A", "B", "C", "D", "d", "e", "f", "m"}

_BASH_OPTIONS_WITH_ARG = {"-O", "+O", "-o", "+o", "--init-file", "--rcfile"}

_BASH_SHORT_OPTION_LETTERS = frozenset("ilrsDcabefhkmnptuvxBCEHPTOo")


def _command_parser_limit_exceeded(command: str) -> bool:
    """Bound all parser work: too long, long with no separator, or too many separators (quoted ones
    over-count, which fails closed)."""
    if len(command) > _MAX_DETECTION_COMMAND_CHARS:
        return True
    # Long separator-free input has no compound-command utility and makes every regex inspect one giant token.
    if len(command) > _MAX_SEPARATOR_FREE_COMMAND_CHARS and not any(char in command for char in ";&|\n"):
        return True
    return sum(command.count(char) for char in ";&|\n") >= _MAX_DETECTION_SEGMENTS


def _backtick_end_from(segment: str, i: int) -> int | None:
    """Index of the backtick closing the one opened at ``i``, or None when none follows."""
    j = segment.find("`", i + 1)
    while j != -1 and segment[j - 1] == "\\":
        j = segment.find("`", j + 1)
    return None if j == -1 else j


def _shell_tokens_with_spans(segment: str, start: int):
    """Shell words of the simple command starting at *start* as ``(value, start, end, inert)``, or None on
    malformed quoting. Stops at an unquoted ``;|&`` or newline, or the ``)`` / backtick closing an enclosing
    substitution (a grep inside ``"$(grep … | cut …)"`` is not read with the outer quote)."""
    tokens, value, token_start, quote = [], [], None, None
    depth = 0  # $(...) nesting opened AFTER start; a closer at depth 0 ends the enclosing substitution
    # A backtick opened AFTER start is an operand substitution (``grep -e `cmd` f``); the matching
    # closer belongs to it, not to an enclosing backtick the command might sit inside.
    in_backtick = False

    def flush(end: int) -> None:
        raw = segment[token_start:end]
        # Only a wholly single-quoted operand is inert shell data. Double quotes still execute $()
        # and backticks; unquoted substitutions do too.
        inert = (raw.startswith("'") and raw.endswith("'")) or ("='" in raw and raw.endswith("'"))
        tokens.append(("".join(value), token_start, end, inert))

    end_at = len(segment)
    for kind, i, _, _ in _scan_shell(segment, start):
        ch = segment[i]
        if kind == "char" and not quote:
            if ch.isspace() and ch != "\n":
                if token_start is not None:
                    flush(i)
                    value, token_start = [], None
                continue
            if segment.startswith("$(", i):
                depth += 1
            elif ch == "`":
                if in_backtick:
                    in_backtick = False
                elif depth == 0 and _backtick_end_from(segment, i) is None:
                    end_at = i  # unmatched: it closes the substitution this command sits inside
                    break
                else:
                    in_backtick = True
            elif ch == ")":
                if depth == 0:
                    end_at = i
                    break
                depth -= 1
            elif ch in ";|&\n":
                end_at = i
                break
        if token_start is None:
            token_start = i
        if kind == "quote":
            quote = None if quote else ch
        elif kind == "esc":
            value.append(segment[i + 1])
        elif ch == "\\" and not quote:
            return None  # dangling backslash
        else:
            value.append(ch)
    if quote:
        return None
    if token_start is not None:
        flush(end_at)
    return tokens


def _quoted_grep_pattern_spans(command: str) -> tuple[list[tuple[int, int]], bool]:
    """Quoted grep -P pattern operands as spans, and whether a grep could not be read (then nothing is
    hidden and the caller fails closed)."""
    spans: list[tuple[int, int]] = []
    offset = 0
    for segment in _iter_top_level_shell_segments(command):
        segment_at = command.find(segment, offset)
        offset = segment_at + len(segment)
        for start, _, word in _iter_shell_command_word_spans(segment):
            if os.path.basename(_deobfuscate_shell_word_for_detection(word)).lower() not in {"grep", "egrep"}:
                continue
            tokens = _shell_tokens_with_spans(segment, start)
            if tokens is None:
                return [], True
            args, pattern_indexes = tokens[1:], []
            pcre = explicit_patterns = False
            operand_index, i, options = None, 0, True
            while i < len(args):
                token = args[i][0]
                if options and token == "--":
                    options = False
                elif options and token.startswith("--"):
                    option, equals, _ = token.partition("=")
                    pcre = pcre or option == "--perl-regexp"
                    explicit_patterns = explicit_patterns or option in {"--regexp", "--file"}
                    takes_next = option in _GREP_OPTIONS_WITH_ARG and not equals
                    if takes_next and i + 1 >= len(args):
                        return [], True
                    if option == "--regexp":
                        pattern_indexes.append(i + 1 if takes_next else i)
                    i += 1 if takes_next else 0
                elif options and token.startswith("-") and token != "-":
                    chars = token[1:]
                    for j, char in enumerate(chars):
                        pcre = pcre or char == "P"
                        explicit_patterns = explicit_patterns or char in {"e", "f"}
                        if char in _GREP_SHORT_OPTIONS_WITH_ARG:
                            # The first argument-taking short option owns the rest of the bundle,
                            # or the next token when it comes last.
                            attached = j + 1 < len(chars)
                            if not attached and i + 1 >= len(args):
                                return [], True
                            if char == "e":
                                pattern_indexes.append(i if attached else i + 1)
                            i += 0 if attached else 1
                            break
                elif operand_index is None:
                    operand_index = i
                i += 1
            if not explicit_patterns:
                if operand_index is None:
                    return [], pcre
                pattern_indexes.append(operand_index)
            if pcre:
                spans.extend(
                    (segment_at + token_start, segment_at + token_end)
                    for _, token_start, token_end, quoted in map(args.__getitem__, pattern_indexes) if quoted
                )
    return spans, False


def _splice(command: str, edits) -> str:
    """Apply sorted, non-overlapping ``(start, end, text)`` edits to *command* in one pass
    (re-slicing per edit is quadratic on 10k+ segments)."""
    parts, previous = [], 0
    for start, end, text in edits:
        parts.extend((command[previous:start], text))
        previous = end
    return "".join(parts) + command[previous:]


def _grep_safe_detection_variant(command: str) -> tuple[str, bool]:
    spans, malformed = _quoted_grep_pattern_spans(command)
    if malformed or not spans:
        return command, malformed
    return _splice(command, [(start, end, " " * (end - start)) for start, end in spans]), False


def _shell_segment_tokens(segment: str, start: int) -> list[str] | None:
    """shlex tokens of a bounded segment; None for malformed quoting (an empty segment is [])"""
    try:
        lexer = shlex.shlex(segment[start:], posix=True, punctuation_chars="<>")
        lexer.whitespace_split, lexer.commenters = True, ""
        return list(lexer)
    except ValueError:
        return None


def _iter_top_level_shell_segments(command: str):
    """Yield top-level command segments in one left-to-right pass."""
    start = 0
    for kind, i, j, quote in _scan_shell(command, comments=True):
        if kind == "comment" or (kind == "char" and quote is None and command[i] in ";&|\n"):
            if start < i:
                yield command[start:i]
            start = j
    if start < len(command):
        yield command[start:]


def _bash_exec_payload(args: list[str]) -> tuple[bool, str | None]:
    """Whether a shell's ``-c`` occurs, and the string it runs (O/o and the rc-file options take a value)."""
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--" or not token.startswith(("-", "+")):
            break
        if token in _BASH_OPTIONS_WITH_ARG:
            index += 2
            continue
        chars = token[1:]
        # Bash option letters are case-sensitive; restricting to the documented alphabet
        # preserves invalid controls such as `-Wc`.
        if token.startswith("--") or not set(chars) <= _BASH_SHORT_OPTION_LETTERS:
            index += 1
            continue
        consumed_option_arg = int("O" in chars or "o" in chars)
        if "c" in chars:
            payload_index = index + 1 + consumed_option_arg
            return True, (args[payload_index] if payload_index < len(args) else None)
        index += 1 + consumed_option_arg
    return False, None


def _read_tool_exec_flag(tool: str, args: list[str]) -> tuple[str, str] | None:
    """Return (option, program) for a read-only tool's program-running flag."""
    flags = _READ_TOOL_EXEC_FLAGS[tool]
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--":
            break
        option, equals, payload = token.partition("=")
        payload = payload if equals else None
        matched = option if option in flags else None
        if tool == "man" and token.startswith(("-P", "-H")) and len(token) > 2:
            matched, payload = token[:2], token[2:]
        if matched:
            if payload is None and index + 1 < len(args):
                payload = args[index + 1]
            # The option owns its program argument regardless of spelling; the real binaries
            # execute a '-'-prefixed payload rather than reparsing it.
            if payload:
                return matched, payload
            index += 2 if payload is not None and "=" not in token else 1
        elif option in _READ_TOOL_LONG_OPTIONS_WITH_ARG[tool] and payload is None:
            index += 2
        elif token.startswith("-") and not token.startswith("--") and len(token) > 1:
            # In a short bundle, the first argument-taking option owns the rest of the token, or
            # the following token when it occurs last.
            shorts = _READ_TOOL_SHORT_OPTIONS_WITH_ARG[tool]
            owner = next((k for k, char in enumerate(token[1:], start=1) if char in shorts), None)
            index += 2 if owner == len(token) - 1 else 1
        else:
            index += 1
    return None


def _execution_flag_findings(command: str):
    """The payloads program-bearing options carry: a shell's `-c` string and a read tool's program option
    (`sort --compress-program`, `rg --pre`, `ag --pager`, `man -P`)."""
    for segment in _iter_top_level_shell_segments(command):
        for start, _, word in _iter_shell_command_word_spans(segment):
            executable_name = os.path.basename(_deobfuscate_shell_word_for_detection(word)).lower()
            if executable_name not in _SHELL_NAMES and executable_name not in _READ_TOOL_EXEC_FLAGS:
                continue
            tokens = _shell_segment_tokens(segment, start)
            if not tokens:
                continue
            args = tokens[1:]
            if executable_name in _SHELL_NAMES:
                found, payload = _bash_exec_payload(args)
                if found and payload:
                    yield payload
            if executable_name in _READ_TOOL_EXEC_FLAGS:
                finding = _read_tool_exec_flag(executable_name, args)
                if finding:
                    yield finding[1]


def _skip_shell_whitespace(command: str, pos: int) -> int:
    while pos < len(command) and command[pos].isspace():
        pos += 1
    return pos


def _scan_shell(text: str, start: int = 0, end: int | None = None, *, subst: str = "",
                brace: bool = False, stop_unterminated: bool = False, naive_backtick: bool = False,
                comments: bool = False):
    """Yield ``(kind, i, j, quote)`` steps over ``text[start:end]`` without expanding: "char", "esc"
    (backslash + char), "quote", "subst" (``$(...)``, backtick, ``${...}`` per *subst*/*brace*), or "comment"
    with *comments*. *stop_unterminated* yields ``("subst", i, None, quote)`` and stops; *naive_backtick*
    closes a backtick at the next one even if escaped."""
    n = len(text) if end is None else end
    quote: str | None = None
    i = start
    while i < n:
        ch = text[i]
        kind, j = "char", i + 1
        if comments and quote is None and _is_shell_comment_start(text, i):
            kind, j = "comment", text.find("\n", i, n)
            if j < 0:
                j = n
        elif quote != "'" and ch == "\\" and i + 1 < n:
            kind, j = "esc", i + 2
        elif ch == quote or (quote is None and ch in "'\""):
            kind = "quote"
        elif quote != "'" and ("q" if quote else "u") in subst and (
            ch == "`" or text.startswith("$(", i) or (brace and not quote and text.startswith("${", i))
        ):
            if ch == "`":
                close = text.find("`", i + 1) + 1 or None if naive_backtick else _scan_backtick_end(text, i)
            elif text[i + 1] == "(":
                close = _scan_dollar_paren_end(text, i)
            else:
                close = text.find("}", i + 2) + 1 or None
            if close is not None:
                kind, j = "subst", close
            elif stop_unterminated:
                yield ("subst", i, None, quote)
                return
        yield (kind, i, j, quote)
        if kind == "quote":
            quote = None if quote else ch
        i = j


def _scan_dollar_paren_end(command: str, start: int) -> int | None:
    """Return the offset after a balanced ``$(...)`` command substitution."""
    depth = 1
    for kind, i, _, quote in _scan_shell(command, start + 2):
        if kind == "char" and not quote:
            depth += command.startswith("$(", i) - (command[i] == ")")
            if depth == 0:
                return i + 1
    return None


def _scan_backtick_end(command: str, start: int) -> int | None:
    # Backticks have no quote awareness: only a backslash escapes the next char.
    match = re.compile(r"(?:\\.|[^`\\])*`", re.DOTALL).match(command, start + 1)
    return match.end() if match else None


def _read_shell_word(command: str, pos: int) -> tuple[int, int, str]:
    """Read one shell word without executing expansions."""
    start = end = _skip_shell_whitespace(command, pos)
    for kind, i, j, quote in _scan_shell(command, start, subst="u", brace=True):
        if kind == "char" and quote is None and (command[i].isspace() or command[i] in ";&|<>()"):
            break
        end = j
    return (start, end, command[start:end])


def _literal_command_substitution_output(script: str) -> str | None:
    """Resolve tiny literal command substitutions without executing a shell."""
    try:
        tokens = shlex.split(script, posix=True)
    except ValueError:
        tokens = []
    if not tokens:
        return None
    command, args = tokens[0].lower(), tokens[1:]
    if command == "echo":
        while args and re.fullmatch(r"-[nEe]+", args[0]):
            args = args[1:]
    elif command != "printf":
        return None
    if len(args) == 1 and _SIMPLE_SHELL_LITERAL_RE.fullmatch(args[0]):
        return args[0]
    if command == "printf" and len(args) == 2 and args[0] == "%s" and _SIMPLE_SHELL_LITERAL_RE.fullmatch(args[1]):
        return args[1]
    return None


def _replace_simple_command_substitutions(word: str) -> str:
    chars: list[str] = []
    i = 0
    while i < len(word):
        opener = 2 if word.startswith("$(", i) else 1 if word[i] == "`" else 0
        end = (_scan_dollar_paren_end if opener == 2 else _scan_backtick_end)(word, i) if opener else None
        replacement = _literal_command_substitution_output(word[i + opener:end - 1]) if end is not None else None
        if replacement is None:
            replacement, end = word[i], i + 1
        chars.append(replacement)
        i = end
    return "".join(chars)


def _replace_simple_shell_expansions(word: str) -> str:
    word = _replace_simple_command_substitutions(word)
    word = _PARAM_REPLACEMENT_RE.sub(lambda match: match.group("replacement"), word)
    return _PARAM_DEFAULT_RE.sub(lambda match: match.group("default"), word)


def _strip_shell_word_syntax(word: str) -> str:
    return "".join(
        word[i + 1] if kind == "esc" else word[i]
        for kind, i, _, _ in _scan_shell(word) if kind != "quote"
    )


def _deobfuscate_shell_word_for_detection(word: str) -> str:
    """Approximate how shell syntax can spell a command word: collapses quoting/escaping plus
    simple literal command substitutions in the word itself. Intentionally narrow and non-executing."""
    for _ in range(2):
        previous = word
        word = _strip_shell_word_syntax(_replace_simple_shell_expansions(word))
        if word == previous:
            break
    return word


def _is_shell_comment_start(command: str, index: int) -> bool:
    return command[index] == "#" and (index == 0 or command[index - 1].isspace()
                                      or command[index - 1] in ";&|()<>")


def _iter_shell_command_starts(command: str):
    starts = [0]

    def scan(start: int, end: int) -> None:
        skip = -1
        for kind, i, j, quote in _scan_shell(command, start, end, subst="uq", stop_unterminated=True,
                                            comments=True):
            if kind == "subst":
                # Record a nested $(...)/backtick command start and scan its body.
                inner = i + (1 if command[i] == "`" else 2)
                starts.append(inner)
                scan(inner, end if j is None else j - 1)
            elif kind == "char" and quote is None and i != skip:
                # `{` opens a group only as its own word: `${IFS}` and `-{delete,print}` stay one word.
                if command[i] in "(;\n" or (command[i] == "{" and (i == 0 or command[i - 1].isspace()
                                                                   or command[i - 1] in "(;&|)")):
                    starts.append(i + 1)
                elif command[i] in "&|":
                    repeated = i + 1 < end and command[i + 1] == command[i]
                    skip = i + 1 if repeated else skip
                    starts.append(i + 1 + repeated)

    scan(0, len(command))
    seen = set()
    for start in starts:
        start = _skip_shell_whitespace(command, start)
        if start >= len(command) or start in seen or _is_shell_comment_start(command, start):
            continue
        seen.add(start)
        yield start
        _, end, word = _read_shell_word(command, start)
        if word in _SHELL_COMMAND_TRANSITIONS:
            starts.append(end)


def _mark_command_starts(command: str, marker: str = "\n") -> str:
    """Insert *marker* before each real (quote-aware) command start, so subshell and brace-group openers
    reach the anchored rules without quoted prose (``--title "block (reboot)"``) doing so."""
    offsets = sorted(o for o in _iter_shell_command_starts(command) if o > 0)
    return _splice(command, [(o, o, marker) for o in offsets]) if offsets else command


def _mask_quoted_newlines(command: str) -> str:
    """A newline inside quotes becomes a space: it is data, and the flat rules read every raw newline
    as a command start. Unquoted newlines stay."""
    if "\n" not in command:
        return command
    return _mask_quoted_newlines_span(command, 0, len(command))


def _mask_quoted_newlines_span(command: str, start: int, end: int) -> str:
    """``_mask_quoted_newlines`` over ``command[start:end]``; a substitution inside double quotes runs,
    so its body is scanned with a fresh quote state."""
    out: list[str] = []
    for kind, i, j, quote in _scan_shell(command, start, end, subst="q"):
        if kind == "subst":
            # j is the index just past the closer; keep the opener and closer, recurse into the body.
            body_start = i + (2 if command.startswith("$(", i) else 1)
            body_end = j - 1
            out.append(command[i:body_start])
            out.append(_mask_quoted_newlines_span(command, body_start, body_end))
            out.append(command[body_end:j])
        elif quote and kind == "char" and command[i] == "\n":
            out.append(" ")
        else:
            out.append(command[i:j])
    return "".join(out)


def _iter_shell_command_word_spans(command: str):
    """Yield command-position words that may be executable names."""
    for pos in _iter_shell_command_starts(command):
        wrapper, positionals = None, 0
        options, skip_arg = True, False
        while pos < len(command):
            redirect = _SHELL_REDIRECTION_RE.match(command, _skip_shell_whitespace(command, pos))
            if redirect:
                _, pos, _ = _read_shell_word(command, redirect.end())
                continue
            word_start, word_end, word = _read_shell_word(command, pos)
            if word_start == word_end:
                break
            pos = word_end
            deobfuscated = _deobfuscate_shell_word_for_detection(word)
            name = os.path.basename(deobfuscated).lower()
            if skip_arg:
                skip_arg = False
                continue
            if wrapper and options and deobfuscated == "--":
                options = False
                continue
            if wrapper and options and deobfuscated.startswith("-"):
                option = deobfuscated.split("=", 1)[0]
                if wrapper == "env" and (option == "--split-string" or deobfuscated.startswith("-S")):
                    # The split string and remaining argv form ONE command, handled
                    # by _env_split_payload; the suffix is not a new executable.
                    break
                queries = _COMMAND_WRAPPER_NON_EXECUTING_OPTIONS.get(wrapper, set())
                if option in queries or (wrapper == "command" and not option.startswith("--")
                                         and set(option[1:]) & {"v", "V"}):
                    break
                skip_arg = "=" not in deobfuscated and option in _COMMAND_WRAPPER_OPTIONS_WITH_ARG.get(wrapper, set())
                continue
            if positionals:
                positionals -= 1
                continue
            if _ENV_ASSIGNMENT_RE.fullmatch(word):
                continue
            yield (word_start, word_end, word)
            if name not in _COMMAND_WRAPPER_WORDS:
                break
            wrapper, options = name, True
            positionals = _COMMAND_WRAPPER_POSITIONAL_ARGS.get(name, 0)


def _command_detection_variants(command: str):
    # Mask quoted newlines BEFORE normalizing: normalizing turns \" into " and would corrupt quote tracking.
    normalized = _normalize_command_for_detection(_mask_quoted_newlines(command))
    # Quote-aware grep parsing hides only structurally identified pattern operands; malformed or
    # ambiguous input stays byte-for-byte intact.
    grep_safe, _ = _grep_safe_detection_variant(normalized)
    seen = {grep_safe}
    yield grep_safe

    def fresh(variant: str) -> bool:
        if not variant or variant in seen:
            return False
        seen.add(variant)
        return True

    # A backslash path (`C:\x`, `\\x`): also read it with `/` for `\`. zsh strips an unquoted backslash, so on macOS
    # this only ever asks more (②Main's review of #320); kept so S2b-1 changes no verdict. Dropping it is its own change.
    if re.search(r"(?:[A-Za-z]:|\\\\)[\\\\]", command) or re.search(r"[A-Za-z]:\\", command):
        win_variant = _normalize_command_for_detection(_mask_quoted_newlines(command.replace("\\", "/")))
        if fresh(win_variant):
            yield win_variant
    # Program-bearing options are parsed in their owning command's context; surfacing only the payload lets the
    # hardline floor inspect what will actually run without promoting similar flags or quoted prose.
    pending = [normalized]
    while pending:
        for payload in _execution_flag_findings(pending.pop()):
            if fresh(payload):
                yield payload
                # A payload may start with an option-looking program and then invoke a hardline command
                # after a separator; mark its starts.
                marked_payload = _mark_command_starts(payload)
                if marked_payload != payload and fresh(marked_payload):
                    yield marked_payload
                pending.append(payload)
    # `(cmd)` and `{ cmd; }` put cmd at a command position the flat patterns cannot see: mark the starts the
    # quote-aware scan found instead (adding `(` to _CMDPOS would match quoted prose).
    marked = _mark_command_starts(grep_safe)
    if marked != grep_safe and fresh(marked):
        yield marked
    # The variants above track quotes on NORMALIZED text, where `\"` is `"`: in `cat "f\"n"; rm -rf /` the start
    # sat inside a phantom quote. Mark starts on the RAW command, then normalize (" \n" survives a trailing \).
    faithful = _normalize_command_for_detection(_mark_command_starts(_mask_quoted_newlines(command), marker=" \n"))
    if fresh(faithful):
        yield faithful
    # r\m, r''m: every command word deobfuscated in one variant per nesting level (spans applied sorted;
    # overlapping ones wait a round). One variant per word was O(words * len) on long heredocs.
    pending = sorted(
        ((word_start, word_end, deobfuscated) for word_start, word_end, word in _iter_shell_command_word_spans(normalized)
         if (deobfuscated := _deobfuscate_shell_word_for_detection(word)) and deobfuscated != word),
        key=lambda span: span[:2],
    )
    while pending:
        applied, carry, cursor = [], [], 0
        for span in pending:
            if span[0] < cursor:
                carry.append(span)
            else:
                applied.append(span)
                cursor = span[1]
        variant = _splice(normalized, applied)
        if fresh(variant):
            yield variant
        pending = carry


# ── what terminal_policy reads ────────────────────────────────────────────────

CMDPOS = _CMDPOS                                    # where a command starts, for the anchored rules
normalize = _normalize_command_for_detection        # ANSI, NUL, fullwidth, continuations, home, escapes, $IFS
variants = _command_detection_variants              # the forms rules are matched against besides the text
has_shell_carrier = _contains_shell_carrier         # a command word runs a quoted argument (sh -c, eval …)
mask_quoted_prose = _mask_quoted_prose
mask_quoted_newlines = _mask_quoted_newlines
too_complex = _command_parser_limit_exceeded         # past what is read at all


def grep_unreadable(command: str) -> bool:
    """A grep whose quoting or options cannot be read for sure (its pattern could hide a command)."""
    return _grep_safe_detection_variant(command)[1]
