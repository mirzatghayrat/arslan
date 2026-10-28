"""SBX-1b (v0.1.64): paths are written as SBPL strings seatbelt actually decodes.

Until SBX-1b every profile wrote paths with `json.dumps`, which spells each non-ASCII character
`\\uXXXX`. sandbox-exec does not decode that, so a rule on a CJK- or accent-named path landed on a
path that does not exist: a deny on such a protected folder let its files be read, and an allow on
such a working folder refused its writes (②Main's review of #471, measured on macOS 26.6.2).
"""
import json
import re
import subprocess
import sys
import unicodedata

import pytest

from server.services import capability_sandbox, command_sandbox
from server.services.sandbox_profile import sbpl_string

macos = pytest.mark.skipif(sys.platform != "darwin" or not command_sandbox.available(),
                           reason="seatbelt is macOS-only")

# Names written as escapes, so each one's code points are explicit (NFC and NFD look the same).
CJK = "\u4fdd\u62a4"                                     # two CJK characters
ACCENTED = unicodedata.normalize("NFC", "\u00fcn\u00efcode")
EMOJI = "box-\U0001F4E6"
CONTROL = "ctl\x01x"
DELETE = "del\x7fx"


@pytest.fixture(autouse=True)
def fresh():
    command_sandbox._reset_for_tests()
    yield
    command_sandbox._reset_for_tests()


# ── the encoder ────────────────────────────────────────────────────────────────

def test_printable_ascii_is_written_exactly_as_before():
    """Every ASCII path keeps the bytes it had under json.dumps (SBX-1's goldens hold)."""
    for code in range(0x20, 0x7F):
        assert sbpl_string(chr(code)) == json.dumps(chr(code)), hex(code)
    for path in ("/Users/a/Library/Application Support/Arslan", 'q"uote', "back\\slash", 'a") (allow default) ("'):
        assert sbpl_string(path) == json.dumps(path)


def test_non_ascii_is_written_as_its_own_characters():
    for name in (CJK, ACCENTED, unicodedata.normalize("NFD", ACCENTED), EMOJI):
        assert sbpl_string("/w/" + name) == '"/w/' + name + '"'
        assert "\\u" not in sbpl_string(name)


def test_control_characters_are_hex_escapes():
    assert sbpl_string(CONTROL) == '"ctl\\x01x"'
    assert sbpl_string(DELETE) == '"del\\x7fx"'
    assert sbpl_string("a\tb\nc\rd") == '"a\\x09b\\x0ac\\x0dd"'


def test_a_name_still_cannot_add_rules():
    for name in ('/x") (allow default) (deny file-read* (subpath "\\', '\\"' + CJK + '")', '"\n(allow default)\n"'):
        written = sbpl_string(name)
        # Outside the quoted string nothing is left: the whole name is one string.
        assert re.fullmatch(r'"(?:\\.|[^"\\])*"', written), written


# ── what the kernel does with it (macOS) ───────────────────────────────────────

def _run(profile: str, *argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(["/usr/bin/sandbox-exec", "-p", profile, *argv], capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin"}, timeout=30)


@pytest.mark.macos
@macos
@pytest.mark.parametrize("name", ["plain", CJK, ACCENTED, EMOJI, CONTROL, DELETE],
                         ids=["ascii", "cjk", "accented", "emoji", "control", "delete"])
def test_a_protected_folder_or_file_is_closed_whatever_its_name(tmp_path, name):
    """A folder is written as a subpath and a file as a literal; both go through the encoder."""
    ws = tmp_path / "ws"
    secret = ws / name / "secret.txt"
    secret.parent.mkdir(parents=True)
    secret.write_text("hush")
    key = ws / f"{name}.key"
    key.write_text("hush")
    text = command_sandbox.profile([ws], [ws / name, key])
    for closed in (secret, key):
        run = _run(text, "/bin/cat", str(closed))
        assert run.returncode != 0 and "hush" not in run.stdout, (name, closed.name, run.stdout, run.stderr)
    # The control: the same command reads a file beside it.
    (ws / "open.txt").write_text("fine")
    assert _run(text, "/bin/cat", str(ws / "open.txt")).stdout == "fine"


@pytest.mark.macos
@macos
def test_a_rule_matches_whichever_unicode_normalization_the_folder_was_stored_in(tmp_path):
    stored = tmp_path / unicodedata.normalize("NFD", ACCENTED)
    stored.mkdir()
    (stored / "secret.txt").write_text("hush")
    given = tmp_path / unicodedata.normalize("NFC", ACCENTED)     # the same folder, spelt the other way
    text = command_sandbox.profile([tmp_path], [given])
    assert _run(text, "/bin/cat", str(stored / "secret.txt")).returncode != 0
    assert _run(text, "/bin/cat", str(given / "secret.txt")).returncode != 0


@pytest.mark.macos
@macos
def test_a_working_folder_with_a_cjk_name_is_writable(tmp_path):
    ws = tmp_path / CJK
    ws.mkdir()
    (tmp_path / "outside").mkdir()
    text = command_sandbox.profile([ws], [])
    made = _run(text, "/usr/bin/touch", str(ws / "new.txt"))
    assert made.returncode == 0 and (ws / "new.txt").exists(), made.stderr
    refused = _run(text, "/usr/bin/touch", str(tmp_path / "outside" / "new.txt"))
    assert refused.returncode != 0 and not (tmp_path / "outside" / "new.txt").exists()


@pytest.mark.macos
@macos
def test_an_mcp_grant_on_a_cjk_folder_is_readable(tmp_path, monkeypatch):
    monkeypatch.setattr(command_sandbox, "default_protected", lambda: [tmp_path / "secret"])
    grant, outside = tmp_path / CJK, tmp_path / "outside"
    for folder in (grant, outside):
        folder.mkdir()
        (folder / "in.txt").write_text("hi")
    text = capability_sandbox.profile(root=tmp_path / "root", folders=[str(grant)], network=False, read=[])
    assert _run(text, "/usr/bin/head", "-c", "2", str(grant / "in.txt")).stdout == "hi"
    assert _run(text, "/usr/bin/head", "-c", "2", str(outside / "in.txt")).returncode != 0
