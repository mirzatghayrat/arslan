"""SBX corpus plumbing. Policy adapters are selected by base name, never by a fallback."""
from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from server.services import command_sandbox
from server.services.sandbox_profile import NetworkMode, default_deny_profile

MEASUREMENT_BASES = ("legacy-commands", "default-deny", "outside-floor")
DENY_BASES = ("default-deny",)


class Harness:
    def __init__(self, root: Path, base: str, network=NetworkMode.NONE, *, executions=None):
        self.root = root.resolve()
        self.base = base
        self.network = network
        # Historical controls share the owning test's evidence stream.
        self.executions = [] if executions is None else executions
        self.work = self.root / "work"
        self.home = self.root / "home"
        self.temp = self.root / "temp"
        self.protected = self.home / ".ssh" if base == "commands" else self.work / "protected"
        for path in (self.work, self.home, self.temp, self.protected):
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.ipc_prefix = "/arslan-" + os.urandom(8).hex() + "-"
        self.env = {
            "HOME": str(self.home), "TMPDIR": str(self.temp),
            "PATH": os.pathsep.join((str(Path(sys.executable).parent), "/opt/homebrew/bin",
                                     "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin")),
            "LANG": "en_US.UTF-8", "ARSLAN_SECRET_KEY_FILE": "",
            "ARSLAN_SECRET_KEY": "sbx-corpus-fake-key", "ARSLAN_DATA_DIR": str(self.root / "data"),
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "/usr/bin/false",
            "SSH_ASKPASS": "/usr/bin/false", "HOMEBREW_NO_AUTO_UPDATE": "1",
            "HOMEBREW_NO_ANALYTICS": "1", "PYTHONNOUSERSITE": "1",
            "npm_config_cache": str(self.work / "npm-cache"),
            "PIP_CACHE_DIR": str(self.work / "pip-cache"),
            "UV_CACHE_DIR": str(self.work / "uv-cache"),
            "XDG_CACHE_HOME": str(self.work / "xdg-cache"),
            "GOCACHE": str(self.work / "go-cache"),
            "CLANG_MODULE_CACHE_PATH": str(self.work / "clang-cache"),
            "SWIFT_MODULECACHE_PATH": str(self.work / "swift-cache"),
            "SBX_IPC_PREFIX": self.ipc_prefix,
        }

    def profile(self, **parameters) -> str:
        if self.base not in BUILT_BASES:
            raise NotImplementedError(f"no profile adapter for {self.base}")
        if self.base in ("commands", "commands-proxy"):
            with pytest.MonkeyPatch.context() as environment:
                for name in ("HOME", "TMPDIR", "ARSLAN_DATA_DIR"):
                    environment.setenv(name, self.env[name])
                environment.setattr(tempfile, "tempdir", str(self.temp))
                return BUILT_BASES[self.base](self, **parameters)
        return BUILT_BASES[self.base](self, **parameters)

    def _measurement_profile(self, **parameters) -> str:
        if self.base == "default-deny":
            options = dict(network=self.network, ipc_prefix=self.ipc_prefix)
            if self.network == NetworkMode.PROXY:
                options["proxy_port"] = 49151  # no listener; actual proxy is SBX-6
            options.update(parameters)
            return default_deny_profile([self.work, self.temp], [self.protected], **options)
        if parameters:
            raise ValueError("candidate parameters cannot be applied to a historical base")
        if self.base == "legacy-commands":
            # DELETE-BY: v0.1.64 after SBX-M records the historical baseline,
            # before SBX-3 replaces this preset. No runtime fallback uses it.
            with pytest.MonkeyPatch.context() as environment:
                environment.setenv("HOME", str(self.home))
                environment.setenv("TMPDIR", str(self.temp))
                environment.setattr(tempfile, "tempdir", str(self.temp))
                return command_sandbox.profile(
                    command_sandbox.default_writable(self.work),
                    [*command_sandbox.default_protected(), self.protected],
                    offline=self.network == NetworkMode.NONE)
        if self.base == "outside-floor":
            return command_sandbox.minimal_profile(offline=self.network == NetworkMode.NONE)
        raise NotImplementedError(f"no profile adapter for {self.base}")

    def run(self, argv, *, probe: str, profile=None, timeout=30, discard=False):
        """Bound a process group, including grandchildren; never retain service output."""
        text = self.profile() if profile is None else profile
        with subprocess.Popen(
            ["/usr/bin/sandbox-exec", "-p", text, *map(str, argv)], cwd=self.work, env=self.env,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL if discard else subprocess.PIPE,
            stderr=subprocess.DEVNULL if discard else subprocess.PIPE, text=True,
            start_new_session=True,
        ) as process:
            execution = {
                "sequence": len(self.executions) + 1, "probe": probe,
                "base": self.base, "network": self.network.value,
                "profile_override": profile is not None,
                "profile_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "profile_text": text,
            }
            self.executions.append(execution)
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                execution["result"] = "timeout"
                raise
            else:
                execution["result"] = "completed"
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass  # The entire group has already exited.
                process.wait()
                execution["returncode"] = process.returncode
        return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)

    def python(self, source: str, *args, **kwargs):
        return self.run([sys.executable, "-I", "-c", source, *map(str, args)], **kwargs)

    def record_executions(self, record_property, artifact_dir=None):
        record_property("base", self.base)
        # Report only safe metadata; exact texts containing local paths stay local.
        record_property("executions", json.dumps([
            {key: value for key, value in execution.items() if key != "profile_text"}
            for execution in self.executions
        ], sort_keys=True))
        if artifact_dir is not None:
            folder = Path(artifact_dir)
            folder.mkdir(parents=True, exist_ok=True)
            for execution in self.executions:
                (folder / (execution["profile_sha256"] + ".sb")).write_bytes(execution["profile_text"].encode())


