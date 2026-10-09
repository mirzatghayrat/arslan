"""D2 (0.1.55): Arslan knows its own version and what changed."""
import json
from pathlib import Path

import pytest

from server import config
from server.services import release_notes

ROOT = Path(__file__).resolve().parents[2]


def test_the_packaged_version_wins(monkeypatch):
    monkeypatch.setenv("ARSLAN_APP_VERSION", "9.8.7")
    assert config._app_version() == "9.8.7"


def test_loaded_settings_carry_it_to_health_and_the_prompt(monkeypatch):
    monkeypatch.setenv("ARSLAN_APP_VERSION", "9.8.7")
    assert config.load_settings().app_version == "9.8.7"


def test_a_source_checkout_says_dev_after_the_last_release(monkeypatch):
    monkeypatch.delenv("ARSLAN_APP_VERSION", raising=False)
    shipped = json.loads((ROOT / "desktop/src-tauri/tauri.conf.json").read_text())["version"]
    assert config._app_version() == f"{shipped}-dev"
    assert config._app_version() != "0.1.0"


def test_recent_is_newest_first_and_never_ahead_of_the_running_version(tmp_path, monkeypatch):
    for name in ("v0.1.9.md", "v0.1.10.md", "v0.1.11.md", "v0.1.12.md", "v0.1.11-beta.1.md", "README.md"):
        (tmp_path / name).write_text(f"notes {name}")
    monkeypatch.setattr(release_notes, "_notes_dir", lambda: tmp_path)
    got = release_notes.recent(3, version="0.1.11")
    # numeric, not text, order: 0.1.10 sorts after 0.1.9; 0.1.12 is not shipped yet
    assert [r["version"] for r in got] == ["0.1.11", "0.1.10", "0.1.9"]
    assert got[0]["notes"] == "notes v0.1.11.md"
    assert [r["version"] for r in release_notes.recent(1, version="0.1.12-dev")] == ["0.1.12"]


def test_every_release_since_048_has_notes_in_the_repo():
    """The gap that made Arslan answer 0.1.48: v0.1.49–v0.1.52 had no notes here."""
    have = {p.name for p in (ROOT / "docs/releases").glob("v*.md")}
    shipped = json.loads((ROOT / "desktop/src-tauri/tauri.conf.json").read_text())["version"]
    base, _, pre = shipped.partition("-")
    last = int(base.split(".")[2])
    if pre:  # a pre-release (0.1.59-beta.1) has its own notes; the final version's come with it
        assert f"v{shipped}.md" in have
        last -= 1
    missing = [f"v0.1.{n}.md" for n in range(48, last + 1) if f"v0.1.{n}.md" not in have]
    assert missing == []


def test_the_notes_ship_in_the_app():
    spec = (ROOT / "packaging/arslan-server.spec").read_text()
    assert '"docs", "releases"), "server/resources/releases"' in spec


@pytest.mark.asyncio
async def test_whats_new_tool_answers_from_the_notes(monkeypatch, tmp_path):
    from server.registry.executors import EXECUTORS
    (tmp_path / "v1.2.3.md").write_text("## 1.2.3 — the thing")
    monkeypatch.setattr(release_notes, "_notes_dir", lambda: tmp_path)
    from dataclasses import replace
    monkeypatch.setattr(release_notes, "settings", replace(release_notes.settings, app_version="1.2.3"))
    out = await EXECUTORS["whats_new"].execute({})
    assert out["ok"] and out["version"] == "1.2.3"
    assert out["releases"][0]["notes"].startswith("## 1.2.3")


def test_the_prompt_names_the_running_version():
    from server.orchestrator import arslan
    assert f"You are Arslan {config.settings.app_version}." in arslan._ANSWER_STABLE_PREFIX
