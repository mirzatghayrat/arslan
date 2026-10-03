"""The Arslan Bridge as Arslan's window sees it (docs/specs/mobile-bridge-protocol.md §6.1).

The Bridge (the iPhone companion helper) has no window. It connects to `/ws/bridge` and this
hub relays between it and Settings › iPhone: a new pairing code (shown as a QR), a pending
"iPhone 'x' wants to connect" request, the device list, revocation. Accepting a phone is a
click in Arslan's window only — this API is behind the same token as every other setting,
and nothing on the phone or in a conversation (voice included) can reach it.

One Bridge at a time; a newer connection replaces an older one. Keys never pass through
here: the Bridge keeps them in its own Keychain items.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

CODE_TIMEOUT_S = 5.0
MAX_PENDING = 8


class BridgeUnavailable(Exception):
    pass


@dataclass
class BridgeHub:
    socket: object | None = None
    info: dict = field(default_factory=dict)
    devices: list = field(default_factory=list)
    pending: dict = field(default_factory=dict)            # request_id -> request
    code: dict | None = None
    _code_waiters: list = field(default_factory=list)

    @property
    def connected(self) -> bool:
        return self.socket is not None

    async def attach(self, socket) -> None:
        self.socket = socket
        self.pending.clear()
        await self._send({"type": "devices.list"})

    def detach(self, socket) -> None:
        if self.socket is socket:
            self.socket, self.code = None, None
            self.pending.clear()

    async def _send(self, frame: dict) -> None:
        if self.socket is None:
            raise BridgeUnavailable()
        await self.socket.send_json(frame)

    async def handle(self, frame: dict) -> None:
        """A frame from the Bridge."""
        kind = frame.get("type")
        if kind == "bridge.hello":
            self.info = {k: frame.get(k) for k in ("device_id", "version", "protocol")}
        elif kind == "pairing.code":
            self.code = {"uri": frame.get("uri"), "qr_png": frame.get("qr_png"), "expires_at": frame.get("expires_at")}
            for waiter in self._code_waiters:
                if not waiter.done():
                    waiter.set_result(self.code)
            self._code_waiters.clear()
        elif kind == "pairing.request":
            if len(self.pending) >= MAX_PENDING or not frame.get("request_id"):
                return
            request = {k: frame.get(k) for k in ("request_id", "pairing_id", "phone_id", "phone_name")}
            self.pending[str(frame["request_id"])] = request
            self._notify(request)
        elif kind == "devices":
            self.devices = [{k: d.get(k) for k in ("device_id", "name", "paired_at", "last_seen")}
                            for d in frame.get("items") or [] if isinstance(d, dict)]

    def _notify(self, request: dict) -> None:
        """A desktop notification and the island: something waits for the user's OK."""
        try:
            from server.services import desktop_status
            desktop_status.push("approval_needed", title="iPhone wants to connect",
                                summary=str(request.get("phone_name") or "iPhone")[:80])
        except Exception:  # noqa: BLE001 — a missed notification never blocks pairing
            pass

    async def request_code(self) -> dict:
        waiter = asyncio.get_running_loop().create_future()
        self._code_waiters.append(waiter)
        await self._send({"type": "pairing.new"})
        try:
            return await asyncio.wait_for(waiter, timeout=CODE_TIMEOUT_S)
        except TimeoutError:
            raise BridgeUnavailable() from None

    async def decide(self, request_id: str, accept: bool) -> bool:
        if self.pending.pop(request_id, None) is None:
            return False
        await self._send({"type": "pairing.decide", "request_id": request_id, "accept": bool(accept)})
        return True

    async def revoke(self, device_id: str) -> bool:
        if not any(d.get("device_id") == device_id for d in self.devices):
            return False
        await self._send({"type": "device.revoke", "device_id": device_id})
        self.devices = [d for d in self.devices if d.get("device_id") != device_id]
        return True

    def status(self) -> dict:
        return {"connected": self.connected, "bridge": self.info if self.connected else {},
                "devices": self.devices, "pending": list(self.pending.values()),
                "code": self.code if self.connected else None}


hub = BridgeHub()
