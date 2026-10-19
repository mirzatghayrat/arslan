"""Bounded file integrity/parsing checks; parsing is never a claim of visual quality."""
from __future__ import annotations

import asyncio
from functools import cache
import importlib.util
import json
import os
from pathlib import Path
import signal
import tempfile

from server.services import artifact_store, code_sandbox


_INSPECTOR = Path(__file__).resolve().parent.parent / "resources" / "artifact_inspector.py"


@cache
def checked_suffixes() -> frozenset[str]:
    """The suffixes the isolated inspector has a parser for: its own CHECKED_SUFFIXES, read from
    its file (it ships as a resource file, not an importable module, packaging/arslan-server.spec).
    This executes the inspector's top level in the host process, outside the sandbox: that top
    level must stay definitions only (constants, functions, the __main__ guard), never work."""
    spec = importlib.util.spec_from_file_location("arslan_artifact_inspector", _INSPECTOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return frozenset(module.CHECKED_SUFFIXES)


async def inspect_bytes(data: bytes, suffix: str) -> dict:
    """Fixed parser in the default-deny compute sandbox, with no fallback/install.

    0.1.63 D2: a type nothing parses is not_applicable, decided here before any sandbox starts
    (the isolated result is only ever passed / failed / not_run). "No parser" is not "the check did
    not run": a helper .swift a turn saved held finished work as task_checks_not_run (M1B, T1).
    Real failures stay not_run or failed: no host Python, no isolation, a timeout, a crash."""
    suffix = suffix.lower()          # ".PDF" from a direct caller is still checked, not skipped
    if suffix not in checked_suffixes():
        return {"status": "not_applicable", "code": "artifact_type_not_checked"}
    return await _inspect_isolated(data, suffix)


async def _inspect_isolated(data: bytes, suffix: str) -> dict:
    try:
        python = code_sandbox._host_python()
    except (RuntimeError, OSError):
        return {"status": "not_run", "code": "artifact_parser_unavailable"}
    with tempfile.TemporaryDirectory(prefix="arslan-validate-") as directory:
        workspace = Path(directory).resolve()
        wrapper = code_sandbox._seatbelt_wrapper(code_sandbox.computation_profile(python, workspace))
        if wrapper is None:
            return {"status": "not_run", "code": "artifact_parser_isolation_unavailable"}
        (workspace / "input.bin").write_bytes(data)
        (workspace / "inspect_file.py").write_bytes(_INSPECTOR.read_bytes())
        try:
            process = await asyncio.create_subprocess_exec(*wrapper, python, "-I", str(workspace / "inspect_file.py"), suffix,
                cwd=workspace, env={"PATH": "/usr/bin:/bin", "HOME": str(workspace), "TMPDIR": str(workspace),
                                    "LC_ALL": "en_US.UTF-8"},
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True, preexec_fn=code_sandbox._child_limits)
        except OSError:
            return {"status": "not_run", "code": "artifact_parser_unavailable"}
        try:
            from arslan.execution_budget import current
            budget = current()
            timeout = min(8, budget.remaining_seconds()) if budget is not None else 8
            output, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except (asyncio.CancelledError, TimeoutError) as exc:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.wait()
            if isinstance(exc, asyncio.CancelledError):
                raise
            return {"status": "not_run", "code": "artifact_parser_timeout"}
        if process.returncode != 0 or len(output) > 4096:
            return {"status": "not_run", "code": "artifact_parser_unavailable"}
        try:
            result = json.loads(output)
            if result.get("status") in {"passed", "failed", "not_run"} and isinstance(result.get("code"), str):
                return result
        except (ValueError, AttributeError):
            pass
        return {"status": "not_run", "code": "artifact_parser_unavailable"}


async def validate(run_id: int, filename: str, *, expected_hash: str | None = None,
                   title: str | None = None, logical_key: str | None = None) -> dict:
    identity = f"artifact:{filename}"
    base = {"id": identity, "run_id": run_id, "filename": filename,
            "url": f"/api/v1/runs/{run_id}/artifacts/{filename}", "title": title, "logical_key": logical_key}
    try:
        metadata, data = artifact_store.read_owned(run_id, filename)
    except (OSError, ValueError, TypeError):
        return {**base, "status": "failed", "code": "artifact_missing_or_changed"}
    base.update({"sha256": metadata["sha256"], "bytes": len(data), "title": metadata.get("title", filename)})
    if logical_key is not None and metadata.get("logical_key") != logical_key:
        return {**base, "status": "failed", "code": "artifact_identity_mismatch"}
    base["logical_key"] = metadata.get("logical_key")
    if expected_hash is not None and expected_hash != metadata["sha256"]:
        return {**base, "status": "failed", "code": "artifact_hash_mismatch"}
    if not data:
        return {**base, "status": "failed", "code": "artifact_empty"}
    inspected = await inspect_bytes(data, Path(filename).suffix.lower())
    return {**base, **inspected}
