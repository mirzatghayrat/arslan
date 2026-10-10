"""0.1.59: with "Desktop, Documents, Downloads" off, the model is told commands cannot open them.

The kernel side (the sandbox closes them) is pinned in test_command_sandbox.py; this pins what the
model reads, so it asks the user instead of trying, and failing, command after command.
"""
import pytest

from server.db.models import Setting
from server.orchestrator import arslan

CLOSED = "keeps Desktop, Documents and Downloads closed"


def _run_command(tools):
    return next(t for t in tools if t["key"] == "run_command")["description"]


@pytest.mark.asyncio
async def test_the_model_is_told_only_while_the_folders_are_off(execution_db):
    async with execution_db() as db:
        db.add(Setting(key="orchestrator_shell_enabled", value="true"))
        await db.commit()
    assert CLOSED not in _run_command(await arslan._arslan_tools())
    async with execution_db() as db:
        db.add(Setting(key="default_read_enabled", value="false"))
        await db.commit()
    assert CLOSED in _run_command(await arslan._arslan_tools())
