"""Portable checks for the unused SBX-2 preset and the corpus contract."""
from pathlib import Path

import pytest

from server.services.sandbox_profile import NetworkMode, default_deny_profile
from tests.server.sbx.harness import Harness, base_parameter


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


def test_harness_uses_explicit_bases_and_strict_future_gate(tmp_path):
    assert not base_parameter("default-deny").marks
    pending = base_parameter("future-surface").marks[0]
    assert pending.name == "xfail" and pending.kwargs["strict"] is True
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
