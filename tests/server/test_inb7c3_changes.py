"""INB7-c3 (v0.1.64): the inspector's 「改动」 reads what the picked run changed from its own conversation
(GET /conversations/{id}/changes), so the steps read says which conversation that is."""
from __future__ import annotations

from server.db.models import Run


async def test_the_steps_read_names_the_runs_conversation(client):
    async with client.db_maker() as db:
        run = Run(conversation_id="chat-7", spawn_name="Arslan", user_message="x", status="recorded", kind="host", task_tokens=0)
        db.add(run)
        await db.commit()
        run_id = run.id
    body = (await client.get(f"/api/v1/runs/{run_id}/process")).json()
    assert body["conversation_id"] == "chat-7"
