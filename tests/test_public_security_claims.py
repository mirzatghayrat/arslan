"""Keep preview-facing security claims aligned with the disabled broker."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name,disabled", [
    ("README.md", "remain disabled"),
    ("README.zh-CN.md", "仍保持禁用"),
    ("README.de.md", "deaktiviert"),
    ("README.es.md", "siguen desactivadas"),
    ("README.ja.md", "無効です"),
    ("README.tr.md", "devre dışıdır"),
])
def test_readme_discloses_broker_gate(name, disabled):
    text = (ROOT / name).read_text()
    safety = next(line for line in text.splitlines() if "icons/shield-check.svg" in line)
    assert disabled in safety
    assert "docs/companion/W11-security-boundary.md" in text
    assert 'src="docs/assets/safety.jpg"' not in text
