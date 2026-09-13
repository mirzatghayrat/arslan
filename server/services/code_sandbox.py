"""Sandboxed Python execution (P1 — the capability that lets spawns actually DO things).

Security model (decisions locked with the user 2026-07-02):
  • On-demand subprocess — no daemon, no container, zero cost when unused.
  • Ephemeral cwd: a fresh tmpdir per run, deleted afterwards.
  • Env fully scrubbed: the child NEVER inherits the server env (no API keys, no DB paths).
  • Resource caps: wall-clock timeout (process-group kill), CPU/address-space/file-size rlimits.
  • Default-deny macOS `sandbox-exec`: runtime read-only, temporary workspace read/write,
    staged references read-only, network and host IPC denied. A missing or failing
    wrapper never triggers an automatic unsandboxed retry. Only the separately configured
    developer escape valve may select an unisolated backend BEFORE execution.
  • Desktop batteries: standalone Python + locked numpy/pandas/matplotlib bundled at build
    time, with no first-run downloads. Source installs create a dedicated venv lazily from
    the host side and explicitly report a host-runtime fallback if that setup fails.

The model supplies CODE TEXT via the safe-tier `run_python` tool; this module is the only
execution path and applies every guard unconditionally.
"""
from __future__ import annotations

import asyncio
import json
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

# Legacy command profile: network isolation ONLY. Commands require separate user approval.
# Python uses computation_profile below; cwd/HOME are never filesystem security boundaries.
_SEATBELT_PROFILE = "(version 1)\n(allow default)\n(deny network*)\n"

# Module cache: resolved sandbox interpreter + one-line env note. Tests may preset this.
_env_cache: tuple[str, str] | None = None


def _data_dir() -> Path:
    # Single resolved root (config.data_dir()): unset ARSLAN_DATA_DIR -> the platform
    # app-data dir, NOT CWD/data — so sandbox_env co-locates with the brain instead of
    # splitting off. Already absolute+resolved: run_python spawns with cwd=tmpdir, so a
    # relative interpreter path would be (wrongly) resolved inside the tmpdir.
    from server import config
    return config.data_dir()


def _create_batteries_env(venv_dir: Path) -> tuple[str, str]:
    """Host-side, one-time: venv + numpy/pandas/matplotlib. Blocking — call in a thread.
    Writes a .ready marker ONLY after pip succeeds, so a half-built env (venv created, pip
    failed) is never mistaken for a working one on the next boot."""
    subprocess.run([_host_python(), "-m", "venv", "--clear", str(venv_dir)],
                   check=True, capture_output=True, timeout=120)
    py = venv_dir / "bin" / "python"
    subprocess.run([str(py), "-m", "pip", "install", "--quiet", *_BATTERIES],
                   check=True, capture_output=True, timeout=600)
    (venv_dir / ".ready").write_text("ok")
    return str(py), "batteries: numpy/pandas/matplotlib"


def _host_python() -> str:
    """A frozen sidecar is NOT a Python CLI; never re-launch the server as one."""
    if not getattr(sys, "frozen", False):
        return sys.executable
    configured = os.environ.get("ARSLAN_SANDBOX_PYTHON", "").strip()
    bundled = Path(sys.executable).parent / "python_runtime" / "bin" / "python3"
    python = configured or (str(bundled) if bundled.is_file() else None)
    if not python or not Path(python).is_absolute() or not Path(python).is_file():
        raise RuntimeError("Packaged Python execution requires Python 3.11+ in the app bundle; "
                           "reinstall Arslan or explicitly set ARSLAN_SANDBOX_PYTHON")
    if Path(python).resolve() == Path(sys.executable).resolve():
        raise RuntimeError("The packaged server cannot be used as the sandbox interpreter")
    probe = subprocess.run(
        [python, "-I", "-c", "import sys; print(int(sys.version_info >= (3, 11)))"],
        capture_output=True, text=True, timeout=5,
        env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent"},
    )
    if probe.returncode != 0 or probe.stdout.strip() != "1":
        raise RuntimeError("Sandbox interpreter must be a working Python 3.11+")
    return python


async def _sandbox_python() -> tuple[str, str]:
    """Resolve (interpreter, env_note), creating the batteries venv lazily on first use."""
    global _env_cache
    if _env_cache is not None:
        return _env_cache
    if getattr(sys, "frozen", False):
        # The signed, build-time populated runtime is read-only to generated code.
        # Never run pip, create a venv, or silently borrow Homebrew in a desktop install.
        python = await asyncio.to_thread(_host_python)
        _env_cache = (python, "packaged Python runtime (no first-run downloads)")
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
        _env_cache = (_host_python(), "batteries unavailable — using host Python runtime")
    return _env_cache


