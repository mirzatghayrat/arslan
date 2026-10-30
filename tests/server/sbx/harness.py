"""SBX corpus plumbing. Policy adapters are selected by base name, never by a fallback."""
from __future__ import annotations

import hashlib
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from server.services import command_sandbox
from server.services.sandbox_profile import NetworkMode, default_deny_profile

# Future p PRs add adapters/parameters; the corresponding a PR adds only its name here.
BUILT_BASES = frozenset({"default-deny", "legacy-commands", "outside-floor"})
MEASUREMENT_BASES = ("legacy-commands", "default-deny", "outside-floor")
DENY_BASES = ("default-deny",)


def base_parameter(name: str):
    marks = [] if name in BUILT_BASES else [pytest.mark.xfail(strict=True, reason=f"{name} not built")]
    return pytest.param(name, id=name, marks=marks)


class Harness:
    def __init__(self, root: Path, base: str, network=NetworkMode.NONE):
        self.root = root.resolve()
        self.base = base
        self.network = network
        self.work = self.root / "work"
        self.home = self.root / "home"
        self.temp = self.root / "temp"
        self.protected = self.work / "protected"
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
                return command_sandbox.profile(
                    command_sandbox.default_writable(self.work),
                    [*command_sandbox.default_protected(), self.protected],
                    offline=self.network == NetworkMode.NONE)
        if self.base == "outside-floor":
            return command_sandbox.minimal_profile(offline=self.network == NetworkMode.NONE)
        raise NotImplementedError(f"no profile adapter for {self.base}")

    def run(self, argv, *, profile=None, timeout=30, discard=False):
        """Bound a process group, including grandchildren; never retain service output."""
        text = self.profile() if profile is None else profile
        with subprocess.Popen(
            ["/usr/bin/sandbox-exec", "-p", text, *map(str, argv)], cwd=self.work, env=self.env,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL if discard else subprocess.PIPE,
            stderr=subprocess.DEVNULL if discard else subprocess.PIPE, text=True,
            start_new_session=True,
        ) as process:
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass  # The entire group has already exited.
                process.wait()
        return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)

    def python(self, source: str, *args, **kwargs):
        return self.run([sys.executable, "-I", "-c", source, *map(str, args)], **kwargs)

    def record_profile(self, record_property):
        record_property("base", self.base)
        record_property("network", self.network.value)
        record_property("profile_sha256", hashlib.sha256(self.profile().encode()).hexdigest())
