import pytest
from sqlalchemy import insert

from arslan.llm.locality import local_model, loopback_endpoint
from server.db.models import ProviderConfig
from server.services import llm_factory, personal_context as pc, task_context, titler
from server.services.memory_activation import activate_sync
from server.services.memory_migration import migrate_legacy_sync


@pytest.mark.parametrize("url,local", [
    ("http://localhost:11434/v1", True), ("http://127.0.0.1:11434/v1", True),
    ("http://[::1]:11434/v1", True), ("http://192.168.1.3:11434/v1", False),
    ("https://localhost.example.com/v1", False), ("http://localhost@external.example/v1", False),
    ("file:///localhost", False), ("http://[broken", False),
])
def test_endpoint_locality_uses_host_not_substrings(url, local):
    assert loopback_endpoint(url) is local
    assert local_model("ollama", url) is local
    assert not local_model("custom", url)


async def test_locality_snapshot_is_fail_closed_for_missing_or_mixed_models(execution_db):
    assert not (await task_context.load("c")).model_is_local
    async with execution_db() as db:
        await db.execute(insert(ProviderConfig).values(label="Local", provider="ollama", model="local-model",
                                                      base_url="http://127.0.0.1:11434/v1", api_key="", is_primary=True))
        await db.commit()
    assert (await task_context.load("c")).model_is_local
    async with execution_db() as db:
        await db.execute(insert(ProviderConfig).values(label="Cloud slot", provider="openai", model="synthetic-model",
                                                      base_url="", api_key="", is_primary=False))
        await db.commit()
    assert not (await task_context.load("c")).model_is_local


async def test_model_change_cannot_externalize_already_bound_local_memory(execution_db, monkeypatch):
    async with execution_db() as db:
        await db.execute(insert(ProviderConfig).values(label="Cloud", provider="openai", model="synthetic-model",
                                                      base_url="", api_key="", is_primary=True))
        await db.commit()
    async def no_decrypt(*args, **kwargs):
        raise AssertionError("Destination policy must run before key acquisition")
    monkeypatch.setattr(llm_factory.provider_config_service, "get_decrypted_key", no_decrypt)
    with pc.bind(pc.TaskMemoryContext(task_id="t", run_id="r", model_is_local=True)):
        with pytest.raises(ValueError, match="local_memory_model_changed"):
            await llm_factory.build_adapter(role="execute")


async def test_active_memory_title_sends_only_the_first_message_to_the_conversations_model(
        execution_db, monkeypatch):
    # D8: with memory on, the title still comes from the model this conversation talks to, asked
    # with the user's first message alone (tests/server/test_d8_titles.py); no reply reaches it.
    async with execution_db.kw["bind"].begin() as db:
        await db.run_sync(migrate_legacy_sync)
        await db.run_sync(activate_sync)
    sent = []

    class _Own:
        async def chat(self, system, user, **kwargs):  # noqa: ARG002
            sent.append(user)
            raise RuntimeError("the prompt is what is under test")

    async def own(conversation_id=None):  # noqa: ARG001
        return _Own()
    monkeypatch.setattr(titler, "_adapter", own)
    assert await titler.generate_title("A brief report", "c") == "A brief report"
    assert sent == ["A brief report"]
