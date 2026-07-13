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
    async def fcs(meta, readme): return {"is_mcp": True, "transport": "stdio", "command": "npx",
        "args": [], "url": None, "reason": "x"}
    monkeypatch.setattr(github_eval, "fetch_repo", fr)
    monkeypatch.setattr(github_eval, "fetch_readme", frd)
    monkeypatch.setattr(mcp_suggest, "classify_and_suggest", fcs)
    out = await ds.evaluate_ref("o", "r")
    assert out["repo"]["stars"] == 1500 and out["trust"]["tier"] == "high"
    assert out["suggestion"]["is_mcp"] is True
