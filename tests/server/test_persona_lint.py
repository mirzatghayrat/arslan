"""HX-6 / spec P2: persona-vs-equipment delivery lint.

The Deck-Master class of bug: a persona promising a delivery FORMAT (PPT/PDF/image...)
the product cannot actually ship. lint_delivery_claims is a deterministic, advisory-only
check run at spawn create / suggest_update time — warnings attach to the response frame,
nothing is ever hard-rejected.
"""
import anyio
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base
from server.services.persona_lint import lint_delivery_claims

# ── unit: format detectors vs tool keys ───────────────────────────────────────


def test_ppt_without_render_deck_warns():
    warnings = lint_delivery_claims("You deliver polished PowerPoint decks.", set())
    assert len(warnings) == 1
    assert "render_deck" in warnings[0]


def test_ppt_with_render_deck_clean():
    assert lint_delivery_claims(
        "You deliver polished PowerPoint decks.", {"render_deck"}) == []


def test_cjk_slides_keyword_fires():
    warnings = lint_delivery_claims("你负责制作精美的幻灯片。", set())
    assert len(warnings) == 1 and "render_deck" in warnings[0]


def test_pptx_token_fires_without_ppt_word_boundary_confusion():
    warnings = lint_delivery_claims("Native editable .pptx export.", set())
    assert len(warnings) == 1 and "render_deck" in warnings[0]


def test_pdf_always_warns_even_with_every_tool():
    warnings = lint_delivery_claims(
        "You produce PDF reports.", {"render_deck", "render_chart", "web_search"})
    assert len(warnings) == 1
    assert "PDF" in warnings[0]


def test_print_to_pdf_from_html_is_exempt():
    # "users can print-to-PDF from the HTML" is not a persona delivery promise.
    assert lint_delivery_claims(
        "Ships single-file HTML (users can print-to-PDF).", set()) == []


def test_html_report_persona_clean_channel_exists():
    # HX-2 gave every spawn a system-level HTML artifact channel — never warn on HTML.
    assert lint_delivery_claims(
        "Ships a designed single-file HTML presentation by default; "
        "完整单文件 HTML 报告输出后由系统打包。", set()) == []


def test_html_qualified_slides_do_not_trip_ppt_detector():
    # "HTML slides" / "HTML 幻灯片" are deliverable via the HTML channel.
    assert lint_delivery_claims("You build beautiful HTML slides.", set()) == []
    assert lint_delivery_claims("交付 HTML 幻灯片。", set()) == []


def test_chart_without_render_chart_warns():
    warnings = lint_delivery_claims("你会画数据图表。", set())
    assert len(warnings) == 1 and "render_chart" in warnings[0]


def test_chart_with_render_chart_clean():
    assert lint_delivery_claims("You render charts on demand.", {"render_chart"}) == []


def test_image_and_poster_always_warn():
    warnings = lint_delivery_claims("你会生成海报和图片。", {"render_chart", "render_deck"})
    assert len(warnings) == 1
    assert "图片" in warnings[0] or "海报" in warnings[0]


def test_chart_illustration_counts_as_image_not_chart():
    # 图表配图 = illustration imagery → image warning; must NOT double-fire the
    # chart detector on the embedded 图表.
    warnings = lint_delivery_claims("为文章生成图表配图。", {"render_chart"})
    assert len(warnings) == 1
    assert "render_chart" not in warnings[0]


def test_excel_warns():
    warnings = lint_delivery_claims("You export Excel workbooks.", set())
    assert len(warnings) == 1
    assert "Excel" in warnings[0]


def test_plain_persona_clean():
    assert lint_delivery_claims("You are a witty copywriter. Tone: playful.", set()) == []


def test_empty_prompt_clean():
    assert lint_delivery_claims("", set()) == []


def test_multiple_claims_accumulate():
    warnings = lint_delivery_claims("交付 PPT、PDF 和海报。", set())
    assert len(warnings) == 3


