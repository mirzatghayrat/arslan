"""Write web/src/locales/proactive-keys.json from the backend's key catalog.

The inbox shows text as KEYS that the UI translates. The backend's catalog
(`arslan.proactive_policy.TITLE_KEYS` / `EVIDENCE_KEYS`) is the source; this file
is the copy the frontend test reads to check that every key has words in all six
languages. `tests/test_proactive_policy.py` fails if the copy is stale.

    .venv/bin/python -m scripts.proactive_keys
"""
from __future__ import annotations

import json
from pathlib import Path

from arslan import proactive_policy as policy

PATH = Path(__file__).resolve().parent.parent / "web" / "src" / "locales" / "proactive-keys.json"


def catalog() -> dict:
    return {"title": sorted(policy.TITLE_KEYS), "evidence": sorted(policy.EVIDENCE_KEYS)}


def main() -> None:
    PATH.write_text(json.dumps(catalog(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {PATH}")


if __name__ == "__main__":
    main()
