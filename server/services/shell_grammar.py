"""What Arslan understands of a command's text (S2a-3 c, the user's decision of 2026-10-22).

"Understood" is an allowlist: a small part of bash 3.2, the shell terminal_exec runs (`/bin/bash -p -c`). A command
is understood only when all of its text is in that part; otherwise `why` says what stopped the reader. Refusing costs
little, so a form bash reads in a way that is hard to follow is refused, not modelled. The named policy rules read
its commands and folders; the command gate asks when the reader does not understand the text.

It reads:
  - words of unquoted characters, backslash escapes, '…' and "…"; $NAME, ${NAME}, the special parameters and $( … ),
    quoted or not; glob characters in arguments;
  - ; & && || | ! and newlines; comments outside $( … ); a line continuation with a blank before it;
  - redirections to a file that is written out, here-strings, and here-documents outside $( … ), whose bodies hold
    only $NAME and ${NAME} when the delimiter is unquoted;
  - ( … ), { …; }, if, for, while, until and case (case outside $( … ));
  - NAME=value before a command or on its own, except the names in CODE_VARIABLES;
  - SAFE_BUILTINS, with export, unset, read, printf and set in their plain forms, and test and [ without -v;
  - these wrappers, read through to the command they start, with no options: sudo, nohup, time, nice, caffeinate,
    command (also command -v), exec, env NAME=value…, timeout DURATION, npx / bunx [-y|--yes];
  - bash or sh -c or -lc with its script written out, read again as a command;
  - Python -m MODULE, and find without -exec and its relatives. Every word that decides this is written out.

Everything else is not understood: other quoting forms, backquotes, arithmetic, brace expansion, ${…} with operators,
process substitution, function definitions, [[ … ]], other builtins, a program named by an expansion or a pattern,
any / in a program word, a shell or interpreter running a file, any wrapper option, xargs, awk and other launchers.

`commands` lists, when understood, every simple command in the text, on every branch whether or not a condition skips
it, and each wrapper's command after the wrapper. It goes by name, and in any case, because the default macOS disk
ignores case. It does not say what a named program goes on to start by itself: `make`, `git`, a Python module or a shell's
startup files may start anything, and a copy of bash under another name is just that name.

`folders` says, for each entry of `commands`, every folder it may run in, and `writes` every file a redirection writes
with the folders it is opened in: "" is the work folder, and anything else is where a `cd` or `pushd` with a written-out
target leads from it, joined as text and folded logically (`.` dropped, `x/..` cancelled). Each call starts a fresh
shell in the work folder. A change that may fail (after `;`, `||`, a newline or `!`) leaves both folders possible;
only `&&` gives the new one alone.
A change in a pipeline segment, a ( … ), a $( … ), a bash -c or a backgrounded list stays there. A change the reader
can't follow makes folder observations unknown for the rest of the text, without changing command parsing.
An empty folder tuple means unknown; prefix parsing never follows folder changes.

A read stops at MAX_TEXT characters, MAX_COMMANDS entries in `commands` and MAX_DEPTH levels; past any of them the
command is not understood and `capped` is set. Its time grows linearly with the text: nothing is read again except a
`bash -c` script, once per level.
"""
from __future__ import annotations

import posixpath
import re
import unicodedata
from dataclasses import dataclass
from typing import Callable

MAX_TEXT = 8000             # terminal_policy.MAX_COMMAND_CHARS forbids anything longer
MAX_COMMANDS = 256
MAX_DEPTH = 8               # a level is a $( … ), a ( … ), any other compound command, a bash -c or a wrapper
MAX_FOLDERS = 8             # folders a command may run in
_FOLDER_CHANGES = frozenset({"cd", "pushd", "popd"})

_META = frozenset(" \t\n;&|()<>")
_REDIRECTIONS = ("&>", "<<<", "<<-", "<<", "<>", "<&", ">>", ">&", ">|", "<", ">")
_FILE_DESCRIPTOR = re.compile(r"[0-9]+(?=[<>])")
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ASSIGNMENT = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=")
_PARAMETER_TEXT = r"[A-Za-z_][A-Za-z0-9_]*|[0-9#?$!@*-]"
_PARAMETER = re.compile(_PARAMETER_TEXT)
_BRACED_PARAMETER = re.compile(r"\{(?:" + _PARAMETER_TEXT + r")\}")
# What runs or continues in an unquoted here-document's body. A backslash doesn't save it: refusing costs nothing.
_BODY_RUNS = re.compile(r"`|\$[(\[]|\$\{(?!(?:" + _PARAMETER_TEXT + r")\})|\\$")
# No `=` and no leading `-`, so a wrapper's option or `sudo A=1` is not a program. A tilde is only `~/`: `~-` is $OLDPWD.
_PROGRAM = re.compile(r"\[|~/[A-Za-z0-9_.+/~@:,-]*|[A-Za-z0-9_./@:][A-Za-z0-9_.+/~@:,-]*")
_DURATION = re.compile(r"[0-9.]+[smhd]?")

