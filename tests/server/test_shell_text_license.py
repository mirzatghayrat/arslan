"""S2b-1: shell_text.py is adapted from Hermes Agent (MIT). MIT asks that the copyright and permission
notice travel with substantial portions, so the notice is kept in THIRD_PARTY_NOTICES.md, where the
module points, and stays there when the vendored copy (and its LICENSE) is deleted in S2b-2."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_the_hermes_mit_notice_travels_with_shell_text():
    notices = ROOT.joinpath("THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    section = notices[notices.index("## Terminal command reading — `server/services/shell_text.py`"):]
    assert "Copyright (c) 2025 Nous Research" in section
    assert ("The above copyright notice and this permission notice shall be included in all\n"
            "copies or substantial portions of the Software.") in section
    assert 'THE SOFTWARE IS PROVIDED "AS IS"' in section
    header = ROOT.joinpath("server/services/shell_text.py").read_text(encoding="utf-8").split('"""')[1]
    assert "THIRD_PARTY_NOTICES.md" in header and "hermes-agent" in header
