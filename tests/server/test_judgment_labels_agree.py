"""Every decision point the judge can record has a name where judgments show (0.1.56 §12): a point added on the server without
a label showed its raw id. Since INB7-c4c (v0.1.64) the labels live in web/src/lib/judgments.ts, for a run's 「诊断」."""
import re
from pathlib import Path

from server.services import judgment

WEB = Path(__file__).resolve().parents[2] / "web" / "src"


def test_every_judgment_point_has_a_label_in_every_language():
    card = (WEB / "lib" / "judgments.ts").read_text()
    labels = dict(re.findall(r'"([a-z_.]+)":\s*"activityPage\.(\w+)"', card))
    recorded = {name for name, point in judgment.REGISTRY.items() if point.mode != "off"}
    assert recorded <= set(labels), recorded - set(labels)
    panel = (WEB / "locales" / "panel.ts").read_text()
    for key in labels.values():
        assert len(re.findall(rf'"{key}":\s*"[^"]+"', panel)) == 6, key
