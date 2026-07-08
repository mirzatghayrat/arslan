"""Tests for arslan.core.dialogue — Dialogue Engine requirement tree state machine."""

from arslan.core.dialogue import DialogueEngine, DialogueState, NODE_ORDER


# ---------------------------------------------------------------------------
# DialogueState tests
# ---------------------------------------------------------------------------


class TestDialogueStateInitial:
    def test_initial_current_node(self):
        state = DialogueState()
        assert state.current_node == "domain"

    def test_initial_current_index(self):
        state = DialogueState()
        assert state.current_index == 0

    def test_initial_not_finished(self):
        state = DialogueState()
        assert state.is_finished is False

    def test_initial_requirements_empty(self):
        state = DialogueState()
        req = state.requirements
        assert req.spawn_name is None
        assert req.domain is None
        assert req.capabilities == []
        assert req.persona is None


class TestDialogueStateSetField:
    def test_set_domain_updates_requirements(self):
        state = DialogueState()
        state.set_field("domain", {"category": "content-creator", "subcategory": "xiaohongshu"})
        assert state.requirements.domain is not None
        assert state.requirements.domain.category == "content-creator"
        assert state.requirements.domain.subcategory == "xiaohongshu"

    def test_set_domain_adds_to_filled(self):
        state = DialogueState()
        state.set_field("domain", {"category": "other", "subcategory": None})
        assert "domain" in state._filled

    def test_set_capabilities_list(self):
        state = DialogueState()
        state.set_field("capabilities", ["content-generation", "qa-interaction"])
        assert state.requirements.capabilities == ["content-generation", "qa-interaction"]

    def test_set_capabilities_scalar_wraps_to_list(self):
        state = DialogueState()
        state.set_field("capabilities", "info-gathering")
        assert state.requirements.capabilities == ["info-gathering"]

    def test_set_persona(self):
        state = DialogueState()
        state.set_field("persona", {"role": "资深美妆博主", "tone": "亲切友好型"})
        assert state.requirements.persona is not None
        assert state.requirements.persona.role == "资深美妆博主"
        assert state.requirements.persona.tone == "亲切友好型"

    def test_set_runtime(self):
        state = DialogueState()
        state.set_field("runtime", {"platform": "web", "trigger": "user"})
        assert state.requirements.runtime.platform == "web"
        assert state.requirements.runtime.trigger == "user"

    def test_set_spawn_name(self):
        state = DialogueState()
        state.set_field("spawn_name", "美妆助手")
        assert state.requirements.spawn_name == "美妆助手"


class TestDialogueStateAdvance:
    def test_advance_skips_filled_nodes(self):
        state = DialogueState()
        state.set_field("domain", {"category": "other", "subcategory": None})
        state.advance()
        assert state.current_node == "capabilities"

    def test_advance_to_done_when_all_filled(self):
        state = DialogueState()
        for node_id in NODE_ORDER:
            if node_id == "domain":
                state.set_field(node_id, {"category": "other", "subcategory": None})
            elif node_id == "capabilities":
                state.set_field(node_id, ["content-generation"])
            elif node_id == "persona":
                state.set_field(node_id, {"role": "assistant", "tone": "亲切友好型"})
            elif node_id == "runtime":
                state.set_field(node_id, {"platform": "web", "trigger": "user"})
            elif node_id == "spawn_name":
                state.set_field(node_id, "TestBot")
        state.advance()
        assert state.current_node == "done"


class TestDialogueStateIsFinished:
    def _fill_all(self, state: DialogueState) -> None:
        state.set_field("domain", {"category": "content-creator", "subcategory": None})
        state.set_field("capabilities", ["content-generation"])
        state.set_field("persona", {"role": "blogger", "tone": ""})
        state.set_field("runtime", {"platform": "web", "trigger": "user"})
        state.set_field("spawn_name", "MyBot")

    def test_is_finished_false_when_incomplete(self):
        state = DialogueState()
        state.set_field("domain", {"category": "other", "subcategory": None})
        assert state.is_finished is False

    def test_is_finished_true_when_all_required_set(self):
        state = DialogueState()
        self._fill_all(state)
        assert state.is_finished is True


# ---------------------------------------------------------------------------
# DialogueEngine tests
# ---------------------------------------------------------------------------


