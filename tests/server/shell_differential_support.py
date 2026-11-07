"""Repository-only corpus and bounded bash observations for S2a-3 d.

No reader output decides which stub exists. Paths to approved real wrappers
are withheld when they could bypass the invocation log; fixture paths reach stubs.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess

from server.services.sandbox_profile import NetworkMode, default_deny_profile, literal, subpath

SOURCES = ("test_shell_grammar.py", "test_terminal_policy.py")
ORDINARY = ("git status", "make check", "grep needle notes.txt", "sort names.txt | uniq",
            "env NOTE=sample nice make check", "find . -name '*.txt'", "printf '%s\\n' ready",
            "if true; then git status; else make check; fi")
FAMILIES = ("original", "single-quote", "double-quote", "split-quote", "backslash",
            "assignment", "env", "nice", "nohup", "time", "caffeinate", "nested-bash",
            "pipe", "here-string", "sequence", "comment")
WRAPPERS = {name: "/usr/bin/" + name for name in
            ("env", "nice", "nohup", "time", "xargs", "find", "caffeinate")}
WRAPPERS.update(bash="/bin/bash", sh="/bin/sh", cat="/bin/cat", grep="/usr/bin/grep")
# A missing real timeout is reported as withheld, never replaced by a no-op.
for _name in ("timeout", "gtimeout"):
    WRAPPERS[_name] = shutil.which(_name, path="/usr/bin:/bin:/opt/homebrew/bin:/usr/local/bin")
LOGIN = re.compile(r"(?<![\w-])-(?:lc|cl|l)(?![\w-])|--login\b")
WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_.+-]*")


@dataclass(frozen=True)
class Seed:
    id: str
    text: str


def corpus():
    """Extract literal command inputs, not expected names or executable test code.

    Runtime-built cap/stress inputs and templates are the grammar unit suite's
    responsibility. Source digests in the measurement make corpus drift visible.
    """
    values = []
    for filename in SOURCES:
        tree = ast.parse(Path(__file__).with_name(filename).read_text())
        constants = {n.targets[0].id: n.value.value for n in tree.body
                     if isinstance(n, ast.Assign) and len(n.targets) == 1
                     and isinstance(n.targets[0], ast.Name) and isinstance(n.value, ast.Constant)
                     and isinstance(n.value.value, str)}
        def literal_text(node):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                return node.value
            if isinstance(node, ast.Name):
                return constants.get(node.id)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "attr", getattr(node.func, "id", ""))
                if name == "parametrize" and len(node.args) >= 2:
                    names = literal_text(node.args[0])
                    rows = node.args[1]
                    if names and "command" in names.split(",") and isinstance(rows, (ast.List, ast.Tuple)):
                        index = names.split(",").index("command")
                        for row in rows.elts:
                            value = row.elts[index] if "," in names and isinstance(row, ast.Tuple) else row
                            text = literal_text(value)
                            if text is not None:
                                values.append((filename, text))
                elif name in {"_programs", "_refused", "read", "assess", "ask_rules", "risk_grade"} and node.args:
                    text = literal_text(node.args[0])
                    if text is not None:
                        values.append((filename, text))
            elif isinstance(node, ast.For) and isinstance(node.target, ast.Name) and node.target.id == "command":
                if isinstance(node.iter, (ast.Tuple, ast.List)):
                    values.extend((filename, text) for item in node.iter.elts
                                  if (text := literal_text(item)) is not None)
    values.extend(("ordinary", text) for text in ORDINARY)
    unique = {}
    for origin, text in values:
        key = origin.removeprefix("test_").removesuffix(".py") + "-" + hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()[:12]
        unique.setdefault(text, Seed(key, text))
    return tuple(unique.values())


def variant(family, text):
    """One deterministic transform per seed; no recursive variant explosion."""
    first = re.match(r"[A-Za-z_][A-Za-z0-9_+-]*", text)
    if family in {"single-quote", "double-quote", "split-quote", "backslash"}:
        if first is None:
            return text
        word = first.group()
        form = {"single-quote": "'" + word + "'", "double-quote": '"' + word + '"',
                "split-quote": word[:1] + "''" + word[1:],
                "backslash": "\\" + word[:1] + word[1:]}[family]
        return form + text[len(word):]
    if family == "original":
        return text
    if family == "assignment":
        return "NOTE=sample " + text
    if family in {"env", "nice", "nohup", "time", "caffeinate"}:
        return ("env NOTE=sample " if family == "env" else family + " ") + text
    if family == "nested-bash":
        return "bash -c " + shlex.quote(text)
    if family == "pipe":
        return "printf '%s\\n' " + shlex.quote(text) + " | bash"
    if family == "here-string":
        return "bash <<< " + shlex.quote(text)
    if family == "sequence":
        return text + "\ngit status"
    if family == "comment":
        return text + "\n# differential tail"
    raise ValueError(family)


SEEDS = corpus()
# Lexical inventory is independent of the reader, including concatenated quoted
# pieces. It deliberately over-approximates: argument words get harmless stubs too.
TEXTS = [variant(family, seed.text) for family in FAMILIES for seed in SEEDS]
# A shell searches PATH for a named script too. Do not invent script inputs
# there: interpreting a logging stub as a script is not a program invocation.
SCRIPT_INPUTS = {name.lower() for seed in SEEDS for name in
                 re.findall(r"\b(?:bash|sh)\s+([A-Za-z_][A-Za-z0-9_.-]*\.sh)\b", seed.text, re.I)}
STUB_NAMES = sorted(({word.lower() for text in TEXTS for spelling in
                     (text, text.translate(str.maketrans("", "", "'\"\\")))
                     for word in WORD.findall(spelling)} | set(WRAPPERS)) - SCRIPT_INPUTS)


def withheld(text):
    if LOGIN.search(text):
        return "login"
    # Conservative lexical check, independent of the reader. Ordinary path
    # arguments and refused/missing executables are no longer blanket-withheld.
    spelling = text.translate(str.maketrans("", "", "'\"\\")).lower()
    if re.search(r"/(?:[a-z0-9_.~-]*/)*(?:" + "|".join(WRAPPERS) + r")(?=$|[^a-z0-9_.+-])", spelling):
        return "unlogged-wrapper-path"
    if any(real is None and re.search(r"\b" + name + r"\b", text, re.I)
           for name, real in WRAPPERS.items()):
        return "missing-wrapper"
    return ""


def make_stubs(directory):
    directory.mkdir()
    for name in STUB_NAMES:
        script = '#!/bin/bash -p\nprintf "%s\\n" "${0##*/}" >> "$HOME/invocations"\n'
        if real := WRAPPERS.get(name):
            if name in {"bash", "sh"}:
                # Guard the shell's option prefix even if a future reader
                # mutation admits a new spelling. Never start a login shell.
                script += 'for arg in "$@"; do\n case "$arg" in -c) break;; --login|-*l*) exit 97;; -*) ;; *) break;; esac\ndone\n'
            script += "exec " + real + (" -p" if name in {"bash", "sh"} else "") + ' "$@"\n'
        else:
            script += "exit 0\n"
        path = directory / name
        path.write_text(script)
        path.chmod(0o700)
    return directory


class ShellRun:
    """A fresh HOME/work tree, offline Seatbelt, a fixed executable set, no rc files."""
    def __init__(self, root, stub_dir):
        self.root = Path(root).resolve()
        self.bin = stub_dir.resolve()
        self.log = self.root / "invocations"
        self.env = {"PATH": str(self.bin), "HOME": str(self.root)}
        runtime = [self.root, self.bin, "/bin", "/usr", "/System", "/private/etc",
                   "/private/var/db/dyld", "/private/var/db/timezone"]
        # Optional Homebrew timeout also needs its shared libraries, read-only.
        if any(real and real.startswith("/opt/homebrew/") for real in WRAPPERS.values()):
            runtime.append("/opt/homebrew")
        self.profile = default_deny_profile([self.root], readable=runtime, network=NetworkMode.NONE)
        self.profile += f'(deny file-write* (require-not {subpath(self.root)}))\n'
        self.profile += '(allow file-read* (literal "/"))\n'
        # The null sink holds no data; every persistent write stays in root.
        self.profile += '(allow file-write-data (literal "/dev/null"))\n'
        self.profile += '(deny process-exec)\n'
        self.profile += f'(allow process-exec {subpath(self.bin)})\n'
        for real in sorted({value for value in WRAPPERS.values() if value}):
            self.profile += f'(allow process-exec {literal(Path(real).resolve())})\n'
        # No daemons, devices or preference writes are needed for stub logging.
        self.profile += '(deny mach-lookup)\n(deny user-preference-write)\n'

    def run(self, text, timeout=2):
        self.log.unlink(missing_ok=True)
        with subprocess.Popen(["/usr/bin/sandbox-exec", "-p", self.profile, "/bin/bash", "-p", "-c", text],
                              cwd=self.root, env=self.env, stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              start_new_session=True) as process:
            expired = False
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                expired = True
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass  # The whole group has already exited.
                except PermissionError:
                    if process.returncode is None:
                        raise
                    # Measured with caffeinate: after the parent is reaped,
                    # kernel-owned orphan zombies can keep the group id alive.
                    # Live-parent cleanup failures must still fail the test.
                process.wait()
        names = {name.lower() for name in self.log.read_text().splitlines()} if self.log.exists() else set()
        return names, expired, process.returncode


# Bounded, corpus-derived file contents: the ordinary simple commands, without
# shell syntax or wrappers. This selects git, make and grep from the same corpus.
FILE_SEEDS = tuple(seed for seed in SEEDS if seed.text in ORDINARY
                   and re.fullmatch(r"[a-z]+(?: [A-Za-z0-9_.-]+)+", seed.text))
FILE_FAMILIES = ("path-relative", "path-home", "path-absolute", "path-link",
                 "file-script", "cwd-script", "written-script", "link-script")


def file_variant(family, seed, run):
    """Vary only how a corpus command/file is reached, inside a fresh work tree."""
    name, _, tail = seed.text.partition(" ")
    # Each fixture path resolves to the immutable stub directory, not a new
    # arbitrary-executable grant. A symlink keeps the actual basename unchanged.
    (run.root / "tools").symlink_to(run.bin, target_is_directory=True)
    (run.root / "links").mkdir()
    (run.root / "links" / name).symlink_to(run.bin / name)
    (run.root / "notes.txt").write_text("needle\n")
    if family.startswith("path-"):
        word = {"path-relative": "./tools/" + name,
                "path-home": "~/tools/" + name,
                "path-absolute": str(run.root / "tools" / name),
                "path-link": "./links/" + name}[family]
        return word + " " + tail
    if family == "cwd-script":
        (run.root / "child").mkdir()
        (run.root / "child" / "notes.txt").write_text("needle\n")
        (run.root / "child" / "case.sh").write_text(seed.text + "\n")
        return "cd child; bash case.sh"
    if family == "written-script":
        return "printf '%s\n' " + shlex.quote(seed.text) + " > case.sh; bash case.sh"
    (run.root / "case.sh").write_text(seed.text + "\n")
    if family == "file-script":
        return "bash ./case.sh"
    if family == "link-script":
        (run.root / "linked.sh").symlink_to("case.sh")
        return "bash ./linked.sh"
    raise ValueError(family)