def _child_limits() -> None:
    """Applied inside the child before exec: CPU, memory, file size."""
    resource.setrlimit(resource.RLIMIT_CPU, (int(TIMEOUT_S), int(TIMEOUT_S) + 2))
    try:
        resource.setrlimit(resource.RLIMIT_AS, (_MEM_BYTES, _MEM_BYTES))
    except (ValueError, OSError):
        pass  # RLIMIT_AS is unreliable on some macOS versions; CPU+timeout still bound us
    resource.setrlimit(resource.RLIMIT_FSIZE, (_FSIZE_BYTES, _FSIZE_BYTES))


def net_profile(proxy_port: int) -> str:
    """Deny all network EXCEPT the local credential proxy — the sandbox's ONLY way out. Seatbelt
    requires the host be `*` or `localhost` (a literal `127.0.0.1:port` is REJECTED — verified
    empirically), and `remote tcp "localhost:port"` is the working form; connecting to 127.0.0.1
    matches it. Used for network git/gh so their HTTPS traffic can only reach the proxy."""
    return (f"(version 1)\n(allow default)\n(deny network*)\n"
            f'(allow network-outbound (remote tcp "localhost:{proxy_port}"))\n')


def readonly_profile(ro_subpath: str) -> str:
    """Deny-all-network PLUS a kernel-enforced deny on WRITES to the staged references dir
    (PC-3 ②). `file-write*` covers write-data, unlink, AND chmod (file-write-mode), so a
    same-uid script CANNOT chmod-then-write its way past the advisory 0o444/0o555 mode bits —
    the kernel refuses regardless of POSIX owner perms. Seatbelt matches on REALPATH, so
    `ro_subpath` MUST already be the resolved (symlink-free) absolute path of the run's
    references/ subdir. macOS-only enforcement; on Linux run_python is fail-closed (no run)."""
    return (f"(version 1)\n(allow default)\n(deny network*)\n"
            f'(deny file-write* (subpath "{ro_subpath}"))\n')


def computation_profile(python: str, workspace: Path, references: Path | None = None) -> str:
    """Default-deny compute policy: runtime reads, workspace writes, no network/host IPC.

    Grant only the interpreter's installation and venv libraries, never their parent
    project or the app-data root. Resolve symlinks before constructing Seatbelt paths.
    JSON quoting is also valid for these SBPL strings and prevents path injection.
    """
    executable = Path(python).absolute()
    resolved = executable.resolve()
    prefixes = {executable.parent.parent, resolved.parent.parent}
    reads = {Path("/System/Library"), Path("/System/Volumes/Preboot/Cryptexes/OS"),
             Path("/usr/lib"), Path("/usr/share/locale")}
    for prefix in prefixes:
        reads.update({(prefix / "lib").resolve(), (prefix / "bin").resolve()})
    lines = ["(version 1)", "(deny default)", "(allow sysctl-read)",
             # dyld on macOS 26 reads the root vnode while locating its shared cache.
             # Literal '/', unlike subpath '/', does NOT grant descendants.
             '(allow file-read-data (literal "/"))',
             "(allow file-read-metadata)", "(allow process-fork)",
             "(allow process-info* (target self))"]
    for path in sorted(reads):
        lines.append(f"(allow file-read* file-map-executable (subpath {json.dumps(str(path))}))")
    for path in ("/dev/null", "/dev/random", "/dev/urandom", "/private/etc/localtime"):
        lines.append(f"(allow file-read* (literal {json.dumps(path)}))")
    for path in {executable, resolved}:
        lines.append(f"(allow process-exec (literal {json.dumps(str(path))}))")
    # Python uses pyvenv.cfg to locate the base stdlib; this does not grant sibling reads.
    for prefix in prefixes:
        lines.append(f"(allow file-read* (literal {json.dumps(str(prefix / 'pyvenv.cfg'))}))")
    lines.append(f"(allow file-read* file-write* (subpath {json.dumps(str(workspace.resolve()))}))")
    lines.append('(allow file-write* (literal "/dev/null"))')
    if references is not None:
        lines.append(f"(deny file-write* (subpath {json.dumps(str(references.resolve()))}))")
    return "\n".join(lines) + "\n"


