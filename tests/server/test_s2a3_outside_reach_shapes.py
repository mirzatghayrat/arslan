"""Step 5: static command shapes, a main differential, and bounded stub observations.

The Bash observation never delegates a wrapper to a real executable. Consequently
an invocation hidden behind an external wrapper is explicitly not covered. Paths
are withheld, including relative executable paths; no generated text is otherwise
executed by any test. Strict xfails describe the measured head, not runtime guesses.
"""
from dataclasses import asdict
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile

import pytest

from server.services import terminal_policy as tp
from tests.server.outside_reach_cases import CASES


def parameter(case):
    marks = [pytest.mark.xfail(strict=True, raises=AssertionError, reason=case.gap)] if case.gap else []
    return pytest.param(case, id=f"{case.category}-{case.id}", marks=marks)


def assert_policy(case):
    verdict = tp.assess(case.text, outside=True)
    rules = tp.ask_rules(case.text, outside=True)
    if case.readonly:
        assert verdict == tp.Assessment("run") and rules == set()
    elif case.id in {"sudo", "command-size"}:
        assert verdict.level in {"ask", "forbid"}
        assert (verdict.rule in rules) if verdict.level == "ask" else not rules
    else:
        assert verdict.level == "ask"
        assert verdict.rule in rules
        assert rules
    if case.category == "indirection" and not case.readonly:
        assert tp.UNREADABLE in rules


@pytest.mark.parametrize("case", [parameter(c) for c in CASES])
def test_outside_shape(case):
    assert_policy(case)


BASELINE = json.loads(Path(__file__).with_name("outside_reach_main.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=lambda c: f"{c.category}-{c.id}")
def test_inside_is_byte_identical_to_main(case):
    # Generated once by importing the module from the pinned main commit via git show.
    # Include the text in the fixture so edits cannot silently reuse a stale expectation.
    assert BASELINE["commit"] == "ed51d4d4"
    expected = BASELINE["cases"][f"{case.category}-{case.id}"]
    assert expected["text"] == case.text
    actual = {"assessment": asdict(tp.assess(case.text, outside=False)),
              "rules": sorted(tp.ask_rules(case.text, outside=False))}
    assert json.dumps(actual, sort_keys=True).encode() == expected["verdict"].encode()


STUB_NAMES = (
    "open", "OPEN", "batch", "launchctl", "LaUnChCtL", "LAUNCHCTL", "shortcuts", "security", "SECURITY",
    "networksetup", "at", "tccutil", "env", "timeout", "nice", "nohup", "caffeinate", "xcrun", "arch",
    "sudo", "npx", "bunx", "pnpm", "sh", "bash", "zsh", "find", "xargs", "watch", "script", "tmux",
    "screen", "parallel", "concurrently", "cat", "\u043epen", "op\u200ben", "op\u202een", "\uff4fpen",
)
REACH_NAMES = {"open", "batch", "launchctl", "shortcuts", "security", "networksetup", "at", "tccutil"}


def observe(text, parent, *, enabled=True):
    """Only Bash, its builtins, and name-logging, exit-zero shims can run.

    The corpus contains no file writes except a scratch script transcript argument
    and no absolute/relative execution outside this function's withheld path class.
    The environment contains exactly PATH and HOME. Every run has a fresh cwd/HOME,
    a deadline and unconditional process-group cleanup, even after normal shell exit.
    """
    if not Path("/bin/bash").is_file():
        pytest.skip("not covered: Bash is unavailable")
    if "/" in text:
        pytest.skip("not covered: path-bearing text withheld without an exec-denial sandbox")
    with tempfile.TemporaryDirectory(dir=parent, prefix="reach-bash-") as scratch:
        root = Path(scratch)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        if enabled:
            for name in STUB_NAMES:
                stub = bin_dir / name
                stub.write_text('#!/bin/bash -p\nprintf "%s\\n" "${0##*/}" >> "$HOME/invocations"\nexit 0\n')
                stub.chmod(0o700)
        with subprocess.Popen(["/bin/bash", "-p", "-c", text], cwd=root,
                              env={"PATH": str(bin_dir), "HOME": str(root)},
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              start_new_session=True) as process:
            expired = False
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                expired = True
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)
        log = root / "invocations"
        return (log.read_text().splitlines() if log.exists() else []), expired


@pytest.mark.parametrize("case", [parameter(c) for c in CASES])
def test_real_bash_comparison(case, tmp_path, record_property):
    names, expired = observe(case.text, tmp_path)
    record_property("observed_programs", json.dumps(names))
    assert not expired, "bounded observation timed out; not denial evidence"
    reached = {name.lower() for name in names} & REACH_NAMES
    if not reached:
        pytest.skip("not covered: no in-scope invocation observed; external wrappers are exit-zero stubs")
    # All reach cases use mutating verbs; read-only cases are separately labelled.
    assert_policy(case)


def test_bash_observation_requires_enabled_shims(tmp_path):
    text = next(c.text for c in CASES if c.id == "single-program")
    enabled, expired = observe(text, tmp_path)
    assert not expired and enabled == ["open"]
    disabled, expired = observe(text, tmp_path, enabled=False)
    assert not expired
    # The same positive observation assertion MUST fail when instrumentation is off.
    with pytest.raises(AssertionError):
        assert disabled == ["open"]
