"""Explicit pytest plugin for probe validation, never the product commands adapter.

Usage: HOME=/private/tmp/arslan-sbx-check-home .venv/bin/python -m pytest tests/server/sbx/test_sbx3_commands.py -p scripts.dev.sbx3_reference -m macos -q
Add --sbx-reference-permissive for the mutation that must fail all 63 gates.
"""
from server.services.sandbox_profile import NetworkMode, default_deny_profile
from tests.server.sbx.harness import BUILT_BASES


def reference(harness, **parameters):
    # Import after registration: the commands module evaluates its xfail mark
    # at import time. The reference must not be mistaken for an absent adapter.
    from tests.server.sbx.test_sbx3_commands import APP_DATA

    options = dict(network=harness.network, ipc_prefix=harness.ipc_prefix,
                   closed=[harness.home / path for path in APP_DATA])
    if harness.network == NetworkMode.PROXY:
        options["proxy_port"] = 49151
    options.update(parameters)
    return default_deny_profile([harness.work, harness.temp], [harness.protected], **options)


def permissive(harness, **parameters):
    """Negative control; every target is owned by the tests."""
    return "(version 1)\n(allow default)\n"


def pytest_addoption(parser):
    parser.addoption("--sbx-reference-permissive", action="store_true",
                     help="replace the reference with its deliberately permissive mutation")


def pytest_configure(config):
    BUILT_BASES["commands"] = permissive if config.getoption("--sbx-reference-permissive") else reference
