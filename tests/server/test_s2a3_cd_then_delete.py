"""S2a-3 e: a delete whose folder the command changed first asks (⓪Plan, from the final M1 of v0.1.63).

Under "Ask only for risky commands" the model deleted files with `cd <folder> && rm <names>` and no card
appeared: delete-outside judged rm's relative operands against the command's own folder and never saw the
cd. With a conversation allowed outside the sandbox that is a real delete anywhere, unasked. Now any change
of folder in the command leaves a relative target unknown, so the delete asks (this time only, like every
delete-outside card). The commands are never run: only the policy reads them.
"""
from __future__ import annotations

import pytest

from server.services import terminal_policy as tp


def _asks_delete_outside(command: str) -> bool:
    return tp.assess(command).level == "ask" and "delete-outside" in tp.ask_rules(command)


@pytest.mark.parametrize("command", [
    "cd /tmp/elsewhere && rm notes.txt",
    "cd /srv/ws && rm -v a.bak notes/b.bak 2>&1; echo done",
    "cd .. && rm notes.txt",
    "cd ~ && rm notes.txt",
    "cd && rm notes.txt",
    "cd - && rm notes.txt",
    "cd sub && rm notes.txt",
    "cd /tmp/elsewhere; rm -r build",
    "cd /tmp/elsewhere\nrm notes.txt",
    "ls && cd /tmp/elsewhere && rm notes.txt",
    "true; cd /tmp/elsewhere; rm notes.txt",
    "ls | (cd /tmp/elsewhere && rm notes.txt)",
    "(cd /tmp/elsewhere; rm notes.txt)",
    "{ cd /tmp/elsewhere; rm notes.txt; }",
    "pushd /tmp/elsewhere && rm notes.txt",
    "pushd /tmp/elsewhere >/dev/null && rm notes.txt && popd",
    "builtin cd /tmp/elsewhere && rm notes.txt",
    "command cd /tmp/elsewhere && rm notes.txt",
    "chdir /tmp/elsewhere && rm notes.txt",
    "cd /tmp/elsewhere && rmdir old",
    "cd /tmp/elsewhere && unlink notes.txt",
    "cd /tmp/elsewhere && find . -name '*.bak' -delete",
    "cd /tmp/elsewhere && find . -name '*.bak' -exec rm {} +",
    "sh -c 'cd /tmp/elsewhere && rm notes.txt'",
    "env -C /tmp/elsewhere rm notes.txt",
    "env --chdir=/tmp/elsewhere rm notes.txt",
])
def test_a_delete_after_the_command_changes_folder_asks(command):
    assert _asks_delete_outside(command), tp.assess(command)


@pytest.mark.parametrize("command", [
    "rm -v a.bak notes/b.bak",
    "rm notes.txt",
    "find . -name '*.bak' -delete",
    "echo cd; rm notes.txt",
    "abcd x && rm notes.txt",
    "rm cdrom.txt",
])
def test_a_delete_in_the_commands_own_folder_still_runs(command):
    assert tp.assess(command).level == "run", tp.assess(command)


@pytest.mark.parametrize("command", [
    "cd sub && ls",
    "cd /tmp/elsewhere && cat notes.txt",
    "pushd sub && git status && popd",
])
def test_changing_folder_without_a_delete_is_not_a_delete(command):
    assert "delete-outside" not in tp.ask_rules(command)
