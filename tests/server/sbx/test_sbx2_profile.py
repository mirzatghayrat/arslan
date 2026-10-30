"""Portable checks for the unused SBX-2 preset and the corpus contract."""
from pathlib import Path
from types import SimpleNamespace
import tempfile

import pytest

from server.services.sandbox_profile import NetworkMode, default_deny_profile
from tests.server.sbx.harness import Harness


def test_default_deny_golden():
    expected = (Path(__file__).parent / "default-deny.sb").read_text()
    assert default_deny_profile() == expected


@pytest.mark.parametrize("mode", list(NetworkMode))
def test_network_is_explicit_and_services_never_wholesale(mode):
    text = default_deny_profile(network=mode, proxy_port=43210 if mode == NetworkMode.PROXY else None,
                                denied_ports=[43211, 43212])
    assert "(allow default)" not in text
    assert "(allow mach-lookup)" not in text
    assert "(allow network*)" not in text
    assert "(allow user-preference-write" not in text
    assert "(deny appleevent-send)" in text
    assert "(deny network-bind network-inbound)" in text
    assert "(allow network-bind" not in text
    if mode == NetworkMode.NONE:
        assert "(deny network*)" in text
        assert "(allow network" not in text
    else:
        assert '(deny network-outbound (remote tcp "localhost:43211"))' in text
        assert '(deny network-outbound (remote tcp "localhost:43212"))' in text


def test_protection_is_last_even_inside_a_grant(tmp_path):
    protected = tmp_path / "protected"
    protected.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(protected)
    text = default_deny_profile([tmp_path], [alias], readable=[tmp_path], closed=[tmp_path / "closed"])
    assert text.endswith(f'(deny network-outbound (subpath "{protected.resolve()}"))\n')
    assert text.index("(allow file-write*") < text.index("(deny file-read*")
    assert str(alias) not in text


def test_empty_read_list_does_not_open_all_reads():
    text = default_deny_profile(readable=[])
    assert "(allow file-read* file-map-executable)" not in text
    assert "(allow file-read-metadata)" in text


@pytest.mark.parametrize("parameters", [
    {"network": "typo"}, {"network": "proxy"}, {"proxy_port": 1234},
    {"denied_ports": [0]}, {"denied_ports": [65536]}, {"denied_ports": [True]},
    {"ipc_prefix": ""}, {"ipc_prefix": "/"}, {"ipc_prefix": '/arslan-.*"'},
])
def test_invalid_parameters_fail_closed(parameters):
    with pytest.raises(ValueError):
        default_deny_profile(**parameters)


def test_ipc_is_omitted_or_confined_to_the_run():
    assert "(allow ipc-" not in default_deny_profile()
    assert '(ipc-posix-name-prefix "/arslan-0123456789abcdef-")' in default_deny_profile(
        ipc_prefix="/arslan-0123456789abcdef-")


def test_harness_rejects_an_unknown_base(tmp_path):
    with pytest.raises(NotImplementedError):
        Harness(tmp_path, "future-surface").profile()


def test_harness_environment_has_no_ambient_credentials_or_config(tmp_path, monkeypatch):
    monkeypatch.setenv("SSH_AUTH_SOCK", "/never/inherit")
    monkeypatch.setenv("HTTP_PROXY", "http://never-inherit.invalid")
    h = Harness(tmp_path, "default-deny")
    assert "SSH_AUTH_SOCK" not in h.env and "HTTP_PROXY" not in h.env
    assert h.env["HOME"] == str(tmp_path.resolve() / "home")
    assert h.env["GIT_TERMINAL_PROMPT"] == "0"
    assert h.env["GIT_ASKPASS"] == "/usr/bin/false"
    assert h.env["ARSLAN_SECRET_KEY_FILE"] == ""


def test_legacy_profile_replaces_and_restores_cached_temp_root(tmp_path, monkeypatch):
    stale = str(tmp_path / "cached-host-temp")
    monkeypatch.setattr(tempfile, "tempdir", stale)
    h = Harness(tmp_path / "scratch", "legacy-commands")
    text = h.profile()
    assert f'(subpath "{h.temp}")' in text
    assert stale not in text
    assert tempfile.tempdir == stale


def test_sbx_fixture_rejects_a_missing_macos_marker(tmp_path):
    from tests.server.sbx.conftest import sbx

    request = SimpleNamespace(node=SimpleNamespace(get_closest_marker=lambda name: None))
    fixture = sbx.__wrapped__(tmp_path, request, lambda *args: None)
    with pytest.raises(pytest.fail.Exception, match="must carry the macos marker"):
        next(fixture)


def test_missing_tool_inside_shell_is_reported_before_execution(tmp_path, monkeypatch):
    from tests.server.sbx.corpus import test_sbx2_corpus as corpus

    h = Harness(tmp_path, "default-deny")
    case = corpus.shell("missing-wrapped-tool", "absent-sbx-tool --version",
                        requires=("absent-sbx-tool",))
    monkeypatch.setattr(corpus.shutil, "which",
                        lambda tool, path: "/bin/bash" if tool == "/bin/bash" else None)
    monkeypatch.setattr(h, "run", lambda *args, **kwargs: pytest.fail("missing tool was executed"))
    properties = {}
    corpus.test_compatibility_measurement(h, case, NetworkMode.NONE, properties.__setitem__)
    assert properties["outcome"] == "tool-unavailable"
    assert properties["missing_tools"] == "absent-sbx-tool"
