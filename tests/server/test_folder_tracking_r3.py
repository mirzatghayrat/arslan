"""Filesystem witnesses and independent component-stack controls for folder cancellation."""
import errno
from itertools import product
import os
import subprocess
from types import SimpleNamespace

import pytest

from server.services import shell_grammar as sg, terminal_policy as tp
from tests.server.test_s2a3_folder_tracking import A, B, DEL, TOOL, stand_in_rules  # noqa: F401


def _delete(prefix):
    return f"cd {prefix}/{B} && cd .. && {DEL} zz-file"


@pytest.mark.parametrize("topology", ["outside-link", "missing", "deep-link", "plain", "inside-link"])
def test_partial_fold_topology(topology, tmp_path):
    work, outside = tmp_path / "work", tmp_path / "outside"
    work.mkdir()
    (outside / B).mkdir(parents=True)
    prefix = A
    if topology == "outside-link":
        (work / A).symlink_to(outside, target_is_directory=True)
    elif topology == "inside-link":
        (work / "zz-real" / B).mkdir(parents=True)
        (work / A).symlink_to(work / "zz-real", target_is_directory=True)
    elif topology == "deep-link":
        (work / A).mkdir()
        (work / A / "zz-link").symlink_to(outside, target_is_directory=True)
        prefix = f"{A}/zz-link"
    elif topology == "plain":
        (work / A / B).mkdir(parents=True)
    result = tp.assess(_delete(prefix), cwd=work)
    assert (result.level, result.rule) == (("run", "") if topology == "plain" else ("ask", "delete-outside"))


def test_link_in_first_component_of_deeper_prefix(tmp_path):
    work, outside = tmp_path / "work", tmp_path / "outside"
    work.mkdir()
    (outside / "zz-real" / B).mkdir(parents=True)
    (work / A).symlink_to(outside, target_is_directory=True)
    assert tp.assess(_delete(f"{A}/zz-real"), cwd=work).level == "ask"


def test_full_return_can_cancel_a_link(tmp_path, monkeypatch):
    (tmp_path / "zz-real").mkdir()
    (tmp_path / A).symlink_to(tmp_path / "zz-real", target_is_directory=True)
    def unexpected(path):
        pytest.fail("full return needs no prefix check")
    monkeypatch.setattr(tp, "os", SimpleNamespace(fspath=os.fspath, path=os.path, listdir=os.listdir, lstat=unexpected))
    assert tp.assess(f"cd {A} && cd .. && {DEL} zz-file", cwd=tmp_path).level == "run"


@pytest.mark.parametrize("error", [errno.EACCES, errno.ENAMETOOLONG, errno.EIO])
def test_uncheckable_prefix_stays_unfolded(error, tmp_path, monkeypatch):
    def fails(path):
        if str(path).startswith(str(tmp_path) + "/"):
            raise OSError(error, "stand-in error")
        return os.lstat(path)
    monkeypatch.setattr(tp, "os", SimpleNamespace(fspath=os.fspath, path=os.path, listdir=os.listdir, lstat=fails))
    assert tp.assess(_delete(A), cwd=tmp_path).level == "ask"


def test_unknown_work_folder_stays_unfolded(monkeypatch):
    def unexpected(path):
        pytest.fail("unknown work folder must not be inspected")
    monkeypatch.setattr(tp, "os", SimpleNamespace(fspath=os.fspath, path=os.path, listdir=os.listdir, lstat=unexpected))
    assert tp.assess(_delete(A)).level == "ask"


def test_checks_are_assessment_local_and_each_component_is_checked_once(tmp_path, monkeypatch):
    (tmp_path / A / "zz-real" / B).mkdir(parents=True)
    original = os.lstat
    calls = []

    def record(path):
        if str(path).startswith(str(tmp_path) + "/"):
            calls.append(os.fspath(path))
        return original(path)

    monkeypatch.setattr(tp, "os", SimpleNamespace(fspath=os.fspath, path=os.path, listdir=os.listdir, lstat=record))
    text = _delete(f"{A}/zz-real") + f" && {DEL} zz-other"
    assert tp.assess(text, cwd=tmp_path).level == "run"
    assert calls == [str(tmp_path / A), str(tmp_path / A / "zz-real")]
    calls.clear()
    (tmp_path / A / "zz-real").rename(tmp_path / "zz-moved")
    (tmp_path / A / "zz-real").symlink_to(tmp_path / "zz-moved", target_is_directory=True)
    assert tp.assess(text, cwd=tmp_path).level == "ask"
    assert calls == [str(tmp_path / A), str(tmp_path / A / "zz-real")]


def test_no_fold_means_no_filesystem_access(tmp_path, monkeypatch):
    def unexpected(path):
        pytest.fail("no fold needs no filesystem access")
    monkeypatch.setattr(tp, "os", SimpleNamespace(fspath=os.fspath, path=os.path, listdir=os.listdir, lstat=unexpected))
    for text in (f"cd {A} && {DEL} zz-file", f"cd .. && {DEL} zz-file", f"{TOOL}"):
        tp.assess(text, cwd=tmp_path)
    assert sg.read(_delete(A)).understood


def test_new_prefix_after_full_return_is_checked(tmp_path):
    (tmp_path / A / B).mkdir(parents=True)
    text = f"cd {A}/../zz-missing/{B}/.. && {DEL} zz-file"
    assert tp.assess(text, cwd=tmp_path).level == "ask"


def stack_oracle(target):
    home = target.startswith("~")
    absolute = target.startswith("/")
    stack = []
    for part in (target[1:] if home else target).split("/"):
        if part in ("", "."):
            continue
        if part == ".." and stack and stack[-1] != "..":
            stack.pop()
        elif part != ".." or not absolute:
            stack.append(part)
    suffix = "/".join(stack)
    return ("~" + ("/" + suffix if suffix else "")) if home else ("/" if absolute else "") + suffix


@pytest.mark.parametrize("anchor", ["~", "", "/"])
@pytest.mark.parametrize("separators", [1, 2, 3])
def test_generated_separator_components(anchor, separators):
    for length in range(1, 5):
        for parts in product((A, B, ".", "..", ""), repeat=length):
            target = anchor + "/" * separators + "/".join(parts) if anchor else "/".join(parts)
            if not target:
                continue
            reading = sg.read(f"cd {target} && {TOOL}")
            assert reading.understood, target
            assert reading.folders[-1] == (stack_oracle(target),), target


def test_symlink_prefix_real_bash_differential(tmp_path):
    home, work, outside = (tmp_path / name for name in ("home", "work", "outside"))
    home.mkdir()
    work.mkdir()
    (outside / B).mkdir(parents=True)
    (work / A).symlink_to(outside, target_is_directory=True)
    text = f'cd {A}/{B} && echo 0 "$PWD" && cd .. && echo 1 "$PWD"'
    reading = sg.read(text, fold_partial=False)
    assert reading.understood
    named = {words[1]: folders for words, folders in zip(reading.commands, reading.folders) if words[0] == "echo"}
    ran = subprocess.run(["/bin/bash", "-p", "-c", text], cwd=work,
                         env={"PATH": "/usr/bin:/bin", "HOME": str(home)}, capture_output=True, text=True, check=True)
    seen = ran.stdout.splitlines()
    assert len(seen) == 2
    for line in seen:
        marker, path = line.split(" ", 1)
        # Compare actual destinations, preserving the unfolded path through the link.
        assert any((work / folder).resolve() == type(work)(path).resolve() for folder in named[marker])
    assert named["1"] == (f"{A}/{B}/..",)
