"""/ws/bridge — the Arslan Bridge's control channel (docs/specs/mobile-bridge-protocol.md §6.1).
Same handshake rules as /ws/arslan: same-origin (or dev loopback) and the API token, both
checked before accept."""
from __future__ import annotations

from fastapi import WebSocket, WebSocketDisconnect

from server import security
from server.auth import is_ws_token_valid
from server.services.phone_bridge import hub


async def bridge_endpoint(ws: WebSocket) -> None:
    if not security.ws_origin_allowed(ws.headers.get("origin"), ws.headers.get("host")):
        await ws.close(code=4403)
        return
    if not is_ws_token_valid(ws.query_params.get("token")):
        await ws.close(code=4001)
        return
    await ws.accept()
    await hub.attach(ws)
    try:
        while True:
            frame = await ws.receive_json()
            if isinstance(frame, dict):
                await hub.handle(frame)
    except (WebSocketDisconnect, RuntimeError, ValueError):
        pass
    finally:
        hub.detach(ws)
