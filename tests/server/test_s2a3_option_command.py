"""S2a-3 interim: a tool given a command to run in an option's value asks, as `unreadable` (0.1.64 release blocker).

The reader treated these option values as data, so whatever they held ran with no card. Until the payload itself is
read (0.1.65), the option alone asks, inside the sandbox and outside, and never forbids. Payloads here are harmless
stand-ins (`true`, `echo hi`): what is pinned is that the option asks, whatever it holds.
"""
import json
import re
from pathlib import Path

import pytest

from server.services import command_confirm, terminal_policy
from server.services.terminal_policy import HIDDEN_OPTION, UNREADABLE, ask_rules, assess

ROOT = Path(__file__).resolve().parents[2]

ASKS = [
    'tar -xf a.tar --to-command="echo hi"',
    "tar -xf a.tar --to-command=true",
    "tar -xf a.tar --to-command true",
    "tar -xf a.tar --to-com=true",                      # a GNU abbreviation
    "tar -xf a.tar -I true",
    "tar -xf a.tar -Itrue",
    "tar -xIf true a.tar",                              # a cluster
    "tar xIf true a.tar",                               # old-style letters
    "tar -cf a.tar --use-compress-program=true d",
    "tar -cf a.tar --checkpoint-action=exec=true d",
    "tar -cf a.tar -F true d",
    "gtar -xf a.tar --to-command=true",
    "rsync -e true a b",
    "rsync -avze true a b",
    "rsync --rsh=true a b",
    "rsync --rsync-path=true a b",
    'vim -c "echo" f.txt',
    'vim +"echo" f.txt',
    'vim --cmd "echo" f.txt',
    "nvim -S x.vim f.txt",
    "vi -u x.vim f.txt",
    'emacs --eval "(message 1)"',
    'emacs -eval "(message 1)"',
    "emacs -l x.el",
    "emacs --load=x.el",
    "emacs -script x.el",                               # emacs takes long options with one dash
    'emacsclient -e "(message 1)"',
    "env A=1 nice tar -xf a.tar --to-command=true",    # through wrappers
    "cd d && vim -c echo f.txt",                        # in a compound
]
# A program word with a path already asks as unreadable for that (the reader's own reason); the basename match is
# pinned on the words directly below.

RUNS = [
    "tar -xf a.tar",
    "tar -czf a.tar d",
    "tar xf a.tar",
    "tar --checkpoint -xf a.tar",                       # a real option that is a prefix of checkpoint-action
    "tar --to-stdout -xf a.tar",
    "rsync -av a b",
    "vim f.txt",
    "vim +12 f.txt",
    "vim + f.txt",
    "nvim -R f.txt",
    "emacs -nw f.txt",
    "emacs -Q f.txt",
    "echo --to-command=true",                           # only the listed tools
]


@pytest.mark.parametrize("outside", [False, True])
@pytest.mark.parametrize("command", ASKS)
def test_a_command_hidden_in_an_option_asks_and_never_forbids(command, outside):
    verdict = assess(command, outside=outside)
    assert (verdict.level, verdict.rule) == ("ask", UNREADABLE), command
    assert verdict.reason == HIDDEN_OPTION
    assert UNREADABLE in ask_rules(command, outside=outside)


@pytest.mark.parametrize("command", RUNS)
def test_the_same_tools_without_such_an_option_still_run(command):
    assert assess(command).level == "run", command


def test_a_named_rule_still_leads_and_unreadable_is_listed_beside_it():
    command = "rsync -e true a host:b"
    assert assess(command).rule == "remote-shell"
    assert {"remote-shell", UNREADABLE} <= ask_rules(command)


def test_the_card_has_a_line_for_it_in_every_language():
    kind = command_confirm.UNREADABLE[HIDDEN_OPTION]
    assert kind == "option-command"
    kinds = re.search(r"UNREADABLE_KINDS = new Set\(\[([^\]]*)\]\)",
                      (ROOT / "web/src/lib/commandRisk.ts").read_text()).group(1)
    for value in command_confirm.UNREADABLE.values():       # every server kind has a web line, and the web knows it
        assert f'"{value}"' in kinds, value
        for lang in ("en", "zh", "de", "es", "fr", "ja"):
            table = json.loads((ROOT / f"web/src/locales/{lang}.json").read_text(encoding="utf-8"))
            found = []

            def walk(node):
                if isinstance(node, dict):
                    for key, child in node.items():
                        if key == f"unreadable-{value}":
                            found.append(child)
                        walk(child)
            walk(table)
            assert found and all(found), (lang, value)


def test_the_tools_are_matched_by_basename_in_any_case():
    assert terminal_policy._option_command((("/opt/homebrew/bin/GTAR", "--to-command=true"),)) == HIDDEN_OPTION