def _seatbelt_wrapper(profile: str | None = None) -> list[str] | None:
    """The seatbelt wrapper, when usable. Probed once per process. `profile` overrides the default
    deny-all-network one (e.g. net_profile(port) to allow ONLY the local credential proxy)."""
    if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").exists():
        return None
    return ["/usr/bin/sandbox-exec", "-p", profile or _SEATBELT_PROFILE]


# ── Pluggable sandbox backends ──────────────────────────────────────────────────
# A backend answers two questions: is a real OS-level isolation mechanism available
# here, and (if so) how do we wrap the child process to enforce it. run_python selects
# one per run and FAILS CLOSED when none is available (unless the visible escape valve is
# set). run_command already refuses on no-wrapper; this aligns run_python to the same bar.

class SandboxBackend:
    """Isolation mechanism interface. `available()` must be honest — return True only when
    the wrapper will actually enforce isolation on this host."""

    name: str = "abstract"

    def available(self) -> bool:  # pragma: no cover - overridden
        raise NotImplementedError

    def wrapper(self, profile: str | None = None) -> list[str] | None:  # pragma: no cover
        raise NotImplementedError


class SeatbeltBackend(SandboxBackend):
    """macOS seatbelt (`sandbox-exec`, kernel-enforced). The only real isolation v1 ships."""

    name = "seatbelt"

    def available(self) -> bool:
        return sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").exists()

    def wrapper(self, profile: str | None = None) -> list[str] | None:
        return _seatbelt_wrapper(profile)


class BubblewrapBackend(SandboxBackend):
    """Linux bubblewrap (`bwrap`) namespace sandbox — NOT YET IMPLEMENTED. Stub kept so the
    registry has a Linux slot to fill; until then it reports unavailable so run_python fails
    closed on Linux rather than running unsandboxed by default."""

    name = "bubblewrap"

    def available(self) -> bool:
        # TODO(P0-followup): implement Linux bubblewrap sandbox (bwrap unshare + net-deny).
        return False

    def wrapper(self, profile: str | None = None) -> list[str] | None:  # pragma: no cover - stub
        return None


class NullBackend(SandboxBackend):
    """No isolation available. Present so run_python can detect 'no backend' and refuse."""

    name = "null"

    def available(self) -> bool:
        return False

    def wrapper(self, profile: str | None = None) -> list[str] | None:
        return None


def _select_backend() -> SandboxBackend:
    """Pick the isolation backend for this host: darwin → seatbelt, else → null (fail closed).
    The Linux bubblewrap slot exists (BubblewrapBackend) but is unavailable until implemented."""
    if sys.platform == "darwin":
        return SeatbeltBackend()
    return NullBackend()


def _unsandboxed_valve_open() -> bool:
    """The deliberate, VISIBLE escape valve: ARSLAN_ALLOW_UNSANDBOXED_PY truthy lets run_python
    execute WITHOUT isolation (pure-stdlib no-net compute is real before bubblewrap lands)."""
    from server import config
    if (config.settings.is_prod or getattr(sys, "frozen", False)
            or os.environ.get("ARSLAN_PACKAGED", "").strip().lower() in {"1", "true", "yes", "on"}):
        return False
    return os.environ.get("ARSLAN_ALLOW_UNSANDBOXED_PY", "").strip().lower() in (
        "1", "true", "yes", "on")


def unsandboxed_active() -> bool:
    """Is run_python currently running UNSANDBOXED? Drives the capability-page warning badge.
    darwin → always False (seatbelt works); elsewhere → True only when the escape valve is open
    (valve off = we refuse, so no unsandboxed runs happen)."""
    return (not _select_backend().available()) and _unsandboxed_valve_open()


def backend_available() -> bool:
    """PC-5 honest, read-only probe: is a real OS-level isolation backend usable on THIS host?

    Selects the backend for this platform and asks its `available()` — it NEVER executes any
    code. Skill health uses it to decide whether a bundled script is truly runnable (a `.py`
    that is otherwise clean is only "runnable" when isolation is actually available; on a host
    with no backend the honest verdict is "sandbox unavailable")."""
    return _select_backend().available()


def backend_name() -> str:
    """Name of the isolation backend selected on this host ("seatbelt"/"bubblewrap"/"null").
    Reported alongside the skill-health verdict so the reason is auditable."""
    return _select_backend().name


