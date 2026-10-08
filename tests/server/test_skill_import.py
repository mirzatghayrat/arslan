"""P3 faithful SKILL.md importer: frontmatter parsing, the license red line (server-side),
verbatim import with attribution, bundled-script storage + sandbox execution + traversal guard."""
import sys

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, SkillPack
from server.services import skill_import
from server.services.skill_import import parse_skill_md

pytestmark = pytest.mark.asyncio

VALID_MD = """---
name: handoff
description: Hand work to a teammate cleanly.
---

# Handoff

1. State the goal. 2. State what's done. 3. State what's next.
"""


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'i.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    # scripts land under the test data dir, never the repo's
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    return m


def _mock_github(monkeypatch, *, license="MIT", tree=None, raws=None):
    async def _fetch_repo(owner, repo):
        return {"full_name": f"{owner}/{repo}", "html_url": f"https://github.com/{owner}/{repo}",
                "stars": 10, "forks": 1, "license": license, "pushed_days": 1,
                "description": "", "topics": []}

    async def _tree_paths(owner, repo):
        return tree or []

    async def _fetch_raw(owner, repo, path):
        return (raws or {})[path]

    monkeypatch.setattr(skill_import.github_eval, "fetch_repo", _fetch_repo)
    monkeypatch.setattr(skill_import, "_tree_paths", _tree_paths)
    monkeypatch.setattr(skill_import, "_fetch_raw", _fetch_raw)


# ── parsing ────────────────────────────────────────────────────────────────────

def test_parse_skill_md_valid():
    info = parse_skill_md(VALID_MD)
    assert info["key"] == "handoff" and info["name"] == "handoff"
    assert info["description"].startswith("Hand work")
    assert info["body"].startswith("# Handoff")           # frontmatter stripped, body verbatim


def test_parse_skill_md_rejects_missing_frontmatter():
    assert parse_skill_md("# just markdown") is None
    assert parse_skill_md("---\nname: x\n---\n\n") is None            # empty body
    assert parse_skill_md("---\ndescription: no name\n---\nbody") is None


# ── the license red line (server-side, both scan and import) ──────────────────

async def test_scan_blocks_unlicensed_repo(maker, monkeypatch):
    _mock_github(monkeypatch, license=None, tree=["skills/handoff/SKILL.md"],
                 raws={"skills/handoff/SKILL.md": VALID_MD})
    out = await skill_import.scan_skills("x/y")
    assert out["license_ok"] is False
    assert out["skills"][0]["importable"] is False
    assert "license" in out["skills"][0]["reason"]


async def test_import_blocks_copyleft(maker, monkeypatch):
    _mock_github(monkeypatch, license="GPL-3.0", tree=["SKILL.md"], raws={"SKILL.md": VALID_MD})
    with pytest.raises(ValueError, match="allowlist"):
        await skill_import.import_skill("x/y", "SKILL.md")


# ── faithful import ────────────────────────────────────────────────────────────

async def test_import_verbatim_with_attribution(maker, monkeypatch):
    _mock_github(monkeypatch, license="MIT", tree=["skills/handoff/SKILL.md"],
                 raws={"skills/handoff/SKILL.md": VALID_MD})
    out = await skill_import.import_skill("mattpocock/skills", "skills/handoff/SKILL.md")
    assert out["key"] == "handoff" and out["license"] == "MIT"
    async with maker() as db:
        row = await db.get(SkillPack, "handoff")
    assert row.tier == "safe" and row.status == "registered" and row.category == "imported"
    assert "Imported verbatim from https://github.com/mattpocock/skills (MIT)" in row.body
    assert "1. State the goal." in row.body               # body content preserved verbatim
    # P0 honesty gate: imported skill has a real body → assignable
    from server.registry.service import skill_is_assignable
    assert skill_is_assignable(row.tier, row.status, row.body)


async def test_import_refuses_existing_key(maker, monkeypatch):
    _mock_github(monkeypatch, license="MIT", tree=["SKILL.md"], raws={"SKILL.md": VALID_MD})
    await skill_import.import_skill("x/y", "SKILL.md")
    with pytest.raises(ValueError, match="already exists"):
        await skill_import.import_skill("x/y", "SKILL.md")


# ── bundled scripts: storage + sandbox execution + traversal guard ─────────────

async def test_import_stores_scripts_and_notes_them(maker, monkeypatch, tmp_path):
    md = VALID_MD
    tree = ["skills/handoff/SKILL.md", "skills/handoff/scripts/helper.py",
            "skills/handoff/scripts/main_calc.py", "skills/handoff/scripts/evil.sh"]
    raws = {"skills/handoff/SKILL.md": md,
            "skills/handoff/scripts/helper.py": "VALUE = 21\n",
            "skills/handoff/scripts/main_calc.py": "from helper import VALUE\nprint(VALUE * 2)\n"}
    _mock_github(monkeypatch, license="MIT", tree=tree, raws=raws)
    out = await skill_import.import_skill("x/y", "skills/handoff/SKILL.md")
    assert sorted(out["scripts"]) == ["helper.py", "main_calc.py"]     # .sh ignored (.py only)
    assert (tmp_path / "skill_scripts" / "handoff" / "main_calc.py").exists()
    async with maker() as db:
        row = await db.get(SkillPack, "handoff")
    assert "## Bundled scripts" in row.body and "handoff/main_calc.py" in row.body


