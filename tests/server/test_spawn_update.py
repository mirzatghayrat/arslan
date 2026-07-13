"""P2 conversational spawn editing: drafter filtering, apply-path prompt regeneration,
router action guards. The confirm card is the only apply trigger; equipment still passes
the Layer-2 choke (covered by replace_user_equipment's own tests + the honesty layer)."""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Spawn

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'u.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


@pytest_asyncio.fixture
async def seeded(maker):
    from server.registry.seeder import seed_registry
    await seed_registry()
    return maker


class _Resp:
    def __init__(self, content):
        self.content = content


async def _mk_spawn(maker, **kw) -> int:
    from server.services.spawn_service import build_system_prompt
    defaults = dict(name="小测", domain_category="content", domain_subcategory="copy",
                    persona_role="a witty copywriter", persona_tone="playful",
                    capabilities=["copywriting"])
    defaults.update(kw)
    prompt = build_system_prompt({
        "persona_role": defaults["persona_role"], "persona_tone": defaults["persona_tone"],
        "domain": f"{defaults['domain_category']}.{defaults['domain_subcategory']}"})
    async with maker() as db:
        s = Spawn(system_prompt=prompt + "\n\nSpecialization (how you differ): B2B only.",
                  **defaults)
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s.id


# ── apply path: system_prompt MUST regenerate on persona change ───────────────

async def test_apply_persona_regenerates_prompt_and_keeps_specialization(maker):
    from server.services import spawn_service
    sid = await _mk_spawn(maker)
    async with maker() as db:
        s = await spawn_service.apply_conversational_update(
            db, sid, {"persona_role": "a formal brand copywriter", "persona_tone": "formal"})
    assert s.persona_role == "a formal brand copywriter"
    assert "You are a formal brand copywriter." in s.system_prompt
    assert "Tone: formal." in s.system_prompt
    assert "witty" not in s.system_prompt                      # old persona gone from prompt
    assert "Specialization (how you differ): B2B only." in s.system_prompt  # suffix preserved


async def test_apply_capabilities_only_keeps_prompt(maker):
    from server.services import spawn_service
    sid = await _mk_spawn(maker)
    async with maker() as db:
        before = (await db.get(Spawn, sid)).system_prompt
        s = await spawn_service.apply_conversational_update(
            db, sid, {"capabilities": ["copywriting", "landing pages"]})
    assert s.capabilities == ["copywriting", "landing pages"]
    assert s.system_prompt == before                           # no persona change → untouched


async def test_apply_unknown_spawn_returns_none(maker):
    from server.services import spawn_service
    async with maker() as db:
        assert await spawn_service.apply_conversational_update(db, 9999, {}) is None


# ── drafter: menu/equipped filtering ───────────────────────────────────────────

async def test_drafter_filters_to_menu_and_equipped(seeded, monkeypatch):
    from server.orchestrator import update_drafter
    sid = await _mk_spawn(seeded)

    class _A:
        async def chat(self, system, user, **kw):
            return _Resp(
                '{"persona_role": null, "persona_tone": "正式", "capabilities": null,'
                ' "add_toolsets": ["deck", "session_search", "bogus"],'
                ' "remove_toolsets": ["charting"],'
                ' "add_skills": ["humanizer"], "remove_skills": [], "reason": "按要求"}'
            )

    monkeypatch.setattr(update_drafter, "_get_adapter", lambda: _A())
    out = await update_drafter.draft_update(sid, "改正式点,加 deck")
    assert out is not None and out["spawn_id"] == sid
    ch = out["changes"]
    assert ch["persona_tone"] == "正式"
    # deck survives (honest menu); session_search (catalog-only, unwired) + bogus dropped
    assert ch["add_toolsets"] == ["deck"]
    # remove_toolsets dropped entirely: charting is not equipped on this spawn
    assert "remove_toolsets" not in ch
    assert ch["add_skills"] == ["humanizer"]


async def test_drafter_no_valid_changes_returns_none(seeded, monkeypatch):
    from server.orchestrator import update_drafter
    sid = await _mk_spawn(seeded)

    class _A:
        async def chat(self, system, user, **kw):
            return _Resp('{"persona_role": null, "persona_tone": null, "capabilities": null,'
                         ' "add_toolsets": ["bogus"], "remove_toolsets": [],'
                         ' "add_skills": [], "remove_skills": [], "reason": "nothing"}')

    monkeypatch.setattr(update_drafter, "_get_adapter", lambda: _A())
    assert await update_drafter.draft_update(sid, "随便") is None


# ── router: suggest_update guards mirror route ────────────────────────────────

async def test_router_accepts_suggest_update_with_real_spawn(maker, monkeypatch):
    from server.orchestrator import router
    sid = await _mk_spawn(maker)

    class _A:
        async def chat(self, system, user, **kw):
            return _Resp(f'{{"action": "suggest_update", "spawn_id": {sid},'
                         f' "task_brief": "语气改正式", "reason": "edit"}}')

    monkeypatch.setattr(router, "_get_adapter", lambda: _A())
    r = await router.route("conv-u", "把小测语气改正式")
    assert r.action == "suggest_update" and r.spawn_id == sid


async def test_router_downgrades_suggest_update_without_spawn(maker, monkeypatch):
    from server.orchestrator import router
    await _mk_spawn(maker)

    class _A:
        async def chat(self, system, user, **kw):
            return _Resp('{"action": "suggest_update", "spawn_id": 4242,'
                         ' "task_brief": "x", "reason": "hallucinated"}')

    monkeypatch.setattr(router, "_get_adapter", lambda: _A())
    r = await router.route("conv-u2", "改一下")
    assert r.action == "answer"
