"""Hands P0 (spec docs/specs/2026-10-08-0157-hands-v2.md §1): seven defects of the
0.1.53 Hands, each pinned by a test that failed before its fix.

D1 an action could run twice after a timeout · D2 append could erase a field ·
D3 submit pressed Return wherever the app's focus was · D4 a wait that timed out
was dropped · D5 Hands' own deadline code did not match the read retry · D6 the
cursor label was English in every language · D7 "delivered, not verified" was
reported as done.
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

from server.registry import hands_tools
from server.services import hands_client, hands_contract
from tests.server import test_hands_0153 as base

_case = base._case
# The 0.1.53 fixtures (a faked Hands, auto-answered cards, a job), shared rather than copied.
isolated, hands, asks, in_turn, in_job = base.isolated, base.hands, base.asks, base.in_turn, base.in_job

pytestmark = pytest.mark.one_arslan


# ── D1: at most once ─────────────────────────────────────────────────────────

class SlowHands:
    """A real socket that answers actions only after the client has given up,
    and keeps every answer so `answer_of` can return it."""

    def __init__(self, folder: Path, delay: float):
        self.folder, self.delay = folder, delay
        self.requests: list[dict] = []
        self.answers: dict[str, dict] = {}
        self.server = None

    async def start(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / "ready.json").write_text(json.dumps({"pid": os.getpid(), "token": "t"}))
        self.server = await asyncio.start_unix_server(self._handle, path=str(self.folder / "s.sock"))

    async def _handle(self, reader, writer):
        line = await reader.readline()
        if not line:
            return
        request = json.loads(line)
        self.requests.append(request)
        if request["op"] == "answer_of":
            wanted = request["args"]["id"]
            for _ in range(100):
                if wanted in self.answers:
                    break
                await asyncio.sleep(0.02)
            reply = ({"ok": True, "state": "done", "answer": self.answers[wanted], "pid": os.getpid()}
                     if wanted in self.answers else {"ok": True, "state": "unknown_id", "pid": os.getpid()})
        else:
            await asyncio.sleep(self.delay)
            reply = {"ok": True, "envelope": _case("click")["envelope"], "id": request["id"]}
            self.answers[request["id"]] = reply
        try:
            writer.write((json.dumps(reply) + "\n").encode())
            await writer.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            writer.close()

    def actions(self):
        return [r for r in self.requests if r["op"] != "answer_of"]

    async def stop(self):
        self.server.close()
        await self.server.wait_closed()


@pytest.fixture
async def slow_hands(monkeypatch):
    folder = Path(tempfile.mkdtemp(prefix="hp0-", dir="/tmp"))      # socket paths are capped at 104 bytes
    monkeypatch.setattr(hands_client, "folder", lambda: folder)
    monkeypatch.setattr(sys, "platform", "darwin")

    async def no_launch():
        raise AssertionError("Hands was already running; nothing should launch it")
    monkeypatch.setattr(hands_client, "_launch", no_launch)
    fake = SlowHands(folder, delay=0.4)
    await fake.start()
    yield fake
    await fake.stop()
    shutil.rmtree(folder, ignore_errors=True)


async def test_an_action_whose_reply_is_late_is_not_sent_again(slow_hands):
    reply = await hands_client.call("click", {"app": "Notes", "ref": "@s:e1"}, timeout=0.1)
    assert len(slow_hands.actions()) == 1, "the click was sent twice"
    assert reply["ok"] is True and reply["envelope"]["command"] == "click"   # the late answer, fetched by id


async def test_when_hands_restarted_meanwhile_the_outcome_is_unknown_not_retried(slow_hands):
    async def restarted():
        await asyncio.sleep(0.03)
        # A different live process now owns ready.json: the Hands that took the request is gone.
        (slow_hands.folder / "ready.json").write_text(json.dumps({"pid": os.getppid(), "token": "t"}))
    asyncio.get_running_loop().create_task(restarted())
    reply = await hands_client.call("click", {"app": "Notes", "ref": "@s:e1"}, timeout=0.1)
    assert len(slow_hands.actions()) == 1
    result = hands_contract.parse(reply)
    assert result.code == "unknown" and "look" in result.advice().lower()


# ── D2: append never erases ──────────────────────────────────────────────────

def _fail(command: str, code: str = "ACTION_FAILED") -> dict:
    return {"ok": True, "envelope": {"version": "2.4", "ok": False, "command": command,
                                     "error": {"code": code, "message": "fake failure"}}}


async def test_append_refuses_when_the_old_text_cannot_be_read(hands, asks, in_job, monkeypatch):
    real = hands.call

    async def unreadable(op, args=None, **kw):
        if op == "get":
            hands.calls.append((op, dict(args or {})))
            return _fail("get")
        return await real(op, args, **kw)
    monkeypatch.setattr(hands_client, "call", unreadable)
    result = await hands_tools.DesktopTypeExecutor().execute(
        {"app": "Notes", "element": "Body", "ref": "@sfixture0:e1", "text": " more", "mode": "append"})
    assert result["ok"] is False and result["code"] == "append_unreadable"
    assert hands.ops("set_value", "type") == [], "the field would have been overwritten with only the new text"


async def test_append_writes_old_plus_new(hands, asks, in_job):
    old = _case("get_value")["envelope"]["data"]["value"]
    result = await hands_tools.DesktopTypeExecutor().execute(
        {"app": "Notes", "element": "Body", "ref": "@sfixture0:e1", "text": " more", "mode": "append"})
    assert result["ok"] is True
    (written,) = [a for op, a in hands.calls if op == "set_value"]
    assert written["value"] == old + " more"


# ── D3: Return only into the field just typed in ─────────────────────────────

def _states(*states):
    return {"ok": True, "envelope": {"version": "2.4", "ok": True, "command": "get",
                                     "data": {"property": "states", "value": list(states)}}}


async def test_submit_does_not_press_return_when_the_field_has_no_focus(hands, asks, in_job, monkeypatch):
    real = hands.call

    async def elsewhere(op, args=None, **kw):
        if op == "get" and (args or {}).get("property") == "states":
            hands.calls.append((op, dict(args or {})))
            return _states()                         # not focused, even after a click
        return await real(op, args, **kw)
    monkeypatch.setattr(hands_client, "call", elsewhere)
    result = await hands_tools.DesktopTypeExecutor().execute(
        {"app": "Notes", "element": "Title", "ref": "@sfixture0:e1", "text": "Hello", "submit": True})
    assert result["ok"] is False and result["code"] == "submit_unsure"
    assert hands.ops("press") == [], "Return went to whatever had the focus"


async def test_submit_presses_return_when_the_field_has_focus(hands, asks, in_job, monkeypatch):
    real = hands.call

    async def focused(op, args=None, **kw):
        if op == "get" and (args or {}).get("property") == "states":
            hands.calls.append((op, dict(args or {})))
            return _states("focused")
        return await real(op, args, **kw)
    monkeypatch.setattr(hands_client, "call", focused)
    result = await hands_tools.DesktopTypeExecutor().execute(
        {"app": "Notes", "element": "Title", "ref": "@sfixture0:e1", "text": "Hello", "submit": True})
    assert result["ok"] is True and hands.ops("press") == ["press"]


# ── D4: a wait that timed out is said ────────────────────────────────────────

async def test_a_wait_that_timed_out_is_reported(hands, asks, in_turn, monkeypatch):
    real = hands.call

    async def never_appears(op, args=None, **kw):
        if op == "wait":
            hands.calls.append((op, dict(args or {})))
            return {"ok": True, "envelope": _case("err_timeout")["envelope"]}
        return await real(op, args, **kw)
    monkeypatch.setattr(hands_client, "call", never_appears)
    result = await hands_tools.DesktopLookExecutor().execute({"app": "Notes", "wait_for_text": "Saved"})
    assert result["ok"] is True
    assert "“Saved” did not appear" in result["text"]


# ── D5: one code for "took too long" ─────────────────────────────────────────

async def test_a_read_cut_by_hands_own_deadline_is_tried_again(hands, monkeypatch):
    tries = []

    async def deadline(op, args=None, **kw):
        tries.append(op)
        if len(tries) == 1:
            return {"ok": False, "refused": {"code": "TIMEOUT", "message": "agent-desktop did not finish in time"}}
        return await hands.call(op, args, **kw)
    monkeypatch.setattr(hands_client, "call", deadline)
    result = await hands_tools._hands("snapshot", {"app": "Notes"})
    assert tries == ["snapshot", "snapshot"] and result.ok


def test_hands_own_deadline_code_is_upper_case():
    source = (Path(__file__).resolve().parents[2] / "desktop" / "hands" / "src" / "server.rs").read_text()
    assert 'refuse("timeout"' not in source and 'refuse("TIMEOUT"' in source
    assert hands_contract.Result(ok=False, code="TIMEOUT", refused=True).advice() != "Arslan Hands refused."


# ── D6: the cursor label speaks the user's language ──────────────────────────

@pytest.mark.parametrize("locale, word", [("zh", "点击"), ("ja", "クリック"), ("en", "clicking")])
async def test_the_cursor_label_is_in_the_ui_language(hands, asks, in_job, monkeypatch, locale, word):
    from server.services import runtime_messages

    async def selected():
        return locale
    monkeypatch.setattr(runtime_messages, "selected_locale", selected)
    await hands_tools.DesktopClickExecutor().execute({"app": "Notes", "element": "Save", "ref": "@sfixture0:e3"})
    (label,) = [a["label"] for op, a in hands.calls if op == "session_label"]
    assert word in label


# ── D7: "delivered, not verified" is not "done" ─────────────────────────────

async def test_an_unverified_click_is_not_reported_as_done(hands, asks, in_job):
    assert _case("click")["envelope"]["data"]["disposition"]["delivery"] == "delivered_unverified"
    result = await hands_tools.DesktopClickExecutor().execute(
        {"app": "Notes", "element": "Save", "ref": "@sfixture0:e3"})
    assert result["ok"] is True and result["outcome"] == "sent_unconfirmed"
    assert not result["text"].startswith("Done") and "not confirmed" in result["text"]


async def test_a_verified_change_is_reported_as_done(hands, asks, in_job):
    result = await hands_tools.DesktopTypeExecutor().execute(
        {"app": "Notes", "element": "Title", "ref": "@sfixture0:e1", "text": "Hello"})
    assert result["outcome"] == "done" and result["text"].startswith("Done")


async def test_an_app_that_kept_the_front_is_said(hands, asks, in_job, monkeypatch):
    real = hands.call

    async def jumped(op, args=None, **kw):
        reply = await real(op, args, **kw)
        if op == "click":
            reply = {**reply, "app": {"name": "Notes", "bundle_id": "com.apple.Notes", "pid": 200},
                     "focus_restored": False, "front": {"before": 100, "after": 200}}
        return reply
    monkeypatch.setattr(hands_client, "call", jumped)
    result = await hands_tools.DesktopClickExecutor().execute(
        {"app": "Notes", "element": "New Note", "ref": "@sfixture0:e3"})
    assert "came to the front" in result["text"]
