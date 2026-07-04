"""ListMyCapabilitiesExecutor: Arslan reports its OWN usable capabilities from real data."""
import pytest

from server.registry.executors import EXECUTORS, ListMyCapabilitiesExecutor


class _NullSession:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *a):
        return False


@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    # The executor opens AsyncSessionLocal only to pass a session to shell_enabled, which we
    # stub — so a null session is enough (no DB needed).
    import server.db.session as db_session
    monkeypatch.setattr(db_session, "AsyncSessionLocal", lambda: _NullSession())


@pytest.mark.asyncio
async def test_builtin_always_present_mcp_empty(monkeypatch):
    from server.services import mcp_service, settings_service
    monkeypatch.setattr(mcp_service, "list_servers", lambda: _aw([]))
    monkeypatch.setattr(settings_service, "shell_enabled", lambda db: _aw(False))

    out = await ListMyCapabilitiesExecutor().execute({})
    assert out["ok"] is True
    keys = [b["key"] for b in out["builtin"]]
    assert keys == ["web_search", "web_extract", "render_chart"]  # no run_command when shell off
    assert out["mcp"] == []


@pytest.mark.asyncio
async def test_installed_mcp_reflected(monkeypatch):
    from server.services import mcp_service, settings_service
    monkeypatch.setattr(mcp_service, "list_servers",
                        lambda: _aw([{"label": "github", "status": "ready"},
                                     {"label": "db", "status": "error"}]))
    monkeypatch.setattr(settings_service, "shell_enabled", lambda db: _aw(False))

    out = await ListMyCapabilitiesExecutor().execute({})
    assert out["mcp"] == [{"label": "github", "status": "ready"},
                          {"label": "db", "status": "error"}]


@pytest.mark.asyncio
async def test_shell_enabled_adds_run_command(monkeypatch):
    from server.services import mcp_service, settings_service
    monkeypatch.setattr(mcp_service, "list_servers", lambda: _aw([]))
    monkeypatch.setattr(settings_service, "shell_enabled", lambda db: _aw(True))

    out = await ListMyCapabilitiesExecutor().execute({})
    assert "run_command" in [b["key"] for b in out["builtin"]]


def test_registered_in_executors():
    assert EXECUTORS.get("list_my_capabilities").__class__ is ListMyCapabilitiesExecutor


async def _aw(value):
    return value
