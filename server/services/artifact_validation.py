"""Bounded file integrity/parsing checks; parsing is never a claim of visual quality."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import signal
import tempfile

from server.services import artifact_store, code_sandbox


async def inspect_bytes(data: bytes, suffix: str) -> dict:
    """Fixed parser in the default-deny compute sandbox, with no fallback/install."""
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
        source = Path(__file__).resolve().parent.parent / "resources" / "artifact_inspector.py"
        (workspace / "inspect_file.py").write_bytes(source.read_bytes())
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
