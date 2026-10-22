"""Tests for SkillPack — the SKILL.md format contract (arslan.skills.skillpack). The skill-pack
directory validator went with arslan/spawn in C7 (v0.1.63)."""

import pytest

from arslan.skills.skillpack import CredentialSpec, SkillPack


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

