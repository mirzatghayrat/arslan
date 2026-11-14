"""What Arslan understands of a command's text (S2a-3 c, the user's decision of 2026-10-22).

"Understood" is an allowlist. This module models one grammar, a subset of bash 3.2 (the shell
terminal_exec runs, `/bin/bash -c`), and a command is understood only when every part of its text is
in it. terminal_policy asks before running anything that is not (`unreadable`, this time only;
unattended it is refused and listed in the Inbox). The reader names what it could not read; it never
guesses past it.

Modelled, and nothing else:
  - words made of unquoted characters, backslash escapes, '…' and "…" (inside double quotes only
    $NAME, ${NAME}, the special parameters and $( … ) whose contents are understood); the same
    expansions unquoted; ~ at the start of a word; glob characters in arguments;
  - ; & && || | ! and newlines; comments; redirections with an optional file descriptor; here-strings;
    here-documents (a quoted delimiter's body is data; an unquoted one's is read like "…");
  - ( … ), { …; }, if / elif / else, for NAME [in …], while, until, case;
  - NAME=value before a command or on its own, except the variables the shell itself reads and the
    ones programs take code or a command from (CODE_VARIABLES);
  - the builtins that only run, print or test (SAFE_BUILTINS), and set / export in their plain forms;
  - the wrappers that only start the command they are given (sudo, doas, env, nohup, time, nice,
    timeout, caffeinate, command, builtin, exec, xargs, find -exec, npx / bunx), which are read through
    to it;
  - bash / sh -c with a literal script, read again as a command.

Everything else is not understood: other quoting forms, backquotes, arithmetic, brace expansion,
${…} with operators, process substitution, function definitions, [[ … ]], other builtins (alias,
eval, source, trap, declare …), a program named by an expansion or a pattern, the shell language of
another shell, launchers that take a command line of their own, an option through which a program
runs a command (rg --pre, git -c core.pager, tar --to-command …; _RUNS_FROM_OPTIONS), git config
writing a key git runs, and the inline code of any other interpreter (python -c, node -e, an awk
program, expect -c, a here-document or pipe into one): what that code starts, the text does not say.

Linear in the text. It reads at most MAX_COMMANDS commands and MAX_DEPTH levels of nesting; past
either the command is not understood, which also bounds what terminal_policy builds afterwards.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from server.services import shell_text

MAX_COMMANDS = 256
MAX_DEPTH = 8

# Characters a person cannot see or that a terminal reinterprets; anywhere in the text, it is not read.
_HIDDEN = re.compile("[\x00-\x08\x0b-\x1f\x7f​-‏‪-‮⁠-⁤⁦-⁩﻿]")
_META = frozenset(" \t\n;&|()<>")
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SPECIAL_PARAMS = frozenset("0123456789#?$!@*-")
_PROGRAM = re.compile(r"\[|[A-Za-z0-9_.+/~@%:,-]+")
_RESERVED = frozenset({"if", "then", "elif", "else", "fi", "for", "in", "do", "done", "while", "until",
                       "case", "esac", "{", "}", "!"})
_UNMODELLED_KEYWORDS = frozenset({"function", "select", "coproc", "[[", "]]", "(("})

# Builtins that only run, print or test. Every other bash builtin changes how later text is read or
# runs text of its own (alias, eval, source, trap, declare, shopt, enable, hash …).
SAFE_BUILTINS = frozenset({"cd", "echo", "printf", "test", "[", "true", "false", ":", "pwd", "read", "exit",
                           "return", "shift", "wait", "umask", "type", "getopts", "jobs", "kill", "times",
                           "ulimit", "break", "continue", "dirs", "pushd", "popd", "export", "unset", "set"})
_OTHER_BUILTINS = frozenset({"alias", "unalias", "eval", "source", ".", "trap", "declare", "typeset", "local",
                             "readonly", "let", "shopt", "enable", "hash", "fc", "bind", "complete", "compgen",
                             "compopt", "caller", "disown", "fg", "bg", "suspend", "logout", "history", "help",
                             "mapfile", "readarray"})
_SET_OPTIONS = frozenset({"errexit", "nounset", "xtrace", "verbose", "pipefail", "noclobber", "noglob"})

# Variables the shell itself reads, and ones programs take code or a command from: assigning one
# changes what the rest of the text means, which this reader does not follow.
CODE_VARIABLES = frozenset({
    "PATH", "IFS", "ENV", "BASH_ENV", "SHELLOPTS", "BASHOPTS", "GLOBIGNORE", "CDPATH", "PS4",
    "PROMPT_COMMAND", "POSIXLY_CORRECT", "EXECIGNORE", "PAGER", "GIT_PAGER", "MANPAGER", "EDITOR",
    "VISUAL", "GIT_EDITOR", "GIT_SEQUENCE_EDITOR", "GIT_SSH", "GIT_SSH_COMMAND", "GIT_ASKPASS",
    "SSH_ASKPASS", "GIT_EXTERNAL_DIFF", "GIT_EXEC_PATH", "GIT_DIR", "GIT_CONFIG", "GIT_CONFIG_GLOBAL",
    "GIT_CONFIG_SYSTEM", "GIT_CONFIG_PARAMETERS", "LESSOPEN", "LESSCLOSE", "BROWSER", "PERL5OPT",
    "PERL5LIB", "PERLLIB", "NODE_OPTIONS", "NODE_PATH", "PYTHONSTARTUP", "PYTHONPATH", "PYTHONHOME",
    "RUBYOPT", "RUBYLIB", "JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS"})
_CODE_VARIABLE_PREFIXES = ("BASH_FUNC_", "LD_", "DYLD_", "GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")

_SHELLS = frozenset({"bash", "sh"})
_OTHER_SHELLS = frozenset({"zsh", "ksh", "mksh", "dash", "ash", "fish", "csh", "tcsh", "pwsh", "nu", "xonsh",
                           "elvish", "yash", "rc"})
_LAUNCHERS = frozenset({"watch", "script", "tmux", "screen", "parallel", "concurrently", "su", "sg", "runuser",
                        "flock", "entr", "nodemon"})
# osascript and shortcuts are not read here: layer ② always asks for them by name (`apple-events`,
# `shortcuts`), and U11 runs an approved plain call by that name.

@dataclass(frozen=True)
class _Interpreter:
    inline: frozenset[str]              # options (or a subcommand) whose operand is code
    operands: frozenset[str] = frozenset()   # options that take a separate operand, so the script is found
    module: str = ""                    # the option naming a module to run, which is a program like a script


# Interpreters whose code can be given on the command line or on standard input.
_INTERPRETERS: dict[str, _Interpreter] = {
    "python": _Interpreter(frozenset({"-c"}), frozenset({"-W", "-X", "-Q"}), module="-m"),
    "node": _Interpreter(frozenset({"-e", "--eval", "-p", "--print"}),
                         frozenset({"-r", "--require", "--import", "--loader", "-C", "--conditions",
                                    "--input-type", "--title", "--env-file"})),
    "deno": _Interpreter(frozenset({"eval"}), frozenset()),
    "bun": _Interpreter(frozenset({"-e", "--eval", "-p", "--print"}), frozenset()),
    "perl": _Interpreter(frozenset({"-e", "-E"}), frozenset({"-I", "-M", "-m"})),
    "ruby": _Interpreter(frozenset({"-e"}), frozenset({"-I", "-r", "-C"})),
    "php": _Interpreter(frozenset({"-r", "-R", "-B", "-E"}), frozenset({"-c", "-d", "-z"})),
    "Rscript": _Interpreter(frozenset({"-e"}), frozenset()),
    "lua": _Interpreter(frozenset({"-e"}), frozenset({"-l"})),
    "luajit": _Interpreter(frozenset({"-e"}), frozenset({"-l", "-j", "-O"})),
    "tclsh": _Interpreter(frozenset()),
    "swift": _Interpreter(frozenset()),
    "julia": _Interpreter(frozenset({"-e", "--eval", "-E", "--print"}), frozenset()),
    "expect": _Interpreter(frozenset({"-c"}), frozenset({"-f"})),
}
_AWKS = frozenset({"awk", "gawk", "nawk", "mawk"})

# Programs that run a command they are given in an option: a nested interpreter as well (S2a-3 c), so the
# option makes the command not understood. rg / ag / sort / man are shell_text's own table. A program that
# is not listed and runs commands from its arguments is a known residual risk: only the sandbox holds it.
_TAR_OPTIONS = frozenset({"--use-compress-program", "-I", "--to-command", "--checkpoint-action", "--info-script",
                          "--new-volume-script", "-F"})
_EDITOR_OPTIONS = frozenset({"-c", "--cmd", "-S"})
_RUNS_FROM_OPTIONS: dict[str, frozenset[str]] = {
    **{name: frozenset(flags) for name, flags in shell_text._READ_TOOL_EXEC_FLAGS.items()},
    "tar": _TAR_OPTIONS, "gtar": _TAR_OPTIONS, "bsdtar": _TAR_OPTIONS,
    "rsync": frozenset({"-e", "--rsh", "--rsync-path"}),
    "vim": _EDITOR_OPTIONS, "vi": _EDITOR_OPTIONS, "nvim": _EDITOR_OPTIONS, "view": _EDITOR_OPTIONS,
    "ex": _EDITOR_OPTIONS, "emacs": frozenset({"--eval", "-l", "--load", "-f", "--funcall", "--script"}),
}
_EDITORS = frozenset({"vim", "vi", "nvim", "view", "ex"})

# git -c is read only for keys that never name a command; git config writes a key that does (git runs
# it through sh: the pager, an editor, an alias with !, a diff or merge driver, a credential helper …).
_GIT_SAFE_KEYS = re.compile(r"(?:user|color|advice)\.[\w.-]+|core\.(?:quotepath|autocrlf)|init\.defaultbranch"
                            r"|(?:commit|tag)\.gpgsign|pull\.rebase|push\.default", re.I)
_GIT_COMMAND_KEYS = re.compile(
    r"core\.(?:pager|editor|sshcommand|fsmonitor|hookspath|askpass|gitproxy)|sequence\.editor"
    r"|gpg\.(?:[\w-]+\.)?program|credential\..*|pager\..*|alias\..*|diff\..*|merge\..*|filter\..*"
    r"|interactive\.difffilter|uploadpack\..*|man\..*|web\.browser|browser\..*|instaweb\..*|sendemail\..*"
    r"|remote\..*|url\..*|include\..*|includeif\..*", re.I)
_PYTHON = re.compile(r"(?:python|pypy)[0-9.]*")


def _interpreter(name: str) -> _Interpreter | None:
    if _PYTHON.fullmatch(name):
        return _INTERPRETERS["python"]
    if name in ("nodejs",):
        return _INTERPRETERS["node"]
    if re.fullmatch(r"perl[0-9.]*", name):
        return _INTERPRETERS["perl"]
    return _INTERPRETERS.get(name)


@dataclass(frozen=True, kw_only=True)
class Reading:
    understood: bool
    why: str = ""
    capped: bool = False       # past MAX_COMMANDS or MAX_DEPTH: nothing more of it should be built
    # Every command the shell would start, wrappers read through, each as its words with quotes
    # removed (an expansion shows as written). Complete only when `understood`.
    commands: tuple[tuple[str, ...], ...] = ()


class _NotUnderstood(Exception):
    def __init__(self, why: str, capped: bool = False):
        super().__init__(why)
        self.why = why
        self.capped = capped


class _Word:
    __slots__ = ("chars", "expanded", "globbed", "quoted", "end", "bare")

    def __init__(self):
        self.chars: list[str] = []
        self.bare: int | None = None    # how many leading characters came from plain unquoted text
        self.expanded = False       # holds $NAME, ${NAME}, a special parameter or $( … )
        self.globbed = False        # holds an unquoted * ? or […]
        self.quoted = False         # any part was quoted or escaped
        self.end = 0

    @property
    def text(self) -> str:
        return "".join(self.chars)

    @property
    def literal(self) -> str | None:
        """Its value, when the text alone fixes it."""
        return None if self.expanded or self.globbed else self.text

    def mark(self) -> None:
        """A quoted, escaped or expanded piece follows: the plain prefix ends here."""
        if self.bare is None:
            self.bare = len(self.text)

    def plain(self, value: str) -> bool:
        """An unquoted, unexpanded word that is exactly `value` (how a reserved word is written)."""
        return not self.quoted and not self.expanded and not self.globbed and self.text == value


@dataclass
class _Redirect:
    op: str
    target: _Word | None      # None for a here-document (its body is read separately)
    heredoc_quoted: bool = False


@dataclass
class _Simple:
    words: list[_Word]
    redirects: list[_Redirect]
    assignments: list[str]


class _Reader:
    def __init__(self, text: str, depth: int, budget: list[int], commands: list[tuple[str, ...]],
                 in_substitution: bool = False):
        if depth > MAX_DEPTH:
            raise _NotUnderstood("it nests commands deeper than Arslan reads", capped=True)
        self.s = text
        self.i = 0
        self.depth = depth
        self.budget = budget                 # commands left, shared by every nested reading
        self.commands = commands
        self.in_substitution = in_substitution
        self.heredocs: list[tuple[str, bool, bool]] = []    # (delimiter, quoted, strip tabs) waiting for a newline
        self.peeked = None

    # ── lexing ──────────────────────────────────────────────────────────────

    def _blank(self) -> None:
        s, n = self.s, len(self.s)
        while self.i < n:
            c = s[self.i]
            if c in " \t":
                self.i += 1
            elif c == "\\" and self.i + 1 < n and s[self.i + 1] == "\n":
                self.i += 2                              # a line continuation between words
            elif c == "#":
                end = s.find("\n", self.i)
                self.i = n if end == -1 else end         # a comment runs to the end of its line
            else:
                return

    def peek(self):
        if self.peeked is None:
            self.peeked = self._token()
        return self.peeked

    def take(self):
        token = self.peek()
        self.peeked = None
        return token

    def _token(self):
        self._blank()
        s, n, i = self.s, len(self.s), self.i
        if i >= n:
            return ("eof",)
        c = s[i]
        if c == "\n":
            self.i += 1
            self._heredoc_bodies()
            return ("nl",)
        two, three = s[i:i + 2], s[i:i + 3]
        if three in (";;&",) or two in ("|&", ";&"):
            raise _NotUnderstood("it uses bash 4 operators the shell here (bash 3.2) does not have")
        if two in ("&&", "||", ";;"):
            self.i += 2
            return ("op", two)
        if c in ";&|()":
            if c == "&" and s.startswith(">", i + 1):
                if s.startswith(">>", i + 1):
                    raise _NotUnderstood("it uses bash 4 operators the shell here (bash 3.2) does not have")
                self.i += 2
                return ("redir", "&>", None)
            self.i += 1
            return ("op", c)
        if c in "<>":
            return self._redirect(None)
        if c.isdigit():
            j = i
            while j < n and s[j].isdigit():
                j += 1
            if j < n and s[j] in "<>":
                self.i = j
                return self._redirect(s[i:j])
        return ("word", self._word())

    def _redirect(self, fd):
        s, i = self.s, self.i
        if s.startswith(("<(", ">("), i):
            raise _NotUnderstood("it uses process substitution")
        for op in ("<<<", "<<-", "<<", "<>", "<&", ">>", ">&", ">|", "<", ">"):
            if s.startswith(op, i):
                self.i = i + len(op)
                return ("redir", op, fd)
        raise AssertionError("unreachable")

    def _word(self) -> _Word:
        s, n = self.s, len(self.s)
        w = _Word()
        start = self.i
        while self.i < n:
            c = s[self.i]
            if c in _META:
                break
            if c == "'":
                end = s.find("'", self.i + 1)
                if end == -1:
                    raise _NotUnderstood("its quoting does not close")
                w.mark()
                w.chars.append(s[self.i + 1:end])
                w.quoted = True
                self.i = end + 1
            elif c == '"':
                w.mark()
                self._double_quoted(w)
            elif c == "\\":
                if self.i + 1 >= n:
                    raise _NotUnderstood("it ends in a lone backslash")
                if s[self.i + 1] != "\n":
                    w.mark()
                    w.chars.append(s[self.i + 1])
                    w.quoted = True
                self.i += 2
            elif c == "$":
                w.mark()
                self._dollar(w)
            elif c == "`":
                raise _NotUnderstood("it uses backquotes")
            elif c == "{":
                if self.i == start and (self.i + 1 >= n or s[self.i + 1] in _META):
                    w.chars.append("{")              # the group's opening word
                    self.i += 1
                elif s.startswith("{}", self.i):
                    w.chars.append("{}")             # find's and xargs' placeholder: bash leaves {} alone
                    self.i += 2
                else:
                    raise _NotUnderstood("it uses brace expansion")
            elif c == "}":
                if self.i == start and (self.i + 1 >= n or s[self.i + 1] in _META):
                    w.chars.append("}")
                    self.i += 1
                else:
                    raise _NotUnderstood("it uses brace expansion")
            else:
                if c in "*?" or (c == "[" and "]" in s[self.i + 1:self._word_end()]):
                    w.globbed = True
                w.chars.append(c)
                self.i += 1
        w.end = self.i
        if w.bare is None:
            w.bare = len(w.text)
        return w

    def _word_end(self) -> int:
        """Where an unquoted word starting here would end at the latest (the next metacharacter)."""
        j, s = self.i, self.s
        while j < len(s) and s[j] not in _META:
            j += 1
        return j

    def _double_quoted(self, w: _Word) -> None:
        s, n = self.s, len(self.s)
        w.quoted = True
        self.i += 1
        while True:
            if self.i >= n:
                raise _NotUnderstood("its quoting does not close")
            c = s[self.i]
            if c == '"':
                self.i += 1
                return
            if c == "\\":
                nxt = s[self.i + 1] if self.i + 1 < n else ""
                if nxt in ('$', '`', '"', "\\"):
                    w.chars.append(nxt)
                    self.i += 2
                elif nxt == "\n":
                    self.i += 2
                else:
                    w.chars.append("\\")
                    self.i += 1
            elif c == "$":
                self._dollar(w)
            elif c == "`":
                raise _NotUnderstood("it uses backquotes")
            else:
                w.chars.append(c)
                self.i += 1

    def _dollar(self, w: _Word) -> None:
        s, n, i = self.s, len(self.s), self.i
        nxt = s[i + 1] if i + 1 < n else ""
        if nxt in ("'", '"'):
            raise _NotUnderstood("it uses $'…' or $\"…\" quoting")
        if nxt == "[":
            raise _NotUnderstood("it uses shell arithmetic")
        if nxt == "(":
            if s.startswith("((", i + 1):
                raise _NotUnderstood("it uses shell arithmetic")
            inner = _Reader(s, self.depth + 1, self.budget, self.commands, in_substitution=True)
            inner.i = i + 2
            inner.list_until(frozenset(), closing=")")
            if inner.i >= n or s[inner.i] != ")":
                raise _NotUnderstood("its command substitution does not close")
            w.chars.append(s[i:inner.i + 1])
            w.expanded = True
            self.i = inner.i + 1
            return
        if nxt == "{":
            m = re.compile(r"\{(?:[A-Za-z_][A-Za-z0-9_]*|[0-9]|[#?$!@*-])\}").match(s, i + 1)
            if not m:
                raise _NotUnderstood("it uses ${…} with an operator")
            w.chars.append(s[i:m.end()])
            w.expanded = True
            self.i = m.end()
            return
        m = _NAME.match(s, i + 1)
        if m:
            w.chars.append(s[i:m.end()])
            w.expanded = True
            self.i = m.end()
            return
        if nxt and nxt in _SPECIAL_PARAMS:
            w.chars.append(s[i:i + 2])
            w.expanded = True
            self.i = i + 2
            return
        w.chars.append("$")                          # a $ before anything else is a plain character
        self.i += 1

    def _heredoc_bodies(self) -> None:
        """The bodies of the here-documents opened on the line that just ended, in order."""
        pending, self.heredocs = self.heredocs, []
        s = self.s
        for delimiter, quoted, strip in pending:
            while True:
                if self.i >= len(s):
                    raise _NotUnderstood("its here-document does not end")
                end = s.find("\n", self.i)
                line = s[self.i:] if end == -1 else s[self.i:end]
                body_start = self.i
                self.i = len(s) if end == -1 else end + 1
                if (line.lstrip("\t") if strip else line) == delimiter:
                    break
                if not quoted:
                    self._expanding_body(line, body_start)

    def _expanding_body(self, line: str, offset: int) -> None:
        """An unquoted delimiter's body line, read like the inside of double quotes."""
        i = 0
        while i < len(line):
            c = line[i]
            if c == "\\":
                i += 2
            elif c == "`":
                raise _NotUnderstood("its here-document uses backquotes")
            elif c == "$":
                saved = self.i
                self.i = offset + i
                w = _Word()
                self._dollar(w)
                i = self.i - offset
                self.i = saved
            else:
                i += 1

    # ── grammar ─────────────────────────────────────────────────────────────

    def _is_stop(self, token, stops: frozenset[str]) -> bool:
        return token[0] == "word" and any(token[1].plain(word) for word in stops)

    def list_until(self, stops: frozenset[str], closing: str = "") -> None:
        """A list of pipelines, up to a reserved word in `stops`, the `closing` character, or the end."""
        while True:
            token = self.peek()
            if token[0] == "nl" or (token[0] == "op" and token[1] in (";", "&")):
                self.take()
                continue
            if token[0] == "eof":
                if stops or closing:
                    raise _NotUnderstood("a compound command in it does not close")
                return
            if closing and token[0] == "op" and token[1] == closing:
                self.peeked = None
                self.i -= 1                          # leave the closing character for the caller
                return
            if self._is_stop(token, stops):
                return
            if token[0] == "op" and token[1] == ";;":
                if "esac" in stops:
                    return
                raise _NotUnderstood("its ;; stands outside a case")
            self._and_or(stops, closing)

    def _and_or(self, stops, closing) -> None:
        self._pipeline(stops, closing)
        while self.peek()[0] == "op" and self.peek()[1] in ("&&", "||"):
            self.take()
            while self.peek()[0] == "nl":
                self.take()
            self._pipeline(stops, closing)

    def _pipeline(self, stops, closing) -> None:
        token = self.peek()
        if token[0] == "word" and token[1].plain("!"):
            self.take()
        index = 0
        while True:
            self._command(index)
            if self.peek()[0] == "op" and self.peek()[1] == "|":
                self.take()
                while self.peek()[0] == "nl":
                    self.take()
                index += 1
                continue
            return

    def _command(self, index: int) -> None:
        token = self.peek()
        if token[0] == "op" and token[1] == "(":
            if self.s.startswith("(", self.i):
                raise _NotUnderstood("it uses shell arithmetic")
            self.take()
            self.list_until(frozenset(), closing=")")
            self.i += 1                              # the closing parenthesis
            self.peeked = None
            self._redirects_after()
            return
        if token[0] != "word":
            if token[0] == "redir":
                self._simple(index)
                return
            raise _NotUnderstood("its syntax is not one Arslan reads")
        word = token[1]
        for keyword in _UNMODELLED_KEYWORDS:
            if word.plain(keyword):
                raise _NotUnderstood(f"it uses `{keyword}`, which Arslan does not read")
        if word.plain("{"):
            self.take()
            self.list_until(frozenset({"}"}))
            self.take()
        elif word.plain("if"):
            self.take()
            self.list_until(frozenset({"then"}))
            self.take()
            while True:
                self.list_until(frozenset({"elif", "else", "fi"}))
                end = self.take()[1]
                if end.plain("fi"):
                    break
                if end.plain("elif"):
                    self.list_until(frozenset({"then"}))
                    self.take()
                else:
                    self.list_until(frozenset({"fi"}))
                    self.take()
                    break
        elif word.plain("for"):
            self.take()
            name = self.take()
            if name[0] != "word" or name[1].literal is None or not _NAME.fullmatch(name[1].text):
                raise _NotUnderstood("its for loop is not one Arslan reads")
            while self.peek()[0] == "nl":
                self.take()
            if self.peek()[0] == "word" and self.peek()[1].plain("in"):
                self.take()
                while self.peek()[0] == "word" and not self.peek()[1].plain("do"):
                    self.take()
            self.list_until(frozenset({"do"}))
            self.take()
            self.list_until(frozenset({"done"}))
            self.take()
        elif word.plain("while") or word.plain("until"):
            self.take()
            self.list_until(frozenset({"do"}))
            self.take()
            self.list_until(frozenset({"done"}))
            self.take()
        elif word.plain("case"):
            if self.in_substitution:
                raise _NotUnderstood("it puts a case inside $( … ), which bash 3.2 misreads")
            self._case()
        elif any(word.plain(r) for r in ("then", "elif", "else", "fi", "do", "done", "esac", "}", "in")):
            raise _NotUnderstood(f"its `{word.text}` stands where no compound command opened")
        else:
            self._simple(index)
            return
        self._redirects_after()

    def _case(self) -> None:
        self.take()
        subject = self.take()
        if subject[0] != "word":
            raise _NotUnderstood("its case is not one Arslan reads")
        while self.peek()[0] == "nl":
            self.take()
        if not (self.peek()[0] == "word" and self.peek()[1].plain("in")):
            raise _NotUnderstood("its case is not one Arslan reads")
        self.take()
        while True:
            while self.peek()[0] in ("nl",) or (self.peek()[0] == "op" and self.peek()[1] == ";"):
                self.take()
            token = self.peek()
            if token[0] == "word" and token[1].plain("esac"):
                self.take()
                return
            if token[0] == "op" and token[1] == "(":
                self.take()
            while True:                              # pattern [| pattern]… )
                pattern = self.take()
                if pattern[0] != "word":
                    raise _NotUnderstood("its case pattern is not one Arslan reads")
                nxt = self.take()
                if nxt == ("op", ")"):
                    break
                if nxt != ("op", "|"):
                    raise _NotUnderstood("its case pattern is not one Arslan reads")
            self.list_until(frozenset({"esac"}))
            token = self.peek()
            if token == ("op", ";;"):
                self.take()
            elif not (token[0] == "word" and token[1].plain("esac")):
                raise _NotUnderstood("its case does not close")

    def _redirects_after(self) -> None:
        while self.peek()[0] == "redir":
            self._redirect_target(self.take(), [])

    def _redirect_target(self, token, into: list[_Redirect]) -> None:
        op = token[1]
        if op in ("<<", "<<-"):
            target = self.take()
            if target[0] != "word":
                raise _NotUnderstood("its here-document has no delimiter")
            word = target[1]
            self.heredocs.append((word.text, word.quoted, op == "<<-"))
            if word.expanded:
                raise _NotUnderstood("its here-document delimiter is an expansion")
            into.append(_Redirect(op, None, heredoc_quoted=word.quoted))
            return
        target = self.take()
        if target[0] != "word":
            raise _NotUnderstood("its redirection has no target")
        into.append(_Redirect(op, target[1]))

    def _simple(self, index: int) -> None:
        words: list[_Word] = []
        redirects: list[_Redirect] = []
        assignments: list[str] = []
        while True:
            token = self.peek()
            if token[0] == "redir":
                self._redirect_target(self.take(), redirects)
                continue
            if token[0] != "word":
                break
            word = token[1]
            if not words:
                name = _assigned_name(word)
                if name is not None:
                    _check_assigned(name)
                    assignments.append(name)
                    self.take()
                    continue
            self.take()
            words.append(word)
            if len(words) == 1 and self.peek() == ("op", "("):
                raise _NotUnderstood("it defines a function")
        if words:
            self._started(words, redirects, index)

    # ── what runs ───────────────────────────────────────────────────────────

    def _count(self) -> None:
        self.budget[0] -= 1
        if self.budget[0] < 0:
            raise _NotUnderstood("it has more commands than Arslan reads before running", capped=True)

    def _started(self, words: list[_Word], redirects: list[_Redirect], index: int) -> None:
        """A simple command: the program it starts, read through the wrappers to the one that runs."""
        self._count()
        argv = list(words)
        while argv:
            head = argv[0]
            name = head.literal
            if name is None:
                raise _NotUnderstood("the program it runs comes from a variable, a substitution or a pattern")
            if not name or not _PROGRAM.fullmatch(name):
                raise _NotUnderstood("its program name has characters Arslan does not read")
            self.commands.append(tuple(w.text for w in argv))
            base = name.rsplit("/", 1)[-1]
            if "/" not in name:
                if base in _OTHER_BUILTINS:
                    raise _NotUnderstood(f"it uses `{base}`, which changes how the shell reads what follows")
                if base in SAFE_BUILTINS:
                    _check_builtin(base, argv)
                    return
            rest = _through_wrapper(base, argv)
            if rest is None:
                break
            if rest and rest is not argv:
                argv = rest
                continue
            return
        if not argv:
            return
        base = argv[0].text.rsplit("/", 1)[-1]
        if base in _SHELLS:
            self._shell(argv, redirects, index)
        elif base in _OTHER_SHELLS:
            if _reads_code(argv[1:], _Interpreter(frozenset({"-c"}), frozenset({"-o"})), redirects, index):
                raise _NotUnderstood(f"it runs {base}'s own shell language")
        elif base in _LAUNCHERS:
            raise _NotUnderstood(f"`{base}` runs a command line of its own, which Arslan does not read")
        elif base in _AWKS:
            if not any(w.text == "-f" or w.text.startswith("-f") for w in argv[1:]):
                raise _NotUnderstood("its awk program is inline code: what it starts, the text does not say")
        elif base == "find":
            self._find(argv)
        elif base == "git":
            _check_git(argv)
        elif base in _RUNS_FROM_OPTIONS and _runs_from_options(base, argv):
            raise _NotUnderstood(f"its {base} option runs a command of its own: what that starts, the text does not say")
        elif (spec := _interpreter(base)) is not None:
            if _reads_code(argv[1:], spec, redirects, index):
                raise _NotUnderstood(f"it runs inline {base} code: what that code starts, the text does not say")

    def _shell(self, argv: list[_Word], redirects: list[_Redirect], index: int) -> None:
        """bash / sh: a literal -c script is read again as a command; code from standard input is not."""
        args = argv[1:]
        k = 0
        wants_script = False
        while k < len(args):
            text = args[k].text
            if text == "--":
                k += 1
                break
            if text in ("-s", "-i", "--login") or not (text.startswith("-") or text.startswith("+")) or text in ("-", "+"):
                if text in ("-s", "-i"):
                    raise _NotUnderstood("it runs shell code from its input")
                if text == "--login":
                    k += 1
                    continue
                break
            if text.startswith("--"):
                if text not in ("--norc", "--noprofile", "--posix", "--noediting", "--restricted"):
                    raise _NotUnderstood(f"its shell option {text} is not one Arslan reads")
                k += 1
                continue
            k += 1
            for flag in text[1:]:
                if flag == "c":
                    wants_script = True
                elif flag in "oO":
                    k += 1                           # the option's name
                elif flag in "si":
                    raise _NotUnderstood("it runs shell code from its input")
                elif flag not in "abefhklmnptuvxBCEHPT":
                    raise _NotUnderstood(f"its shell option {text} is not one Arslan reads")
        if wants_script:
            if k >= len(args) or args[k].literal is None:
                raise _NotUnderstood("it runs a shell script that is not written out")
            inner = _Reader(args[k].literal, self.depth + 1, self.budget, self.commands)
            inner.list_until(frozenset())
            inner.end_of_text()
            return
        if k < len(args):
            return                                   # a script file: a program like any other
        if _code_from_input(redirects, index):
            raise _NotUnderstood("it feeds shell code to a shell on its input")

    def _find(self, argv: list[_Word]) -> None:
        """find -exec / -execdir / -ok starts its command once per file found, with {} in its words
        replaced by the file's path. It is recorded once per starting path, {} written as a file under it,
        so what judges the command sees where it acts (`find . -exec rm {} \\;` stays in the folder;
        `find / -exec rm {} \\;` does not)."""
        words = argv[1:]
        k = 0
        while k < len(words) and words[k].text in ("-H", "-L", "-P", "-E", "-X", "-d", "-s", "-x"):
            k += 1
        starts = []
        while k < len(words) and not words[k].text.startswith("-") and words[k].text not in ("(", "!", ")"):
            starts.append(words[k].text)
            k += 1
        starts = starts or ["."]
        while k < len(words):
            if words[k].text in ("-exec", "-execdir", "-ok", "-okdir"):
                end = k + 1
                while end < len(words) and words[end].text not in (";", "+"):
                    end += 1
                if end >= len(words) or end == k + 1:
                    raise _NotUnderstood("its find -exec does not end")
                for start in starts:
                    self._started([_placed(w, start) for w in words[k + 1:end]], [], 0)
                k = end
            k += 1

    def end_of_text(self) -> None:
        if self.peek()[0] != "eof":
            raise _NotUnderstood("its syntax is not one Arslan reads")
        if self.heredocs:
            raise _NotUnderstood("its here-document does not end")


