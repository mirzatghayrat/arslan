"""SkillPack — the skill-pack format contract (P0).

A spawn's deliverable is a *skill-pack*: a ``SKILL.md`` (YAML frontmatter + a
Markdown body that must carry ``## Trigger`` and ``## 决策规则`` sections) plus
cross-platform CLI scripts and a declarative credentials manifest. This module
defines the parsed model and section helpers; directory-level validation lives
in :func:`validate_skillpack` (see ``validate.py``).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from arslan.spawn.quality import CheckResult

#: Markdown sections every skill-pack body must carry (spec §4.2).
REQUIRED_SECTIONS = ("Trigger", "决策规则")


class CredentialSpec(BaseModel):
    """A credential the skill-pack declares it may need.

    Declarative only — never holds a plaintext secret. Actual values are
    resolved at runtime from CLI flag / .env / environment, and encrypted at
    rest via the server's crypto layer.
    """

    name: str
    required: bool = False
    description: str = ""
    storage: str = ""


class SkillPack(BaseModel):
    """Parsed representation of a ``SKILL.md`` frontmatter + body."""

    name: str
    description: str
    version: str
    authors: list[str] = Field(default_factory=list)
    credentials: list[CredentialSpec] = Field(default_factory=list)
    body: str = ""

    @classmethod
    def from_skill_md(cls, text: str) -> SkillPack:
        """Parse a ``SKILL.md`` string into a :class:`SkillPack`.

        Raises ``ValueError`` when the YAML frontmatter block is missing or
        not terminated.
        """
        frontmatter, body = _split_frontmatter(text)
        data = yaml.safe_load(frontmatter) or {}
        data["body"] = body
        return cls(**data)

    def has_section(self, title: str) -> bool:
        """True when the body contains a Markdown heading equal to ``title``."""
        for line in self.body.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                if stripped.lstrip("#").strip() == title:
                    return True
        return False


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Split a frontmatter document into ``(yaml_str, body_str)``."""
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        raise ValueError("SKILL.md missing YAML frontmatter (expected leading '---')")
    after_open = stripped[len("---"):].lstrip("\n")
    parts = after_open.split("\n---", 1)
    if len(parts) != 2:
        raise ValueError("SKILL.md frontmatter not terminated with '---'")
    frontmatter, body = parts
    return frontmatter, body.lstrip("\n")


class SkillPackValidator:
    """Validates a skill-pack *directory*, mirroring :class:`QualityGate`.

    Checks (each yields a :class:`CheckResult`): SKILL.md present, frontmatter
    parses with required fields, required body sections present, a CLI script
    exists, and the python CLI answers ``doc`` with exit code 0.
    """

    def __init__(self, pack_path: Path) -> None:
        self.pack_path = Path(pack_path)
        self._pack: SkillPack | None = None
        self._parse_error: str | None = None
        self._parsed = False

    # -- helpers ------------------------------------------------------------

    def _skill_md_path(self) -> Path:
        return self.pack_path / "SKILL.md"

    def _parse(self) -> SkillPack | None:
        if self._parsed:
            return self._pack
        self._parsed = True
        md = self._skill_md_path()
        if not md.exists():
            self._parse_error = "SKILL.md not found"
            return None
        try:
            self._pack = SkillPack.from_skill_md(md.read_text(encoding="utf-8"))
        except ValueError as exc:
            self._parse_error = str(exc)
        return self._pack

    def _cli_scripts(self) -> list[Path]:
        scripts = self.pack_path / "scripts"
        if not scripts.is_dir():
            return []
        return sorted(scripts.glob("*_cli.*"))

    # -- individual checks --------------------------------------------------

    def check_skill_md(self) -> CheckResult:
        if self._skill_md_path().exists():
            return CheckResult(name="skill_md", passed=True)
        return CheckResult(name="skill_md", passed=False, message="SKILL.md not found")

    def check_frontmatter(self) -> CheckResult:
        if self._parse() is None:
            msg = self._parse_error or "frontmatter parse failed"
            return CheckResult(name="frontmatter", passed=False, message=msg)
        return CheckResult(name="frontmatter", passed=True)

    def check_sections(self) -> CheckResult:
        pack = self._parse()
        if pack is None:
            return CheckResult(
                name="sections", passed=False,
                message="cannot check sections: frontmatter unparsed",
            )
        missing = [s for s in REQUIRED_SECTIONS if not pack.has_section(s)]
        if missing:
            return CheckResult(
                name="sections", passed=False,
                message=f"missing required section(s): {', '.join(missing)}",
            )
        return CheckResult(name="sections", passed=True)

    def check_cli_present(self) -> CheckResult:
        if self._cli_scripts():
            return CheckResult(name="cli_present", passed=True)
        return CheckResult(
            name="cli_present", passed=False, message="no scripts/*_cli.* found",
        )

    def check_cli_doc(self) -> CheckResult:
        py = [s for s in self._cli_scripts() if s.suffix == ".py"]
        if not py:
            return CheckResult(
                name="cli_doc", passed=False, message="no python CLI to run `doc`",
            )
        try:
            proc = subprocess.run(
                [sys.executable, str(py[0]), "doc"],
                capture_output=True, text=True, timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return CheckResult(name="cli_doc", passed=False, message=f"doc run error: {exc}")
        if proc.returncode != 0:
            return CheckResult(
                name="cli_doc", passed=False,
                message=f"`doc` exited {proc.returncode}: {proc.stderr.strip()[:120]}",
            )
        return CheckResult(name="cli_doc", passed=True)

    # -- composite ----------------------------------------------------------

    def run_all(self) -> list[CheckResult]:
        return [
            self.check_skill_md(),
            self.check_frontmatter(),
            self.check_sections(),
            self.check_cli_present(),
            self.check_cli_doc(),
        ]


def validate_skillpack(pack_path: Path | str) -> list[CheckResult]:
    """Run all skill-pack checks against a pack directory."""
    return SkillPackValidator(Path(pack_path)).run_all()