@pytest.mark.skipif(
    sys.platform != "darwin",
    reason="executes the skill script in a REAL sandbox (macOS seatbelt); Linux run_python "
    "is fail-closed (refusal path covered in test_code_sandbox.py)",
)
# @pytest.mark.macos is a SELECTION marker added alongside the per-test skipif
# above — never instead of it. The skipif is why this passes off macOS; the
# marker is how a macOS CI job finds it. Measured 2026-08-06: part of a 25-test
# set that skips on Linux and had never executed on any CI runner.
@pytest.mark.macos
async def test_skill_script_runs_with_siblings(maker, monkeypatch, tmp_path):
    # store a two-file script set, then run the entry via the executor's skill_script path
    from server.registry.executors import RunPythonExecutor
    from server.services import code_sandbox
    monkeypatch.setattr(code_sandbox, "_env_cache", (sys.executable, "test-env"))
    d = tmp_path / "skill_scripts" / "handoff"
    d.mkdir(parents=True)
    (d / "helper.py").write_text("VALUE = 21\n")
    (d / "main_calc.py").write_text("from helper import VALUE\nprint(VALUE * 2)\n")
    out = await RunPythonExecutor().execute({"skill_script": "handoff/main_calc.py"})
    assert out["ok"] is True and "42" in out["stdout"]     # sibling import worked in the sandbox


async def test_skill_script_traversal_rejected(maker, tmp_path):
    from server.registry.executors import RunPythonExecutor
    for ref in ("../secrets.py", "handoff/../../x.py", "handoff/", "absolute//etc.py"):
        out = await RunPythonExecutor().execute({"skill_script": ref})
        assert out["ok"] is False, ref


# ── 0.1.55: the license is read per skill, from the skill's own license file ───

APACHE = "                                 Apache License\n                           Version 2.0, January 2004\n"
ANTHROPIC_TERMS = ("© 2025 Anthropic, PBC. All rights reserved.\n\nLICENSE: Use of these materials ... is governed "
                   "by your agreement with Anthropic")


def _anthropic_like(monkeypatch):
    """The shape of github.com/anthropics/skills, checked 2026-10-08: no repo license,
    a LICENSE.txt in every skill folder — Apache-2.0 for most, Anthropic's own terms
    for the document skills (docx/pdf/pptx/xlsx)."""
    _mock_github(monkeypatch, license=None,
                 tree=["skills/theme-factory/SKILL.md", "skills/theme-factory/LICENSE.txt",
                       "skills/docx/SKILL.md", "skills/docx/LICENSE.txt"],
                 raws={"skills/theme-factory/SKILL.md": VALID_MD.replace("handoff", "theme-factory"),
                       "skills/theme-factory/LICENSE.txt": APACHE,
                       "skills/docx/SKILL.md": VALID_MD.replace("handoff", "docx"),
                       "skills/docx/LICENSE.txt": ANTHROPIC_TERMS})


async def test_a_skill_with_its_own_permissive_license_imports_from_an_unlicensed_repo(maker, monkeypatch):
    _anthropic_like(monkeypatch)
    out = await skill_import.scan_skills("anthropics/skills")
    by_key = {s["key"]: s for s in out["skills"]}
    assert by_key["theme-factory"]["importable"] is True
    assert by_key["theme-factory"]["license"] == "Apache-2.0"
    assert by_key["docx"]["importable"] is False and "not a permissive license" in by_key["docx"]["reason"]
    done = await skill_import.import_skill("anthropics/skills", "skills/theme-factory/SKILL.md")
    assert done["license"] == "Apache-2.0"
    async with maker() as db:
        row = await db.get(SkillPack, "theme-factory")
    assert "(Apache-2.0, skills/theme-factory/LICENSE.txt)" in row.body


async def test_a_proprietary_skill_is_refused_on_import_too(maker, monkeypatch):
    _anthropic_like(monkeypatch)
    with pytest.raises(ValueError, match="not a permissive license"):
        await skill_import.import_skill("anthropics/skills", "skills/docx/SKILL.md")


async def test_the_skills_own_license_wins_over_a_permissive_repo(maker, monkeypatch):
    _mock_github(monkeypatch, license="MIT", tree=["skills/x/SKILL.md", "skills/x/LICENSE"],
                 raws={"skills/x/SKILL.md": VALID_MD, "skills/x/LICENSE": ANTHROPIC_TERMS})
    with pytest.raises(ValueError, match="not a permissive license"):
        await skill_import.import_skill("x/y", "skills/x/SKILL.md")


def test_license_text_detection():
    from server.services.skill_import import detect_license
    assert detect_license(APACHE) == "Apache-2.0"
    assert detect_license("Permission is hereby granted, free of charge, to any person") == "MIT"
    assert detect_license(ANTHROPIC_TERMS) is None
    assert detect_license("GNU GENERAL PUBLIC LICENSE Version 3") is None