def _placed(word: _Word, start: str) -> _Word:
    """`word` with find's {} written as a file under `start`."""
    if "{}" not in word.text:
        return word
    placed = _Word()
    placed.chars = [word.text.replace("{}", start.rstrip("/") + "/found")]
    placed.expanded, placed.globbed, placed.quoted, placed.bare = word.expanded, word.globbed, word.quoted, word.bare
    return placed


def _assigned_name(word: _Word) -> str | None:
    """NAME of a NAME=value word (the name must be unquoted to count)."""
    m = _NAME.match(word.text)
    if not m or not word.text.startswith("=", m.end()) or (word.bare or 0) <= m.end():
        return None
    return m.group(0)


def _check_assigned(name: str) -> None:
    if name in CODE_VARIABLES or name.startswith(_CODE_VARIABLE_PREFIXES):
        raise _NotUnderstood(f"it sets {name}, which changes what the rest of it runs")


def _check_builtin(base: str, argv: list[_Word]) -> None:
    if base == "export" or base == "unset":
        for w in argv[1:]:
            if w.text in ("-p", "--"):
                continue
            if w.text.startswith("-"):
                raise _NotUnderstood(f"it uses {base} {w.text}, which Arslan does not read")
            name = w.text.split("=", 1)[0]
            if not _NAME.fullmatch(name):
                raise _NotUnderstood(f"its {base} is not one Arslan reads")
            _check_assigned(name)
    elif base == "set":
        args = [w.text for w in argv[1:]]
        k = 0
        while k < len(args):
            a = args[k]
            if a == "--":
                return                               # the rest are positional parameters
            # flags, possibly ending in o, which names an option (-euo pipefail); not -k: it moves assignments
            m = re.fullmatch(r"[-+]([abefhmnuvxBCEHPT]*)(o?)", a)
            if not m or a in ("-", "+"):
                raise _NotUnderstood("its set option is not one Arslan reads")
            if m.group(2):
                if k + 1 >= len(args) or args[k + 1] not in _SET_OPTIONS:
                    raise _NotUnderstood("its set option is not one Arslan reads")
                k += 2
                continue
            k += 1


