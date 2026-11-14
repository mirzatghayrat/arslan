"""Ending a command's process group when only zombies are left.

`_end_group` asks `_group_alive` (which reads EPERM as "only zombies left") and then kills the group. If the group
became zombie-only in between, `os.killpg` raises PermissionError; it escaped `terminal_exec.run`, even for `true`
(seen under parallel load). Both readers now agree."""
import asyncio
import errno
import os

import pytest

from server.services import terminal_exec


class _Proc:
    pid = 4242


def _raise(error):
    def killpg(pgid, sig):
        code = errno.EPERM if error is PermissionError else errno.ESRCH
        raise error(code, os.strerror(code))
    return killpg


@pytest.mark.parametrize("error", [PermissionError, ProcessLookupError])
def test_kill_group_takes_a_group_with_nothing_left_to_signal(monkeypatch, error):
    monkeypatch.setattr(terminal_exec.os, "killpg", _raise(error))
    terminal_exec._kill_group(_Proc())                                   # no exception


def test_end_group_survives_the_group_going_zombie_only_between_its_two_reads(monkeypatch):
    calls = []

    def killpg(pgid, sig):
        calls.append(sig)
        if len(calls) == 1:
            return None                                                  # `_group_alive`: still alive
        raise PermissionError(errno.EPERM, os.strerror(errno.EPERM))     # then only zombies are left

    monkeypatch.setattr(terminal_exec.os, "killpg", killpg)
    assert asyncio.run(terminal_exec._end_group(_Proc())) is True
    assert calls[:2] == [0, terminal_exec.signal.SIGKILL]


def test_another_os_error_still_raises(monkeypatch):
    def killpg(pgid, sig):
        raise OSError(errno.EINVAL, os.strerror(errno.EINVAL))

    monkeypatch.setattr(terminal_exec.os, "killpg", killpg)
    with pytest.raises(OSError):
        terminal_exec._kill_group(_Proc())
