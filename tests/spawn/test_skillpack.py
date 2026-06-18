"""Tests for SkillPack — skill-pack format contract + validation (P0)."""
from pathlib import Path

import pytest

from arslan.spawn.skillpack import CredentialSpec, SkillPack


VALID_SKILL_MD = """\
---
name: github-eval
description: 评估某 GitHub 仓库并匹配到用户需求 —— 它做什么、值不值得挂载/借鉴。
version: 0.1.0
authors:
  - Arslan
credentials:
  - name: GITHUB_TOKEN
    required: false
    description: 提升 API 速率上限；匿名可用（低速率）。
    storage: ".env / 环境变量 / --token"
---

## Trigger

当需要评估某个 GitHub 仓库是否值得挂载或借鉴时激活。

## 决策规则

- 先看 stars / 活跃度 / license
"""


# --- frontmatter parsing -------------------------------------------------


def test_from_skill_md_parses_frontmatter_fields():
    pack = SkillPack.from_skill_md(VALID_SKILL_MD)
    assert pack.name == "github-eval"
    assert pack.version == "0.1.0"
    assert pack.authors == ["Arslan"]
    assert "GitHub" in pack.description


def test_from_skill_md_parses_credentials():
    pack = SkillPack.from_skill_md(VALID_SKILL_MD)
    assert len(pack.credentials) == 1
    cred = pack.credentials[0]
    assert isinstance(cred, CredentialSpec)
    assert cred.name == "GITHUB_TOKEN"
    assert cred.required is False


def test_from_skill_md_keeps_body_separate_from_frontmatter():
    pack = SkillPack.from_skill_md(VALID_SKILL_MD)
    assert "## Trigger" in pack.body
    assert "name: github-eval" not in pack.body


# --- section detection ---------------------------------------------------


def test_has_section_detects_present_and_absent():
    pack = SkillPack.from_skill_md(VALID_SKILL_MD)
    assert pack.has_section("Trigger") is True
    assert pack.has_section("决策规则") is True
    assert pack.has_section("Nonexistent") is False


# --- malformed input -----------------------------------------------------


def test_from_skill_md_rejects_missing_frontmatter():
    with pytest.raises(ValueError):
        SkillPack.from_skill_md("# just a body, no frontmatter")


# --- validator (validate_skillpack) --------------------------------------

VALID_CLI = """\
import sys
if len(sys.argv) > 1 and sys.argv[1] == "doc":
    print("usage: github_eval_cli.py <search|extract|doc>")
    sys.exit(0)
sys.exit(1)
"""


def _write_valid_pack(root: Path, skill_md: str = VALID_SKILL_MD) -> Path:
    pack = root / "github-eval"
    (pack / "scripts").mkdir(parents=True)
    (pack / "SKILL.md").write_text(skill_md, encoding="utf-8")
    (pack / "scripts" / "github_eval_cli.py").write_text(VALID_CLI, encoding="utf-8")
    (pack / "credentials.yaml").write_text(
        "- name: GITHUB_TOKEN\n  required: false\n", encoding="utf-8"
    )
    return pack


def _failed(results, name):
    return [r for r in results if r.name == name and not r.passed]


def test_validate_valid_pack_all_pass(tmp_path):
    from arslan.spawn.skillpack import validate_skillpack

    pack = _write_valid_pack(tmp_path)
    results = validate_skillpack(pack)
    for r in results:
        assert r.passed is True, f"Check '{r.name}' failed: {r.message}"


def test_validate_returns_list_of_check_results(tmp_path):
    from arslan.spawn.quality import CheckResult
    from arslan.spawn.skillpack import validate_skillpack

    pack = _write_valid_pack(tmp_path)
    results = validate_skillpack(pack)
    assert isinstance(results, list)
    assert all(isinstance(r, CheckResult) for r in results)


def test_validate_missing_skill_md_fails(tmp_path):
    from arslan.spawn.skillpack import validate_skillpack

    pack = tmp_path / "empty"
    pack.mkdir()
    results = validate_skillpack(pack)
    assert _failed(results, "skill_md")


def test_validate_missing_trigger_section_fails(tmp_path):
    from arslan.spawn.skillpack import validate_skillpack

    no_trigger = VALID_SKILL_MD.replace("## Trigger", "## Intro")
    pack = _write_valid_pack(tmp_path, skill_md=no_trigger)
    results = validate_skillpack(pack)
    assert _failed(results, "sections")


def test_validate_missing_required_frontmatter_field_fails(tmp_path):
    from arslan.spawn.skillpack import validate_skillpack

    no_version = "\n".join(
        ln for ln in VALID_SKILL_MD.splitlines() if not ln.startswith("version:")
    )
    pack = _write_valid_pack(tmp_path, skill_md=no_version)
    results = validate_skillpack(pack)
    assert _failed(results, "frontmatter")


def test_validate_missing_cli_script_fails(tmp_path):
    from arslan.spawn.skillpack import validate_skillpack

    pack = _write_valid_pack(tmp_path)
    (pack / "scripts" / "github_eval_cli.py").unlink()
    results = validate_skillpack(pack)
    assert _failed(results, "cli_present")


def test_validate_cli_doc_nonzero_exit_fails(tmp_path):
    from arslan.spawn.skillpack import validate_skillpack

    pack = _write_valid_pack(tmp_path)
    # CLI that exits non-zero even for `doc`
    (pack / "scripts" / "github_eval_cli.py").write_text(
        "import sys\nsys.exit(2)\n", encoding="utf-8"
    )
    results = validate_skillpack(pack)
    assert _failed(results, "cli_doc")