def _through_wrapper(base: str, argv: list[_Word]) -> list[_Word] | None:
    """The command a wrapper starts (argv from it on), [] when it starts none, or None when `base`
    is not a wrapper."""
    args = argv[1:]

    def after(options_with_arg: set[str], flags: str = "", positional: int = 0,
              long_flags: frozenset[str] = frozenset()) -> list[_Word]:
        k = 0
        while k < len(args):
            t = args[k].text
            if t == "--":
                k += 1
                break
            if not t.startswith("-") or t == "-":
                break
            if t in options_with_arg:
                k += 2
                continue
            if t.startswith("--") and "=" in t and t.split("=", 1)[0] in options_with_arg:
                k += 1
                continue
            if not t.startswith("--") and len(t) > 2 and t[:2] in options_with_arg:
                k += 1                               # an operand written onto its option (-n1, -I{})
                continue
            if t in long_flags or (flags and re.fullmatch("-[" + re.escape(flags) + "]+", t)):
                k += 1
                continue
            raise _NotUnderstood(f"its {base} option {t} is not one Arslan reads")
        k += positional
        return args[k:] if k <= len(args) else []

    if base == "sudo":
        for w in args:
            if w.text in ("-s", "--shell", "-i", "--login", "-e", "--edit") or (
                    w.text.startswith("-") and not w.text.startswith("--") and set(w.text[1:]) & set("sie")):
                raise _NotUnderstood("its sudo runs a shell or an editor")
            if not w.text.startswith("-"):
                break
        return after({"-u", "--user", "-g", "--group", "-h", "--host", "-p", "--prompt", "-C", "--close-from",
                      "-U", "--other-user", "-r", "--role", "-t", "--type", "-T", "--command-timeout"},
                     flags="AbEHknPS")
    if base == "doas":
        if any(w.text == "-s" or (w.text.startswith("-") and "s" in w.text[1:]) for w in args
               if w.text.startswith("-") and not w.text.startswith("--")):
            raise _NotUnderstood("its doas runs a shell")
        return after({"-u", "-C"}, flags="nL")
    if base == "env":
        for w in args:
            if not w.text.startswith("-"):
                break
            if w.text in ("-S", "--split-string", "-P") or w.text.startswith(("--split-string=", "-S", "-P")):
                raise _NotUnderstood("its env splits a string into a command")
        rest = after({"-u", "--unset", "-C", "--chdir"}, flags="i0", long_flags=frozenset({"--ignore-environment"}))
        # env takes any NAME=value before its command, names the shell could not hold included
        # (BASH_FUNC_x%%=…, an exported function): every one is checked.
        while rest and "=" in rest[0].text[1:]:
            name = rest[0].text.split("=", 1)[0]
            if not _NAME.fullmatch(name):
                _check_assigned(name)
                raise _NotUnderstood(f"its env sets {name}, a name the shell could not hold")
            _check_assigned(name)
            rest = rest[1:]
        return rest
    if base in ("nohup", "setsid"):
        return args
    if base == "time":
        return after(set(), flags="p")
    if base == "nice":
        return after({"-n", "--adjustment"})
    if base in ("timeout", "gtimeout"):
        return after({"-k", "--kill-after", "-s", "--signal"}, positional=1) if args else []
    if base == "caffeinate":
        return after({"-t", "-w"}, flags="dimsu")
    if base == "stdbuf":
        return after({"-i", "-o", "-e", "--input", "--output", "--error"})
    if base == "command":
        if any(w.text in ("-v", "-V") for w in args[:1]):
            return []
        return after(set(), flags="p")
    if base == "builtin":
        if args and args[0].literal not in SAFE_BUILTINS:
            raise _NotUnderstood("its builtin is not one Arslan reads")
        return args
    if base == "exec":
        return after({"-a"}, flags="cl")
    if base == "xargs":
        rest = after({"-I", "-J", "-L", "-n", "-P", "-s", "-E", "-d", "-a", "-R", "-S", "--max-args",
                      "--max-procs", "--delimiter", "--arg-file", "--replace", "--max-lines"}, flags="0tprxo")
        return rest if rest else []                  # no command: xargs runs echo
    if base in ("npx", "bunx"):
        if any(w.text in ("-c", "--call") or w.text.startswith("--call=") for w in args):
            raise _NotUnderstood(f"its {base} runs a command line of its own")
        return after({"-p", "--package"}, flags="yq",
                     long_flags=frozenset({"--yes", "--no", "--quiet", "--no-install", "--ignore-existing"}))
    return None


