import json
from uuid import uuid4

import pytest

from server.activation_control_entry import decode_request, run


@pytest.mark.parametrize("payload", [
    {"action": "rollback"},
    {"action": "inspect"},
    {"action": "rollback", "operation_id": str(uuid4())},
    {"action": "switch", "candidate": "restored", "secret": "synthetic-only"},
    {"action": "finalize", "operation_id": str(uuid4()), "secret": "synthetic-only"},
])
def test_exact_action_requests(payload):
    assert decode_request(json.dumps(payload).encode()) == payload


@pytest.mark.parametrize("payload", [
    {}, [], {"action": []}, {"action": "serve"}, {"action": "rollback", "secret": "extra"},
    {"action": "rollback", "active": "/elsewhere"},
    {"action": "rollback", "operation_id": "invalid"}, {"action": "inspect", "secret": "extra"},
    *[{"action": "switch", "candidate": name, "secret": "synthetic-only"}
      for name in ("", ".", "..", "../active", "/active", "a/b", "a\\b", "a\0b", "x" * 256, 4)],
    *[{"action": "switch", "candidate": "restored", "secret": secret}
      for secret in (None, "", "  ", "a\0b", "x" * 8193)],
    {"action": "finalize", "operation_id": "invalid", "secret": "synthetic-only"},
    {"action": "finalize", "operation_id": str(uuid4())},
])
def test_invalid_requests_cannot_choose_paths_or_extra_actions(payload):
    with pytest.raises((ValueError, TypeError)):
        decode_request(json.dumps(payload).encode())


@pytest.mark.parametrize("data", [b'{"action":"rollback","action":"switch"}', b"x" * 16385])
def test_duplicate_keys_and_oversized_messages(data):
    with pytest.raises(ValueError):
        decode_request(data)


def test_preloaded_runtime_refuses_without_echoing_input(capsys):
    assert run(lambda: pytest.fail("must not sanitize or access a profile")) == 1
    assert json.loads(capsys.readouterr().out) == {"ok": False, "code": "activation_control_refused"}
