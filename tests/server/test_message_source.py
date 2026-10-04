"""Mobile bridge: a message the Bridge forwarded from a paired iPhone is stored and shown as
"from iPhone"; anything else (the window, or any other claimed source) is the window."""
import pytest

from server.orchestrator import arslan, tool_loop
from server.services import turn_facts
from server.ws.arslan import _history, message_source
from tests.server.test_arslan_loop import _LLMResp, _NativeAdapter, _events, maker  # noqa: F401


@pytest.mark.parametrize("frame,source", [
    ({"source": "phone"}, "phone"),
    ({"source": "window"}, None),
    ({"source": "admin"}, None),
    ({"source": None}, None),
    ({}, None),
])
def test_only_the_phone_source_is_kept(frame, source):
    assert message_source(frame) == source


async def _no_facts(conv, msg):
    return []


async def test_a_phone_message_is_stored_and_returned_with_its_source(maker, monkeypatch):  # noqa: F811
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: _NativeAdapter([_LLMResp(content="ok"), _LLMResp(content="ok")]))
    monkeypatch.setattr(turn_facts, "extract", _no_facts)
    await arslan.handle_user_message("c-phone", "find flights", _events([]), source="phone")
    await arslan.handle_user_message("c-phone", "and hotels", _events([]))
    users = [m for m in await _history("c-phone") if m["role"] == "user"]
    assert [(m["content"], m["source"]) for m in users] == [("find flights", "phone"), ("and hotels", None)]