def _option_given(word: str, option: str) -> bool:
    if word == option or word.startswith(option + "="):
        return True
    return len(option) == 2 and not option.startswith("--") and word.startswith(option) and len(word) > 2


def _runs_from_options(base: str, argv: list[_Word]) -> bool:
    for w in argv[1:]:
        if any(_option_given(w.text, option) for option in _RUNS_FROM_OPTIONS[base]):
            return True
        if base in _EDITORS and w.text.startswith("+"):
            return True                              # vi's +command
    return False


def _check_git(argv: list[_Word]) -> None:
    """git's own options before its subcommand, and git config writing a key git runs as a command."""
    args = [w.text for w in argv[1:]]
    k = 0
    while k < len(args):
        t = args[k]
        if t in ("-c",) or (t.startswith("-c") and len(t) > 2 and not t.startswith("--")):
            pair = args[k + 1] if t == "-c" and k + 1 < len(args) else t[2:]
            if not _GIT_SAFE_KEYS.fullmatch(pair.split("=", 1)[0]):
                raise _NotUnderstood("its git -c sets something git may run as a command")
            k += 2 if t == "-c" else 1
            continue
        if t.startswith(("--config-env", "--exec-path")):
            raise _NotUnderstood(f"its git {t.split('=', 1)[0]} changes what git runs")
        if t in ("-C", "--git-dir", "--work-tree", "--namespace", "--super-prefix"):
            k += 2
            continue
        if t.startswith("-"):
            k += 1
            continue
        break
    if k < len(args) and args[k] == "config":
        operands = [a for a in args[k + 1:] if not a.startswith("-")]
        if len(operands) >= 2 and _GIT_COMMAND_KEYS.fullmatch(operands[0]):
            raise _NotUnderstood("its git config sets a command git runs later")


