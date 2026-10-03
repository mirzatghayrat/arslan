"""No ordering of tests may write into the platform data dir — end to end.

2026-10-03: ``test_default_data_dir_import_has_no_filesystem_side_effect`` failed
because ``~/Library/Application Support/Arslan/does_not_exist_probe/spawns/{S,S2}/.evolution``
already existed. The chain:

  1. test_data_dir's autouse ``_reload_config_to_baseline`` reloaded ``server.config``
     while the test's env patches were still in place. It tears down BEFORE
     ``monkeypatch``, because ``_testclient_models_loopback`` (tests/server/conftest.py)
     instantiates ``monkeypatch`` first — so the "baseline" config kept pointing at the
     probe dir or, after the darwin-default test, at the real one.
  2. ``_heal_config_drift`` only compared the secret and the API token, so nothing
     brought the paths back.
  3. test_dispatcher_override dispatched spawns ``S`` and ``S2``;
     ``evolution_service.prompt_suffix`` -> ``EvolutionEngine.__init__`` mkdir'd
     ``<settings.spawns_dir>/<name>/.evolution`` wherever the stale config pointed.

The first case is that chain. The second is the other way in: a plain ``pytest`` with
``ARSLAN_DATA_DIR`` unset resolves the platform dir from the very first import.

Each case runs a child pytest with HOME pointed at a temp dir, so the platform data
dir it can resolve is a throwaway — this test cannot touch the real one either.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _child_pytest(home: Path, args: list[str], data_dir_env: str | None = "data"):
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("ARSLAN_", "PYTEST_"))}
    env.pop("XDG_DATA_HOME", None)
    env.update(HOME=str(home), ARSLAN_SECRET_KEY="ci-secret", ARSLAN_API_TOKEN="")
    if data_dir_env is not None:
        env["ARSLAN_DATA_DIR"] = data_dir_env
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args],
        cwd=REPO, env=env, capture_output=True, text=True, timeout=110,
    )


@pytest.mark.parametrize(
    ("args", "data_dir_env"),
    [
        pytest.param(
            ["tests/server/test_data_dir.py::test_default_macos_uses_application_support",
             "tests/server/test_dispatcher_override.py"],
            "data",
            id="darwin-default-test-then-dispatch",
        ),
        pytest.param(
            ["tests/server/test_dispatcher_override.py"],
            None,
            id="ARSLAN_DATA_DIR-unset",
        ),
    ],
)
def test_nothing_lands_under_the_platform_data_dir(tmp_path, args, data_dir_env):
    home = tmp_path / "home"
    home.mkdir()
    proc = _child_pytest(home, args, data_dir_env)

    written = sorted(path.relative_to(home).as_posix() for path in home.rglob("*"))
    assert written == [], f"the child run wrote under HOME: {written}"
    assert proc.returncode == 0, proc.stdout[-4000:] + proc.stderr[-2000:]


def test_the_session_guard_fails_a_run_that_writes_there(tmp_path):
    """A guard that never fires looks exactly like one that works: run a child whose one
    test writes into the platform data dir (under a temp HOME) and expect the run to
    fail, naming what was created."""
    home = tmp_path / "home"
    home.mkdir()
    leaky = tmp_path / "leaky" / "test_leaky.py"
    leaky.parent.mkdir()
    leaky.write_text(
        "from tests import real_data_dir_guard\n\n\n"
        "def test_writes_into_the_real_data_dir():\n"
        "    (real_data_dir_guard.REAL_DATA_DIR / 'leak').mkdir(parents=True)\n"
    )

    # The root conftest loaded as a plugin: the leaky file lives outside tests/.
    proc = _child_pytest(home, ["-p", "tests.conftest", str(leaky)])

    assert proc.returncode != 0, proc.stdout[-4000:]
    assert "1 passed, 1 error" in proc.stdout, proc.stdout[-4000:]
    assert "created 2 entries in the real Arslan data dir" in proc.stdout, proc.stdout[-4000:]
    assert "/leak" in proc.stdout
