"""Usage: HOME=/private/tmp/arslan-sbx-check-home .venv/bin/python -m pytest tests/server/sbx/test_sbx4_presets.py -p scripts.dev.sbx4_reference --sbx-mac -q

Reference only; --sbx4-control permissive must fail every new surface gate.
--sbx4-control legacy measures today's computation/artifact/MCP presets.
DELETE-BY: v0.1.64 after SBX-4a registers and validates all product adapters.
"""
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from server.services import capability_sandbox, code_sandbox
from server.services.sandbox_profile import NetworkMode, default_deny_profile, literal, subpath
from tests.server.sbx.harness import BUILT_BASES


def reference(harness, **parameters):
    grants = parameters.pop("granted_folders", [])
    protected = parameters.pop("protected", [harness.protected])
    references = parameters.pop("references", None)
    if harness.base in {"run-python", "artifact"}:
        # Reuse today's exact runtime read rules; broad parent reads are not a reference.
        python = parameters.pop("python", sys.executable)
        legacy = code_sandbox.computation_profile(python, harness.work, references)
        reads = [line for line in legacy.splitlines() if line.startswith("(allow file-read")]
        text = default_deny_profile([harness.work], readable=[harness.work],
                                    network=NetworkMode.NONE, ipc_prefix=harness.ipc_prefix)
        text += "\n" + "\n".join(reads) + "\n"
        if references is not None and harness.base == "run-python":
            text += f'(deny file-write* {subpath(references)})\n'
        text += '(deny process-exec)\n'
        for path in sorted({Path(python).absolute(), Path(python).resolve()}):
            text += f'(allow process-exec {literal(path)})\n'
        return text + device_rules()
    reads = parameters.pop("read", [])
    if harness.base == "mcp-proxy":
        # Match SBX-6p and capability_sandbox.profile's public argument names.
        proxy_port = parameters.pop("proxy_port", getattr(harness, "proxy_port", None))
        ports = list(parameters.pop("bound_ports", []))
        for setting in parameters.pop("system_proxies", []):
            proxy = urlsplit(setting)
            if proxy.port == proxy_port:
                raise ValueError("proxy port collides with a configured system proxy")
            if proxy.hostname in {"localhost", "127.0.0.1", "::1"}:
                ports.append(proxy.port)
        parameters.update(proxy_port=proxy_port, denied_ports=ports)

    return default_deny_profile([harness.work, *grants], protected,
                                readable=[*capability_sandbox.SYSTEM_READ, Path(sys.prefix),
                                          Path(sys.base_prefix), harness.work, *grants, *map(Path, reads)],
                                network=harness.network, ipc_prefix=harness.ipc_prefix, **parameters) + '(allow file-read-data (literal "/"))\n' + device_rules()


def device_rules():
    devices = '(literal "/dev/tty") (literal "/dev/ptmx") (regex #"^/dev/ttys[0-9]+$")'
    return (f'(deny file-read* file-write* {devices})\n'
            f'(deny file-read-data file-write-data {devices})\n'
            f'(deny file-ioctl {devices})\n'
            '(deny pseudo-tty)\n'
            '(deny mach-lookup (global-name "com.apple.FSEvents"))\n')


def legacy(harness, **parameters):
    if harness.base in {"run-python", "artifact"}:
        return code_sandbox.computation_profile(sys.executable, harness.work,
               parameters.get("references") if harness.base == "run-python" else None)
    with patch("server.services.command_sandbox.default_protected",
               return_value=parameters.get("protected", [harness.protected])):
        return capability_sandbox.profile(root=harness.work,
            folders=list(map(str, parameters.get("granted_folders", []))),
            network=harness.network != NetworkMode.NONE,
            read=[sys.prefix, sys.base_prefix])


def permissive(harness, **parameters):
    return "(version 1)\n(allow default)\n"


def pytest_addoption(parser):
    parser.addoption("--sbx4-control", choices=["reference", "legacy", "permissive"], default="reference")


def pytest_configure(config):
    adapter = {"reference": reference, "legacy": legacy, "permissive": permissive}[config.getoption("--sbx4-control")]
    for base in ("run-python", "artifact", "mcp", "mcp-proxy"):
        BUILT_BASES[base] = adapter
