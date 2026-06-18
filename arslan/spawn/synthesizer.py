"""CLI synthesis — LLM-generated CLI scripts with validation + retry (P1.2).

When the deterministic templates can't express a tool's logic, the Architect
asks the LLM to write a self-contained CLI script. Each attempt is validated
(it must answer ``doc`` with exit 0); on failure the validation message is fed
back and the LLM retries, up to ``max_attempts``. This keeps a weak model on a
short leash — the framework verifies, the model only fills in the body.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from arslan.spawn.skillpack import SkillPackValidator


class SynthesisError(RuntimeError):
    """Raised when no valid CLI is produced within ``max_attempts``."""


_SYSTEM = (
    "You write a single self-contained Python CLI script for a spawn tool. "
    "The script MUST support a `doc` subcommand that prints usage and exits 0. "
    "Reply with ONLY the Python source — no prose, no explanation."
)


def _strip_fences(text: str) -> str:
    """Strip a leading/trailing Markdown code fence if present."""
    s = text.strip()
    if s.startswith("```"):
        lines = s.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    return s + "\n"


def _cli_doc_ok(script: str, slug: str) -> tuple[bool, str]:
    """Run the synthesized script through the validator's `doc` check."""
    with tempfile.TemporaryDirectory() as tmp:
        scripts = Path(tmp) / "scripts"
        scripts.mkdir()
        (scripts / f"{slug}_cli.py").write_text(script, encoding="utf-8")
        result = SkillPackValidator(Path(tmp)).check_cli_doc()
        return result.passed, result.message


async def synthesize_cli(adapter, *, name: str, slug: str, need: str, max_attempts: int = 3) -> str:
    """Ask ``adapter`` to write a CLI for ``need``; validate and retry.

    Returns the validated script source. Raises :class:`SynthesisError` when all
    attempts fail validation.
    """
    last_msg = ""
    for _ in range(max_attempts):
        user = f"Tool need for spawn '{name}': {need}"
        if last_msg:
            user += f"\n\nThe previous attempt failed validation: {last_msg}\nFix it."
        resp = await adapter.chat(system=_SYSTEM, user=user)
        script = _strip_fences(resp.content or "")
        ok, msg = _cli_doc_ok(script, slug)
        if ok:
            return script
        last_msg = msg
    raise SynthesisError(f"CLI synthesis failed after {max_attempts} attempts: {last_msg}")
