"""WebSocket handshake token enforcement — integration coverage for all 3 endpoints.

The three inline WS routes in ``main.py`` (``/ws/chat``, ``/ws/arslan``,
``/ws/sandbox``) delegate to the handlers in ``server/ws/*.py``, each of which
validates the ``?token=`` query param via ``is_ws_token_valid`` *before*
accepting the socket. ``test_auth.py`` already unit-tests the helper; these tests
prove the wiring end to end:

* with ``ARSLAN_API_TOKEN`` set, a wrong or missing token closes the handshake
  with code ``4001`` (the socket never upgrades — the guard runs before
  ``ws.accept()``);
* the correct token connects and receives the first ``history`` frame;
* with the token unset, the empty-token passthrough lets any client connect,
  mirroring the HTTP ``require_auth`` no-op-when-unset semantics.

The DB seed + every ``websocket_connect`` run on one ``portal`` loop over a
NullPool engine (see ``conftest.build_ws_client``), so no pooled aiosqlite
connection is reused across event loops.
"""
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from server.db.models import Spawn
from tests.server.conftest import build_ws_client

# (path, human name) for each of the three token-guarded WS endpoints. The
# arslan channel is the highest-risk one (drives spawn dispatch / roster edits).
WS_ENDPOINTS = [
    ("/ws/chat/1", "chat"),
    ("/ws/arslan/main", "arslan"),
    ("/ws/sandbox/1", "sandbox"),
]


def _build_client(tmp_path, monkeypatch, portal, token: str) -> TestClient:
    """Build a TestClient whose app sees ``ARSLAN_API_TOKEN=token``.

    Seeds one spawn (id=1) so the chat/sandbox handlers get past their spawn
    lookup once the token check passes. ``ARSLAN_API_TOKEN`` is passed as env so
    the factory's config reload makes ``config.settings.api_token`` reflect it.
    """

    async def _seed(maker):
        async with maker() as s:
            s.add(
                Spawn(
                    name="beauty-guru",
                    domain_category="content-creator",
                    domain_subcategory="xiaohongshu",
                    capabilities=["content-generation"],
                    system_prompt="You are a beauty expert.",
                )
            )
            await s.commit()

    return build_ws_client(
        portal, tmp_path, monkeypatch, _seed,
        db_name="wsauth.db", env={"ARSLAN_API_TOKEN": token},
    )


@pytest.mark.parametrize("path,name", WS_ENDPOINTS)
def test_ws_rejects_wrong_token(tmp_path, monkeypatch, portal, path, name):
    client = _build_client(tmp_path, monkeypatch, portal, "secret123")
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"{path}?token=wrong") as ws:
            ws.receive_json()
    assert exc.value.code == 4001


@pytest.mark.parametrize("path,name", WS_ENDPOINTS)
def test_ws_rejects_missing_token(tmp_path, monkeypatch, portal, path, name):
    client = _build_client(tmp_path, monkeypatch, portal, "secret123")
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(path) as ws:  # no ?token=
            ws.receive_json()
    assert exc.value.code == 4001


@pytest.mark.parametrize("path,name", WS_ENDPOINTS)
def test_ws_accepts_correct_token(tmp_path, monkeypatch, portal, path, name):
    client = _build_client(tmp_path, monkeypatch, portal, "secret123")
    with client.websocket_connect(f"{path}?token=secret123") as ws:
        frame = ws.receive_json()
        assert frame["type"] == "history"


@pytest.mark.parametrize("path,name", WS_ENDPOINTS)
def test_ws_open_when_token_unset(tmp_path, monkeypatch, portal, path, name):
    # Empty token => auth disabled => any client (even token-less) connects.
    client = _build_client(tmp_path, monkeypatch, portal, "")
    with client.websocket_connect(path) as ws:  # no ?token=
        frame = ws.receive_json()
        assert frame["type"] == "history"
