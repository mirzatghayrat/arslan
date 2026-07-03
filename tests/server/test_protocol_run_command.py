from server.ws import protocol


def test_propose_run_command_shape():
    f = protocol.propose_run_command("c1", "git", ["status"], "check repo")
    assert f["type"] == "propose_run_command"
    assert f["call_id"] == "c1"
    assert f["command"] == "git"
    assert f["argv"] == ["status"]
    assert f["pretty"] == "git status"
    assert f["reason"] == "check repo"


def test_propose_run_command_default_reason():
    f = protocol.propose_run_command("c2", "gh", ["pr", "list"])
    assert f["reason"] == ""
    assert f["pretty"] == "gh pr list"
