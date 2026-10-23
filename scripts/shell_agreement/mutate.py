"""Mechanical forms of a command (card S2a-3 d, "自动变形"): the same text with a wrapper program in
front, in a chain, inside a compound command, or re-quoted into `bash -c`. Nothing here is a crafted
escape; each form is an ordinary way a person or a model writes the same command, and the real-shell
comparison judges every form the same way it judges the original."""
from __future__ import annotations

import shlex
from collections.abc import Iterator

# Wrapper programs the reader reads through; the real program starts the command after its options.
PREFIXES = ("nohup {c}", "env {c}", "env -i {c}", "env FOO=bar {c}", "command {c}", "exec {c}",
            "nice -n 5 {c}", "timeout 30 {c}", "time {c}", "sudo {c}", "sudo -u nobody {c}",
            "caffeinate -i {c}", "setsid {c}", "stdbuf -oL {c}", "builtin command {c}")
# The command in a chain or a compound command.
STRUCTURES = ("true && {c}", "false || {c}", ": ; {c}", "{c} ; :", "{c} &", "! {c}", "( {c} )", "{{ {c} ; }}",
              "if true; then {c}; fi", "if false; then :; else {c}; fi", "for i in 1 2; do {c}; done",
              "while false; do :; done; {c}", "case x in x) {c};; esac", "echo $( {c} )", "x=$( {c} )",
              "echo `{c}`", "{c} > out.txt", "{c} 2>&1", "{c} < /dev/null", "> out.txt {c}",
              "FOO=bar {c}", "LC_ALL=C {c}", "{c} # a comment", "\t{c}\n", "{c}\n\n")
# The command handed to a shell again, re-quoted.
CARRIERS = ("bash -c {q}", "sh -c {q}", "bash -lc {q}", "bash -euo pipefail -c {q}", "eval {q}",
            "bash -c {d}", "echo {q} | bash", "bash <<'EOF'\n{c}\nEOF", "bash <<EOF\n{c}\nEOF",
            "bash -s <<< {q}", "xargs -0 -I{{}} {c} < /dev/null", "find . -maxdepth 0 -exec {c} \;",
            "watch -n 1 {q}", "script -q /dev/null -c {q}", "tmux new {q}", "npx -y {c}")


def _double_quoted(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`") + '"'


def forms(command: str) -> Iterator[tuple[str, str]]:
    """Each mechanical form of `command` with the template that made it. A command of several lines
    only takes the forms that keep lines whole (a here-document inside `bash -c '…'` still works, a
    here-document inside `$( )` on one line does not)."""
    one_line = "\n" not in command
    quoted = shlex.quote(command)
    for template in PREFIXES:
        if one_line:
            yield template, template.format(c=command)
    for template in STRUCTURES:
        if one_line or template in ("{c} ; :", "{c} &", "{c}\n\n", "\t{c}\n", "{c} 2>&1"):
            yield template, template.format(c=command)
    for template in CARRIERS:
        if "{c}" in template and not one_line and "EOF" not in template:
            continue
        yield template, template.format(c=command, q=quoted, d=_double_quoted(command))
