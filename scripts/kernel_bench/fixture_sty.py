"""STY read test fixture: the small work folder the ten task prompts (11-20 in sty_prompts.json) act on.

Synthetic and deterministic: no real people, no personal data, the same bytes on every build. Every
file has a different size, so "sort by size" (prompt 14) has one right order. What a reply should say
is returned (FACTS), never written into the folder.

    python -m scripts.kernel_bench.fixture_sty <dir>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

NOTES = """# Weekly sync: search page redesign

Attendees: product lead, designer, two engineers, support lead.

## Discussion
- Support reported that users cannot find the filter button on small screens.
- The designer showed two layouts; the team preferred the one with filters on top.
- The engineers estimated the API change at three days.

## Decisions
1. Decision: ship the filters-on-top layout in the next release.
2. Decision: keep the old search endpoint for one more release, then remove it.
3. Decision: support writes the help article before launch.
"""

CONFIG = {"name": "search-service", "timeout": 10, "retries": 3, "log_level": "info"}

BROKEN = """settings = {"host": "localhost", "debug": False}


def connect(config):
    return f"{config['host']}:{config['port']}"


print(connect(settings))
"""

CSV = """item,amount,unit
paper,12,box
pens,30,pack
folders,7,box
tape,25,roll
labels,16,sheet
"""

TODO = """# To do

- [x] Draft the release notes
- [ ] Update the screenshots
- [x] Review the settings page
- [ ] Book the demo room
"""

README = """# Serach service
A small service that answers search queries for the demo app.

Run it with `python3 -m search_service`.
"""

TEXTS = {
    "draft.txt": "First draft of the onboarding email.\n",
    "log.txt": "build 41 ok\nbuild 42 ok\nbuild 43 failed: missing icon\nbuild 44 ok\n",
    "list.txt": "apples\nrice\n",
}

FILES = {
    "notes.md": NOTES,
    "config.json": json.dumps(CONFIG, indent=2) + "\n",
    "broken.py": BROKEN,
    "data.csv": CSV,
    "todo.md": TODO,
    "README.md": README,
    **TEXTS,
}

# What a correct reply contains; kept with the runner and the doc, not in the folder.
FACTS = {
    "decisions": 3,
    "timeout_before": 10,
    "broken_error": "KeyError: 'port'",
    "csv_rows": 5,
    "csv_columns": 3,
    "csv_column2_total": 90,
    "todo_done": ["Draft the release notes", "Review the settings page"],
    "readme_typo": ("Serach", "Search"),
    "txt_files": sorted(TEXTS),
}


def fixture(run: str) -> dict:
    """Write the folder into `run` (created if missing); return FACTS plus each file's size."""
    root = Path(run)
    root.mkdir(parents=True, exist_ok=True)
    for name, text in FILES.items():
        (root / name).write_text(text, encoding="utf-8")
    return {**FACTS, "sizes": {name: len(text.encode("utf-8")) for name, text in FILES.items()}}


if __name__ == "__main__":
    print(json.dumps(fixture(sys.argv[1]), ensure_ascii=False, indent=1))