_THEN = frozenset({"then"})
_ARMS = frozenset({"elif", "else", "fi"})
_FI = frozenset({"fi"})
_DO = frozenset({"do"})
_DONE = frozenset({"done"})
_RBRACE = frozenset({"}"})
_ESAC = frozenset({"esac"})
_CLOSERS = frozenset({"then", "elif", "else", "fi", "do", "done", "esac", "}", "in"})
_UNREAD_KEYWORDS = frozenset({"function", "select", "coproc", "[["})

# Builtins that only run, print or test. export, unset, read, printf and set can assign: _check_builtin holds them to
# their plain forms. Every other bash builtin changes how later text is read or runs text of its own.
SAFE_BUILTINS = frozenset({"cd", "echo", "printf", "test", "[", "true", "false", ":", "pwd", "read", "exit", "return",
                           "shift", "wait", "umask", "type", "kill", "times", "ulimit", "break", "continue", "dirs",
                           "pushd", "popd", "export", "unset", "set"})
_ASSIGNING_BUILTINS = frozenset({"export", "unset", "read", "printf", "set"})
_OTHER_BUILTINS = frozenset({"alias", "unalias", "eval", "source", ".", "trap", "declare", "typeset", "local", "readonly",
                             "let", "shopt", "enable", "hash", "fc", "bind", "complete", "compgen", "compopt", "caller",
                             "disown", "fg", "bg", "suspend", "logout", "history", "help", "mapfile", "readarray",
                             "builtin", "getopts", "jobs"})
_SET_FLAGS = re.compile(r"[-+](?=.)[eux]*o?")
_SET_OPTIONS = frozenset({"errexit", "nounset", "xtrace", "pipefail"})

# Variables the shell itself reads, and known ones programs take code or a command from: assigning one changes what the
# rest of the text means, which this reader does not follow. Not a complete list of the second kind, which can't be.
CODE_VARIABLES = frozenset({
    "PATH", "IFS", "ENV", "BASH_ENV", "SHELLOPTS", "BASHOPTS", "GLOBIGNORE", "CDPATH", "PS4", "HOME", "PWD", "OLDPWD",
    "LANG", "LC_ALL", "LC_CTYPE", "PROMPT_COMMAND", "POSIXLY_CORRECT", "EXECIGNORE", "PAGER", "GIT_PAGER", "MANPAGER",
    "EDITOR", "VISUAL", "GIT_EDITOR", "GIT_SEQUENCE_EDITOR", "GIT_SSH", "GIT_SSH_COMMAND", "GIT_ASKPASS", "SSH_ASKPASS",
    "GIT_PROXY_COMMAND", "GIT_EXTERNAL_DIFF", "GIT_EXEC_PATH", "GIT_DIR", "GIT_CONFIG", "GIT_CONFIG_GLOBAL",
    "GIT_CONFIG_SYSTEM", "GIT_CONFIG_PARAMETERS", "LESSOPEN", "LESSCLOSE", "BROWSER", "ZDOTDIR", "LUA_INIT", "PERL5OPT",
    "PERL5LIB", "PERLLIB", "NODE_OPTIONS", "NODE_PATH", "PYTHONSTARTUP", "PYTHONPATH", "PYTHONHOME", "RUBYOPT", "RUBYLIB",
    "JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS"})
_CODE_VARIABLE_PREFIXES = ("BASH_FUNC_", "LD_", "DYLD_", "GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")

_PLAIN_WRAPPERS = frozenset({"sudo", "nohup", "time", "nice", "caffeinate", "command", "exec"})
# Programs that take a command from their own syntax or from data. osascript and shortcuts are not read here: layer ②
# always asks for them by name (`apple-events`, `shortcuts`), and U11 runs an approved plain call by that name.
_LAUNCHERS = frozenset({"watch", "script", "tmux", "screen", "parallel", "concurrently", "su", "sg", "runuser", "flock",
                        "entr", "nodemon", "arch", "xcrun", "stdbuf", "setsid", "sandbox-exec", "xargs", "gxargs", "gfind",
                        "awk", "gawk", "nawk", "mawk", "lockf"})
# Programs whose code is not in the command text, except the inline shells and Python modules read below.
_INTERPRETER = re.compile(r"(?:bash|sh|zsh|ksh|mksh|dash|ash|fish|csh|tcsh|pwsh|nu|xonsh|elvish|yash|rc|python|pypy|node"
                          r"|nodejs|deno|bun|perl|ruby|php|rscript|lua|luajit|tclsh|swift|julia)[0-9.-]*")
_PYTHONS = ("python", "pypy")
_NON_SCRIPT_SUBCOMMANDS = {"swift": {"build"}, "bun": {"install"}, "deno": {"info"}}
_FIND_RUNS = frozenset({"-exec", "-execdir", "-ok", "-okdir"})


