"""QualityGate — validates a generated spawn directory."""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str = ""


class QualityGate:
    """Runs a suite of checks against a spawn directory."""

    def __init__(self, spawn_path: Path) -> None:
        self.spawn_path = spawn_path

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def check_syntax(self) -> CheckResult:
        """Parse all .py files with ast.parse; fail on any SyntaxError."""
        py_files = list(self.spawn_path.rglob("*.py"))
        if not py_files:
            return CheckResult(name="syntax", passed=True, message="no Python files found")

        for py_file in py_files:
            try:
                source = py_file.read_text(encoding="utf-8")
                ast.parse(source)
            except SyntaxError as exc:
                rel = py_file.relative_to(self.spawn_path)
                return CheckResult(
                    name="syntax",
                    passed=False,
                    message=f"SyntaxError in {rel}: {exc}",
                )

        return CheckResult(name="syntax", passed=True)

    def check_config(self) -> CheckResult:
        """Verify config.yaml exists and contains a spawn_name field."""
        config_path = self.spawn_path / "config.yaml"
        if not config_path.exists():
            return CheckResult(
                name="config",
                passed=False,
                message="config.yaml not found",
            )

        try:
            data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            return CheckResult(name="config", passed=False, message=f"YAML error: {exc}")

        if "spawn_name" not in data:
            return CheckResult(
                name="config",
                passed=False,
                message="config.yaml missing 'spawn_name' field",
            )

        return CheckResult(name="config", passed=True)

    def check_requirements(self) -> CheckResult:
        """Verify requirements.txt exists and is non-empty."""
        req_path = self.spawn_path / "requirements.txt"
        if not req_path.exists():
            return CheckResult(
                name="requirements",
                passed=False,
                message="requirements.txt not found",
            )

        content = req_path.read_text(encoding="utf-8").strip()
        if not content:
            return CheckResult(
                name="requirements",
                passed=False,
                message="requirements.txt is empty",
            )

        return CheckResult(name="requirements", passed=True)

    # ------------------------------------------------------------------
    # Composite
    # ------------------------------------------------------------------

    def run_all(self) -> list[CheckResult]:
        """Run all checks and return their results."""
        return [
            self.check_syntax(),
            self.check_config(),
            self.check_requirements(),
        ]
