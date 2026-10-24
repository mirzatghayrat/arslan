"""No test, and no review probe run through `scripts/dev/probe.sh`, can read the real secret file.

Incident 2026-10-24 (docs/incidents/2026-10-24-dev-secret-read.md): a review probe ran product code with
`.venv/bin/python` outside pytest, with the real HOME and an explicit ARSLAN_SECRET_KEY. The secret
bootstrap then read `~/.arslan/secret_key` to compare it with the explicit value (it logs only the path).
The suite itself was never exposed: its conftest pins ARSLAN_SECRET_KEY_FILE="" and a HOME of its own.
These pin both ways in: inside the suite, an open under the real `~/.arslan` fails whatever the code
under test does; outside it, the probe runner gives a script the suite's own protections.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests import real_data_dir_guard

ROOT = Path(__file__).resolve().parents[1]


def test_the_suite_reads_no_secret_file_and_has_a_home_of_its_own():
    assert os.environ.get("ARSLAN_SECRET_KEY_FILE") == ""
    assert Path.home().resolve() != real_data_dir_guard.REAL_HOME


def test_an_open_under_the_real_secret_folder_is_refused_whatever_the_code_does():
    """A name that does not exist: without the guard this is a FileNotFoundError, never a read of the key."""
    target = real_data_dir_guard.REAL_HOME / ".arslan" / "no-such-file-the-guard-test-opens"
    with pytest.raises(PermissionError, match="real secret folder"):
        target.read_text()
    with pytest.raises(PermissionError, match="real secret folder"):
        os.open(str(target), os.O_RDONLY)


def test_a_path_that_only_starts_like_it_is_not_refused(tmp_path):
    neighbour = tmp_path / "x"
    neighbour.write_text("ok")
    assert neighbour.read_text() == "ok"
    sibling = real_data_dir_guard.REAL_HOME / ".arslan-not-the-secret-folder" / "nothing"
    with pytest.raises(FileNotFoundError):
        sibling.read_text()


def test_the_probe_runner_gives_a_script_a_scratch_home_and_no_secret_file(tmp_path):
    script = tmp_path / "where.py"
    script.write_text(
        "import os\nfrom pathlib import Path\n"
        "print('HOME', Path.home())\n"
        "print('FILE', repr(os.environ.get('ARSLAN_SECRET_KEY_FILE')))\n"
        "print('DATA', os.environ.get('ARSLAN_DATA_DIR'))\n"
        "print('KEY', os.environ.get('ARSLAN_SECRET_KEY'))\n")
    scratch = tmp_path / "scratch"
    env = {k: v for k, v in os.environ.items() if not k.startswith("ARSLAN_")}
    env.update(HOME=str(real_data_dir_guard.REAL_HOME), PROBE_SCRATCH=str(scratch))
    out = subprocess.run(["bash", str(ROOT / "scripts/dev/probe.sh"), str(script)], cwd=ROOT, env=env,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    seen = dict(line.split(" ", 1) for line in out.stdout.splitlines() if " " in line)
    assert Path(seen["HOME"]).resolve().is_relative_to(scratch.resolve())
    assert seen["FILE"] == "''"                                  # set but empty: no secret file is ever read
    assert Path(seen["DATA"]).resolve().is_relative_to(scratch.resolve())
    assert seen["KEY"] and seen["KEY"] != "None"                 # a fake explicit key, never the real file


def test_the_probe_runner_refuses_a_scratch_folder_inside_the_real_home_secret_folder(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("ARSLAN_")}
    env.update(HOME=str(real_data_dir_guard.REAL_HOME),
               PROBE_SCRATCH=str(real_data_dir_guard.REAL_HOME / ".arslan" / "probe"))
    out = subprocess.run(["bash", str(ROOT / "scripts/dev/probe.sh"), "-c", "print(1)"], cwd=ROOT, env=env,
                         capture_output=True, text=True, timeout=60)
    assert out.returncode != 0 and "scratch" in out.stderr


def test_the_probe_runner_defaults_to_a_fresh_temporary_scratch():
    env = {k: v for k, v in os.environ.items() if not k.startswith("ARSLAN_") and k != "PROBE_SCRATCH"}
    env["HOME"] = str(real_data_dir_guard.REAL_HOME)
    out = subprocess.run(["bash", str(ROOT / "scripts/dev/probe.sh"), "-c",
                          "from pathlib import Path; print(Path.home())"], cwd=ROOT, env=env,
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert Path(out.stdout.strip()).resolve() != real_data_dir_guard.REAL_HOME
