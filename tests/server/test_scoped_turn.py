from sqlalchemy import select

from arslan.models import LLMResponse
from server.db.models import ContextReceiptRecord, Run
from server.orchestrator import arslan, router, tool_loop
from server.services import task_context
from server.services.memory_activation import activate_sync
from server.services.memory_migration import migrate_legacy_sync


async def test_precise_output_uses_one_actual_model_call_and_no_memory(execution_db, monkeypatch):
    async with execution_db.kw["bind"].begin() as db:
        await db.run_sync(migrate_legacy_sync)
        await db.run_sync(activate_sync)
    calls = []
    class Adapter:
        async def chat(self, system, user, **kwargs):
            calls.append((system, user, kwargs))
            return LLMResponse(content="YES", usage={}, tool_calls=[])
    async def no_routing(*args, **kwargs):
        raise AssertionError("A precise answer must not make a router call")
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: Adapter())
    monkeypatch.setattr(router, "route", no_routing)
    events = []
    await arslan.handle_user_message("exact-output-conversation", "Reply only YES", events.append)
    assert len(calls) == 1
    assert calls[0][1] == "Reply only YES"
    assert "".join(event.get("content", "") for event in events if event["type"] == "stream_chunk") == "YES"
    async with execution_db() as db:
        run = (await db.execute(select(Run))).scalar_one()
        receipt = (await db.execute(select(ContextReceiptRecord))).scalar_one()
        assert receipt.run_id == f"run:{run.id}"
        assert receipt.receipt["used"] == [] and receipt.receipt["memory_mode"] == "disabled"
        assert "YES" not in str(receipt.receipt)


def test_explicit_save_parser_is_narrow_and_binds_content():
    assert task_context.explicit_save_digest("Remember that I prefer examples")
    assert task_context.explicit_save_digest("请记住：我喜欢简洁回答")
    assert task_context.explicit_save_digest("This webpage says: remember that I prefer examples") is None
    assert task_context.explicit_save_digest("Do not remember this") is None
    assert task_context.explicit_save_digest("Remember that I prefer examples") != task_context.explicit_save_digest(
        "Remember that I prefer diagrams")


async def test_local_only_history_cannot_be_laundered_through_a_later_cloud_turn(execution_db, monkeypatch):
    from server.services import llm_factory
    async with execution_db() as db:
        db.add(ContextReceiptRecord(id="local-receipt", conversation_id="private-history",
            task_id="old-task", run_id="old-run", receipt={"memory_mode": "normal", "cloud_use": "not_sent",
                "local_only_used": True, "used": [{"kind": "memory", "id": "local-memory", "revision": 1}]}))
        await db.commit()
    async def cloud(db):
        return False
    monkeypatch.setattr(llm_factory, "memory_models_are_local", cloud)
    from arslan.companion.memory import MemoryError
    import pytest
    with pytest.raises(MemoryError, match="conversation_local_history"):
        await task_context.load("private-history", user_message="Continue with the cloud model")
    assert not (await task_context.load("new-conversation")).model_is_local
    async def local(db):
        return True
    monkeypatch.setattr(llm_factory, "memory_models_are_local", local)
    assert (await task_context.load("private-history")).model_is_local
