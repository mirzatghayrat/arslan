"""Run in a child pytest by test_runs_root_in_pytest_temp.py, never collected on its own (the name matches no
`python_files` pattern). It does a run's worth of `run_temp` work, for two data folders, and writes to
$RUNS_ROOT_PROBE_OUT where the product would have put each runs' root and its cache, and where the suite put them."""
import json
import os

from server.services import command_sandbox, execution_context, run_temp, terminal_exec


def _record(seen: list) -> None:
    product = getattr(run_temp.root, "__wrapped__", run_temp.root)      # the product's own rule, without the suite's
    seen.append({"product": str(product()), "suite": str(run_temp.root()), "cache": str(run_temp.cache("commands"))})


async def _a_run(tmp_path, run_id: int) -> None:
    with execution_context.bind_run(run_id):
        result = await terminal_exec.run('echo x > "$TMPDIR/left"', cwd=tmp_path)
    assert result["ok"], result
    run_temp.finish(run_id)                                              # the run ended
    outside = await terminal_exec.run("true", cwd=tmp_path)             # a command outside any run
    assert outside["ok"], outside
    command_sandbox.cache_environment(run_temp.cache("commands"))       # the commands' cache, as a sandboxed run makes it


async def test_a_run_for_each_of_two_data_folders(tmp_path, monkeypatch):
    from server import config
    seen: list = []
    await _a_run(tmp_path, 41)
    _record(seen)
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path / "second-data")     # a test with a data folder of its own
    await _a_run(tmp_path, 42)
    _record(seen)
    with open(os.environ["RUNS_ROOT_PROBE_OUT"], "w", encoding="utf-8") as out:
        json.dump(seen, out)
