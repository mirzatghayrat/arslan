"""No test, and no review probe run through `scripts/dev/probe.sh`, can read the real secret file.

Incident 2026-10-24 (docs/incidents/2026-10-24-dev-secret-read.md): a review probe ran product code with
`.venv/bin/python` outside pytest, with the real HOME and an explicit ARSLAN_SECRET_KEY. The secret
bootstrap then read `~/.arslan/secret_key` to compare it with the explicit value (it logs only the path).
The suite itself was never exposed: its conftest pins ARSLAN_SECRET_KEY_FILE="" and a HOME of its own.
These pin both ways in. Inside the suite, an open of the real `~/.arslan` is refused, and a refusal the code
under test swallows still fails the test. Outside it, the probe runner gives a script a clean start.

Nothing here touches the real `~/.arslan`: the probe runner is pointed at a fake home, and the hook's cases
run in a child pytest session whose home, and so whose "real" secret folder, is a temp folder.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests import real_data_dir_guard

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "scripts/dev/probe.sh"


def test_the_suite_reads_no_secret_file_and_has_a_home_of_its_own():
    assert os.environ.get("ARSLAN_SECRET_KEY_FILE") == ""
    assert Path.home().resolve() != real_data_dir_guard.REAL_HOME


def test_an_open_under_the_real_secret_folder_is_refused_and_recorded():
    """A name that does not exist: without the guard this is a FileNotFoundError, never a read of the key."""
    target = real_data_dir_guard.REAL_HOME / ".arslan" / "no-such-file-the-guard-test-opens"
    with pytest.raises(PermissionError, match="real secret folder"):
        target.read_text()
    with pytest.raises(PermissionError, match="real secret folder"):
        os.open(str(target), os.O_RDONLY)
    assert real_data_dir_guard.take_secret_refusals() == [str(target), str(target)]


def test_a_path_that_only_starts_like_it_is_not_refused(tmp_path):
    neighbour = tmp_path / "x"
    neighbour.write_text("ok")
    assert neighbour.read_text() == "ok"
    sibling = real_data_dir_guard.REAL_HOME / ".arslan-not-the-secret-folder" / "nothing"
    with pytest.raises(FileNotFoundError):
        sibling.read_text()
    assert real_data_dir_guard.take_secret_refusals() == []


# --- the hook, in a child session whose home is a temp folder -------------------------------------------------

def _child(tmp_path, source: str, home: Path):
    """A child pytest session with the root conftest loaded as a plugin, `home` as its HOME (so its real secret
    folder is `home/.arslan`), and no ARSLAN_* or PYTEST_* variable of this session."""
    test_file = tmp_path / "child" / "test_child.py"
    test_file.parent.mkdir(exist_ok=True)
    test_file.write_text(source)
    env = {key: value for key, value in os.environ.items() if not key.startswith(("ARSLAN_", "PYTEST_"))}
    env.update(HOME=str(home), ARSLAN_SECRET_KEY="ci-secret", ARSLAN_API_TOKEN="", ARSLAN_DATA_DIR="data")
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "tests.conftest",
         "-c", str(ROOT / "pyproject.toml"), "--rootdir", str(ROOT), "-rA", str(test_file)],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=110)


_SPELLINGS = '''
import os
from pathlib import Path

import pytest

from tests import real_data_dir_guard

HOME = real_data_dir_guard.REAL_HOME
OUTSIDE = Path(__OUTSIDE__)


@pytest.mark.parametrize("spelling", [
    "home/.arslan/secret_key",              # the folder is a link: the literal spelling
    "outside/secret_key",                   # where the link points: what the secret bootstrap opens
    "home/link-to-it/secret_key",           # another link into it
    "home/nope/../.arslan/secret_key",      # a ".." through a folder that does not exist
    "home/.arslan/",                        # the folder itself, trailing slash
])
def test_every_spelling_of_the_secret_folder_is_refused(spelling):
    path = spelling.replace("home/", str(HOME) + "/", 1).replace("outside/", str(OUTSIDE) + "/", 1)
    with pytest.raises(PermissionError, match="real secret folder"):
        os.open(path, os.O_RDONLY)
    assert len(real_data_dir_guard.take_secret_refusals()) == 1


def test_a_neighbour_outside_both_is_read():
    assert (OUTSIDE.parent / "neighbour.txt").read_text() == "fine"
    assert real_data_dir_guard.take_secret_refusals() == []
'''


_LETTER_CASE = '''
import sys

import pytest

from tests import real_data_dir_guard

HOME = real_data_dir_guard.REAL_HOME


def test_another_letter_case_is_the_same_folder_on_macos_and_another_folder_elsewhere():
    path = str(HOME) + "/.ARSLAN/secret_key"
    if sys.platform == "darwin":
        with pytest.raises(PermissionError, match="real secret folder"):
            open(path).close()
        assert len(real_data_dir_guard.take_secret_refusals()) == 1
    else:
        with pytest.raises(FileNotFoundError):
            open(path).close()
        assert real_data_dir_guard.take_secret_refusals() == []
'''


def test_another_letter_case_of_a_plain_secret_folder_is_refused_on_macos(tmp_path):
    """No link to resolve here: on macOS only the case fold catches it."""
    home = tmp_path / "home"
    (home / ".arslan").mkdir(parents=True)
    (home / ".arslan" / "secret_key").write_text("fake-value-for-the-test")
    proc = _child(tmp_path, _LETTER_CASE, home)
    assert proc.returncode == 0, proc.stdout[-4000:] + proc.stderr[-1500:]
    assert proc.stdout.count("PASSED") == 1, proc.stdout[-4000:]


def test_links_and_dots_do_not_get_past_the_hook(tmp_path):
    home, outside = tmp_path / "home", tmp_path / "elsewhere" / "secrets"
    home.mkdir()
    outside.mkdir(parents=True)
    (outside / "secret_key").write_text("fake-value-for-the-test")
    (outside.parent / "neighbour.txt").write_text("fine")
    (home / ".arslan").symlink_to(outside, target_is_directory=True)
    (home / "link-to-it").symlink_to(home / ".arslan", target_is_directory=True)
    proc = _child(tmp_path, _SPELLINGS.replace("__OUTSIDE__", repr(str(outside))), home)
    assert proc.returncode == 0, proc.stdout[-4000:] + proc.stderr[-1500:]
    assert proc.stdout.count("PASSED") == 6, proc.stdout[-4000:]


_SWALLOWED = '''
import logging

from server import secret_bootstrap
from tests import real_data_dir_guard


def test_code_that_swallows_the_refusal():
    """The secret bootstrap's own read: it catches OSError, so the test sees nothing."""
    path = real_data_dir_guard.REAL_HOME / ".arslan" / "secret_key"
    secret_bootstrap._warn_on_mismatch(path, "an-explicit-fake-key", log=logging.getLogger("child"))
