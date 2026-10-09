"""0.1.58 §1: every tool Arslan can be offered has words in the reply's steps.

A tool without an entry in web/src/lib/toolWords.json would show its raw key — the
"whats_new ok · 完成" line the user asked to get rid of. The words themselves are checked
in six languages by web/src/__tests__/reply-0158.test.tsx; this checks the list is whole.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from server.registry.executors import EXECUTORS

ROOT = Path(__file__).resolve().parents[2]


def _offered() -> set[str]:
    keys = set(EXECUTORS)
    for rel in ("server/orchestrator/arslan.py", "server/orchestrator/tool_loop.py"):
        keys |= set(re.findall(r'"key": "([a-z_]+)"', (ROOT / rel).read_text()))
    return keys


def test_every_offered_tool_has_words():
    words = json.loads((ROOT / "web/src/lib/toolWords.json").read_text())
    missing = sorted(_offered() - set(words))
    assert not missing, f"tools without words in web/src/lib/toolWords.json: {missing}"


def test_no_words_for_tools_that_do_not_exist():
    words = {k for k in json.loads((ROOT / "web/src/lib/toolWords.json").read_text()) if not k.startswith("_")}
    assert words <= _offered(), sorted(words - _offered())
