"""S1-0: schedule_task's description no longer says scheduled runs are read-only (card S1, U14).

It said "Scheduled runs are read-only: they cannot write files or run commands", and the model repeated
that to the user. It isn't true: the cloud audit found steps a scheduled run can still take. S1 a–c settle
what such a run may do, and only then does the description get its new sentence. Until then it says
nothing about it rather than something false.
"""
from server.orchestrator import arslan


async def test_schedule_task_does_not_claim_scheduled_runs_are_read_only(execution_db):
    desc = {t["key"]: t["description"] for t in await arslan._callable_tools()}["schedule_task"]   # K7: on demand
    assert "runs are read-only" not in desc and "cannot write files" not in desc
    # v0.1.63: the sentence S1 settled says what a scheduled run may do; "read-only" there names MCP tools only.
    assert "only calls MCP tools the server marks read-only" in desc
    assert "The user is asked for permission" in desc      # the rest of the description stays
