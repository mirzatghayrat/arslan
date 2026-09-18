import json
import os
from uuid import uuid4

import pytest

from server.activation_trial_entry import decode_request, read_request, run


def valid():
    return {"operation_id": str(uuid4()), "access_token": "ab" * 32, "secret": "synthetic-only"}


@pytest.mark.parametrize("problem", ["extra", "missing", "uuid", "token", "blank", "huge", "duplicate"])
def test_invalid_control_request_is_refused(problem):
    value = valid()
    if problem == "extra":
        value["active_path"] = "/must-not-be-accepted"
    elif problem == "missing":
        del value["secret"]
    elif problem == "uuid":
        value["operation_id"] = "invalid"
    elif problem == "token":
        value["access_token"] = "short"
    elif problem == "blank":
        value["secret"] = "  "
    elif problem == "huge":
        value["secret"] = "x" * 20_000
    data = json.dumps(value).encode()
    if problem == "duplicate":
        data = data[:-1] + b', "secret":"duplicate"}'
    with pytest.raises(ValueError):
        decode_request(data)


@pytest.mark.parametrize("mode", ["valid", "eof", "partial", "trailing"])
def test_pipe_read_is_bounded_and_requires_one_complete_message(mode):
    read, write = os.pipe()
    value = valid()
    try:
        if mode == "eof":
            os.close(write)
            write = None
        else:
            message = json.dumps(value).encode()
            if mode != "partial":
                message += b"\n"
            if mode == "trailing":
                message += b"unexpected"
            os.write(write, message)
        if mode == "valid":
            assert read_request(read, timeout=0.05) == value
        else:
            with pytest.raises(ValueError):
                read_request(read, timeout=0.05)
    finally:
        os.close(read)
        if write is not None:
            os.close(write)


def test_preloaded_runtime_is_refused_without_echoing_secret(capsys):
    # The main test runtime already loaded config; production requires a fresh child.
    assert run(lambda: pytest.fail("must not alter environment")) == 1
    assert capsys.readouterr().out == "ARSLAN_ERROR=activation_trial_refused\n"
