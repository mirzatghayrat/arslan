"""A5 (v0.1.63): the third-party notices ship inside the app, beside Arslan's own licence.

A notice that stays in the repository is not one a user of the app can read. tauri.conf.json's bundle resources
copy both files into Arslan.app/Contents/Resources (a map entry's source is relative to desktop/src-tauri, and its
target is the value), and packaging/fresh_install_check.py checks them in a built app."""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TAURI = ROOT / "desktop" / "src-tauri"


def _resources() -> dict[str, str]:
    return json.loads((TAURI / "tauri.conf.json").read_text())["bundle"]["resources"]


@pytest.mark.parametrize("name", ["THIRD_PARTY_NOTICES.md", "LICENSE"])
def test_the_app_bundles_the_file_at_the_top_of_its_resources(name):
    sources = [src for src, target in _resources().items() if target == name]
    assert len(sources) == 1, f"{name} is not in tauri.conf.json's bundle resources"
    assert (TAURI / sources[0]).resolve() == ROOT / name     # the repository's own file, not a copy beside it


def test_every_resource_the_app_bundles_from_the_repository_exists():
    # binaries/ is staged by the build (the sidecar, listen, Hands); everything else must be in the checkout
    missing = [src for src in _resources() if not src.startswith("binaries/") and not (TAURI / src).exists()]
    assert missing == []


def test_the_notices_name_what_ships_and_carry_the_licence_texts():
    text = (ROOT / "THIRD_PARTY_NOTICES.md").read_text()
    for credit in ("anthropics/skills", "Copyright 2026 Anthropic, PBC.", "NousResearch/hermes-agent",
                   "Copyright (c) 2025 Nous Research", "lahfir/agent-desktop", "msitarzewski/agency-agents"):
        assert credit in text, credit
    assert "Permission is hereby granted, free of charge" in text                 # the MIT text it points to
    assert "above (obra/superpowers)" not in text                                 # a section C9 removed
    assert (ROOT / "arslan/skills/bundled/skill-creator/LICENSE.txt").is_file()  # Apache-2.0 beside the adapted skill


@pytest.fixture
def probe():
    packaging = str(ROOT / "packaging")
    sys.path.insert(0, packaging)
    try:
        yield importlib.import_module("fresh_install_check")
    finally:
        sys.path.remove(packaging)


def test_the_install_check_passes_a_bundle_with_the_files_and_fails_one_without(probe, tmp_path):
    app = tmp_path / "Arslan.app"
    resources = app / "Contents" / "Resources"
    resources.mkdir(parents=True)
    empty = probe.Checks()
    probe.check_notices(app, empty)
    assert len(empty.failures) == 2 and not empty.passes
    for name in ("THIRD_PARTY_NOTICES.md", "LICENSE"):
        (resources / name).write_bytes((ROOT / name).read_bytes())
    shipped = probe.Checks()
    probe.check_notices(app, shipped)
    assert shipped.failures == [] and len(shipped.passes) == 2
    (resources / "LICENSE").write_text("not the licence")
    stale = probe.Checks()
    probe.check_notices(app, stale)
    assert len(stale.failures) == 1 and "LICENSE" in stale.failures[0]
