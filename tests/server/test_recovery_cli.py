import json
import sqlite3

import pytest

from server.services import backup, recovery_cli


def archive(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    with sqlite3.connect(source / "arslan.db") as db:
        db.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
    path = tmp_path / "backup.zip"
    backup.create(source, path)
    return path


def test_new_machine_restores_without_boot_or_secret(tmp_path, capsys, monkeypatch):
    path = archive(tmp_path)
    destination = tmp_path / "restored"
    monkeypatch.setenv("ARSLAN_SECRET_KEY", "synthetic-not-used")
    assert recovery_cli.main(["--archive", str(path), "--new-data-dir", str(destination),
                              "--new-machine"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True
    assert result["result"]["deletion_record_selection"]["selected_source"] == "none"
    assert (destination / "arslan.db").is_file()
    assert not (destination / "api_token").exists()


@pytest.mark.parametrize("extra", [[], ["--new-machine", "--current-db-path", "current.db"],
                                   ["--new-machine", "--unknown"]])
def test_requires_explicit_unambiguous_mode(tmp_path, extra):
    target = tmp_path / "absent"
    with pytest.raises(SystemExit) as error:
        recovery_cli.main(["--archive", "missing", "--new-data-dir", str(target), *extra])
    assert error.value.code == 2
    assert not target.exists()


@pytest.mark.parametrize("error", [ValueError("private payload"), OSError("private path"),
                                  RuntimeError("private credential"), ValueError("data_profile_in_use")])
def test_errors_are_bounded_and_never_include_private_details(tmp_path, monkeypatch, capsys, error):
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(backup, "restore", fail)
    assert recovery_cli.main(["--archive", "missing", "--new-data-dir", str(tmp_path / "new"),
                              "--new-machine"]) == 1
    output = capsys.readouterr()
    assert json.loads(output.out) == {"ok": False, "code": (
        "data_profile_in_use" if str(error) == "data_profile_in_use" else "restore_refused")}
    assert not output.err


def test_existing_destination_is_preserved(tmp_path, capsys):
    path = archive(tmp_path)
    destination = tmp_path / "existing"
    destination.mkdir()
    inode = destination.stat().st_ino
    assert recovery_cli.main(["--archive", str(path), "--new-data-dir", str(destination),
                              "--new-machine"]) == 1
    assert json.loads(capsys.readouterr().out) == {"ok": False, "code": "restore_refused"}
    assert destination.stat().st_ino == inode and not list(destination.iterdir())
