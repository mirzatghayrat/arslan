"""The verification driver must not bootstrap a real installation itself."""
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import frozen_browser_reader_smoke as smoke


def test_driver_import_has_no_server_bootstrap_side_effects(tmp_path):
    result = subprocess.run(
        [sys.executable, "-c", "import sys; import scripts.frozen_browser_reader_smoke; "
         "assert 'server.config' not in sys.modules; "
         "assert 'server.secret_bootstrap' not in sys.modules"],
        cwd=Path(__file__).resolve().parent.parent,
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("binary,runtime", [
    (Path("/not-a-temporary-candidate/arslan-server"), Path("/tmp/arslan-reader-runtime.fixture")),
    (Path("/tmp/unapproved-candidate/arslan-server"), Path("/tmp/arslan-reader-runtime.fixture")),
    (Path("/tmp/arslan-native-candidate.fixture/wrong-name"), Path("/tmp/arslan-reader-runtime.fixture")),
    (Path("/tmp/arslan-native-candidate.fixture/arslan-server"), Path("/not-a-temporary-runtime")),
])
def test_driver_refuses_non_fixture_targets_before_launch(binary, runtime, monkeypatch):
    def unexpected_start(*args, **kwargs):
        raise AssertionError("Must not launch a non-fixture executable")
    monkeypatch.setattr(smoke, "start", unexpected_start)
    with pytest.raises(ValueError):
        smoke.run(binary, runtime)
