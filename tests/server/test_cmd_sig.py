from server.ws.arslan import _cmd_sig


def test_cmd_sig_distinguishes_git_subcommands():
    # The CRITICAL bug: these must NOT collide.
    assert _cmd_sig("git", ["status"]) != _cmd_sig("git", ["push"])
    assert _cmd_sig("git", ["status"]) != _cmd_sig("git", ["clean"])
    assert _cmd_sig("git", ["status"]) != _cmd_sig("git", ["reset", "--hard"])


def test_cmd_sig_same_subcommand_different_values_collapse():
    # Same subcommand + same flags, different free value → same shape (intended:
    # "remember git commit -m <anything>").
    assert _cmd_sig("git", ["commit", "-m", "a"]) == _cmd_sig("git", ["commit", "-m", "b"])