# ── flow: WS confirm_create attaches capability_warnings ─────────────────────


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_SPAWNS_DIR", str(tmp_path / "spawns"))
    import importlib

    import server.config as config

    importlib.reload(config)

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'plint.db'}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    anyio.run(_setup)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)

    from server.main import create_app

    return TestClient(create_app())


def _drain_roster_after_created(ws) -> None:
    f = ws.receive_json()
    if f.get("type") == "roster_event":
        f = ws.receive_json()
    assert f.get("type") == "roster_update"


def test_confirm_create_ppt_persona_without_deck_carries_warnings(app_client):
    draft = {
        "name": "slide-smith",
        "domain": "content-creator.presentations",
        "capabilities": ["presentations"],
        "persona_role": "a designer who delivers polished PowerPoint decks",
        "persona_tone": "crisp",
        # explicitly-empty equipment: the drafter curated and chose nothing
        "tools": [], "skills": [], "mcps": [],
    }
    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update
        ws.send_json({"type": "confirm_create", "draft": draft})
        created = ws.receive_json()
        assert created["type"] == "spawn_created"
        warnings = created.get("capability_warnings")
        assert warnings, "spawn_created must carry capability_warnings for a PPT persona with no render_deck"
        assert any("render_deck" in w for w in warnings)
        _drain_roster_after_created(ws)


def test_confirm_create_plain_persona_has_no_warnings(app_client):
    draft = {
        "name": "translator",
        "domain": "personal-assistant.translator",
        "capabilities": ["qa-interaction"],
        "persona_role": "translator",
        "persona_tone": "precise",
        "tools": [], "skills": [], "mcps": [],
    }
    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update
        ws.send_json({"type": "confirm_create", "draft": draft})
        created = ws.receive_json()
        assert created["type"] == "spawn_created"
        assert created.get("capability_warnings") == []
        _drain_roster_after_created(ws)


# ── flow: suggest_update proposal carries capability_warnings ─────────────────


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'plint_u.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    anyio.run(_setup)
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


async def _mk_spawn(maker) -> int:
    from server.db.models import Spawn
    async with maker() as db:
        s = Spawn(name="小测", domain_category="content", persona_role="a witty copywriter",
                  persona_tone="playful", capabilities=["copywriting"],
                  system_prompt="You are a witty copywriter.")
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s.id


async def test_draft_update_ppt_persona_without_deck_warns(seeded, monkeypatch):
    from server.orchestrator import update_drafter
    from server.ws import protocol
    sid = await _mk_spawn(seeded)

    class _A:
        async def chat(self, system, user, **kw):
            return _Resp('{"persona_role": "a PowerPoint deck specialist", "persona_tone": null,'
                         ' "capabilities": null, "add_toolsets": [], "remove_toolsets": [],'
                         ' "add_skills": [], "remove_skills": [], "reason": "按要求"}')

    monkeypatch.setattr(update_drafter, "_get_adapter", lambda: _A())
    out = await update_drafter.draft_update(sid, "改成专做 PPT")
    assert out is not None
    warnings = out.get("capability_warnings")
    assert warnings and any("render_deck" in w for w in warnings)
    # the proposal payload must round-trip into the suggest_update frame for the confirm card
    frame = protocol.suggest_update(**out)
    assert frame["capability_warnings"] == warnings


async def test_draft_update_adding_deck_toolset_clears_ppt_warning(seeded, monkeypatch):
    from server.orchestrator import update_drafter
    sid = await _mk_spawn(seeded)

    class _A:
        async def chat(self, system, user, **kw):
            return _Resp('{"persona_role": "a PowerPoint deck specialist", "persona_tone": null,'
                         ' "capabilities": null, "add_toolsets": ["deck"], "remove_toolsets": [],'
                         ' "add_skills": [], "remove_skills": [], "reason": "按要求"}')

    monkeypatch.setattr(update_drafter, "_get_adapter", lambda: _A())
    out = await update_drafter.draft_update(sid, "改成专做 PPT,配上 deck 工具")
    assert out is not None
    assert out.get("capability_warnings") == []
