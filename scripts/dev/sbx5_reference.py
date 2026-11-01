"""Usage: HOME=/private/tmp/arslan-sbx-check-home .venv/bin/python -m pytest tests/server/sbx/test_sbx5_paths.py -p scripts.dev.sbx5_reference --sbx-mac -q

Add --sbx5-permissive for the negative control.
DELETE-BY: v0.1.64 after SBX-5a's product adapters pass these gates.
"""
import sys
from server.services.sandbox_profile import default_deny_profile, subpath
from tests.server.sbx import harness
from tests.server.sbx.harness import BUILT_BASES


def reference(h, **parameters):
    from server.services.code_sandbox import computation_profile
    cap = [h.home / ".agents" / "skills", h.plugin_root, h.data_root]
    caches = [h.home / ".npm", h.home / ".cache", h.home / "Library" / "Caches"]
    if h.base == "outside-floor":
        text = '(version 1)\n(allow default)\n(deny network*)\n'
    elif h.base == "run-python":
        text = computation_profile(sys.executable, h.work)
    else:
        text = default_deny_profile([h.work, h.home, h.cache_root], closed=[h.peer_cache],
                                    ipc_prefix=h.ipc_prefix)
    for path in cap:
        text += f'(deny file-read* file-write* {subpath(path.resolve())})\n'
    if h.base != "outside-floor":
        for path in caches:
            text += f'(deny file-write* {subpath(path.resolve())})\n'
    return text


def permissive(h, **parameters):
    return '(version 1)\n(allow default)\n'


def pytest_addoption(parser):
    parser.addoption("--sbx5-permissive", action="store_true")


def pytest_configure(config):
    # Advertise the feature even for the permissive mutation: regressions must
    # fail as real gates instead of being hidden by the missing-feature guard.
    harness.BUILT_FEATURES = harness.BUILT_FEATURES | {"cap6b"}
    for base in ("commands", "outside-floor", "mcp", "run-python"):
        BUILT_BASES[base] = permissive if config.getoption("--sbx5-permissive") else reference
