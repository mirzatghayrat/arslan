"""Usage: HOME=/private/tmp/arslan-sbx-check-home .venv/bin/python -m pytest tests/server/sbx/test_sbx6_network.py -p scripts.dev.sbx6_reference --sbx-mac -q

Add --sbx6-permissive to require real failures, including the retirement gate.
DELETE-BY: v0.1.64 after SBX-6a's product adapters pass these gates.
"""
import sys
from urllib.parse import urlsplit

from server.services.sandbox_profile import NetworkMode, default_deny_profile
from tests.server.sbx.harness import BUILT_BASES


def reference(h, **parameters):
    if h.base in {"commands", "commands-proxy"} and h.network == NetworkMode.ANY_DECLARED:
        raise ValueError("commands no longer accept any-declared")
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
    return default_deny_profile([h.work, h.temp], [h.protected], network=mode,
        proxy_port=proxy_port if mode == NetworkMode.PROXY else None,
        denied_ports=ports, ipc_prefix=h.ipc_prefix, **parameters)


def permissive(h, **parameters):
    return '(version 1)\n(allow default)\n'


def pytest_addoption(parser):
    parser.addoption("--sbx6-permissive", action="store_true")


def pytest_configure(config):
    adapter = permissive if config.getoption("--sbx6-permissive") else reference
    for base in ("commands", "commands-proxy", "mcp-proxy", "run-python", "network-sbx6"):
        BUILT_BASES[base] = adapter
    if adapter is permissive:
        from server.services import ssh_exec
        ssh_exec.ssh_profile = lambda: permissive(None)