def _code_from_input(redirects: list[_Redirect], index: int) -> bool:
    """Whether the program reads its code from standard input: a here-document, a here-string, or the
    pipe it stands at the end of (a file named with < is a script like any other)."""
    for r in redirects:
        if r.op in ("<<", "<<-", "<<<"):
            return True
    return index > 0 and not any(r.op == "<" for r in redirects)


def _reads_code(args: list[_Word], spec: _Interpreter, redirects: list[_Redirect], index: int) -> bool:
    """Whether an interpreter runs code from the command line or from its input, not a script file."""
    inline, operands = spec.inline, spec.operands
    k = 0
    while k < len(args):
        t = args[k].text
        if t in inline or any(t.startswith(opt + "=") for opt in inline if opt.startswith("--")):
            return True
        if len(inline) and t.startswith("-") and not t.startswith("--") and len(t) > 2 and any(
                "-" + ch in inline for ch in t[1:]):
            return True                              # combined short flags (-pe, -ne)
        if t in operands:
            k += 2
            continue
        if spec.module and t == spec.module:
            return False                             # a module is the program, like a script file; input is data
        if t == "-":
            return True                              # the script is standard input
        if t.startswith("-"):
            k += 1
            continue
        if t in inline:                              # a subcommand (deno eval)
            return True
        return False                                 # the first operand is the script file
    return _code_from_input(redirects, index)


def read(text: str) -> Reading:
    """Whether `text` is in the grammar above, and every command it would start."""
    text = str(text or "")
    if _HIDDEN.search(text):
        return Reading(understood=False, why="it contains control or invisible characters")
    commands: list[tuple[str, ...]] = []
    try:
        reader = _Reader(text, 0, [MAX_COMMANDS], commands)
        reader.list_until(frozenset())
        reader.end_of_text()
    except _NotUnderstood as exc:
        return Reading(understood=False, why=exc.why, capped=exc.capped)
    except RecursionError:
        return Reading(understood=False, why="it nests commands deeper than Arslan reads", capped=True)
    return Reading(understood=True, commands=tuple(commands))
