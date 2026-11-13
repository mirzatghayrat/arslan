"""H1-a: the two Claude switches are plain settings (the bench sets them through BENCH_ARSLAN_SETTINGS),
read once where an adapter is built, for the primary, a conversation's own model and the legacy flat settings."""
import pytest
from sqlalchemy import insert

from arslan.llm.model_params import Switches
from server.db.models import ConversationModel, ProviderConfig
from server.services import llm_factory, settings_service


async def _set(db_maker, values: dict) -> None:
    async with db_maker() as db:
        await settings_service.update_settings(db, values)


@pytest.mark.parametrize("values,expected", [
    ({}, Switches()),
    ({"claude_effort": "high"}, Switches(claude_effort="high")),
    ({"claude_effort": "Medium "}, Switches(claude_effort="medium")),
    ({"claude_effort": "max"}, Switches()),                       # only the two measured levels
    ({"output_cap_raised": "true"}, Switches(output_cap=True)),
    ({"output_cap_raised": "yes"}, Switches()),
    ({"tool_temperature_vendor": "true"}, Switches()),            # the vetoed switch is gone
])
async def test_the_switches_read_off_unless_set(execution_db, values, expected):
    await _set(execution_db, values)
    async with execution_db() as db:
        assert await settings_service.model_switches(db) == expected


async def test_the_settings_api_round_trips_them(client):
    """The bench's driver writes them with PUT /settings as strings (arslan_driver.settings_body)."""
    r = await client.put("/api/v1/settings", json={"claude_effort": "medium", "output_cap_raised": "true"})
    assert r.status_code == 200, r.text
    got = (await client.get("/api/v1/settings")).json()
    assert (got["claude_effort"], got["output_cap_raised"]) == ("medium", "true")
    assert "tool_temperature_vendor" not in got


async def test_every_adapter_the_factory_builds_carries_them(execution_db, monkeypatch):
    async def key(*args, **kwargs):
        return "k"
    monkeypatch.setattr(llm_factory.provider_config_service, "get_decrypted_key", key)
    async with execution_db() as db:
        await db.execute(insert(ProviderConfig).values(id=1, label="Claude", provider="anthropic",
                                                      model="claude-opus-5-5", base_url="", api_key="",
                                                      is_primary=True))
        await db.execute(insert(ConversationModel).values(conversation_id="c1", config_id=1, model=""))
        await db.commit()
    await _set(execution_db, {"claude_effort": "high", "output_cap_raised": "true"})
    on = Switches(claude_effort="high", output_cap=True)
    primary = await llm_factory.build_adapter(role="execute")
    chosen = await llm_factory.build_conversation_adapter("c1")
    assert primary._provider.switches == on and chosen._provider.switches == on
    assert primary._provider.max_tokens == 32_768


async def test_the_legacy_flat_settings_adapter_carries_them(execution_db, monkeypatch):
    async def key(*args, **kwargs):
        return "k"
    monkeypatch.setattr(llm_factory.settings_service, "get_decrypted_api_key", key)
    await _set(execution_db, {"llm_provider": "deepseek", "llm_model": "deepseek-v4-pro",
                              "claude_effort": "medium"})
    adapter = await llm_factory.build_adapter()
    assert adapter._provider.switches == Switches(claude_effort="medium")