@dataclass(frozen=True, kw_only=True)
class Reading:
    understood: bool
    why: str = ""
    capped: bool = False       # past MAX_TEXT, MAX_COMMANDS or MAX_DEPTH: nothing more of it should be built
    # Each command as its words with quotes removed (an expansion shows as written). Empty unless `understood`.
    commands: tuple[tuple[str, ...], ...] = ()
    folders: tuple[tuple[str, ...], ...] = ()                   # one per command; "" is the work folder
    writes: tuple[tuple[str, tuple[str, ...]], ...] = ()        # (file, its folders) for each redirection that writes

    # Ordered effect observations; None is a write or an assignment of unknown effect.
    effects: tuple[tuple[str, ...] | None, ...] = ()
    # Events in [start, end) also depend on [other_start, other_end), e.g. another pipeline segment.
    effect_scopes: tuple[tuple[int, int, int, int], ...] = ()


class _Out:
    __slots__ = ("commands", "folders", "writes", "fold_partial", "fold_guard", "effects", "effect_scopes", "backgrounds",
                 "track_folders", "folders_known", "owners", "carriers")

    def __init__(self, fold_partial: bool = True, fold_guard=None, *, track_folders=False):
        self.track_folders = track_folders
        self.folders_known = True
        self.fold_partial = fold_partial
        self.fold_guard = fold_guard
        self.effects = []
        self.effect_scopes = []
        self.backgrounds = []
        self.commands: list[tuple[str, ...]] = []
        self.folders: list[tuple[str, ...]] = []
        self.writes: list[tuple[str, tuple[str, ...]]] = []
        self.owners: list[int] = []          # one per write: the index in `commands` it is on, or -1
        self.carriers: set[int] = set()      # indexes in `commands` that only start the ones after them


@dataclass(frozen=True, kw_only=True)
class PrefixReading:
    """Commands parsed before a refusal, for additive policy checks only.

    This is never evidence that the whole input is understood. In particular,
    nothing after the first unread form is scanned or treated as a command.

    For the card's steps (card_purpose, LOOP1 d2b), read only when not `refused`: `writes` is each file a redirection
    writes, with the index in `commands` of the simple command it is on (-1: on a compound command, or with no
    command), and `carriers` the indexes of entries that only start the entries after them (a wrapper read through to
    its command, or bash -c with its script). Neither changes what is read or refused.
    """
    commands: tuple[tuple[str, ...], ...] = ()
    refused: bool = False
    why: str = ""
    capped: bool = False
    writes: tuple[tuple[str, int], ...] = ()
    carriers: frozenset[int] = frozenset()


class _NotUnderstood(Exception):
    def __init__(self, why: str, capped: bool = False):
        super().__init__(why)
        self.why = why
        self.capped = capped


class _Word:
    __slots__ = ("chars", "assigns", "expanded", "globbed", "quoted")

    def __init__(self):
        self.chars: list[str] = []
        self.assigns: str | None = None  # NAME of a word that starts NAME=, unquoted
        self.expanded = False            # holds $NAME, ${NAME}, a special parameter or $( … )
        self.globbed = False             # holds an unquoted * ? or [
        self.quoted = False              # any part was quoted or escaped

    @property
    def text(self) -> str:
        return "".join(self.chars)

    @property
    def literal(self) -> str | None:
        """Its value, when the text alone fixes it."""
        return None if self.expanded or self.globbed else self.text

    @property
    def keyword(self) -> str | None:
        """Its text, when a reserved word could be written that way."""
        return None if self.quoted else self.text


