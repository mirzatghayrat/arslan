from types import SimpleNamespace

import pytest

from server import main
from server.api import browser
from server.mcp.session import manager
from server.services import curation_loop, evolution_watcher, scheduler


@pytest.mark.parametrize("failure", [None, "watcher", "scheduler", "curation", "browser", "mcp", "database"])
async def test_recovery_shutdown_confirmation_requires_every_cleanup(monkeypatch, failure):
    events = []
    def cleanup(name):
        async def call():
            events.append(name)
            if name == failure:
                raise RuntimeError("synthetic cleanup failure")
        return call
    monkeypatch.setattr(evolution_watcher, "stop", cleanup("watcher"))
    monkeypatch.setattr(scheduler, "stop", cleanup("scheduler"))
    monkeypatch.setattr(curation_loop, "stop", cleanup("curation"))
    monkeypatch.setattr(browser, "shutdown", cleanup("browser"))
    monkeypatch.setattr(manager, "aclose_all", cleanup("mcp"))
    monkeypatch.setattr(main, "engine", SimpleNamespace(dispose=cleanup("database")))
    app = SimpleNamespace(state=SimpleNamespace(shutdown_complete=True))
    if failure in {"browser", "mcp", "database"}:
        with pytest.raises(RuntimeError, match="synthetic"):
            await main._shutdown_services(app)
    else:
        await main._shutdown_services(app)
        assert events == ["watcher", "scheduler", "curation", "browser", "mcp", "database"]
    assert app.state.shutdown_complete is (failure is None)