class TestDialogueEngineGetNextQuestion:
    def test_initial_question_is_for_domain(self):
        engine = DialogueEngine()
        q = engine.get_next_question()
        assert q is not None
        assert q.node_id == "domain"
        assert "领域" in q.text or "domain" in q.text.lower() or "分身" in q.text

    def test_domain_question_has_options(self):
        engine = DialogueEngine()
        q = engine.get_next_question()
        assert q is not None
        assert q.options is not None
        assert len(q.options) > 0

    def test_question_is_none_when_finished(self):
        engine = DialogueEngine()
        # Fill everything via process_user_input
        engine.process_user_input("小红书美妆内容")  # domain
        engine.process_user_input("生成文案")         # capabilities
        engine.process_user_input("资深美妆博主，亲切友好")  # persona
        engine.process_user_input("网页对话")          # runtime
        engine.process_user_input("美妆助手")          # spawn_name
        assert engine.get_next_question() is None


class TestDialogueEngineProcessInput:
    def test_xiaohongshu_sets_domain_correctly(self):
        engine = DialogueEngine()
        engine.process_user_input("小红书美妆内容")
        req = engine.state.requirements
        assert req.domain is not None
        assert req.domain.category == "content-creator"
        assert req.domain.subcategory == "xiaohongshu"

    def test_input_advances_to_next_node(self):
        engine = DialogueEngine()
        engine.process_user_input("小红书美妆内容")
        assert engine.state.current_node == "capabilities"

    def test_capabilities_extracted_from_keywords(self):
        engine = DialogueEngine()
        engine.process_user_input("其他")          # domain — falls through to "other"
        engine.process_user_input("生成文案写内容")  # capabilities
        assert "content-generation" in engine.state.requirements.capabilities

    def test_capabilities_default_when_no_match(self):
        engine = DialogueEngine()
        engine.process_user_input("其他")  # domain
        engine.process_user_input("帮我做事情")  # capabilities — no keywords
        assert engine.state.requirements.capabilities == ["content-generation"]

    def test_spawn_name_sets_name_directly(self):
        engine = DialogueEngine()
        # Advance past domain, capabilities, persona, runtime
        engine.process_user_input("客服")
        engine.process_user_input("对话问答")
        engine.process_user_input("专业客服代表")
        engine.process_user_input("命令行")
        # Now at spawn_name
        engine.process_user_input("客服小明")
        assert engine.state.requirements.spawn_name == "客服小明"

    def test_persona_uses_full_input_as_role(self):
        engine = DialogueEngine()
        engine.process_user_input("数据分析")   # domain
        engine.process_user_input("分析数据")   # capabilities
        engine.process_user_input("严谨的数据科学家")  # persona
        assert engine.state.requirements.persona is not None
        assert engine.state.requirements.persona.role == "严谨的数据科学家"

    def test_persona_tone_extracted_from_keywords(self):
        engine = DialogueEngine()
        engine.process_user_input("数据分析")
        engine.process_user_input("分析")
        engine.process_user_input("幽默风趣的助手")
        assert engine.state.requirements.persona is not None
        assert engine.state.requirements.persona.tone == "幽默风趣型"

    def test_runtime_web_keyword(self):
        engine = DialogueEngine()
        engine.process_user_input("小红书")
        engine.process_user_input("生成")
        engine.process_user_input("博主")
        engine.process_user_input("网页对话")
        assert engine.state.requirements.runtime.platform == "web"

    def test_runtime_cli_default(self):
        engine = DialogueEngine()
        engine.process_user_input("小红书")
        engine.process_user_input("生成")
        engine.process_user_input("博主")
        engine.process_user_input("命令行")
        assert engine.state.requirements.runtime.platform == "cli"


class TestDialogueEngineIsFinished:
    def test_is_finished_after_full_dialogue(self):
        engine = DialogueEngine()
        engine.process_user_input("小红书美妆内容")
        engine.process_user_input("生成文案")
        engine.process_user_input("资深美妆博主，亲切友好")
        engine.process_user_input("网页对话")
        engine.process_user_input("美妆助手")
        assert engine.state.is_finished is True


class TestDialogueEngineGetSummary:
    def _complete_dialogue(self, engine: DialogueEngine) -> None:
        engine.process_user_input("小红书美妆内容")
        engine.process_user_input("生成文案")
        engine.process_user_input("资深美妆博主，亲切友好")
        engine.process_user_input("网页对话")
        engine.process_user_input("美妆助手")

    def test_summary_includes_spawn_name(self):
        engine = DialogueEngine()
        self._complete_dialogue(engine)
        summary = engine.get_summary()
        assert "美妆助手" in summary

    def test_summary_includes_domain(self):
        engine = DialogueEngine()
        self._complete_dialogue(engine)
        summary = engine.get_summary()
        assert "content-creator" in summary

    def test_summary_includes_capabilities(self):
        engine = DialogueEngine()
        self._complete_dialogue(engine)
        summary = engine.get_summary()
        assert "content-generation" in summary

    def test_summary_non_empty_when_partial(self):
        engine = DialogueEngine()
        engine.process_user_input("客服")
        summary = engine.get_summary()
        assert len(summary) > 0
