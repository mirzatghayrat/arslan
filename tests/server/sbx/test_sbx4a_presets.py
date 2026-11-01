"""SBX-4a (v0.1.64): run_python, the artifact checks and installed MCP servers on the shared default-deny base.

- Each preset is `sandbox_profile.default_deny_profile` with its own parameters, then its own rules after it
  (the last rule wins). The base's fixed block is byte-identical in every preset (the card's acceptance).
- Computation keeps today's narrow reads and runs only its own interpreter; MCP drops its wholesale
  `mach-lookup` and shared-memory grants, and reaches the network only when it declared it (any-declared).

Whether what should be denied is denied under real seatbelt is SBX-4p's (Codex).
"""
import re
import sys
from pathlib import Path

import pytest

from server.services import capability_sandbox, code_sandbox, command_sandbox
from server.services.sandbox_profile import NetworkMode, default_deny_profile

macos = pytest.mark.skipif(sys.platform != "darwin", reason="seatbelt is macOS-only")

#: The base's rules that no parameter changes, in its order.
FIXED = ["(version 1)", "(deny default)", "(allow process-exec process-fork)", "(allow signal (target same-sandbox))",
         "(allow process-info* (target self))", "(allow sysctl-read)", "(allow user-preference-read)",
         "(allow pseudo-tty)", "(deny network-bind network-inbound)", "(deny appleevent-send)",
         "(deny user-preference-write)"]


def _block(text: str) -> list[str]:
    return [line for line in text.splitlines() if line in FIXED]


@pytest.fixture
def home(monkeypatch, tmp_path):
    home = tmp_path / "home"
    (home / "ws").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: home)
    return home


def _presets(home):
    work = home / "ws"
    return {
        "run-python": code_sandbox.computation_profile(sys.executable, work, work / "refs"),
        "artifact": code_sandbox.computation_profile(sys.executable, work),
        "mcp": capability_sandbox.profile(root=home / "srv", folders=[str(home / "grant")], network=False, read=[]),
        "mcp-online": capability_sandbox.profile(root=home / "srv", folders=[], network=True, read=[]),
    }


def test_the_base_block_is_byte_identical_in_every_preset(home):
    base = _block(default_deny_profile())
    assert base == FIXED
    for name, text in _presets(home).items():
        assert _block(text) == base, name
        assert text.startswith("(version 1)\n(deny default)\n(allow process-exec process-fork)\n"), name


_PARAMETERISED = ("(allow file-read* file-write-data ", "(allow file-ioctl ", "(allow mach-lookup ",
                  "(allow network-outbound ", "(deny network")


def test_the_bases_parameterised_lines_match_too(home):
    """#666 review: the device, ioctl, service and network lines the base writes for a preset's mode appear in
    the preset exactly and in the base's order (a preset closes what it doesn't need after them)."""
    modes = {"run-python": NetworkMode.NONE, "artifact": NetworkMode.NONE, "mcp": NetworkMode.NONE,
             "mcp-online": NetworkMode.ANY_DECLARED}
    for name, text in _presets(home).items():
        base = [line for line in default_deny_profile(network=modes[name]).splitlines()
                if line.startswith(_PARAMETERISED)]
        assert base and [line for line in text.splitlines() if line in base] == base, name


def test_computation_and_mcp_close_the_terminal_the_base_opens(home):
    for name, text in _presets(home).items():
        tail = text.split("(deny user-preference-write)", 1)[1]
        assert "(deny pseudo-tty)" in tail, name
        assert '(literal "/dev/tty") (literal "/dev/ptmx")' in tail.split("(deny file-ioctl", 1)[1], name
    python = _presets(home)["run-python"]
    assert '(deny mach-lookup (global-name "com.apple.FSEvents"))' in python
    assert "(deny user-preference-read)" in python and "(deny file-map-executable (subpath " in python


def test_no_preset_has_a_wholesale_grant(home):
    for name, text in _presets(home).items():
        assert "(allow default)" not in text, name
        assert not re.search(r"\(allow mach-lookup\)", text), name
        assert "(allow ipc-posix-shm" not in text, name        # no IPC prefix: no POSIX IPC
        assert "(allow network* system-socket)" not in text, name
        assert "user-preference-write" not in text.replace("(deny user-preference-write)", ""), name


