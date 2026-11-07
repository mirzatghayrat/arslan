#!/usr/bin/env python3
"""A git merge driver for web/src/locales/??.json: merges key by key, so PRs that touch different keys never conflict.

Text merges conflicted on these six files in 20 of 415 merges of main (measured over 500 PRs, 2026-11-07), always all six at
once, and each time because the changed lines were near each other, not because two PRs changed one key. A key both sides
changed differently, or a file that doesn't parse, falls back to git's own text merge, with its usual conflict markers.

Git runs it as `merge_json_keys.py %O %A %B` (base, ours, theirs) and takes the result from %A. A clone without the setting
below merges these files as text, as it would with no driver. GitHub never runs custom drivers.

    git config merge.json-keys.driver "python3 scripts/dev/merge_json_keys.py %O %A %B"
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

MISSING = object()


class Clash(Exception):
    pass


def ordered(ours: dict, theirs: dict, kept: dict) -> dict:
    """In ours' order. A key only theirs has goes after the key it follows there, so a merge moves no line."""
    order = [key for key in ours if key in kept]
    previous = None
    for key in theirs:
        if key in kept and key not in order:
            order.insert(order.index(previous) + 1 if previous in order else 0, key)
        previous = key if key in order else previous
    return {key: kept[key] for key in order}


def merge(base: dict, ours: dict, theirs: dict) -> dict:
    kept = {}
    for key in {**ours, **theirs}:
        was, mine, other = base.get(key, MISSING), ours.get(key, MISSING), theirs.get(key, MISSING)
        if mine == other or was == other:
            value = mine
        elif was == mine:
            value = other
        elif isinstance(mine, dict) and isinstance(other, dict):
            value = merge(was if isinstance(was, dict) else {}, mine, other)
        else:
            raise Clash(key)
        if value is not MISSING:
            kept[key] = value
    return ordered(ours, theirs, kept)


def main(base: str, ours: str, theirs: str) -> int:
    try:
        merged = merge(*(json.loads(Path(path).read_text(encoding="utf-8")) for path in (base, ours, theirs)))
    except (Clash, ValueError):
        return subprocess.call(["git", "merge-file", ours, base, theirs])
    Path(ours).write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4]))
