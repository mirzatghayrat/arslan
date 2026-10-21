"""The engine behind Arslan Hands (agent-desktop), behind one small interface for the harness:
`look()` the fixture's window into elements, then `click / set_value / type_text / press /
hotkey` one of them. It goes through the real Hands socket (a development Hands, peer check
off), so Hands' own rules apply exactly as in the product.
"""
from __future__ import annotations

import json
import socket
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

FOLDER = Path.home() / "Library" / "Application Support" / "Arslan Hands"


class Hands:
    def __init__(self) -> None:
        self.token = json.loads((FOLDER / "ready.json").read_text())["token"]

    def call(self, op: str, args: dict | None = None, timeout: float = 90) -> dict:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(str(FOLDER / "s.sock"))
            s.sendall((json.dumps({"token": self.token, "id": f"harness-{uuid.uuid4().hex}", "op": op,
                                   "args": args or {}}) + "\n").encode())
            data = b""
            while not data.endswith(b"\n"):
                chunk = s.recv(1 << 20)
                if not chunk:
                    break
                data += chunk
        return json.loads(data)


@dataclass
class Element:
    id: str
    role: str
    label: str


@dataclass
class Act:
    """What one engine call reported."""
    ok: bool
    outcome: str | None
    code: str | None
    ms: int
    raw: dict = field(repr=False, default_factory=dict)


def _act(reply: dict, started: float) -> Act:
    refused = (reply.get("refused") or {}).get("code")
    envelope = reply.get("envelope") or {}
    error = (envelope.get("error") or {}).get("code") if envelope.get("ok") is False else None
    return Act(ok=reply.get("ok") is True and not error, outcome=reply.get("outcome"), code=refused or error,
               ms=round((time.monotonic() - started) * 1000), raw=reply)


class AgentDesktop:
    name = "agent-desktop"

    def __init__(self, hands: Hands, app: str):
        self.hands, self.app = hands, app

    def look(self) -> tuple[list[Element], int]:
        started = time.monotonic()
        reply = self.hands.call("snapshot", {"app": self.app})
        ms = round((time.monotonic() - started) * 1000)
        envelope = reply.get("envelope") or {}
        if reply.get("ok") is not True or envelope.get("ok") is not True:
            raise RuntimeError(f"look failed: {reply.get('refused') or envelope.get('error')}")
        tree = (envelope.get("data") or {}).get("tree") or {}
        found: list[Element] = []

        def walk(node: dict) -> None:
            if node.get("ref_id"):
                found.append(Element(str(node["ref_id"]), str(node.get("role") or ""), str(node.get("name") or "")))
            for child in node.get("children") or []:
                if isinstance(child, dict):
                    walk(child)
        walk(tree)
        return found, ms

    def look_with_screenshot(self) -> tuple[dict, dict, int]:
        """Hands v2's look as desktop_look makes it: the tree with bounds, then Hands' screenshot of
        the window just read. (snapshot data, capture, total ms)."""
        from concurrent.futures import ThreadPoolExecutor
        started = time.monotonic()
        with ThreadPoolExecutor(2) as pool:       # asked together, as desktop_look does
            front = pool.submit(self.hands.call, "capture_window", {"app": self.app})
            reply = self.hands.call("snapshot", {"app": self.app, "include_bounds": True})
            shot = front.result()
        envelope = reply.get("envelope") or {}
        if reply.get("ok") is not True or envelope.get("ok") is not True:
            raise RuntimeError(f"look failed: {reply.get('refused') or envelope.get('error')}")
        data = envelope.get("data") or {}
        read = str((data.get("window") or {}).get("id") or "")
        if shot.get("ok") and read and str(shot["capture"].get("window_id")) != read.removeprefix("w-"):
            shot = self.hands.call("capture_window", {"app": self.app, "window": read})
        ms = round((time.monotonic() - started) * 1000)
        if shot.get("ok") is not True:
            raise RuntimeError(f"capture failed: {shot.get('refused')}")
        return data, shot["capture"], ms

    def click(self, element: Element) -> Act:
        started = time.monotonic()
        return _act(self.hands.call("click", {"app": self.app, "ref": element.id}), started)

    def set_value(self, element: Element, text: str) -> Act:
        started = time.monotonic()
        return _act(self.hands.call("set_value", {"app": self.app, "ref": element.id, "value": text}), started)

    def type_text(self, element: Element, text: str) -> Act:
        started = time.monotonic()
        return _act(self.hands.call("type", {"app": self.app, "ref": element.id, "text": text}), started)

    def select(self, element: Element, value: str) -> Act:
        started = time.monotonic()
        # Hands v2 §6.3: a pop-up borrows the front, with the user's switch (on, as by default).
        return _act(self.hands.call("select", {"app": self.app, "ref": element.id, "value": value, "borrow": True}),
                    started)

    def menu(self, path: list[str]) -> Act:
        """Hands v2: a menu item pressed in the background by its path (Hands' own accessibility)."""
        started = time.monotonic()
        return _act(self.hands.call("menu", {"app": self.app, "path": path}), started)

    def press(self, keys: str, element: Element | None = None) -> Act:
        """agent-desktop presses keys for the whole app: to aim them, the element is clicked
        (focused) first, and that click is part of the measured action."""
        started = time.monotonic()
        if element is not None:
            self.hands.call("click", {"app": self.app, "ref": element.id})
        return _act(self.hands.call("press", {"app": self.app, "keys": keys}), started)


def find(elements: list[Element], label: str, role: str = "") -> Element | None:
    """The first element whose label is `label` (case-insensitive) and whose role contains `role`."""
    for e in elements:
        if e.label.strip().lower() == label.lower() and role.lower() in e.role.lower():
            return e
    return None
