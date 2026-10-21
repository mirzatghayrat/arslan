"""K5: tool descriptions say what the tools really do (card K5).

- read_file pages a long file with offset / limit (by lines), and that's how saved tool outputs are read.
- run_command stops after 120 seconds unless timeout_s says otherwise (5-600, F1). It has a `network`
  argument: after outside content in a turn, commands run offline unless the user allows it (S2a-1).
  Saved tool outputs are read with read_file, not cat: cat hits the sandbox and asks the user (⓪Plan's
  10-20 bench).
"""
from server.db.models import Setting
from server.orchestrator import arslan
from server.services import terminal_exec


async def _descriptions(execution_db, tmp_path) -> dict[str, str]:
    async with execution_db() as db:
        db.add(Setting(key="workspace_dir", value=str(tmp_path)))
        db.add(Setting(key="orchestrator_shell_enabled", value="true"))
        await db.commit()
    return {t["key"]: t["description"] for t in await arslan._arslan_tools()}


async def test_read_file_says_it_pages_by_lines(execution_db, tmp_path):
    text = (await _descriptions(execution_db, tmp_path))["read_file"]
    assert "offset" in text and "limit" in text and "lines" in text


async def test_run_command_states_its_time_limit_and_its_network_argument(execution_db, tmp_path):
    text = (await _descriptions(execution_db, tmp_path))["run_command"]
    assert f"{terminal_exec.DEFAULT_TIMEOUT_S} seconds" in text
    assert f"{terminal_exec.MIN_TIMEOUT_S}-{terminal_exec.MAX_TIMEOUT_S}" in text
    assert "network" in text and "offline" in text


async def test_run_command_points_saved_outputs_to_read_file_not_cat(execution_db, tmp_path):
    text = (await _descriptions(execution_db, tmp_path))["run_command"]
    assert "saved tool output" in text and "read_file" in text and "not cat" in text
