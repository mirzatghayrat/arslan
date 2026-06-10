"""Direct tests for the shared parse_json_object helper (json_protocol.py).

This parser sits on the security-relevant dispatch path for both the router
(action selection) and spawn_loop (tool/escalate gating), so correctness is
tested here independently of either caller.
"""
from server.orchestrator.json_protocol import parse_json_object


def test_plain_json():
    result = parse_json_object('{"tool": "web_search", "args": {"query": "test"}}')
    assert result == {"tool": "web_search", "args": {"query": "test"}}


def test_fenced_json():
    content = '```json\n{"action": "route", "spawn_id": 7}\n```'
    result = parse_json_object(content)
    assert result == {"action": "route", "spawn_id": 7}


def test_fenced_json_no_lang_tag():
    content = '```\n{"action": "answer"}\n```'
    result = parse_json_object(content)
    assert result == {"action": "answer"}


def test_commentary_wrapped_rescue():
    """Weak models often emit commentary before/after the JSON object."""
    content = 'Sure! {"tool": "x", "args": {}} now.'
    result = parse_json_object(content)
    assert result == {"tool": "x", "args": {}}


def test_non_dict_json_returns_none():
    """Arrays and scalars are not valid protocol responses."""
    assert parse_json_object("[1, 2, 3]") is None
    assert parse_json_object('"just a string"') is None
    assert parse_json_object("42") is None


def test_garbage_returns_none():
    assert parse_json_object("not json at all") is None
    assert parse_json_object("") is None
    assert parse_json_object("   ") is None


def test_none_input_returns_none():
    # content arg accepts str; callers may pass empty string
    assert parse_json_object("") is None
