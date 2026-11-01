"""The SBX tests fail on a broken macOS sandbox, rather than skipping it."""
import platform
import json
import subprocess

import pytest

from tests.server.sbx.harness import BUILT_BASES, Harness
from server.services.sandbox_profile import NetworkMode


def pytest_addoption(parser):
    parser.addoption("--sbx-artifacts", help="Local directory for exact SBPL texts; never commit these paths")


_RESULTS = {}


def pytest_runtest_logreport(report):
    if report.when == "call":
        _RESULTS[report.nodeid] = {"result": report.outcome}
    elif report.when == "teardown" and any(k == "base" for k, _ in report.user_properties):
        _RESULTS.setdefault(report.nodeid, {}).update(report.user_properties)


def pytest_terminal_summary(terminalreporter):
    rows = {node: value for node, value in _RESULTS.items() if "base" in value}
    if rows:
        terminalreporter.write_sep("-", "SBX measurements (tool failures are not kernel-test passes)")
        for node, value in sorted(rows.items()):
            terminalreporter.write_line(json.dumps({"test": node, **value}, sort_keys=True))


@pytest.fixture
def sbx(tmp_path, request, record_property):
    if request.node.get_closest_marker("macos") is None:
        pytest.fail("tests using sbx must carry the macos marker and their own platform skip")
    base = getattr(request, "param", "default-deny")
    if base == "commands":
        record_property("base", base)
        # The one deliberate expected failure, before any smoke/probe runs.
        # Once registered, fixture or probe failures are ordinary test failures.
        assert base in BUILT_BASES, "SBX-3a commands adapter is not built"
    parameters = getattr(getattr(request.node, "callspec", None), "params", {})
    harness = Harness(tmp_path, base, parameters.get("mode", NetworkMode.NONE))
    try:
        # Syntax errors and nested/unavailable seatbelt are failures on macOS.
        result = harness.run(["/usr/bin/true"], probe="fixture-smoke")
        assert result.returncode == 0, result.stderr
        record_property("macos", platform.mac_ver()[0])
        record_property("hardware", platform.machine())
        record_property("os_build", subprocess.check_output(["/usr/bin/sw_vers", "-buildVersion"], text=True).strip())
        yield harness
    finally:
        harness.record_executions(record_property, request.config.getoption("--sbx-artifacts"))
