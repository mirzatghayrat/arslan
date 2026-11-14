"""The suite's runs' roots live under pytest's temp folder, not in the user's temp folder.

`run_temp.root()` is one `arslan-runs-<hash of the data folder>` per data folder, in the per-user temp folder, with an
`arslan-cache-<same>` beside it, and the product never removes either (they are meant to outlive a start). Every
pytest process pins a fresh data folder, and many tests take one of their own, so each run left roots behind: about
6,600 of each on one Mac (2026-11-14). The root conftest (`_runs_roots_in_pytest_temp`) moves them under pytest's
basetemp, which pytest prunes to the last three runs."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from server.services import run_temp
from server.services.sandbox_profile import real

REPO = Path(__file__).resolve().parents[3]
PROBE = Path(__file__).with_name("runs_root_probe.py")


def _roots_in(folder: Path) -> set[str]:
    return {name for name in os.listdir(folder) if name.startswith(("arslan-runs-", "arslan-cache-"))}


def test_this_process_puts_its_runs_root_under_pytest_temp(tmp_path_factory):
    product = run_temp.root.__wrapped__()
    assert product.parent == real(tempfile.gettempdir())               # the product's place is unchanged
    assert run_temp.root().is_relative_to(tmp_path_factory.getbasetemp().resolve())
    assert run_temp.root().name == product.name                        # one root per data folder, as named


def test_a_child_pytest_run_leaves_no_runs_root_in_the_users_temp(tmp_path):
    """A child pytest does a run's worth of `run_temp` work for two data folders. None of the roots it would have
    made in the user's temp folder may be there afterwards. Only those names are counted (each hashes a data folder
    made fresh for that run), so other runs going on at the same time, `-n auto` included, do not count."""
    system = real(tempfile.gettempdir())
    before = _roots_in(system)
    out = tmp_path / "seen.json"
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("PYTEST_XDIST") and key != "PYTEST_CURRENT_TEST"}
    env["RUNS_ROOT_PROBE_OUT"] = str(out)
    child = subprocess.run(
        [sys.executable, "-m", "pytest", str(PROBE), "-q", "-p", "no:cacheprovider", "-p", "no:xdist",
         f"--basetemp={tmp_path / 'child-basetemp'}"],
        cwd=REPO, env=env, capture_output=True, text=True, timeout=110)
    assert child.returncode == 0, child.stdout[-4000:] + child.stderr[-4000:]
    seen = json.loads(out.read_text(encoding="utf-8"))
    assert len(seen) == 2 and seen[0]["product"] != seen[1]["product"]           # two data folders, two roots
    ours = set()
    for entry in seen:
        product = Path(entry["product"])
        assert product.parent == system, entry                                    # named in the user's temp
        ours |= {product.name, product.name.replace("arslan-runs-", "arslan-cache-")}
    assert not ours & before                                                      # fresh names
    left = (_roots_in(system) - before) & ours
    assert not left, f"the child run left {sorted(left)} in {system}"
    for entry in seen:                                                            # and they went to its basetemp
        assert Path(entry["suite"]).is_relative_to((tmp_path / "child-basetemp").resolve()), entry
        assert Path(entry["cache"]).is_relative_to((tmp_path / "child-basetemp").resolve()), entry
