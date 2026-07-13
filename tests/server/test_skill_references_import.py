"""PC-2: import bundled references/ alongside scripts and surface them.

Mirrors the scripts path: text refs (.md/.txt) under a skill's references/ dir are fetched,
capped (per-file size + per-skill count), stored to data_dir/skill_scripts/<key>/references/,
listed in a "## Bundled references" body section, and reported. Optional read side:
read_skill(section="references/<file>") fetches one reference, caged + traversal-guarded.
"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, SkillPack
from server.services import skill_import

pytestmark = pytest.mark.asyncio

VALID_MD = """---
name: handoff
description: Hand work to a teammate cleanly.
---

# Handoff

Body that references references/guide.md for detail.
"""


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'i.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
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


# ── storage + surfacing + per-file size cap ────────────────────────────────────

async def test_import_stores_references_and_notes_them(maker, monkeypatch, tmp_path):
    over = "x" * (skill_import._MAX_REFERENCE_BYTES + 1)
    tree = ["skills/handoff/SKILL.md",
            "skills/handoff/references/guide.md",
            "skills/handoff/references/notes.txt",
            "skills/handoff/references/big.md",      # over per-file cap → dropped
            "skills/handoff/references/evil.py"]     # not text (.md/.txt) → ignored
    raws = {"skills/handoff/SKILL.md": VALID_MD,
            "skills/handoff/references/guide.md": "# Guide\nhello world\n",
            "skills/handoff/references/notes.txt": "note body\n",
            "skills/handoff/references/big.md": over,
            "skills/handoff/references/evil.py": "import os\n"}
    _mock_github(monkeypatch, license="MIT", tree=tree, raws=raws)

    out = await skill_import.import_skill("x/y", "skills/handoff/SKILL.md")

    # .py ignored, big.md trimmed by the per-file size cap
    assert sorted(out["references"]) == ["guide.md", "notes.txt"]
    ref_dir = tmp_path / "skill_scripts" / "handoff" / "references"
    assert (ref_dir / "guide.md").exists()
    assert (ref_dir / "notes.txt").exists()
    assert not (ref_dir / "big.md").exists()
    assert not (ref_dir / "evil.py").exists()

    async with maker() as db:
        row = await db.get(SkillPack, "handoff")
    assert "## Bundled references" in row.body
    assert "references/guide.md" in row.body and "references/notes.txt" in row.body


# ── per-skill count cap (mirrors _MAX_SCRIPTS) ─────────────────────────────────

async def test_import_reference_count_cap(maker, monkeypatch, tmp_path):
    n = skill_import._MAX_REFERENCES + 3
    tree = ["skills/handoff/SKILL.md"] + \
        [f"skills/handoff/references/r{i:02d}.md" for i in range(n)]
    raws = {"skills/handoff/SKILL.md": VALID_MD}
    for i in range(n):
        raws[f"skills/handoff/references/r{i:02d}.md"] = f"ref {i}\n"
    _mock_github(monkeypatch, license="MIT", tree=tree, raws=raws)

    out = await skill_import.import_skill("x/y", "skills/handoff/SKILL.md")

    assert len(out["references"]) == skill_import._MAX_REFERENCES
    ref_dir = tmp_path / "skill_scripts" / "handoff" / "references"
    assert len(list(ref_dir.glob("*.md"))) == skill_import._MAX_REFERENCES


# ── no references → no section, empty report list ──────────────────────────────

async def test_import_without_references(maker, monkeypatch):
    _mock_github(monkeypatch, license="MIT", tree=["SKILL.md"], raws={"SKILL.md": VALID_MD})
    out = await skill_import.import_skill("x/y", "SKILL.md")
    assert out["references"] == []
    async with maker() as db:
        row = await db.get(SkillPack, "handoff")
    assert "## Bundled references" not in row.body


# ── read side (optional): read_skill fetches a reference, caged + traversal-safe ─

async def test_read_skill_fetches_reference(maker, monkeypatch, tmp_path):
    tree = ["skills/handoff/SKILL.md", "skills/handoff/references/guide.md"]
    raws = {"skills/handoff/SKILL.md": VALID_MD,
            "skills/handoff/references/guide.md": "# Guide\nhello world\n"}
    _mock_github(monkeypatch, license="MIT", tree=tree, raws=raws)
    await skill_import.import_skill("x/y", "skills/handoff/SKILL.md")

    from server.registry.executors import ReadSkillExecutor
    out = await ReadSkillExecutor().execute({"key": "handoff", "section": "references/guide.md"})
    assert out["ok"] is True and "hello world" in out["body"]

    bad = await ReadSkillExecutor().execute(
        {"key": "handoff", "section": "references/../../etc/passwd"})
    assert bad["ok"] is False
