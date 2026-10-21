"""D8 (docs/plans/0162/D8-titles.md): a conversation's title comes from the user's first message
alone, sent to the model this conversation already talks to. No reply, no memory, no turn context
goes out, and no other model is used (the title slot is gone). A temporary conversation and a
failed call keep their local titles."""
import pytest
from arslan.models import LLMResponse

from server.services import llm_factory, task_context, titler


class _Model:
    def __init__(self, name: str, answer: str | Exception = "Kyoto Trip Plan"):
        self.name, self.answer, self.prompts = name, answer, []

    async def chat(self, system, user, **kwargs):  # noqa: ARG002
        self.prompts.append(user)
        if isinstance(self.answer, Exception):
            raise self.answer
        return LLMResponse(content=self.answer, tool_calls=[], usage={})


@pytest.fixture
def models(monkeypatch):
    """The conversation's own model (when one was chosen for it) and the default chat model."""
    own, default = _Model("own"), _Model("default")
    built: list[str] = []

    async def conversation_adapter(conversation_id):
        built.append(f"conversation:{conversation_id}")
        return own if conversation_id == "chosen" else None

    async def build_adapter(role=None):
        built.append(f"role:{role}")
        return default

    async def not_temporary(conversation_id):  # noqa: ARG001
        return False

    monkeypatch.setattr(llm_factory, "build_conversation_adapter", conversation_adapter)
    monkeypatch.setattr(llm_factory, "build_adapter", build_adapter)
    monkeypatch.setattr(task_context, "is_temporary", not_temporary)
    return own, default, built


async def test_only_the_first_message_goes_to_the_conversations_own_model(models, client):
    own, default, _ = models
    r = await client.post("/api/v1/orchestrator/title", json={
        "first_message": "Plan a three-day trip to Kyoto", "conversation_id": "chosen",
        "first_reply": "Sure — you told me you hate crowds, so…"})          # an older web app still sends it
    assert r.status_code == 200 and r.json()["title"] == "Kyoto Trip Plan"
    assert own.prompts == ["Plan a three-day trip to Kyoto"] and default.prompts == []


async def test_without_a_chosen_model_the_title_uses_the_model_the_chat_turn_uses(models):
    _, default, built = models
    assert await titler.generate_title("Plan a three-day trip to Kyoto", conversation_id="c") == "Kyoto Trip Plan"
    assert default.prompts == ["Plan a three-day trip to Kyoto"]
    assert built == ["conversation:c", "role:execute"]                      # tool_loop._get_adapter's role


async def test_turn_context_never_goes_out_with_the_title_request(models):
    from server.orchestrator import turn_context
    own, _, _ = models
    request = turn_context.prepend(turn_context.wrap("memory: hates crowds"), "Plan a trip to Kyoto")
    assert turn_context.OPEN in request                              # the block exactly as a turn sends it
    await titler.generate_title(request, conversation_id="chosen")
    assert own.prompts == ["Plan a trip to Kyoto"]


async def test_a_temporary_conversation_asks_no_model(models, monkeypatch):
    _, _, built = models

    async def temporary(conversation_id):  # noqa: ARG001
        return True
    monkeypatch.setattr(task_context, "is_temporary", temporary)
    assert await titler.generate_title("Plan a trip to Kyoto", conversation_id="chosen") == "Temporary conversation"
    assert built == []


@pytest.mark.parametrize("answer", [RuntimeError("model down"), "", "   "])
async def test_a_failed_or_empty_answer_keeps_the_first_words(models, answer):
    own, _, _ = models
    own.answer = answer
    assert await titler.generate_title("Plan a three-day trip to Kyoto", conversation_id="chosen") == \
        "Plan a three-day trip to..."


async def test_the_title_slot_is_gone(models, execution_db):
    from server.services import settings_service
    assert "title_config_id" not in llm_factory.SLOT_KEYS
    assert not {"title_config_id", "title_model"} & set(settings_service._PLAIN_KEYS)