def test_computation_starts_with_the_base_and_keeps_its_narrow_rules(home):
    work = home / "ws"
    text = code_sandbox.computation_profile(sys.executable, work, work / "refs")
    assert "(deny network*)" in text and "(allow file-read* file-map-executable)\n" not in text   # reads narrow
    exe = Path(sys.executable).absolute()
    lines = text.splitlines()
    after = lines[lines.index("(deny process-exec)") + 1:]          # only its own interpreter runs
    assert f'(allow process-exec (literal "{exe}"))' in after
    assert f'(deny file-write* (subpath "{(work / "refs").resolve()}"))' in after
    assert '(allow file-read-data (literal "/"))' in text


def test_mcp_closes_the_protected_paths_after_its_grants_and_reopens_its_own_folder(home, monkeypatch):
    data = home / "data"
    monkeypatch.setattr(command_sandbox, "default_protected", lambda: [data])
    root, grant, runtime = data / "caps" / "x", home / "grant", data / "runtimes" / "py"
    text = capability_sandbox.profile(root=root, folders=[str(grant)], network=True, read=[str(runtime)])
    lines = text.splitlines()
    protected = lines.index(f'(deny file-read* file-write* file-map-executable (subpath "{data.resolve()}"))')
    assert f'(allow file-read* file-map-executable (subpath "{runtime.resolve()}"))' in lines[protected:]
    assert f'(allow file-read* file-write* file-map-executable (subpath "{root.resolve()}"))' in lines[protected:]
    assert '(allow network-outbound (remote tcp "*:*"))' in text                       # declared: any-declared
    off = capability_sandbox.profile(root=root, folders=[], network=False, read=[])
    assert "(deny network*)" in off and '"*:*"' not in off


def test_the_sbx_harness_registers_the_three_presets():
    from tests.server.sbx.harness import BUILT_BASES, Harness
    for base in ("run-python", "artifact", "mcp"):
        assert BUILT_BASES[base] is not Harness._measurement_profile, base


@pytest.mark.parametrize("mode", [NetworkMode.PROXY, NetworkMode.PORT_22])
def test_the_harness_refuses_an_mcp_mode_the_product_lacks(tmp_path, mode):
    """MCP has none and any-declared only, until the SBX-6 MCP proxy PR: no quiet mapping to any-declared."""
    from tests.server.sbx.harness import Harness
    with pytest.raises(ValueError, match="SBX-6 MCP proxy"):
        Harness(tmp_path, "mcp", mode).profile()


@pytest.mark.macos
@macos
def test_python_still_computes_and_an_mcp_server_still_starts(tmp_path):
    """What should run does run: numpy-free arithmetic under the computation preset, and a Python MCP
    stand-in that writes its own folder under the MCP preset."""
    import subprocess
    work = tmp_path / "ws"
    work.mkdir()
    out = subprocess.run(["/usr/bin/sandbox-exec", "-p", code_sandbox.computation_profile(sys.executable, work),
                          sys.executable, "-I", "-c", "import json, math; print(json.dumps(math.factorial(5)))"],
                         cwd=work, capture_output=True, text=True, timeout=30)
    assert out.returncode == 0 and out.stdout.strip() == "120", out.stderr
    root = tmp_path / "srv"
    (root / "home").mkdir(parents=True)
    text = capability_sandbox.profile(root=root, folders=[], network=False,
                                      read=[sys.prefix, sys.base_prefix])
    out = subprocess.run(["/usr/bin/sandbox-exec", "-p", text, sys.executable, "-I", "-c",
                          "import pathlib; pathlib.Path('own.txt').write_text('ok'); print('ok')"],
                         cwd=root / "home", capture_output=True, text=True, timeout=30)
    assert out.returncode == 0 and out.stdout.strip() == "ok", out.stderr
    assert (root / "home" / "own.txt").read_text() == "ok"
