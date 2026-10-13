import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, DiscoveryCandidate


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'ds.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


def _snap(full="o/r"):
    return {"repo": {"full_name": full, "html_url": "u", "stars": 9}, "trust": {"tier": "low"},
            "suggestion": {"is_mcp": False}}


async def test_save_upserts_by_full_name(maker):
    from server.services import discovery_service as ds
    await ds.save_candidate(_snap("o/r"))
    await ds.save_candidate({**_snap("o/r"), "trust": {"tier": "high"}})   # same repo → update
    async with maker() as s:
        rows = (await s.execute(select(DiscoveryCandidate))).scalars().all()
    assert len(rows) == 1 and rows[0].snapshot["trust"]["tier"] == "high"


async def test_save_requires_full_name(maker):
    from server.services import discovery_service as ds
    with pytest.raises(ValueError):
        await ds.save_candidate({"repo": {}})


async def test_list_and_delete(maker):
    from server.services import discovery_service as ds
    await ds.save_candidate(_snap("o/a"))
    r = await ds.save_candidate(_snap("o/b"))
    listed = await ds.list_candidates()
    await ds.delete_candidate(r["id"])
    after = await ds.list_candidates()
    assert {c["full_name"] for c in listed} == {"o/a", "o/b"}
    assert {c["full_name"] for c in after} == {"o/a"}


async def test_refresh_re_evaluates(maker, monkeypatch):
    from server.services import discovery_service as ds
    async def fake_eval(owner, repo):
        return {"repo": {"full_name": f"{owner}/{repo}", "html_url": "u2", "stars": 999},
                "trust": {"tier": "high"}, "suggestion": {"is_mcp": True}}
    monkeypatch.setattr(ds, "evaluate_ref", fake_eval)
    c = await ds.save_candidate(_snap("o/r"))
    r = await ds.refresh_candidate(c["id"])
    assert r["snapshot"]["trust"]["tier"] == "high" and r["snapshot"]["suggestion"]["is_mcp"] is True


async def test_evaluate_ref_composes(monkeypatch):
    from server.services import discovery_service as ds, github_eval, mcp_suggest
    async def fr(o, r): return {"full_name": "o/r", "html_url": "u", "stars": 1500, "forks": 1,
        "license": "MIT", "pushed_days": 10, "description": "d", "topics": []}
    async def frd(o, r): return "readme"
    async def nofile(o, r, p): return ""         # no arslan.plugin.json: fetch_file would otherwise call GitHub
    async def fcs(meta, readme): return {"is_mcp": True, "transport": "stdio", "command": "npx",
        "args": [], "url": None, "reason": "x"}
    monkeypatch.setattr(github_eval, "fetch_repo", fr)
    monkeypatch.setattr(github_eval, "fetch_readme", frd)
    monkeypatch.setattr(github_eval, "fetch_file", nofile)
    monkeypatch.setattr(mcp_suggest, "classify_and_suggest", fcs)
    out = await ds.evaluate_ref("o", "r")
    assert out["repo"]["stars"] == 1500 and out["trust"]["tier"] == "high"
    assert out["suggestion"]["is_mcp"] is True


# ── a renamed repository: fetch_repo follows the 301, the README and the manifest reads do not ────────────

def _renamed(monkeypatch, full_name="new-owner/new-name"):
    """GitHub answers the old name with the repository under its new one; `asked` is every README / file read."""
    from server.services import github_eval, mcp_suggest, repo_overview, skill_suggest
    asked = []

    async def fr(o, r):
        return {"full_name": full_name, "html_url": "u", "stars": 1, "forks": 0, "license": "MIT", "pushed_days": 1,
                "description": "", "topics": []}

    async def readme(o, r):
        asked.append(("readme", o, r))
        return "readme"

    async def a_file(o, r, path):
        asked.append(("file", o, r))
        return ""

    async def suggest(meta, text):
        return {"is_mcp": False}

    async def explain(meta, text):
        return {"what": "x", "use_cases": []}

    async def draft(meta, text):
        return {"name": "n", "description": "d", "body": "b"}
    monkeypatch.setattr(github_eval, "fetch_repo", fr)
    monkeypatch.setattr(github_eval, "fetch_readme", readme)
    monkeypatch.setattr(github_eval, "fetch_file", a_file)
    monkeypatch.setattr(mcp_suggest, "classify_and_suggest", suggest)
    monkeypatch.setattr(repo_overview, "explain", explain)
    monkeypatch.setattr(skill_suggest, "generate_skill", draft)
    return asked


async def test_after_a_rename_the_readme_and_the_manifest_are_read_under_the_new_name(monkeypatch):
    """fetch_readme and fetch_file read a redirect as "nothing there": asked under the old name, a renamed
    repository's evaluation would silently lose its README and its arslan.plugin.json."""
    from server.services import discovery_service as ds
    asked = _renamed(monkeypatch)
    await ds.evaluate_ref("old-owner", "old-name")
    assert asked == [("readme", "new-owner", "new-name"), ("file", "new-owner", "new-name")]


async def test_after_a_rename_the_skill_draft_reads_the_readme_under_the_new_name(monkeypatch):
    from server.services import discovery_service as ds
    asked = _renamed(monkeypatch)
    out = await ds.generate_skill_draft("old-owner", "old-name")
    assert asked == [("readme", "new-owner", "new-name")] and out["repo"]["full_name"] == "new-owner/new-name"


@pytest.mark.parametrize("full_name", ["", "no-slash", "a/b/c", "../x", "o/..", "o/r r", "o/r?x=1", "/r", "o/"])
async def test_a_full_name_that_is_not_an_owner_and_a_name_leaves_the_name_that_was_asked_for(monkeypatch, full_name):
    from server.services import discovery_service as ds
    asked = _renamed(monkeypatch, full_name=full_name)
    await ds.evaluate_ref("o", "r")
    assert asked == [("readme", "o", "r"), ("file", "o", "r")]
