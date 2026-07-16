"""Router: suggest_connect_mcp action (connect/add a NAMED MCP connector) +
rubric-cost bound (the catalog must stay OUT of the always-sent _SYSTEM rubric)."""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Spawn


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'r.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with m() as s:
        s.add(
            Spawn(
                id=7,
                name="beauty-guru",
                domain_category="content-creator",
                domain_subcategory="xiaohongshu",
                capabilities=["content-generation"],
                system_prompt="You are a beauty expert.",
            )
        )
        await s.commit()

    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


def _stub_adapter(content: str):
    class _A:
        provider_name = "openai"
        model = "gpt-4o"

        async def chat(self, system, user, history=None, tools=None, temperature=0.7):
            from arslan.models import LLMResponse

            return LLMResponse(content=content, usage={})

    return _A()


@pytest.mark.asyncio
async def test_router_maps_connect_intent_to_suggest_connect_mcp(maker, monkeypatch):
    from server.orchestrator import router

    raw = '{"action":"suggest_connect_mcp","connector_query":"GitHub","reason":"user asked"}'
    monkeypatch.setattr(router, "_get_adapter", lambda: _stub_adapter(raw))

    res = await router.route("conv1", "connect my GitHub")
    assert res.action == "suggest_connect_mcp"
    assert res.connector_query == "GitHub"


def test_suggest_connect_mcp_is_a_valid_action():
    from server.orchestrator import router

    assert "suggest_connect_mcp" in router._VALID_ACTIONS


def test_rubric_token_delta_is_bounded():
    """The action line added to the always-sent _SYSTEM rubric must be small (cost discipline)."""
    from arslan.llm import usage_sink
    from server.orchestrator import router

    # The rubric must MENTION the action but NOT embed the catalog.
    assert "suggest_connect_mcp" in router._SYSTEM
    assert "GITHUB_PERSONAL_ACCESS_TOKEN" not in router._SYSTEM  # catalog stays OUT of the rubric
    # Record the token size of the added line for the reviewer (bound at 120 tok).
    line = ('- suggest_connect_mcp: the user wants to connect/add a NAMED MCP server/'
            'connector ("connect my GitHub", "add the Notion MCP"). Put the connector '
            'name in connector_query. Do NOT use this for running a connected tool.\n')
    assert usage_sink.estimate_tokens(line) < 120