class _Reader:
    def __init__(self, text: str, depth: int, out: _Out, in_substitution: bool = False,
                 here: frozenset[str] = frozenset({""})):
        self.s = text
        self.i = 0
        self.depth = depth
        self._check_depth()
        self.out = out                       # shared by every nested reading
        self.commands = out.commands
        self.in_substitution = in_substitution
        self.here = here                     # the folders the next command may run in
        self.failed: frozenset[str] = frozenset()   # where it is instead if a change of folder since failed
        self.loops = 0
        self.heredocs: list[tuple[str, bool, bool]] = []    # (delimiter, quoted, strip tabs) waiting for a newline
        self.peeked = None

    def _check_depth(self) -> None:
        if self.depth > MAX_DEPTH:
            raise _NotUnderstood("it nests commands deeper than Arslan reads", capped=True)

    # ── lexing ──────────────────────────────────────────────────────────────

    def _blank(self) -> None:
        s, n = self.s, len(self.s)
        while self.i < n:
            c = s[self.i]
            if c in " \t":
                self.i += 1
            elif c == "\\" and s.startswith("\n", self.i + 1):
                if self.i and s[self.i - 1] not in " \t\n":
                    raise _NotUnderstood("a line continuation touches a token")
                self.i += 2
            elif c == "#":
                self._no_hash_here()
                end = s.find("\n", self.i)
                self.i = n if end == -1 else end     # a comment runs to the end of its line
            else:
                return

    def _no_hash_here(self) -> None:
        if self.in_substitution:
            raise _NotUnderstood("it has a # inside $( … ), which bash 3.2 can read as ending it")

    def peek(self):
        if self.peeked is None:
            self.peek_effect_start = len(self.out.effects)
            self.peeked = self._token()
        return self.peeked

    def take(self):
        token = self.peek()
        self.peeked = None
        return token

    def _skip_newlines(self) -> None:
        while self.peek()[0] == "nl":
            self.take()

    def _at(self, keyword: str) -> bool:
        token = self.peek()
        return token[0] == "word" and token[1].keyword == keyword

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
        if s.startswith((";;&", ";&", "|&", "&>>"), i):
            raise _NotUnderstood("it uses bash 4 operators the shell here (bash 3.2) does not have")
        if s.startswith(("&&", "||", ";;"), i):
            self.i += 2
            return ("op", s[i:i + 2])
        if s.startswith("&>", i) or c in "<>":
            return self._redirect_operator()
        if c in ";&|()":
            self.i += 1
            return ("op", c)
        descriptor = _FILE_DESCRIPTOR.match(s, i)
        if descriptor:
            self.i = descriptor.end()
            return self._redirect_operator()
        return ("word", self._word())

    def _redirect_operator(self):
        s, i = self.s, self.i
        if s.startswith(("<(", ">("), i):
            raise _NotUnderstood("it uses process substitution")
        op = next(op for op in _REDIRECTIONS if s.startswith(op, i))
        self.i = i + len(op)
        return ("redir", op)

    def _word(self) -> _Word:
        s, n = self.s, len(self.s)
        w = _Word()
        start = self.i
        assignment = _ASSIGNMENT.match(s, start)
        if assignment:
            w.assigns = assignment.group(1)
        while self.i < n:
            c = s[self.i]
            if c in _META:
                break
            if c == "'":
                end = s.find("'", self.i + 1)
                if end == -1:
                    raise _NotUnderstood("its quoting does not close")
                w.chars.append(s[self.i + 1:end])
                w.quoted = True
                self.i = end + 1
            elif c == '"':
                self._double_quoted(w)
            elif c == "\\":
                nxt = s[self.i + 1:self.i + 2]
                if not nxt:
                    raise _NotUnderstood("it ends in a lone backslash")
                if nxt == "\n":
                    raise _NotUnderstood("a line continuation splits a word")
                w.chars.append(nxt)
                w.quoted = True
                self.i += 2
            elif c == "$":
                self._dollar(w)
            elif c == "`":
                raise _NotUnderstood("it uses backquotes")
            elif c in "{}":
                nxt = s[self.i + 1:self.i + 2]
                if self.i != start or (nxt and nxt not in _META):
                    raise _NotUnderstood("it uses brace expansion")
                w.chars.append(c)                    # a group's opening or closing word
                self.i += 1
            else:
                if c == "#":
                    self._no_hash_here()             # `\ #` reads as a comment to bash 3.2's scan
                elif c in "*?[":
                    w.globbed = True
                w.chars.append(c)
                self.i += 1
        if w.chars == ["["]:
            w.globbed = False                        # the test builtin's name
        return w

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
                nxt = s[self.i + 1:self.i + 2]
                if nxt == "\n":
                    raise _NotUnderstood("a line continuation splits a word")
                if nxt in ("$", "`", '"', "\\"):
                    w.chars.append(nxt)
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
        s, i = self.s, self.i
        nxt = s[i + 1:i + 2]
        if nxt in ("'", '"'):
            raise _NotUnderstood("it uses $'…' or $\"…\" quoting")
        if nxt == "[" or s.startswith("((", i + 1):
            raise _NotUnderstood("it uses shell arithmetic")
        if nxt == "(":
            inner = _Reader(s, self.depth + 1, self.out, in_substitution=True, here=self.here)
            inner.i = i + 2
            inner.list_until(closing=True, may_be_empty=True)
            inner.take()
            end = inner.i
        elif nxt == "{":
            m = _BRACED_PARAMETER.match(s, i + 1)
            if not m:
                raise _NotUnderstood("it uses ${…} with an operator")
            end = m.end()
        else:
            m = _PARAMETER.match(s, i + 1)
            if not m:
                w.chars.append("$")                  # a $ before anything else is a plain character
                self.i += 1
                return
            end = m.end()
        w.chars.append(s[i:end])
        w.expanded = True
        self.i = end

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
                self.i = len(s) if end == -1 else end + 1
                if not quoted and _BODY_RUNS.search(line):
                    raise _NotUnderstood("its here-document runs a command or continues a line")
                if (line.lstrip("\t") if strip else line) == delimiter:
                    break

    # ── grammar ─────────────────────────────────────────────────────────────

    def read_all(self) -> None:
        self.list_until(may_be_empty=True)
        if self.heredocs:
            raise _NotUnderstood("its here-document does not end")

    def list_until(self, stops: frozenset[str] = frozenset(), closing: bool = False, may_be_empty: bool = False) -> None:
        """Commands up to a reserved word in `stops`, the `)` when `closing`, or the end of the text. Only the end of a
        case arm stops at `;;`. What stopped it is left unread."""
        empty = separated = True
        while True:
            token = self.peek()
            if token[0] == "nl":
                self.take()
                separated = True
                continue
            if token[0] == "eof" and (stops or closing):
                raise _NotUnderstood("a compound command in it does not close")
            if (token[0] == "eof" or (closing and token == ("op", ")"))
                    or (token[0] == "word" and token[1].keyword in stops)
                    or (stops is _ESAC and token == ("op", ";;"))):
                if empty and not may_be_empty:
                    raise _NotUnderstood("its syntax is not one Arslan reads")
                return
            if not separated:
                raise _NotUnderstood("its syntax is not one Arslan reads")
            effect_start = self.peek_effect_start
            before = (self.here, self.failed)
            self._and_or()
            empty = separated = False
            if self.peek() in (("op", ";"), ("op", "&")):
                if self.take() == ("op", "&"):
                    self.out.backgrounds.append((effect_start, len(self.out.effects)))
                    self.here, self.failed = before      # a backgrounded list runs in a subshell
                separated = True

    def _settle(self) -> None:
        self.here, self.failed = self.here | self.failed, frozenset()

    def _and_or(self) -> None:
        self._pipeline()
        exact = True                             # every pipeline so far succeeded, if the next one runs
        while self.peek() in (("op", "&&"), ("op", "||")):
            exact = self.take() == ("op", "&&") and exact
            if not exact:
                self._settle()
            self._skip_newlines()
            self._pipeline()
        self._settle()

    def _pipeline(self) -> None:
        self.peek()
        start = self.peek_effect_start
        negated = self._at("!")
        if negated:
            self.take()
        before = (self.here, self.failed)
        self._command()
        segments = [(start, len(self.out.effects))]
        while self.peek() == ("op", "|"):
            self.here, self.failed = before      # each segment runs in a subshell of its own
            self.take()
            self._skip_newlines()
            start = self.peek_effect_start
            self._command()
            segments.append((start, len(self.out.effects)))
            self.here, self.failed = before
        for start, end in segments:
            if end < segments[-1][1]:
                self.out.effect_scopes.append((start, end, end, segments[-1][1]))
        if negated:
            self._settle()

    def _command(self) -> None:
        token = self.peek()
        if token[0] == "word":
            keyword = token[1].keyword
            if keyword in _UNREAD_KEYWORDS:
                raise _NotUnderstood(f"it uses `{keyword}`, which Arslan does not read")
            if keyword in _CLOSERS:
                raise _NotUnderstood(f"its `{keyword}` stands where no compound command opened")
            compound = self._COMPOUNDS.get(keyword)
        elif token == ("op", "("):
            compound = _Reader._subshell
        elif token[0] == "redir":
            compound = None
        else:
            raise _NotUnderstood("its syntax is not one Arslan reads")
        if compound is None:
            self._simple()
            return
        start = len(self.out.effects)
        self.depth += 1
        self._check_depth()
        compound(self)
        self.depth -= 1
        end = len(self.out.effects)
        while self.peek()[0] == "redir":
            self._redirection()
        self.out.effect_scopes.append((start, end, end, len(self.out.effects)))

    def _subshell(self) -> None:
        self.take()
        if self.s.startswith("(", self.i):
            raise _NotUnderstood("it uses shell arithmetic")
        before = (self.here, self.failed)
        self.list_until(closing=True)
        self.take()
        self.here, self.failed = before

    def _group(self) -> None:
        self.take()
        self.list_until(_RBRACE)
        self.take()

    def _if(self) -> None:
        self.take()
        while True:
            self.list_until(_THEN)
            self.take()
            self.list_until(_ARMS)
            arm = self.take()[1].keyword
            if arm == "fi":
                return
            if arm == "else":
                self.list_until(_FI)
                self.take()
                return

    def _for(self) -> None:
        self.take()
        name = self.take()
        if name[0] != "word" or not _NAME.fullmatch(name[1].keyword or ""):
            raise _NotUnderstood("its for loop is not one Arslan reads")
        _check_assigned(name[1].text)
        if self.peek() == ("op", ";"):
            self.take()
        else:
            self._skip_newlines()
            if self._at("in"):
                self.take()
                while self.peek()[0] == "word":
                    self.take()
                if self.peek()[0] != "nl" and self.peek() != ("op", ";"):
                    raise _NotUnderstood("its for loop is not one Arslan reads")
                self.take()
        self._skip_newlines()
        if not self._at("do"):
            raise _NotUnderstood("its for loop is not one Arslan reads")
        self.take()
        self.loops += 1
        self.list_until(_DONE)
        self.loops -= 1
        self.take()

    def _loop(self) -> None:
        self.take()
        self.loops += 1                          # a change of folder in a loop moves again each time round
        self.list_until(_DO)
        self.take()
        self.list_until(_DONE)
        self.loops -= 1
        self.take()

    def _case(self) -> None:
        if self.in_substitution:
            raise _NotUnderstood("it puts a case inside $( … ), which bash 3.2 misreads")
        self.take()
        if self.take()[0] != "word":
            raise _NotUnderstood("its case is not one Arslan reads")
        self._skip_newlines()
        if not self._at("in"):
            raise _NotUnderstood("its case is not one Arslan reads")
        self.take()
        while True:
            self._skip_newlines()
            if self._at("esac"):
                self.take()
                return
            if self.peek()[0] == "eof":
                raise _NotUnderstood("a compound command in it does not close")
            if self.peek() == ("op", "("):
                self.take()
            while True:                              # pattern [| pattern]… )
                if self.take()[0] != "word":
                    raise _NotUnderstood("its case pattern is not one Arslan reads")
                after = self.take()
                if after == ("op", ")"):
                    break
                if after != ("op", "|"):
                    raise _NotUnderstood("its case pattern is not one Arslan reads")
            self.list_until(_ESAC, may_be_empty=True)
            if self.peek() == ("op", ";;"):
                self.take()

    _COMPOUNDS = {"{": _group, "if": _if, "for": _for, "while": _loop, "until": _loop, "case": _case}

    def _redirection(self) -> None:
        op = self.take()[1]
        here_document = op in ("<<", "<<-")
        if here_document and self.in_substitution:
            raise _NotUnderstood("it puts a here-document inside $( … ), which bash 3.2 misreads")
        target = self.take()
        if target[0] != "word":
            raise _NotUnderstood("its here-document has no delimiter" if here_document else "its redirection has no target")
        word = target[1]
        if here_document:
            if word.expanded:
                raise _NotUnderstood("its here-document delimiter is an expansion")
            self.heredocs.append((word.text, word.quoted, op == "<<-"))
        elif op != "<<<":
            if word.literal is None:
                raise _NotUnderstood("its redirection goes to an expansion or a pattern")
            if "/dev/tcp/" in word.text or "/dev/udp/" in word.text:
                raise _NotUnderstood("its redirection opens a network socket")
            if op in ("<&", ">&") and word.text.startswith("-") and word.text != "-":
                raise _NotUnderstood("its redirection has text after the -, which bash reads as a program")
            if op != "<" and not (op in ("<&", ">&") and (word.text.isdigit() or word.text == "-")):
                self.out.writes.append((word.text, tuple(sorted(self.here)) if self.out.folders_known else ()))
                self.out.owners.append(-1)           # a simple command's own: `_simple` says which
                self.out.effects.append(None)

    def _simple(self) -> None:
        words: list[_Word] = []
        own: list[int] = []                          # this command's writes, not a $( … )'s inside its words
        while True:
            token = self.peek()
            if token[0] == "redir":
                before = len(self.out.writes)
                self._redirection()
                own.extend(range(before, len(self.out.writes)))
                continue
            if token[0] != "word":
                break
            word = self.take()[1]
            if not words and word.assigns is not None:
                _check_assigned(word.assigns)
                self.out.effects.append(None)
            else:
                words.append(word)
            if self.peek() == ("op", "("):
                raise _NotUnderstood("it defines a function or an array")
        if words:
            for k in own:                            # the entry `_started` adds first: every $( … ) in it is in
                self.out.owners[k] = len(self.commands)
            self._started(words)

    # ── what runs ───────────────────────────────────────────────────────────

    def _started(self, words: list[_Word]) -> None:
        """A simple command: the program it starts, read through the wrappers to the one that runs."""
        layers = 0
        while True:
            name = words[0].literal
            if name is None:
                raise _NotUnderstood("the program it runs comes from a variable, a substitution or a pattern")
            if "/" in name:
                raise _NotUnderstood("its program word contains a path")
            if not _PROGRAM.fullmatch(name):
                raise _NotUnderstood("its program name, or a wrapper's option, is not one Arslan reads")
            if len(self.commands) >= MAX_COMMANDS:
                raise _NotUnderstood("it has more commands than Arslan reads before running", capped=True)
            self.commands.append(tuple(w.text for w in words))
            self.out.effects.append(tuple(w.text for w in words))
            self.out.folders.append(tuple(sorted(self.here)) if self.out.folders_known else ())
            base = name.lower()
            args = words[1:]
            if self.out.track_folders and self.out.folders_known and base in _FOLDER_CHANGES:
                self._change_folder(base, args, layers)
            if base in _OTHER_BUILTINS:
                raise _NotUnderstood(f"it uses `{base}`, which changes how the shell reads what follows")
            if base in SAFE_BUILTINS:
                if layers and base in _ASSIGNING_BUILTINS:      # `command export A=$x` splits $x, and assigns the rest
                    raise _NotUnderstood(f"it runs {base} through a wrapper")
                _check_builtin(base, args)
                return
            if base in _LAUNCHERS:
                raise _NotUnderstood(f"`{base}` takes a program of its own, which Arslan does not read")
            wrapped = _after_wrapper(base, args)
            if wrapped is None:
                self._program(base, args)
                return
            if not wrapped:
                return
            self.out.carriers.add(len(self.commands) - 1)
            words = wrapped
            layers += 1
            if layers > MAX_DEPTH:
                raise _NotUnderstood("it nests commands deeper than Arslan reads", capped=True)

    def _change_folder(self, base: str, args: list[_Word], layers: int) -> None:
        """S2a-3 step 4: where a cd or pushd leads, from every folder the shell may be in."""
        value = args[0].literal if len(args) == 1 and base != "popd" else None
        if (layers or self.loops or not value or value.startswith(("-", "+"))
                or (value.startswith("~") and (args[0].quoted or not (value == "~" or value.startswith("~/"))))):
            self.out.folders_known = False
            return
        joined = (value if value.startswith(("/", "~")) or not f else f"{f.rstrip('/')}/{value}"
                  for f in self.here)
        def select(folder):
            normal = _logical_folder(folder)
            prefix = _fold_prefix(folder)
            # The optional policy guard runs at the move, not at a later endpoint. The first
            # reading has already collected effects from all concurrent segments and redirects.
            if (self.out.fold_guard is not None and ".." in folder.split("/") and normal != folder
                    and not normal.startswith(("/", "~")) and ".." not in normal.split("/")):
                return normal if self.out.fold_guard(prefix, len(self.out.effects)) else folder
            return normal if self.out.fold_partial or not prefix else folder

        moved = frozenset(select(f) for f in joined)
        if len(moved | self.here | self.failed) > MAX_FOLDERS:
            self.out.folders_known = False
            return
        self.failed, self.here = self.failed | self.here, moved

    def _program(self, base: str, args: list[_Word]) -> None:
        if base == "find":
            for w in args:
                if w.literal is None or w.text in _FIND_RUNS:
                    raise _NotUnderstood("its find runs a command, or may from an expansion")
        elif _INTERPRETER.fullmatch(base):
            first = args[0].literal if args else None
            if first in _NON_SCRIPT_SUBCOMMANDS.get(base, ()):
                return
            if base in ("bash", "sh") and first in ("-c", "-lc"):
                if not _names_something(args[1:]):
                    raise _NotUnderstood("it runs a shell script that is not written out")
                self.out.carriers.add(len(self.commands) - 1)
                _Reader(args[1].text, self.depth + 1, self.out, here=self.here).read_all()
            elif not (first == "-m" and base.startswith(_PYTHONS) and _names_something(args[1:])):
                raise _NotUnderstood(f"it runs a {base} script whose code the text does not say")


