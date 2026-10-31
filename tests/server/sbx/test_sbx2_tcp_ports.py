"""Keep the measured TCP allow pairs and their port exclusions intact."""
import ctypes as C
import re
import sys

import pytest

from server.services import sandbox_profile
from server.services.sandbox_profile import NetworkMode, default_deny_profile


# Includes the original dropped ports (49345, 59626), boundary ports, and the
# proxy denying its own port. M8 and the pre-fix wildcard grant must fail here.
PORTS = (1, 21, 23, 80, 443, 43210, 49345, 59626, 65535)
PROXY_PORT = 43210
MODES = (NetworkMode.PROXY, NetworkMode.PORT_22)


@pytest.mark.parametrize("mode", MODES)
def test_tcp_port_denies_follow_the_complete_allow_list(mode):
    options = {"network": mode}
    if mode == NetworkMode.PROXY:
        options["proxy_port"] = PROXY_PORT
    for ports in (PORTS, (22,), ()):
        if mode == NetworkMode.PORT_22 and 22 in ports:
            with pytest.raises(ValueError, match="port-22 cannot exclude port 22"):
                default_deny_profile(**options, denied_ports=ports)
            continue
        text = default_deny_profile(**options, denied_ports=ports)
        lines = [line.strip() for line in text.splitlines()]
        # Select every network grant, regardless of filters or operation spelling.
        # A future Unix-socket grant must explicitly update this reviewed list too.
        allows = [(i, line) for i, line in enumerate(lines)
                  if re.match(r"\(allow\b.*\bnetwork", line)]
        destination = f"localhost:{PROXY_PORT}" if mode == NetworkMode.PROXY else "*:22"
        assert [line for _, line in allows] == [
            '(allow network-outbound (remote tcp "localhost:*"))',
            f'(allow network-outbound (remote tcp "{destination}"))',
        ], "complete network allow list changed"
        denies = [(i, line) for i, line in enumerate(lines)
                  if re.match(r"\(deny\s+network-outbound\s+\(remote\s+tcp\b", line)]
        assert [line for _, line in denies] == [
            f'(deny network-outbound (remote tcp "localhost:{port}"))'
            for port in sorted(set(ports))
        ], "requested TCP port deny missing or changed"
        assert all(i > allows[-1][0] for i, _ in denies), "TCP denies must follow all network allows"


@pytest.mark.parametrize("ports", [(22,), (443, 22)])
def test_port_22_exclusion_fails_before_rules_are_generated(ports, monkeypatch):
    monkeypatch.setattr(sandbox_profile, "Profile", lambda *args: pytest.fail("rules generated"))
    with pytest.raises(ValueError, match="port-22 cannot exclude port 22"):
        default_deny_profile(network="port-22", denied_ports=iter(ports))


def _compile_profile(text):
    # ABI declarations (facts only): chromium/src/sandbox/mac/seatbelt.cc,
    # https://chromium.googlesource.com/chromium/src/sandbox/+/refs/heads/main/mac/seatbelt.cc
    class CompiledProfile(C.Structure):
        _fields_ = [("builtin", C.c_char_p), ("data", C.c_void_p), ("size", C.c_size_t)]

    lib = C.CDLL("/usr/lib/libsandbox.dylib")
    lib.sandbox_compile_string.argtypes = [C.c_char_p, C.c_void_p, C.POINTER(C.c_void_p)]
    lib.sandbox_compile_string.restype = C.POINTER(CompiledProfile)
    lib.sandbox_free_profile.argtypes = [C.POINTER(CompiledProfile)]
    lib.sandbox_free_profile.restype = None
    lib.sandbox_free_error.argtypes = [C.c_void_p]
    lib.sandbox_free_error.restype = None
    error = C.c_void_p()
    profile = lib.sandbox_compile_string(text.encode(), None, C.byref(error))
    try:
        assert profile, C.string_at(error).decode() if error.value else "Seatbelt compilation failed"
        return C.string_at(profile.contents.data, profile.contents.size)
    finally:
        if profile:
            lib.sandbox_free_profile(profile)
        if error.value:
            lib.sandbox_free_error(error)


@pytest.mark.macos
@pytest.mark.skipif(sys.platform != "darwin", reason="macOS seatbelt compiler")
@pytest.mark.parametrize("mode", MODES)
def test_tcp_port_denies_survive_compilation(mode):
    options = {"network": mode}
    if mode == NetworkMode.PROXY:
        options["proxy_port"] = PROXY_PORT
    text = default_deny_profile(**options)
    baseline = _compile_profile(text)
    assert baseline == _compile_profile(text), "compiler output is not deterministic"
    # About 1,000 ports per mode, retaining every known regression port.
    ports = sorted(set(PORTS) | set(range(1, 65536, 65)) | ({22} if mode == NetworkMode.PROXY else set()))
    for port in ports:
        denied = _compile_profile(default_deny_profile(**options, denied_ports=[port]))
        assert denied != baseline, f"{mode.value} compiler dropped deny for port {port}"
