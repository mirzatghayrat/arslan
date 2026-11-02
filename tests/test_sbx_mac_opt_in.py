"""The sbx_mac corpus is left out of a local run unless the run asks for it (the user, 2026-10-31).

Its real-seatbelt probes act on the user's own session (launchd, preferences, the keychain's reachability), so
`pytest tests/` no longer runs them on the user's Mac. CI's macOS step (`-m macos`) and the SBX-M runbook
(`-m sbx_mac`) still select every case, and `--sbx-mac` opts a run in. Collection only: nothing here runs a probe.
"""
import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
KERNEL = "tests/server/sbx/test_sbx2_kernel.py"     # every case in it is marked sbx_mac


def collected(*args: str) -> int:
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("PYTEST_XDIST", "PYTEST_CURRENT_TEST"))}
    env.setdefault("ARSLAN_SECRET_KEY", "collection-only-fake-secret")
    result = subprocess.run([sys.executable, "-m", "pytest", KERNEL, "--collect-only", "-q", "-p", "no:cacheprovider", *args],
                            cwd=ROOT, capture_output=True, text=True, env=env)
    assert result.returncode in (0, 5), result.stdout[-2000:] + result.stderr[-2000:]   # 5: everything was left out
    return sum(1 for line in result.stdout.splitlines() if line.startswith(KERNEL + "::"))


@pytest.fixture(scope="module")
def every_case() -> int:
    """The file's whole population, through an expression that keeps everything."""
    total = collected("-m", "sbx_mac or not sbx_mac")
    assert total > 0
    return total


def test_a_plain_run_leaves_the_corpus_out():
    assert collected() == 0


def test_an_expression_that_does_not_name_it_leaves_it_out_too():
    assert collected("-m", "not real_network") == 0


@pytest.mark.parametrize("args", [("-m", "sbx_mac"), ("-m", "macos"), ("--sbx-mac",)],
                         ids=["the runbook", "the macOS CI step", "the flag"])
def test_a_run_that_asks_gets_every_case(every_case, args):
    assert collected(*args) == every_case


def test_an_expression_that_names_it_still_decides():
    assert collected("-m", "not sbx_mac") == 0