def _logical_folder(folder: str) -> str:
    """Bash's default logical cd, without resolving the work folder or home on disk.

    Home is an unknown anchor: a parent beyond it must remain outside, just like a leading parent beyond the work
    folder. This folds only the shell's folder; delete operands keep their own parent-component check.
    """
    home = folder == "~" or folder.startswith("~/")
    collapsed = re.sub(r"/+", "/", folder)
    normal = posixpath.normpath(collapsed[2:] if home else collapsed)
    if home:
        return "~" if normal == "." else f"~/{normal}"
    return "" if normal == "." else normal


def _fold_prefix(folder: str) -> str:
    """Work-relative prefix retained by a cancellation; empty means no containment check.

    Only surviving components retained at a cancellation need checking.
    Home, absolute and leading-parent destinations already remain outside the work anchor.
    This is text-only; policy decides whether a retained prefix is safe on disk.
    """
    normal = _logical_folder(folder)
    if not normal or normal.startswith(("/", "~")) or normal == ".." or normal.startswith("../"):
        return ""
    stack: list[str] = []
    kept = 0
    for part in folder.split("/"):
        if part in ("", "."):
            continue
        if part == ".." and stack and stack[-1] != "..":
            stack.pop()
            kept = len(stack)
        else:
            stack.append(part)
    return "/".join(stack[:kept])