'''


def test_a_refusal_the_code_swallows_still_fails_the_test(tmp_path):
    home = tmp_path / "home"
    (home / ".arslan").mkdir(parents=True)
    (home / ".arslan" / "secret_key").write_text("fake-value-for-the-test")
    proc = _child(tmp_path, _SWALLOWED, home)
    assert proc.returncode == 1, proc.stdout[-4000:] + proc.stderr[-1500:]
    assert "refused an open of the real secret folder" in proc.stdout, proc.stdout[-4000:]
    assert str(home / ".arslan" / "secret_key") in proc.stdout


# --- the probe runner, against a fake home -----------------------------------------------------------------

def _probe(*args: str, home: Path, scratch: str | None = None, extra: dict[str, str] | None = None):
    env = {key: value for key, value in os.environ.items() if key != "PROBE_SCRATCH"}
    env["HOME"] = str(home)
    if scratch is not None:
        env["PROBE_SCRATCH"] = scratch
    env.update(extra or {})
    return subprocess.run(["bash", str(PROBE), *args], cwd=ROOT, env=env, capture_output=True, text=True,
                          timeout=120)


def _tree(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*")}


@pytest.mark.parametrize("scratch", [
    pytest.param("{home}/.arslan/probe", id="secret-folder-not-there-yet"),
    pytest.param("{home}/.arslan/a/b/probe", id="a-missing-middle-folder"),
    pytest.param("{home}/nope/../.arslan/probe", id="a-dot-dot-through-a-missing-folder"),
    pytest.param("{home}/link/probe", id="a-link-to-the-secret-folder"),
    pytest.param("{home}/elsewhere-secrets/probe", id="where-a-linked-secret-folder-points"),
    pytest.param("{home}/.ARSLAN/probe", id="another-letter-case"),
    pytest.param("{home}", id="the-home-itself"),
    pytest.param("{home}/", id="the-home-with-a-trailing-slash"),
])
@pytest.mark.parametrize("linked", [False, True], ids=["plain-home", "secret-folder-is-a-link"])
def test_the_probe_runner_refuses_the_real_home_and_its_secret_folder_however_spelt(tmp_path, scratch, linked):
    home = tmp_path / "home"
    home.mkdir()
    if linked:
        (home / "elsewhere-secrets").mkdir()
        (home / ".arslan").symlink_to(home / "elsewhere-secrets", target_is_directory=True)
    (home / "link").symlink_to(home / ".arslan", target_is_directory=True)   # dangling while .arslan is not there
    before = _tree(home)
    for home_spelling in (str(home), str(home) + "/"):
        out = _probe("-c", "print('ran')", home=Path(home_spelling), scratch=scratch.format(home=home))
        if not linked and "elsewhere-secrets" in scratch:
            assert out.returncode == 0, out.stderr                       # a plain folder of that name is fine
            continue
        assert out.returncode == 2 and "scratch folder" in out.stderr, (out.returncode, out.stderr)
        assert "ran" not in out.stdout
    if linked or "elsewhere-secrets" not in scratch:
        assert _tree(home) == before                                     # nothing was created anywhere


def test_the_probe_runner_gives_a_script_a_scratch_home_and_no_secret_file(tmp_path):
    script = tmp_path / "where.py"
    script.write_text(
        "import os\nfrom pathlib import Path\n"
        "print('HOME', Path.home())\n"
        "print('FILE', repr(os.environ.get('ARSLAN_SECRET_KEY_FILE')))\n"
        "print('DATA', os.environ.get('ARSLAN_DATA_DIR'))\n"
        "print('KEY', os.environ.get('ARSLAN_SECRET_KEY'))\n"
        "import server.config\nprint('IMPORTS', 'yes')\n")
    scratch = tmp_path / "scratch"
    out = _probe(str(script), home=tmp_path / "fake-home", scratch=str(scratch))
    assert out.returncode == 0, out.stderr
    seen = dict(line.split(" ", 1) for line in out.stdout.splitlines() if " " in line)
    assert Path(seen["HOME"]).resolve().is_relative_to(scratch.resolve())
    assert seen["FILE"] == "''"                                  # set but empty: no secret file is ever read
    assert Path(seen["DATA"]).resolve().is_relative_to(scratch.resolve())
    assert seen["KEY"] and seen["KEY"] != "None"                 # a fake explicit key, never the real file
    assert seen["IMPORTS"] == "yes"                              # a script outside the checkout imports server


def test_no_variable_of_the_calling_shell_reaches_the_script_but_the_allowlist(tmp_path):
    passed_in = {"ARSLAN_SPAWNS_DIR": "/from-the-caller", "ARSLAN_API_TOKEN": "fake-caller-token",
                 "ARSLAN_DB_PATH": "/from-the-caller.db", "GH_TOKEN": "fake-gh-token",
                 "OPENAI_API_KEY": "fake-openai-key", "PYTHONPATH": "/from-the-caller",
                 "PYTHONSTARTUP": "/from-the-caller.py", "SOME_OTHER_SECRET": "fake"}
    out = _probe("-c", "import os, json; print(json.dumps(dict(os.environ)))", home=tmp_path / "fake-home",
                 scratch=str(tmp_path / "scratch"), extra=passed_in)
    assert out.returncode == 0, out.stderr
    import json
    env = json.loads(out.stdout.strip().splitlines()[-1])
    for key, value in passed_in.items():
        assert env.get(key) != value, key
    assert env["PYTHONPATH"] == str(ROOT.resolve())
    allowed = {"PATH", "TMPDIR", "LANG", "TERM", "USER", "LOGNAME", "HOME", "PYTHONPATH", "ARSLAN_SECRET_KEY_FILE",
               "ARSLAN_SECRET_KEY", "ARSLAN_DATA_DIR", "ARSLAN_MCP_SUPERVISOR"}
    assert set(env) - allowed <= {"__CF_USER_TEXT_ENCODING", "PWD", "SHLVL", "_", "LC_CTYPE"}, sorted(env)


def test_the_probe_runner_defaults_to_a_fresh_temporary_scratch(tmp_path):
    home = tmp_path / "fake-home"
    out = _probe("-c", "from pathlib import Path; print(Path.home())", home=home)
    assert out.returncode == 0, out.stderr
    seen = Path(out.stdout.strip()).resolve()
    assert seen != home.resolve() and not seen.is_relative_to(home.resolve())
