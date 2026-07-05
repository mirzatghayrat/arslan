from server.services import command_policy as cp


def test_is_network_command():
    assert cp.is_network_command("gh", ["pr", "view"]) is True
    assert cp.is_network_command("git", ["push"]) is True
    assert cp.is_network_command("git", ["clone", "https://x"]) is True
    assert cp.is_network_command("git", ["status"]) is False
    assert cp.is_network_command("git", ["commit", "-m", "x"]) is False
    assert cp.is_network_command("ffmpeg", ["-i", "a.mp4"]) is False
    assert cp.is_network_command("pandoc", ["a.md"]) is False


def test_resolve_target_host():
    R = {"origin": "https://github.com/me/repo.git"}
    assert cp.resolve_target_host("gh", ["pr", "view"], repo_remotes={}) == "github.com"
    assert cp.resolve_target_host("git", ["clone", "https://github.com/a/b.git"], repo_remotes={}) == "github.com"
    assert cp.resolve_target_host("git", ["push", "origin", "main"], repo_remotes=R) == "github.com"
    assert cp.resolve_target_host("git", ["push"], repo_remotes=R) == "github.com"  # default origin
    assert cp.resolve_target_host("git", ["clone", "git@gitlab.com:a/b.git"], repo_remotes={}) == "gitlab.com"
    assert cp.resolve_target_host("git", ["fetch", "nope"], repo_remotes={}) is None


def test_is_host_allowed():
    assert cp.is_host_allowed("github.com", repo_remote_hosts=set()) is True
    assert cp.is_host_allowed("api.github.com", repo_remote_hosts=set()) is True
    assert cp.is_host_allowed("gitlab.com", repo_remote_hosts={"gitlab.com"}) is True
    assert cp.is_host_allowed("evil.com", repo_remote_hosts={"gitlab.com"}) is False
    assert cp.is_host_allowed(None, repo_remote_hosts=set()) is False
    assert cp.is_host_allowed("", repo_remote_hosts=set()) is False
