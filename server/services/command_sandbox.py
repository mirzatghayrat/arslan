"""Seatbelt-wrapped execution of a whitelisted command (spec §组件2).

Reuses code_sandbox's Seatbelt wrapper and resource limits. A command is NEVER run
without an OS sandbox. No unrestricted compatibility fallback exists.

Assumes the caller already ran command_policy.validate() — this module does NOT
re-validate the whitelist; it only executes.

Filesystem access is limited to a host-selected workspace, temporary directory and
read-only tool runtimes. HOME/cwd alone are not a security boundary.
"""
from __future__ import annotations

import asyncio
import os
import json
import shutil
import signal
import tempfile
from pathlib import Path

from server.services.code_sandbox import (
    MAX_OUTPUT_CHARS,
    _child_limits,
    _seatbelt_wrapper,
)

TIMEOUT_S = 30.0  # commands (ffmpeg/pandoc) can be heavier than a python snippet


def command_profile(executable: Path, workspace: Path, temporary: Path,
                    proxy_port: int | None = None, read_files: tuple[Path, ...] = ()) -> str:
    """Kernel-enforced workspace boundary, with no host IPC or credential access.

    Runtime directories are read-only. Only the selected executable and Apple's
    git helpers can execute; project hooks and arbitrary system credential helpers cannot.
    Explicit file exceptions are host-selected public certificates, never secret material.
    """
    def quote(path):
        return json.dumps(str(Path(path).resolve()))
    lines = ["(version 1)", "(deny default)", "(allow sysctl-read)",
             "(allow file-read-metadata)", "(allow process-fork)",
             "(allow process-info* (target self))",
             '(allow file-read-data (literal "/"))']
    runtime = ("/System/Library", "/System/Volumes/Preboot/Cryptexes/OS", "/usr/lib",
               "/usr/share", "/usr/bin", "/bin", "/Library/Developer/CommandLineTools/usr",
               "/opt/homebrew/Cellar", "/opt/homebrew/lib", "/usr/local/Cellar", "/usr/local/lib")
    for path in runtime:
        lines.append(f"(allow file-read* file-map-executable (subpath {quote(path)}))")
    for path in {executable, executable.resolve()}:
        lines.append(f"(allow file-read* file-map-executable process-exec (literal {quote(path)}))")
    if executable.name == "git":
        for path in ("/Library/Developer/CommandLineTools/usr/bin/git",
                     "/Library/Developer/CommandLineTools/usr/libexec/git-core"):
            lines.append(f"(allow process-exec (subpath {quote(path)}))")
        # Homebrew git delegates HTTPS to this fixed helper, not a workspace hook.
        helper = executable.resolve().parent.parent / "libexec/git-core/git-remote-https"
        if helper.is_file():
            lines.append(f"(allow process-exec (literal {quote(helper)}))")
    for path in ("/dev/null", "/dev/random", "/dev/urandom", "/private/etc/localtime", *read_files):
        lines.append(f"(allow file-read* (literal {quote(path)}))")
    for path in {workspace.resolve(), temporary.resolve()}:
        lines.append(f"(allow file-read* file-write* (subpath {quote(path)}))")
    lines.append('(allow file-write* (literal "/dev/null"))')
    if proxy_port is not None:
        if not 1 <= proxy_port <= 65535:
            raise ValueError("Invalid proxy port")
        lines.append(f'(allow network-outbound (remote tcp "localhost:{proxy_port}"))')
    return "\n".join(lines) + "\n"


def _trunc(s: str) -> str:
    if len(s) <= MAX_OUTPUT_CHARS:
        return s
    return s[:MAX_OUTPUT_CHARS] + f"\n…[truncated, {len(s)} chars total]"


async def run_command(command: str, argv: list[str], *, timeout_s: float = TIMEOUT_S,
                      proxy_port: int | None = None, cwd: str | None = None,
                      extra_env: dict | None = None, read_files: tuple[Path, ...] = ()) -> dict:
    """Execute [command, *argv] inside a seatbelt sandbox. Returns {ok, stdout, stderr, exit_code}
    — plus error when not ok.

    Local commands (default): ephemeral workspace, HOME/TMPDIR scrubbed, ALL network denied.
    Network commands (git/gh): pass `proxy_port` → seatbelt allows ONLY localhost:proxy_port;
    `cwd` = the real repo (so git operates on it); `extra_env` = proxy/CA env. HOME/TMPDIR stay
    scrubbed to `tmp` to avoid ambient configuration. Absolute paths outside the allowed
    workspace/runtime are denied. The public CA is an explicit host-selected read exception."""
    tmp = Path(tempfile.mkdtemp(prefix="arslan-cmd-"))
    try:
        executable = shutil.which(command)
        if executable is None:
            return {"ok": False, "exit_code": None, "error": "command executable unavailable"}
        profile = command_profile(Path(executable), Path(cwd) if cwd else tmp, tmp, proxy_port, read_files)
        wrapper = _seatbelt_wrapper(profile)
        if wrapper is None:
            return {"ok": False, "exit_code": None,
                    "error": "command sandbox unavailable (macOS seatbelt required); refusing to run"}
        env = {"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
               "HOME": str(tmp), "TMPDIR": str(tmp), "LC_ALL": "en_US.UTF-8",
               "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
               "GIT_TERMINAL_PROMPT": "0"}
        if extra_env:
            if set(extra_env) - {"HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "GIT_SSL_CAINFO", "SSL_CERT_FILE", "GH_TOKEN"}:
                return {"ok": False, "exit_code": None, "error": "command environment override denied"}
            env.update(extra_env)
        cmd = [*wrapper, executable, *argv]
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=(cwd or str(tmp)), env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            start_new_session=True, preexec_fn=_child_limits,
        )
        try:
            out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        except asyncio.CancelledError:
            # Run cancel (S3-M1): the child must not outlive the cancelled task.
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
            await proc.wait()
            raise
        except TimeoutError:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
            await proc.wait()
            return {"ok": False, "exit_code": None,
                    "error": f"command timed out after {int(timeout_s)}s"}

        stdout = _trunc((out_b or b"").decode("utf-8", errors="replace"))
        stderr = _trunc((err_b or b"").decode("utf-8", errors="replace"))
        ok = proc.returncode == 0
        result = {"ok": ok, "exit_code": proc.returncode, "stdout": stdout, "stderr": stderr}
        if not ok:
            result["error"] = f"exit {proc.returncode}: {stderr[-500:] or 'no stderr'}"
        return result
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