def _names_something(args: list[_Word]) -> bool:
    """The first word is written out, can't be an option, and has no /dev/ in it, in any case: that path can be the
    text's own input. So a `bash -c` script or a printf format with /dev/ in it is refused too; that costs little."""
    value = args[0].literal if args else None
    return value is not None and value[:1] not in ("-", "+") and "/dev/" not in value.lower()


def _check_assigned(name: str) -> None:
    if name in CODE_VARIABLES or name.startswith(_CODE_VARIABLE_PREFIXES):
        raise _NotUnderstood(f"it sets {name}, which changes what the rest of it runs")


def _check_builtin(base: str, args: list[_Word]) -> None:
    if base in ("export", "unset", "read"):
        names = args[1:] if base == "read" and args and args[0].text == "-r" else args
        for w in names:
            name = w.text.split("=", 1)[0]
            if not _NAME.fullmatch(name):
                raise _NotUnderstood(f"its {base} is not one Arslan reads")
            _check_assigned(name)
    elif base == "printf":
        if args and not _names_something(args):
            raise _NotUnderstood("its printf is not one Arslan reads")
    elif base in ("test", "[") and any(w.text == "-v" for w in args):    # bash 4.2 and up evaluate an array subscript
        raise _NotUnderstood(f"its {base} uses -v, which can run a command in a newer bash")
    elif base == "set":
        k = 0
        while k < len(args):
            flag = args[k].text
            if flag == "--":
                return                               # the rest are positional parameters
            if not _SET_FLAGS.fullmatch(flag):
                raise _NotUnderstood("its set option is not one Arslan reads")
            k += 1
            if flag.endswith("o"):
                if k >= len(args) or args[k].text not in _SET_OPTIONS:
                    raise _NotUnderstood("its set option is not one Arslan reads")
                k += 1


