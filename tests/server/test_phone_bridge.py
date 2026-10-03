"""Settings › iPhone over the Bridge's control channel (mobile-bridge-protocol §6.1): the hub
relays codes, pending requests, devices and revocation; accepting is a window-side REST call;
/ws/bridge has the same handshake rules as /ws/arslan."""
import asyncio

import pytest
from starlette.websockets import WebSocketDisconnect

from server.services import desktop_status, phone_bridge
from server.services.phone_bridge import BridgeHub, BridgeUnavailable
from tests.server.conftest import build_ws_client


class FakeSocket:
    def __init__(self):
        self.sent = []

    async def send_json(self, frame):
        self.sent.append(frame)


@pytest.fixture
def hub(monkeypatch):
    fresh = BridgeHub()
    monkeypatch.setattr(phone_bridge, "hub", fresh)
    import server.api.phone as api
    monkeypatch.setattr(api, "hub", fresh)
    return fresh


async def test_attaching_asks_for_the_device_list_and_hello_names_the_bridge(hub):
    sock = FakeSocket()
    await hub.attach(sock)
    assert sock.sent == [{"type": "devices.list"}]
    await hub.handle({"type": "bridge.hello", "device_id": "mac-1", "version": "0.1.53", "protocol": 1, "secret": "x"})
    assert hub.status()["bridge"] == {"device_id": "mac-1", "version": "0.1.53", "protocol": 1}
    await hub.handle({"type": "devices", "items": [{"device_id": "iphone-1", "name": "A", "paired_at": "t",
                                                    "last_seen": "t", "signing": "never relayed"}]})
    assert hub.status()["devices"] == [{"device_id": "iphone-1", "name": "A", "paired_at": "t", "last_seen": "t"}]


async def test_a_new_code_waits_for_the_bridge_and_times_out_without_one(hub, monkeypatch):
    sock = FakeSocket()
    await hub.attach(sock)

    async def answer():
        await asyncio.sleep(0.01)
        await hub.handle({"type": "pairing.code", "uri": "arslan://pair?payload=x", "qr_png": "iVBO", "expires_at": "t"})
    asyncio.get_running_loop().create_task(answer())
    code = await hub.request_code()
    assert code["uri"].startswith("arslan://pair") and sock.sent[-1] == {"type": "pairing.new"}
    monkeypatch.setattr(phone_bridge, "CODE_TIMEOUT_S", 0.05)
    with pytest.raises(BridgeUnavailable):
        await hub.request_code()
    hub.detach(sock)
    with pytest.raises(BridgeUnavailable):
        await hub.request_code()


async def test_a_request_waits_for_the_users_click_and_is_decided_once(hub):
    desktop_status._events.clear()
    sock = FakeSocket()
    await hub.attach(sock)
    await hub.handle({"type": "pairing.request", "request_id": "r1", "pairing_id": "p", "phone_id": "iphone-1",
                      "phone_name": "Mirror iPhone"})
    assert [p["request_id"] for p in hub.status()["pending"]] == ["r1"]
    assert desktop_status._events[-1]["kind"] == "approval_needed"
    assert await hub.decide("r1", True) is True
    assert sock.sent[-1] == {"type": "pairing.decide", "request_id": "r1", "accept": True}
    assert await hub.decide("r1", True) is False                 # once
    assert hub.status()["pending"] == []


async def test_pending_requests_are_bounded_and_cleared_when_the_bridge_goes(hub):
    sock = FakeSocket()
    await hub.attach(sock)
    for i in range(phone_bridge.MAX_PENDING + 3):
        await hub.handle({"type": "pairing.request", "request_id": f"r{i}", "phone_name": "x"})
    assert len(hub.status()["pending"]) == phone_bridge.MAX_PENDING
    hub.detach(FakeSocket())                                       # someone else's socket: no effect
    assert hub.connected
    hub.detach(sock)
    assert not hub.connected and hub.status()["pending"] == [] and hub.status()["code"] is None


async def test_revoke_only_known_devices(hub):
    sock = FakeSocket()
    await hub.attach(sock)
    await hub.handle({"type": "devices", "items": [{"device_id": "iphone-1", "name": "A"}]})
    assert await hub.revoke("iphone-2") is False
    assert await hub.revoke("iphone-1") is True
    assert sock.sent[-1] == {"type": "device.revoke", "device_id": "iphone-1"}
    assert hub.status()["devices"] == []


async def test_the_window_api(client, hub):
    assert (await client.get("/api/v1/phone")).json()["connected"] is False
    assert (await client.post("/api/v1/phone/pairing")).status_code == 503
    sock = FakeSocket()
    await hub.attach(sock)
    await hub.handle({"type": "pairing.request", "request_id": "r1", "phone_name": "A"})
    assert (await client.post("/api/v1/phone/requests/nope", json={"accept": True})).status_code == 404
    r = await client.post("/api/v1/phone/requests/r1", json={"accept": False})
    assert r.status_code == 200 and sock.sent[-1] == {"type": "pairing.decide", "request_id": "r1", "accept": False}
    assert (await client.delete("/api/v1/phone/devices/iphone-9")).status_code == 404


def test_the_control_socket_requires_the_token(tmp_path, monkeypatch, portal):
    client = build_ws_client(portal, tmp_path, monkeypatch, None, db_name="bridge.db",
                             env={"ARSLAN_API_TOKEN": "secret123"})
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/bridge?token=wrong") as ws:
            ws.receive_json()
    assert exc.value.code == 4001
    with client.websocket_connect("/ws/bridge?token=secret123") as ws:
        assert ws.receive_json() == {"type": "devices.list"}
        ws.send_json({"type": "bridge.hello", "device_id": "mac-ws", "version": "t", "protocol": 1})
        ws.send_json({"type": "devices", "items": []})
    assert phone_bridge.hub.connected is False                    # detached on close
