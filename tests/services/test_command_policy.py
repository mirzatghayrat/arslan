from server.services import command_policy as cp


def test_allowed_binary_simple_argv_ok():
    r = cp.validate("git", ["status"])
    assert r["ok"] is True


def test_binary_not_in_whitelist_rejected():
    r = cp.validate("bash", ["-c", "echo hi"])
    assert r["ok"] is False
    assert "not allowed" in r["reason"]


def test_argv_must_be_list_not_string():
    r = cp.validate("git", "status")  # type: ignore[arg-type]
    assert r["ok"] is False
    assert "list" in r["reason"]


def test_shell_metachar_in_argv_rejected():
    for bad in ["a; rm -rf /", "a | sh", "a && b", "$(whoami)", "`id`", "a > /etc/x", "a & b"]:
        r = cp.validate("git", [bad])
        assert r["ok"] is False, bad
        assert "shell" in r["reason"] or "denied" in r["reason"]


def test_sudo_and_rm_rf_hard_denied():
    assert cp.validate("git", ["sudo", "x"])["ok"] is False
    assert cp.validate("git", ["rm", "-rf", "x"])["ok"] is False


def test_absolute_path_binary_arg_rejected():
    r = cp.validate("git", ["/bin/sh"])
    assert r["ok"] is False


def test_non_string_argv_element_rejected():
    r = cp.validate("git", ["status", 5])  # type: ignore[list-item]
    assert r["ok"] is False


def test_empty_command_rejected():
    assert cp.validate("", ["status"])["ok"] is False


def test_ffmpeg_pandoc_gh_whitelisted():
    assert cp.validate("ffmpeg", ["-version"])["ok"] is True
    assert cp.validate("pandoc", ["-v"])["ok"] is True
    assert cp.validate("gh", ["--version"])["ok"] is True


def test_classify_readonly_is_low():
    assert cp.classify("git", ["status"]) == "LOW"
    assert cp.classify("git", ["log", "--oneline"]) == "LOW"
    assert cp.classify("git", ["--version"]) == "LOW"
    assert cp.classify("ffmpeg", ["-version"]) == "LOW"
    assert cp.classify("pandoc", ["--help"]) == "LOW"


def test_classify_local_mutation_is_medium():
    assert cp.classify("git", ["commit", "-m", "x"]) == "MEDIUM"
    assert cp.classify("git", ["add", "."]) == "MEDIUM"
    assert cp.classify("pandoc", ["in.md", "-o", "out.html"]) == "MEDIUM"
    assert cp.classify("ffmpeg", ["-i", "a.mov", "b.mp4"]) == "MEDIUM"


def test_classify_network_is_high():
    assert cp.classify("git", ["push"]) == "HIGH"
    assert cp.classify("git", ["pull"]) == "HIGH"
    assert cp.classify("git", ["clone", "https://x"]) == "HIGH"
    assert cp.classify("gh", ["pr", "create"]) == "HIGH"


def test_classify_unknown_subcommand_defaults_high():
    assert cp.classify("git", ["some-unknown-subcmd"]) in ("MEDIUM", "HIGH")


def test_classify_verbose_flag_never_downgrades_risky_subcommand():
    # -v riding on a real operation must NOT masquerade as a version probe.
    assert cp.classify("git", ["push", "-v"]) == "HIGH"
    assert cp.classify("git", ["commit", "-v", "-m", "x"]) == "MEDIUM"
    assert cp.classify("git", ["add", "-v", "."]) == "MEDIUM"


def test_classify_bare_probe_is_low():
    assert cp.classify("git", ["--version"]) == "LOW"
    assert cp.classify("git", ["-v"]) == "LOW"
    assert cp.classify("ffmpeg", ["-version"]) == "LOW"
