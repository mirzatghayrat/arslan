"""Only the committed display locale crosses the sidecar/native boundary."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select

from server.db.models import Setting
from server.services import native_locale, settings_service


@pytest_asyncio.fixture
async def session(execution_db):
    async with execution_db() as session:
        yield session


@pytest.mark.parametrize("language", ["en", "zh", "ja", "es", "de", "fr"])
def test_hint_contains_only_normalized_locale(tmp_path, monkeypatch, language):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    native_locale.write_hint(language)
    path = tmp_path / native_locale.FILENAME
    assert path.read_text() == language + "\n"
    assert path.stat().st_mode & 0o777 == 0o600
    assert sorted(p.name for p in tmp_path.iterdir()) == [native_locale.FILENAME]


def test_hint_does_not_follow_target_symlink(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    outside = tmp_path / "untouched"
    outside.write_text("keep")
    (tmp_path / native_locale.FILENAME).symlink_to(outside)
    native_locale.write_hint("fr")
    assert outside.read_text() == "keep"
    assert not (tmp_path / native_locale.FILENAME).is_symlink()


def test_hint_failure_is_nonfatal_and_cleans_temporary_file(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    def refuse(*args):
        raise OSError("read-only")
    monkeypatch.setattr(native_locale.os, "replace", refuse)
    native_locale.write_hint("fr")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_failed_commit_does_not_publish_new_hint(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    native_locale.write_hint("de")
    async def fake_set(*args):
        pass
    class FailedSession:
        async def commit(self):
            raise RuntimeError("commit refused")
    monkeypatch.setattr(settings_service, "_set_raw", fake_set)
    with pytest.raises(RuntimeError, match="commit refused"):
        await settings_service.update_settings(FailedSession(), {"language": "fr"})
    assert (tmp_path / native_locale.FILENAME).read_text() == "de\n"


@pytest.mark.asyncio
async def test_cache_failure_does_not_undo_saved_language(session, tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    def refuse(*args, **kwargs):
        raise OSError("read-only")
    monkeypatch.setattr(native_locale.tempfile, "mkstemp", refuse)
    await settings_service.update_settings(session, {"language": "fr"})
    assert await session.scalar(select(Setting.value).where(Setting.key == "language")) == "fr"


@pytest.mark.asyncio
async def test_committed_setting_drives_hint_and_boot_repair(session, tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    await settings_service.update_settings(session, {"language": "ja"})
    assert await session.scalar(select(Setting.value).where(Setting.key == "language")) == "ja"
    path = tmp_path / native_locale.FILENAME
    assert path.read_text() == "ja\n"
    path.unlink()
    await native_locale.sync(session)
    assert path.read_text() == "ja\n"
    await settings_service.update_settings(session, {"language": "fr"})
    assert path.read_text() == "fr\n"


def test_native_catalog_has_exact_six_complete_locales():
    root = Path(__file__).resolve().parents[2]
    copy = json.loads((root / "desktop/src-tauri/native_messages.json").read_text())
    assert set(copy) == {"en", "zh", "ja", "es", "de", "fr"}
    for key in copy["en"]:
        assert len({row[key] for row in copy.values()}) == 6
    for row in copy.values():
        assert set(row) == set(copy["en"])
        assert all(value.strip() for value in row.values())
