from server.services import command_policy as cp


def test_is_network_command():
    assert cp.is_network_command("gh", ["pr", "view"]) is True
    assert cp.is_network_command("git", ["push"]) is True
    assert cp.is_network_command("git", ["clone", "https://x"]) is True
    assert cp.is_network_command("git", ["status"]) is False
    assert cp.is_network_command("git", ["commit", "-m", "x"]) is False
    assert cp.is_network_command("ffmpeg", ["-i", "a.mp4"]) is False
    assert cp.is_network_command("pandoc", ["a.md"]) is False
