"""TEMPORARY CI diagnostic for #443 (to be reverted before merge): why do S3a's checkpoint tests find no
saved copy on this branch's Linux CI? It saves a checkpoint the way the wiring tests do and reports, as a
skip reason (CI prints skip reasons with -rs), the skip it got, the free space, and the volumes. It never
fails. DELETE-BY: before #443 merges."""
import os
import shutil
import tempfile

import pytest

from server import config
from server.services import checkpoints, execution_context


async def test_report_why_a_checkpoint_is_skipped_here(tmp_path, monkeypatch):
    data, ws = tmp_path / "data", tmp_path / "ws"
    data.mkdir()
    ws.mkdir()
    (ws / "notes.md").write_text("x")
    monkeypatch.setattr(config, "data_dir", lambda: data)
    checkpoints._reset_for_tests()
    with execution_context.bind_run(999):
        await checkpoints.ensure(999, [ws])
    entry = (checkpoints.manifest(999) or {}).get("roots") or [{}]
    mounts = ""
    try:
        with open("/proc/mounts") as f:
            mounts = " | ".join(line.split()[2] + " " + line.split()[1] for line in f
                                if line.split()[1] in ("/", "/tmp", "/home", "/home/runner/work"))
    except OSError:
        mounts = "no /proc/mounts"
    checkpoints._reset_for_tests()
    pytest.skip(f"S64-0b CI probe: skipped={entry[0].get('skipped')!r} "
                f"free_tmp={shutil.disk_usage(tmp_path).free / 2**30:.2f}GiB "
                f"free_root={shutil.disk_usage('/').free / 2**30:.2f}GiB "
                f"MIN_FREE={checkpoints.MIN_FREE / 2**30:.0f}GiB tmpdir={tempfile.gettempdir()} "
                f"dev_ws={os.stat(ws).st_dev} dev_data={os.stat(data).st_dev} "
                f"data_dir={config.data_dir()} mounts=[{mounts}]")
