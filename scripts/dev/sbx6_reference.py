"""Usage: HOME=/private/tmp/arslan-sbx-check-home .venv/bin/python -m pytest tests/server/sbx/test_sbx6_network.py -p scripts.dev.sbx6_reference --sbx-mac -q

Add --sbx6-permissive to require real failures, including the retirement gate.
For the settings gates, add tests/server/sbx/test_sbx6_settings.py and
--sbx6-proxy-source /private/tmp/sbx6-settings/sandbox_proxy.py. Prepare that
read-only snapshot with git show 8efb8f9401e774f67dd07ddfaf094055e86cbdc2:server/services/sandbox_proxy.py.
The reference builds no proxy; it drives Hands' implementation through test seams.
DELETE-BY: v0.1.64 after SBX-6a's product adapters pass these gates.
"""
import sys
from urllib.parse import urlsplit

import pytest

from server.services.sandbox_profile import NetworkMode, default_deny_profile
from tests.server.sbx.harness import BUILT_BASES
from tests.server.sbx import harness


def reference(h, **parameters):
    if h.base in {"commands", "commands-proxy"} and h.network == NetworkMode.ANY_DECLARED:
        raise ValueError("commands no longer accept any-declared")
    trust_service = parameters.pop("trust_service", False)
    offline = parameters.pop("offline", False)
    mode = h.network if h.network is not None else NetworkMode.NONE if offline else NetworkMode.PROXY
    if h.base == "run-python":
        from server.services.code_sandbox import computation_profile
        return computation_profile(sys.executable, h.work)
    proxy_port = parameters.pop("proxy_port", getattr(h, "proxy_port", None))
    ports = list(parameters.pop("bound_ports", []))
    for setting in parameters.pop("system_proxies", []):
        proxy = urlsplit(setting)
        if proxy.port == proxy_port:
            raise ValueError("proxy port collides with a configured system proxy")
        if proxy.hostname in {"localhost", "127.0.0.1", "::1"}:
            ports.append(proxy.port)
    text = default_deny_profile([h.work, h.temp], [h.protected], network=mode,
        proxy_port=proxy_port if mode == NetworkMode.PROXY else None,
        denied_ports=ports, ipc_prefix=h.ipc_prefix, **parameters)
    if trust_service and mode == NetworkMode.PROXY:
        text += '(allow mach-lookup (global-name "com.apple.trustd.agent"))\n'
    return text


def permissive(h, **parameters):
    return '(version 1)\n(allow default)\n'


def pytest_addoption(parser):
    parser.addoption("--sbx6-permissive", action="store_true")
    parser.addoption("--sbx6-proxy-source", help="Read-only 6a sandbox_proxy.py snapshot for trusted-LAN gates")


def pytest_configure(config):
    harness.BUILT_FEATURES |= {"trustd-toggle"}
    if config.getoption("--sbx6-proxy-source"):
        harness.BUILT_FEATURES |= {"trusted-lan"}
    adapter = permissive if config.getoption("--sbx6-permissive") else reference
    for base in ("commands", "commands-proxy", "mcp-proxy", "run-python", "network-sbx6"):
        BUILT_BASES[base] = adapter
    if adapter is permissive:
        from server.services import ssh_exec
        ssh_exec.ssh_profile = lambda: permissive(None)


@pytest.fixture(autouse=True)
def permissive_lan_control(request, monkeypatch):
    if request.config.getoption("--sbx6-permissive") and "proxy_module" in request.fixturenames:
        module = request.getfixturevalue("proxy_module")
        # Negative control only: admit all synthetic private answers. Tests map
        # every outbound dial to a disposable listener, including this mutant.
        def trust_every_host(host, trusted, resolve=None):
            return module.socket.getaddrinfo(host, None)[0][4][0]
        monkeypatch.setattr(module, "trusted_address", trust_every_host)