# SBX-3a's commands entry calls its real product preset, under scratch
# HOME/TMPDIR, with this harness's work/temp, IPC prefix, mode and denied_ports.
# It must not delegate commands to the candidate.
def _commands_profile(self, **parameters) -> str:
    # The test process's own listeners are not Arslan's: bound ports and system proxies come only from the
    # test (SBX-6p passes stand-ins), never from this process or this Mac.
    options = dict(network=self.network, ipc_prefix=self.ipc_prefix, bound_ports=[], system_proxies=[])
    if self.network == NetworkMode.PROXY:
        options["proxy_port"] = getattr(self, "proxy_port", None) or 49151  # 49151: no listener
    options.update(parameters)
    return command_sandbox.commands_profile(self.work, temp=self.temp, **options)


# SBX-6a: the base with SBX-6's loopback exclusions, as the product computes them (`sandbox_proxy`).
def _sbx6_base_profile(self, **parameters) -> str:
    from server.services import sandbox_proxy
    proxy_port = parameters.pop("proxy_port", getattr(self, "proxy_port", None))
    denied = sandbox_proxy.excluded_ports(parameters.pop("bound_ports", []), parameters.pop("system_proxies", []),
                                          proxy_port=proxy_port or 0)
    return default_deny_profile([self.work, self.temp], [self.protected], network=self.network,
                                proxy_port=proxy_port if self.network == NetworkMode.PROXY else None,
                                denied_ports=denied, ipc_prefix=self.ipc_prefix, **parameters)


BUILT_BASES = {base: Harness._measurement_profile for base in MEASUREMENT_BASES}
BUILT_BASES["commands"] = _commands_profile
BUILT_BASES["commands-proxy"] = _commands_profile
BUILT_BASES["network-sbx6"] = _sbx6_base_profile


# SBX-4a's entries call the real product presets: `code_sandbox.computation_profile` for run_python (with its
# read-only references) and the artifact checks (without), and `capability_sandbox.profile` for an installed
# MCP server, whose own folder is this harness's work folder and whose protected paths are the test's.
def _computation_profile(self, **parameters) -> str:
    from server.services import code_sandbox
    references = parameters.pop("references", None)
    parameters.pop("granted_folders", None)          # computation has no granted folders
    parameters.pop("protected", None)                # nor protected paths: its reads are the runtime's only
    if parameters:
        raise ValueError(f"computation takes no {sorted(parameters)}")
    return code_sandbox.computation_profile(sys.executable, self.work,
                                            references if self.base == "run-python" else None)


def _mcp_profile(self, **parameters) -> str:
    from unittest.mock import patch
    from server.services import capability_sandbox
    grants = parameters.pop("granted_folders", [])
    protected = parameters.pop("protected", [self.protected])
    parameters.pop("references", None)
    if parameters:
        raise ValueError(f"MCP takes no {sorted(parameters)}")
    if self.network not in (NetworkMode.NONE, NetworkMode.ANY_DECLARED):
        raise ValueError(f"MCP has no {self.network.value} mode yet (SBX-6 MCP proxy)")
    with patch.object(command_sandbox, "default_protected", return_value=list(protected)):
        return capability_sandbox.profile(root=self.work, folders=list(map(str, grants)),
                                          network=self.network != NetworkMode.NONE,
                                          read=[sys.prefix, sys.base_prefix])


BUILT_BASES.update({"run-python": _computation_profile, "artifact": _computation_profile, "mcp": _mcp_profile})
