"""SBX-1 (v0.1.64): the SBPL builder every seatbelt profile is written with (`sandbox_profile`)."""
import json
import os
import re

from server.services.sandbox_profile import Profile, file_or_folder, literal, real, remote_tcp, subpath


def test_a_profile_starts_with_its_version_and_default():
    assert Profile("deny").text() == "(version 1)\n(deny default)\n"
    assert Profile("allow").text() == "(version 1)\n(allow default)\n"


def test_rules_come_out_in_the_order_they_are_added():
    # Seatbelt applies the last matching rule, so this order is the policy.
    rules = Profile("allow")
    rules.deny("file-write*", subpath("/"))
    rules.allow("file-write*", subpath("/w"), literal("/f"))
    rules.deny("network-outbound", subpath("/w/s"))
    rules.allow("process-info*", "(target self)")
    assert rules.text().splitlines()[2:] == [
        '(deny file-write* (subpath "/"))',
        '(allow file-write* (subpath "/w") (literal "/f"))',
        '(deny network-outbound (subpath "/w/s"))',
        "(allow process-info* (target self))",
    ]


def test_no_paths_open_nothing():
    """A rule without a filter matches everything: `(allow file-read*)` would open every file."""
    rules = Profile("deny")
    rules.allow_paths("file-read*", [])
    rules.allow_paths("file-read*", (p for p in ()), literal)
    assert rules.text() == "(version 1)\n(deny default)\n"
    rules.allow_paths("file-read*", ["/a", "/b"])
    rules.allow_paths("file-write*", ["/a/c"], literal)
    assert rules.text().splitlines()[2:] == ['(allow file-read* (subpath "/a") (subpath "/b"))',
                                             '(allow file-write* (literal "/a/c"))']


def test_a_deny_over_no_paths_denies_everything():
    # The protected lists are never empty today; if one were, its deny would fail closed, as on main.
    rules = Profile("allow")
    rules.deny("file-read* file-write*")
    assert rules.text().splitlines()[2:] == ["(deny file-read* file-write*)"]


def test_a_path_is_one_json_string_so_its_name_cannot_add_rules():
    name = '/x") (allow default) (deny file-read* (subpath "\\'
    for kind in (subpath, literal):
        written = kind(name)
        assert written.endswith(json.dumps(name) + ")")
        # Outside the quoted string nothing is left but the filter's own name.
        assert re.sub(r'"(?:\\.|[^"\\])*"', '""', written) in ('(subpath "")', '(literal "")')


def test_a_file_is_a_literal_and_a_folder_or_a_missing_path_a_subpath(tmp_path):
    (tmp_path / "f").write_text("x")
    assert file_or_folder(tmp_path / "f") == literal(tmp_path / "f")
    assert file_or_folder(tmp_path) == subpath(tmp_path)
    assert file_or_folder(tmp_path / "not-yet") == subpath(tmp_path / "not-yet")


def test_real_resolves_links_and_the_home_folder(tmp_path):
    (tmp_path / "target").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "target")
    assert real(tmp_path / "link") == real(tmp_path / "target") == real(os.path.realpath(tmp_path / "target"))
    assert real("~/x") == real(os.path.join(os.path.expanduser("~"), "x"))


def test_a_remote_tcp_destination_names_a_port():
    assert remote_tcp("*", 22) == '(remote tcp "*:22")'
    assert remote_tcp("localhost", 8080) == '(remote tcp "localhost:8080")'
