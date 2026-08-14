"""An authorization failure must say so, not disappear into str(exc).

TWO SHAPES THIS FIXES (spec ③ §0.2):
 * a 401/403 became `str(exc)[:500]` — whatever httpx's prose happened to be,
   with zero indication the fix is credentials rather than the server;
 * `str(InvalidToken())` is the EMPTY STRING (measured in spec ⓪ §2.3), so the
   same line wrote an empty last_error — an error slot that looks unset.
"""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, MCPServer
from server.mcp.discovery import _describe_failure


def _status_error(code: int) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", "http://mcp.example.test/mcp")
    return httpx.HTTPStatusError(
        f"http {code}", request=req, response=httpx.Response(code, request=req),
    )


class TestDescribeFailure:
    def test_401_names_authorization_not_prose(self):
        msg = _describe_failure(_status_error(401), has_headers=True)
        assert "authorization" in msg.lower()
        assert "401" in msg
        # With headers configured the fix is THOSE credentials, and it says so.
        assert "header" in msg.lower() or "credential" in msg.lower()

    def test_401_without_headers_says_none_are_configured(self):
        msg = _describe_failure(_status_error(401), has_headers=False)
        assert "authorization" in msg.lower()
        assert "no " in msg.lower()

    def test_403_is_authorization_too(self):
        assert "authorization" in _describe_failure(_status_error(403), has_headers=True).lower()

    def test_a_wrapped_401_is_still_found(self):
        # anyio task groups wrap transport errors; the classifier must look inside
        # or the wrapped case silently regresses to prose.
        eg = ExceptionGroup("boom", [_status_error(401)])
        assert "authorization" in _describe_failure(eg, has_headers=True).lower()

    def test_other_statuses_keep_todays_prose(self):
        msg = _describe_failure(_status_error(500), has_headers=True)
        assert "authorization" not in msg.lower()

    def test_an_exception_with_an_empty_str_is_not_an_empty_error(self):
        class Mute(Exception):
            def __str__(self) -> str: return ""
        msg = _describe_failure(Mute(), has_headers=False)
        assert msg.strip(), "an empty last_error looks unset — name the type instead"
        assert "Mute" in msg


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'a.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    async with m() as s:
        s.add(MCPServer(id=1, label="remote", transport="http",
                        url="http://mcp.example.test/mcp", command="", args=[],
                        env=None, status="registered"))
        await s.commit()
    return m


async def test_the_classified_message_reaches_last_error(maker, monkeypatch):
    """End to end through connect_and_discover, because a classifier nobody calls
    is the old behaviour with better structure."""
    from server.mcp import discovery

    async def fail(server):
        raise _status_error(401)

    monkeypatch.setattr(discovery.manager, "list_tools", fail)
    with pytest.raises(httpx.HTTPStatusError):
        await discovery.connect_and_discover(1)

    async with maker() as s:
        srv = await s.get(MCPServer, 1)
    assert srv.status == "error"
    assert "authorization" in (srv.last_error or "").lower()
