"""Tests for the Arslan CLI entry point (arslan/cli.py)."""
from __future__ import annotations

import pytest
from click.testing import CliRunner

from arslan.cli import main


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# main --help / --version
# ---------------------------------------------------------------------------


def test_main_help(runner: CliRunner) -> None:
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0, result.output
    assert "Arslan" in result.output


def test_main_version(runner: CliRunner) -> None:
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0, result.output
    assert "0.1.0" in result.output


# ---------------------------------------------------------------------------
# list command
# ---------------------------------------------------------------------------


def test_list_empty(runner: CliRunner, tmp_path) -> None:
    """list with an empty spawns dir shows an 'empty' indicator."""
    result = runner.invoke(main, ["list", "--spawns-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    # Must mention something about no spawns existing
    lowered = result.output.lower()
    assert any(
        token in lowered for token in ("没有", "no spawn", "empty", "尚未", "yet", "0")
    ), f"Expected empty indicator in output, got:\n{result.output}"


def test_list_shows_spawn(runner: CliRunner, tmp_path) -> None:
    """list shows a spawn that has a valid .arslan-meta.yaml."""
    import yaml

    spawn_dir = tmp_path / "my-agent"
    spawn_dir.mkdir()
    meta = {
        "name": "my-agent",
        "domain": "content-creator",
        "template_used": "",
        "generation_level": 1,
    }
    (spawn_dir / ".arslan-meta.yaml").write_text(
        yaml.dump(meta, allow_unicode=True), encoding="utf-8"
    )

    result = runner.invoke(main, ["list", "--spawns-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "my-agent" in result.output


# ---------------------------------------------------------------------------
# new command
# ---------------------------------------------------------------------------


def test_new_help(runner: CliRunner) -> None:
    result = runner.invoke(main, ["new", "--help"])
    assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# run command
# ---------------------------------------------------------------------------


def test_run_help(runner: CliRunner) -> None:
    result = runner.invoke(main, ["run", "--help"])
    assert result.exit_code == 0, result.output


def test_run_missing_spawn(runner: CliRunner, tmp_path) -> None:
    """run with a non-existent spawn name should exit non-zero."""
    result = runner.invoke(
        main, ["run", "nonexistent-spawn", "--spawns-dir", str(tmp_path)]
    )
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# evolve command
# ---------------------------------------------------------------------------


def test_evolve_help(runner: CliRunner) -> None:
    result = runner.invoke(main, ["evolve", "--help"])
    assert result.exit_code == 0, result.output


def test_evolve_missing_spawn(runner: CliRunner, tmp_path) -> None:
    """evolve with a non-existent spawn name should exit non-zero."""
    result = runner.invoke(
        main, ["evolve", "nonexistent-spawn", "--spawns-dir", str(tmp_path)]
    )
    assert result.exit_code != 0