def _truncate(s: str) -> str:
    if len(s) <= MAX_OUTPUT_CHARS:
        return s
    return s[:MAX_OUTPUT_CHARS] + f"\n…[truncated, {len(s)} chars total]"


async def _bounded_communicate(proc) -> tuple[bytes, bytes]:
    """Drain pipes continuously but retain only a bounded prefix, not unbounded RAM."""
    if not hasattr(proc, "stdout") or not hasattr(proc, "stderr"):
        return await proc.communicate()  # Minimal injected process doubles.

    async def read(stream):
        kept = bytearray()
        total = 0
        while block := await stream.read(65536):
            total += len(block)
            kept.extend(block[:max(0, MAX_OUTPUT_CHARS * 4 - len(kept))])
        if total > len(kept):
            kept.extend(f"\n[output truncated; {total} bytes]".encode())
        return bytes(kept)

    out, err = await asyncio.gather(read(proc.stdout), read(proc.stderr))
    await proc.wait()
    return out, err


async def run_python(code: str, *, timeout_s: float = TIMEOUT_S,
                     extra_files: dict[str, str] | None = None,
                     read_only_files: dict[str, str] | None = None) -> dict:
    """Execute `code` in the sandbox. `extra_files` (name → content, flat safe names) are
    written beside main.py before exec — used for imported skills' bundled scripts so
    sibling imports/data files work.

    `read_only_files` (name → content) are the skill's bundled references (PC-3 ②): their
    CONTENT is copied into a `references/` subdir of the ephemeral run tmpdir so a script can
    READ them. Enforcement of read-only is PER PLATFORM (be precise about the source):
      • macOS: a seatbelt rule `(deny file-write* (subpath <references realpath>))` makes the
        references genuinely read-only — the kernel refuses write/unlink/chmod even to the
        same-uid owner, so a chmod-then-write bypass of the advisory 0o444/0o555 mode bits is
        DENIED. This is the real guarantee. (The 0o444/0o555 bits are belt-and-suspenders.)
      • Linux/other: run_python is FAIL-CLOSED above (no isolation backend → refuses), so
        skill-script execution does not run there at all — the deny rule does NOT protect
        Linux because nothing executes there. Do not imply otherwise.
    Independently of platform, the STORED originals are never handed to the sandbox (only
    their text crosses the boundary), so no in-sandbox action can affect the stored files.

    Returns {ok, stdout, stderr, exit_code, files, network_isolated, env_note} — plus error
    when not ok."""
    if not isinstance(code, str) or not code.strip():
        return {"ok": False, "error": "missing 'code'"}
    if len(code) > MAX_CODE_CHARS:
        return {"ok": False, "error": f"code too large (max {MAX_CODE_CHARS} chars)"}

    # Fail closed: if no real isolation backend is available (non-darwin until bubblewrap
    # lands, or a broken seatbelt), REFUSE — unless the deliberate, visible escape valve is
    # set. This aligns run_python with run_command (command_sandbox refuses on no-wrapper).
    backend = _select_backend()
    if not backend.available():
        if not _unsandboxed_valve_open():
            return {"ok": False, "sandboxed": False,
                    "error": "沙箱不可用(需 macOS seatbelt),已拒绝执行 run_python;"
                             "设 ARSLAN_ALLOW_UNSANDBOXED_PY=1 可强制裸跑(不安全)"}
        logger.warning("⚠ UNSANDBOXED run_python (ARSLAN_ALLOW_UNSANDBOXED_PY=1): "
                       "no isolation — code ran with full host access")
        sandboxed = False
    else:
        sandboxed = True

    try:
        python, env_note = await _sandbox_python()
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "sandboxed": False, "network_isolated": False,
                "error": str(exc)}
    tmp = Path(tempfile.mkdtemp(prefix="arslan-sbx-"))
    try:
        script = tmp / "main.py"
        script.write_text(code, encoding="utf-8")
        (tmp / ".mpl").mkdir()
        extra_names = set()
        for fname, content in (extra_files or {}).items():
            # flat, safe names only — no separators, no traversal, never main.py
            if not re.fullmatch(r"[A-Za-z0-9._-]+", fname) or fname in {".", "..", "main.py"}:
                continue
            (tmp / fname).write_text(str(content), encoding="utf-8")
            extra_names.add(fname)
        # Read-only references (PC-3 ②): copy CONTENT into references/. The REAL read-only
        # enforcement is the seatbelt deny rule below (applied to the realpath of this dir);
        # the 0o444/0o555 mode bits are belt-and-suspenders (advisory against the owner).
        # Perms are restored in `finally` so cleanup (rmtree) still works.
        ro_dir = tmp / "references"
        wrote_ro = False
        for fname, content in (read_only_files or {}).items():
            if not re.fullmatch(r"[A-Za-z0-9._-]+", fname) or fname in {".", ".."}:
                continue
            if not wrote_ro:
                ro_dir.mkdir()
                wrote_ro = True
            fp = ro_dir / fname
            fp.write_text(str(content), encoding="utf-8")
            fp.chmod(0o444)
        if wrote_ro:
            ro_dir.chmod(0o555)
        # Scrubbed env: NOTHING from the server process leaks into the child.
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp), "TMPDIR": str(tmp),
            "MPLBACKEND": "Agg", "MPLCONFIGDIR": str(tmp / ".mpl"),
            "PYTHONDONTWRITEBYTECODE": "1", "LC_ALL": "en_US.UTF-8",
        }
        argv = [python, str(script)]
        # When references are staged, tighten the seatbelt profile with a kernel write-deny on
        # their REALPATH (resolve symlinks — seatbelt matches realpath; /var → /private/var on
        # macOS). Only emit the rule when the dir exists, and never loosen the base profile.
        profile = computation_profile(python, tmp, ro_dir if wrote_ro else None) if sandboxed else None
        wrapper = backend.wrapper(profile) if sandboxed else None
        if sandboxed and not wrapper:
            return {"ok": False, "sandboxed": False, "network_isolated": False,
                    "error": "sandbox backend returned no wrapper; refusing to execute",
                    "env_note": env_note}
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
            out_b, err_b = await asyncio.wait_for(_bounded_communicate(proc), timeout=timeout_s)
        except asyncio.CancelledError:
            # Run cancel (S3-M1): the child must not outlive the cancelled task.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
            await proc.wait()
            raise
        except TimeoutError:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
            await proc.wait()
            return {"ok": False, "error": f"execution timed out after {int(timeout_s)}s",
                    "sandboxed": sandboxed,
                    "network_isolated": network_isolated, "env_note": env_note}

        # stderr is untrusted program output, not proof of a launcher failure. Even a
        # genuine sandbox startup failure must remain a failure: never retry with fewer
        # restrictions. The execution decision above is final for this invocation.
        # A child may close its pipes and keep running after the interpreter exits.
        # Kill the owned session's remaining group before snapshotting files.
        if getattr(proc, "pid", None) is not None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        stdout = _truncate((out_b or b"").decode("utf-8", errors="replace"))
        stderr = _truncate((err_b or b"").decode("utf-8", errors="replace"))
        from itertools import islice
        files = sorted(
            f"{p.relative_to(tmp)} ({p.stat().st_size}B)"
            for p in islice(tmp.rglob("*"), 512)
            if not p.is_symlink() and p.is_file() and p != script and ".mpl" not in p.parts
            and "references" not in p.parts  # read-only inputs we staged, not code outputs
            and p.name not in extra_names  # inputs we staged, not outputs the code produced
        )
        result = {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": stdout, "stderr": stderr, "files": files,
            "sandboxed": sandboxed,
            "network_isolated": network_isolated, "env_note": env_note,
        }
        from server.services import artifact_store, execution_context
        run_id = execution_context.current_run_id()
        if run_id is not None:
            artifacts, warnings = artifact_store.export_workspace(
                run_id, tmp, excluded={"main.py", ".mpl", "references", *extra_names})
            result["artifacts"] = artifacts
            result["artifact_warnings"] = warnings
        elif files:
            result["artifact_warnings"] = [
                "No recorded Run owns this execution; temporary files are not downloadable"]
        if proc.returncode != 0:
            result["error"] = f"exit {proc.returncode}: {stderr[-500:] or 'no stderr'}"
        return result
    finally:
        # Restore write perms on the locked-down references/ so rmtree can clean it up
        # (a 0o555 dir / 0o444 files would otherwise leak the tmpdir).
        ro_dir = tmp / "references"
        if not ro_dir.is_symlink() and ro_dir.is_dir():
            try:
                ro_dir.chmod(0o755)
                for p in ro_dir.iterdir():
                    if not p.is_symlink():
                        p.chmod(0o644)
            except OSError:
                pass
        shutil.rmtree(tmp, ignore_errors=True)
