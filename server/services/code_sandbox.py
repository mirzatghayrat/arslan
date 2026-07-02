"""Sandboxed Python execution (P1 — the capability that lets spawns actually DO things).

Security model (decisions locked with the user 2026-07-02):
  • On-demand subprocess — no daemon, no container, zero cost when unused.
  • Ephemeral cwd: a fresh tmpdir per run, deleted afterwards.
  • Env fully scrubbed: the child NEVER inherits the server env (no API keys, no DB paths).
  • Resource caps: wall-clock timeout (process-group kill), CPU/address-space/file-size rlimits.
  • NETWORK DENIED on macOS via `sandbox-exec` (kernel seatbelt). If the wrapper is unavailable
    (non-darwin, or nested-sandbox environments), we run WITHOUT it and say so honestly in the
    result — never silently pretend isolation. v2: user-configurable domain allowlist.
  • Batteries: a dedicated venv with numpy/pandas/matplotlib, created lazily on FIRST use from
    the host side (host has network; the sandboxed child does not). Falls back to the server's
    interpreter (stdlib-only) if creation fails — again, stated in the result.

The model supplies CODE TEXT via the safe-tier `run_python` tool; this module is the only
execution path and applies every guard unconditionally.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

TIMEOUT_S = 15.0            # < tool_loop's 20s per-tool cap, leaves headroom
MAX_CODE_CHARS = 100_000
MAX_OUTPUT_CHARS = 20_000   # stdout and stderr each, tail-truncated
_MEM_BYTES = 1024 ** 3      # 1 GB address space (pandas/matplotlib need room)
_FSIZE_BYTES = 50 * 1024 ** 2
_BATTERIES = ("numpy", "pandas", "matplotlib")

# Seatbelt profile: allow everything EXCEPT network. File writes are already confined by
# cwd=tmpdir + scrubbed HOME/TMPDIR + FSIZE rlimit; the hard line v1 draws is exfiltration.
_SEATBELT_PROFILE = "(version 1)\n(allow default)\n(deny network*)\n"

# Module cache: resolved sandbox interpreter + one-line env note. Tests may preset this.
_env_cache: tuple[str, str] | None = None


def _data_dir() -> Path:
    # resolve(): run_python spawns with cwd=tmpdir, so a relative interpreter path would be
    # (wrongly) resolved inside the tmpdir. The sandbox env must be addressed absolutely.
    return Path(os.environ.get("ARSLAN_DATA_DIR", "data")).resolve()


def _create_batteries_env(venv_dir: Path) -> tuple[str, str]:
    """Host-side, one-time: venv + numpy/pandas/matplotlib. Blocking — call in a thread.
    Writes a .ready marker ONLY after pip succeeds, so a half-built env (venv created, pip
    failed) is never mistaken for a working one on the next boot."""
    subprocess.run([sys.executable, "-m", "venv", "--clear", str(venv_dir)],
                   check=True, capture_output=True, timeout=120)
    py = venv_dir / "bin" / "python"
    subprocess.run([str(py), "-m", "pip", "install", "--quiet", *_BATTERIES],
                   check=True, capture_output=True, timeout=600)
    (venv_dir / ".ready").write_text("ok")
    return str(py), "batteries: numpy/pandas/matplotlib"


async def _sandbox_python() -> tuple[str, str]:
    """Resolve (interpreter, env_note), creating the batteries venv lazily on first use."""
    global _env_cache
    if _env_cache is not None:
        return _env_cache
    venv_dir = _data_dir() / "sandbox_env"
    py = venv_dir / "bin" / "python"
    if py.exists() and (venv_dir / ".ready").exists():
        _env_cache = (str(py), "batteries: numpy/pandas/matplotlib")
        return _env_cache
    try:
        _env_cache = await asyncio.to_thread(_create_batteries_env, venv_dir)
    except Exception as exc:  # noqa: BLE001 — degraded but honest fallback
        logger.warning("sandbox batteries env creation failed: %s", exc)
        shutil.rmtree(venv_dir, ignore_errors=True)
        _env_cache = (sys.executable, "batteries unavailable — stdlib only")
    return _env_cache


def _child_limits() -> None:
    """Applied inside the child before exec: CPU, memory, file size."""
    resource.setrlimit(resource.RLIMIT_CPU, (int(TIMEOUT_S), int(TIMEOUT_S) + 2))
    try:
        resource.setrlimit(resource.RLIMIT_AS, (_MEM_BYTES, _MEM_BYTES))
    except (ValueError, OSError):
        pass  # RLIMIT_AS is unreliable on some macOS versions; CPU+timeout still bound us
    resource.setrlimit(resource.RLIMIT_FSIZE, (_FSIZE_BYTES, _FSIZE_BYTES))


def _seatbelt_wrapper() -> list[str] | None:
    """The network-deny wrapper, when usable. Probed once per process."""
    if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").exists():
        return None
    return ["/usr/bin/sandbox-exec", "-p", _SEATBELT_PROFILE]


def _truncate(s: str) -> str:
    if len(s) <= MAX_OUTPUT_CHARS:
        return s
    return s[:MAX_OUTPUT_CHARS] + f"\n…[truncated, {len(s)} chars total]"


async def run_python(code: str, *, timeout_s: float = TIMEOUT_S,
                     extra_files: dict[str, str] | None = None) -> dict:
    """Execute `code` in the sandbox. `extra_files` (name → content, flat safe names) are
    written beside main.py before exec — used for imported skills' bundled scripts so
    sibling imports/data files work. Returns
    {ok, stdout, stderr, exit_code, files, network_isolated, env_note} — plus error when not ok."""
    if not isinstance(code, str) or not code.strip():
        return {"ok": False, "error": "missing 'code'"}
    if len(code) > MAX_CODE_CHARS:
        return {"ok": False, "error": f"code too large (max {MAX_CODE_CHARS} chars)"}

    python, env_note = await _sandbox_python()
    tmp = Path(tempfile.mkdtemp(prefix="arslan-sbx-"))
    try:
        script = tmp / "main.py"
        script.write_text(code, encoding="utf-8")
        (tmp / ".mpl").mkdir()
        extra_names = set()
        for fname, content in (extra_files or {}).items():
            # flat, safe names only — no separators, no traversal, never main.py
            if not re.fullmatch(r"[A-Za-z0-9._-]+", fname) or fname == "main.py":
                continue
            (tmp / fname).write_text(str(content), encoding="utf-8")
            extra_names.add(fname)
        # Scrubbed env: NOTHING from the server process leaks into the child.
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp), "TMPDIR": str(tmp),
            "MPLBACKEND": "Agg", "MPLCONFIGDIR": str(tmp / ".mpl"),
            "PYTHONDONTWRITEBYTECODE": "1", "LC_ALL": "en_US.UTF-8",
        }
        argv = [python, str(script)]
        wrapper = _seatbelt_wrapper()
        network_isolated = wrapper is not None
        if wrapper:
            argv = [*wrapper, *argv]

        async def _spawn(cmd: list[str]):
            return await asyncio.create_subprocess_exec(
                *cmd, cwd=str(tmp), env=env,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                start_new_session=True, preexec_fn=_child_limits,
            )

        proc = await _spawn(argv)
        try:
            out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        except TimeoutError:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
            await proc.wait()
            return {"ok": False, "error": f"execution timed out after {int(timeout_s)}s",
                    "network_isolated": network_isolated, "env_note": env_note}

        # Nested-sandbox environments refuse sandbox-exec itself (exit 65/71 before user code
        # runs). Retry WITHOUT the wrapper and report isolation honestly.
        if wrapper and proc.returncode != 0 and b"sandbox-exec" in (err_b or b""):
            network_isolated = False
            proc = await _spawn([python, str(script)])
            try:
                out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
            except TimeoutError:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    proc.kill()
                await proc.wait()
                return {"ok": False, "error": f"execution timed out after {int(timeout_s)}s",
                        "network_isolated": network_isolated, "env_note": env_note}

        stdout = _truncate((out_b or b"").decode("utf-8", errors="replace"))
        stderr = _truncate((err_b or b"").decode("utf-8", errors="replace"))
        files = sorted(
            f"{p.relative_to(tmp)} ({p.stat().st_size}B)"
            for p in tmp.rglob("*")
            if p.is_file() and p != script and ".mpl" not in p.parts
            and p.name not in extra_names  # inputs we staged, not outputs the code produced
        )
        result = {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": stdout, "stderr": stderr, "files": files,
            "network_isolated": network_isolated, "env_note": env_note,
        }
        if proc.returncode != 0:
            result["error"] = f"exit {proc.returncode}: {stderr[-500:] or 'no stderr'}"
        return result
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
