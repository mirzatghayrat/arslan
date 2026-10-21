"""K7's test setup: default config on a Mac without Hands, plus three MCP servers of realistic size
(50 tools, about the size of the user's own largest). Shared by the K7 tests."""
import sys
from types import SimpleNamespace

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, MCPServer, Setting, Tool, Toolset
from server.mcp import session
from server.registry import hands_tools
from server.services import agent_browser, task_service

SERVERS = {
    1: ("files", ["read_text_file", "read_media_file", "read_multiple_files", "write_file", "edit_file",
                  "create_directory", "list_directory", "list_directory_with_sizes", "directory_tree",
                  "move_file", "search_files", "get_file_info", "list_allowed_directories", "head_file"]),
    2: ("github", ["create_issue", "update_issue", "get_issue", "list_issues", "search_issues", "add_comment",
                   "create_pull_request", "get_pull_request", "list_pull_requests", "merge_pull_request",
                   "get_pull_request_files", "get_pull_request_status", "create_review", "get_file_contents",
                   "create_or_update_file", "push_files", "search_code", "search_repositories",
                   "create_repository", "fork_repository", "create_branch", "list_commits", "get_commit",
                   "list_branches", "get_me", "search_users"]),
    3: ("notes", ["search", "fetch", "create_page", "update_page", "move_page", "duplicate_page",
                  "create_database", "query_database", "get_comments", "create_comment"]),
}


def _schema(name: str) -> dict:
    """A parameter table the size real servers send: a few described fields, two required."""
    return {"type": "object",
            "properties": {
                "target": {"type": "string", "description": f"What {name.replace('_', ' ')} works on: a path, "
                                                            "an id or a URL, exactly as returned by a list call."},
                "query": {"type": "string", "description": "Free text to match; leave empty to take everything."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100,
                          "description": "At most this many results (default 20)."},
                "options": {"type": "object", "description": "Extra settings the server accepts, by name."}},
            "required": ["target", "query"]}


async def _closed():
    return None


@pytest_asyncio.fixture
async def mac_with_mcp(tmp_path, monkeypatch):
    monkeypatch.setattr(session.manager, "_sessions", {})
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'k7.db'}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)
    from server.registry import executors
    monkeypatch.setattr(executors, "AsyncSessionLocal", maker)
    async with maker() as s:
        s.add(Setting(key="workspace_dir", value=str(tmp_path)))
        for sid, (label, names) in SERVERS.items():
            s.add(MCPServer(id=sid, label=label, command="x", args=[], env=None, status="connected",
                            state="ready", host_allowed=True))
            s.add(Toolset(key=f"mcp_{sid}", name=label, description="d", tier="orchestrator", status="registered"))
            for name in names:
                s.add(Tool(key=f"mcp_{sid}__{name}", toolset_key=f"mcp_{sid}", tier="orchestrator",
                           status="wired", external_name=name, input_schema=_schema(name),
                           description=f"{name.replace('_', ' ').capitalize()} in {label}. Returns the result as "
                                       "JSON; errors name the field that was wrong."))
            session.manager._sessions[sid] = (object(), SimpleNamespace(aclose=_closed))
        await s.commit()
    # A Mac with the browser set up and Hands not granted (Q1: the gate's configuration).
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(agent_browser, "available", lambda: True)
    monkeypatch.setattr(hands_tools, "desktop_available", lambda: False)
    monkeypatch.setattr(task_service, "current", lambda: object())
    yield maker
    await engine.dispose()