def _after_wrapper(base: str, args: list[_Word]) -> list[_Word] | None:
    """The words of the command a wrapper starts, [] when it starts none, or None when `base` is not a wrapper."""
    if base in _PLAIN_WRAPPERS:
        return [] if base == "command" and args and args[0].text in ("-v", "-V") else args
    if base == "env":
        k = 0
        while k < len(args) and "=" in args[k].text:     # to env, any word with = in it is a setting
            name = args[k].text.split("=", 1)[0]
            if args[k].literal is None or not _NAME.fullmatch(name):
                raise _NotUnderstood("its env setting is not one Arslan reads")
            _check_assigned(name)
            k += 1
        return args[k:]
    if base in ("timeout", "gtimeout"):
        if not args or not _DURATION.fullmatch(args[0].literal or ""):
            raise _NotUnderstood(f"its {base} is not one Arslan reads")
        return args[1:]
    if base in ("npx", "bunx"):
        return args[1:] if args and args[0].text in ("-y", "--yes") else args
    return None


def _unseen(c: str) -> bool:
    """A control, format or unassigned character, or a space other than the plain one."""
    return c not in " \t\n" and unicodedata.category(c)[0] in "CZ"


def _read_commands(text: str, out: _Out) -> PrefixReading:
    """Read once into shared observations, retaining commands on refusal only for additive rules."""
    if not isinstance(text, str):
        return PrefixReading(refused=True, why="it is not text")
    if len(text) > MAX_TEXT:
        return PrefixReading(refused=True, why="it is longer than Arslan reads", capped=True)
    if any(map(_unseen, set(text))):
        return PrefixReading(refused=True, why="it contains control or invisible characters")
    try:
        _Reader(text, 0, out).read_all()
    except _NotUnderstood as exc:
        return PrefixReading(commands=tuple(out.commands), refused=True, why=exc.why, capped=exc.capped)
    except RecursionError:
        return PrefixReading(commands=tuple(out.commands), refused=True,
                             why="it nests commands deeper than Arslan reads", capped=True)
    return PrefixReading(commands=tuple(out.commands), writes=tuple(zip((f for f, _ in out.writes), out.owners)),
                         carriers=frozenset(out.carriers))


