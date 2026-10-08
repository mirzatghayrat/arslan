"""The two engines behind Arslan Hands, behind one small interface for the harness:
`look()` the fixture's window into elements, then `click / set_value / type_text / press /
hotkey` one of them. Both go through the real Hands socket (a development Hands, peer check
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
        return _act(self.hands.call("select", {"app": self.app, "ref": element.id, "value": value}), started)

    def press(self, keys: str, element: Element | None = None) -> Act:
        """agent-desktop presses keys for the whole app: to aim them, the element is clicked
        (focused) first, and that click is part of the measured action."""
        started = time.monotonic()
        if element is not None:
            self.hands.call("click", {"app": self.app, "ref": element.id})
        return _act(self.hands.call("press", {"app": self.app, "keys": keys}), started)


class Cua:
    name = "cua"

    def __init__(self, hands: Hands, app: str):
        self.hands, self.app = hands, app
        self.pid: int | None = None
        self.window: int | None = None

    def _call(self, tool: str, args: dict) -> dict:
        return self.hands.call("cua", {"tool": tool, "args": args, "session": "harness"})

    def _target(self) -> None:
        app = None
        deadline = time.monotonic() + 3          # a just-started app takes a moment to be listed
        while app is None and time.monotonic() < deadline:
            listed = self._call("list_apps", {})
            if listed.get("ok") is not True:
                raise RuntimeError(f"list_apps failed: {listed.get('refused')} ({listed.get('completion')})")
            apps = (listed.get("result") or {}).get("structuredContent", {}).get("apps", [])
            app = next((a for a in apps if a.get("name") == self.app and a.get("running")), None)
            if app is None:
                time.sleep(0.3)
        if app is None:
            names = sorted({str(a.get("name")) for a in apps if a.get("running")})
            raise RuntimeError(f"{self.app} is not in Cua's app list ({len(apps)} apps; running: {names[:30]})")
        self.pid = int(app["pid"])
        windows = ((self._call("list_windows", {"pid": self.pid}).get("result") or {})
                   .get("structuredContent") or {}).get("windows") or []
        self.window = int(windows[0]["window_id"]) if windows else None

    def look(self) -> tuple[list[Element], int]:
        self._target()
        started = time.monotonic()
        reply = self._call("get_window_state", {"pid": self.pid, "window_id": self.window, "max_image_dimension": 800})
        ms = round((time.monotonic() - started) * 1000)
        if reply.get("ok") is not True:
            raise RuntimeError(f"look failed: {reply.get('refused')}")
        elements = ((reply.get("result") or {}).get("structuredContent") or {}).get("elements") or []
        return [Element(str(e["element_token"]), str(e.get("role") or ""), str(e.get("label") or ""))
                for e in elements if e.get("element_token")], ms

    def click(self, element: Element) -> Act:
        started = time.monotonic()
        return _act(self._call("click", {"pid": self.pid, "element_token": element.id}), started)

    def set_value(self, element: Element, text: str) -> Act:
        started = time.monotonic()
        return _act(self._call("set_value", {"pid": self.pid, "element_token": element.id, "value": text}), started)

    def type_text(self, element: Element, text: str) -> Act:
        started = time.monotonic()
        return _act(self._call("type_text", {"pid": self.pid, "element_token": element.id, "text": text}), started)

    def select(self, element: Element, value: str) -> Act:
        return self.set_value(element, value)

    def press(self, keys: str, element: Element | None = None) -> Act:
        """Cua aims keys at an element itself (`element_token`)."""
        parts = [k.strip() for k in keys.split("+") if k.strip()]
        aim = {"element_token": element.id} if element is not None else {}
        started = time.monotonic()
        if len(parts) == 1:
            return _act(self._call("press_key", {"pid": self.pid, "key": parts[0], **aim}), started)
        return _act(self._call("hotkey", {"pid": self.pid, "keys": parts, **aim}), started)


def find(elements: list[Element], label: str, role: str = "") -> Element | None:
    """The first element whose label is `label` (case-insensitive) and whose role contains `role`."""
    for e in elements:
        if e.label.strip().lower() == label.lower() and role.lower() in e.role.lower():
            return e
    return None


class Arc:
    """arc-driver (shhivv/arc-cua, MIT) over its own MCP stdio server — a bake-off candidate
    only (spec §15 A2): it is NOT behind Hands, so Hands' rules do not apply to it here, and it
    runs with this process's grants. `ARC_CUA` names its `arc-cua` executable."""
    name = "arc"

    def __init__(self, executable: str, app: str, settle: bool = True):
        import subprocess
        self.app, self.settle = app, settle
        self.proc = subprocess.Popen([executable, "mcp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True)
        self._id = 0
        self._rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                 "clientInfo": {"name": "hands-harness", "version": "1"}})
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        self.proc.stdin.flush()
        self.pid: int | None = None
        self.snapshot: str | None = None

    def _rpc(self, method: str, params: dict) -> dict:
        self._id += 1
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}) + "\n")
        self.proc.stdin.flush()
        while True:
            message = json.loads(self.proc.stdout.readline())
            if message.get("id") == self._id:
                return message.get("result") or {}

    def _tool(self, name: str, args: dict) -> dict:
        result = self._rpc("tools/call", {"name": name, "arguments": args})
        return result.get("structuredContent") or {}

    def close(self) -> None:
        self.proc.kill()

    def look(self) -> tuple[list[Element], int]:
        if self.pid is None:
            apps = self._tool("apps", {}).get("apps") or []
            app = next((a for a in apps if a.get("name") == self.app), None)
            if app is None:
                raise RuntimeError(f"{self.app} is not in arc's app list")
            self.pid = int(app["pid"])
        started = time.monotonic()
        state = self._tool("observe", {"pid": self.pid})
        ms = round((time.monotonic() - started) * 1000)
        if not state.get("snapshot"):
            raise RuntimeError(f"look failed: {state.get('code')}: {state.get('message')}")
        self.snapshot = state["snapshot"]
        return [Element(str(e["id"]), str(e.get("role") or ""), str(e.get("name") or ""))
                for e in state.get("elements") or []], ms

    def _act(self, action: str, element: Element | None, **extra) -> Act:
        args = {"snapshot": self.snapshot, "action": action, "settle": self.settle, **extra}
        if element is not None:
            args["element"] = element.id
        started = time.monotonic()
        result = self._tool("act", args)
        ms = round((time.monotonic() - started) * 1000)
        status = result.get("status")
        if result.get("snapshot"):                 # settle returns a fresh snapshot
            self.snapshot = result["snapshot"]
        # arc's word: done (acted), changed / stale (refused: the screen moved since the look).
        outcome = {"done": "sent_unconfirmed", "changed": "refused", "stale": "refused"}.get(status)
        if status == "done" and result.get("state_changed") is True:
            outcome = "done"
        ok = status == "done"
        return Act(ok=ok, outcome=outcome, code=None if ok else (result.get("code") or status), ms=ms, raw=result)

    def click(self, element: Element) -> Act:
        return self._act("CLICK", element)

    def set_value(self, element: Element, text: str) -> Act:
        return self._act("SET_VALUE", element, value=text)

    def select(self, element: Element, value: str) -> Act:
        return self._act("SET_VALUE", element, value=value)

    def type_text(self, element: Element, text: str) -> Act:
        return self._act("TYPE_TEXT", element, value=text)

    def press(self, keys: str, element: Element | None = None) -> Act:
        parts = [k.strip().upper() for k in keys.split("+") if k.strip()]
        if len(parts) == 1:
            key = {"RETURN": "ENTER"}.get(parts[0], parts[0])
            return self._act("PRESS_KEY", element, key=key)
        chord = "+".join("MOD" if p == "CMD" else p for p in parts)
        return self._act("HOTKEY", element, hotkey=chord)