def _read_prefix(text: str) -> PrefixReading:
    """Prefix mode has no folder-tracking side effects, including in nested readers."""
    return _read_commands(text, _Out())


def read_prefix(text: str) -> PrefixReading:
    """Read commands before a refusal for additive policy checks only."""
    return _read_prefix(text)


def read(text: str, *, fold_partial: bool = True,
         fold_guard: Callable[[str, int], bool] | None = None) -> Reading:
    """Read commands and folders; a refusal never exposes partial observations.

    With fold_partial=False, retain work-relative partial cancellations as written.
    Policy can supply fold_guard(prefix, effect_position) on a second reading to select
    candidates using the first reading's effect scopes. Filesystem checks belong to that
    optional policy callback; the default reader remains filesystem-free.
    """
    out = _Out(fold_partial, fold_guard, track_folders=True)
    prefix = _read_commands(text, out)
    if prefix.refused:
        return Reading(understood=False, why=prefix.why, capped=prefix.capped)
    # A background part can still be running when any later part of this text starts.
    out.effect_scopes.extend((start, end, end, len(out.effects)) for start, end in out.backgrounds)
    return Reading(understood=True, commands=tuple(out.commands), folders=tuple(out.folders), writes=tuple(out.writes),
                   effects=tuple(out.effects), effect_scopes=tuple(out.effect_scopes))
