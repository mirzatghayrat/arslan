"""H1-c (docs/plans/2026-11-11-harness-plan.md §5 H1 step 4 and 5): three plain contradictions.

(1) edit_file's errors named `old`, but the schema's parameter is `old_string` (a plain bug fix, no switch).
(2) The system prompt said "call my_status" / "whats_new", but neither is in the tool table (K7: on demand). Switch
    `status_route_in_prompt`: ON (default) the prompt says to call them with use_tool; OFF the old words, byte for byte.
(3) promise_guard's trigger list matched ordinary words ("working on", "generating", "in progress"). Switch
    `promise_guard_trim_words`: ON (default) they are gone; OFF the old list.

Both switches: DELETE-BY: v0.1.65.
"""
import inspect
import re

import pytest

from server.orchestrator import answer_rules, arslan, promise_guard
from server.registry import file_tools, tool_defs
from server.services import settings_service
from tests.server.test_file_tools import ws  # noqa: F401 — the fixture

# -- (1) edit_file's error names ---------------------------------------------------------------------------------------

EDIT_PARAMS = set(next(t for t in tool_defs.TOOLS if t.name == "edit_file").schema["properties"])


def _quoted(text: str) -> set[str]:
    return set(re.findall(r"'([A-Za-z_]+)'", text))


async def test_every_parameter_an_edit_file_error_names_is_a_schema_parameter(ws):  # noqa: F811
    run = file_tools.EditFileExecutor().execute
    (ws / "dup.txt").write_text("x x")
    errors = [
        (await run({"path": "notes.md", "old_string": "", "new_string": "x"}))["error"],
        (await run({"path": "notes.md", "old_string": "hello", "new_string": 3}))["error"],
        (await run({"path": "notes.md", "old_string": "absent text", "new_string": "x"}))["error"],
        (await run({"path": "dup.txt", "old_string": "x", "new_string": "y"}))["error"],
    ]
    names = set().union(*(_quoted(e) for e in errors))
    assert names == {"old_string", "new_string"}, errors      # the errors do name parameters, and only real ones
    assert names <= EDIT_PARAMS


def test_no_quoted_name_in_the_executors_source_is_a_stray_parameter():
    """Covers the branches the run above does not reach (a missing file etc.): any quoted identifier in an error
    literal of the executor must be a schema parameter."""
    source = inspect.getsource(file_tools.EditFileExecutor)
    literals = re.findall(r"\"error\": f?\"([^\"]*)\"", source)
    assert literals
    for text in literals:
        assert _quoted(text) <= EDIT_PARAMS, text


# -- (2) the my_status wording --------------------------------------------------------------------------------------------

OLD_SELF = ("\n- Questions about yourself (your version, model, sandbox, approvals, phones, SSH hosts, what failed "
            "lately) are answered from my_status and whats_new, never from memory. Questions about your own plans or "
            "code are answered from GitHub: https://github.com/mirzatghayrat/arslan, branch main, and the newest "
            "folder under docs/plans there; never from a folder on this Mac. If something you find is older than "
            "your own version, say so and check again.")
OLD_VERSION_TAIL = ("state, call my_status and answer from what it returns, and whats_new for what changed; never answer "
                    "them from this line or from memory. Only when my_status isn't offered, say this line's version.")


def test_status_route_on_tells_the_model_to_reach_my_status_through_use_tool():
    prefix = str(arslan._build_answer_system())
    assert prefix == arslan._ANSWER_STABLE_PREFIX
    assert OLD_SELF not in prefix and OLD_VERSION_TAIL not in prefix
    assert 'call each with use_tool (name "my_status" or "whats_new")' in prefix
    assert "call my_status (with use_tool, as it isn't in your tool list)" in prefix


def test_status_route_off_is_the_old_prompt_byte_for_byte():
    prefix = str(arslan._build_answer_system(status_route=False))
    assert OLD_SELF in prefix and OLD_VERSION_TAIL in prefix
    assert prefix == answer_rules.LEGACY_ANSWER_STABLE_PREFIX
    # the two prefixes differ only where the two pieces differ
    new = arslan._ANSWER_STABLE_PREFIX
    assert new.replace(answer_rules.WORK_SELF_FROM_LIVE_SOURCES, OLD_SELF).replace(
        answer_rules.VERSION_LINE, answer_rules.LEGACY_VERSION_LINE) == prefix


def test_the_prompts_route_matches_the_tool_table():
    """The promise: use_tool can reach both tools, and neither is resident (so the old bare 'call' had no listed tool)."""
    assert "my_status" not in arslan.RESIDENT and "whats_new" not in arslan.RESIDENT
    assert "use_tool" in answer_rules.WORK_SELF_FROM_LIVE_SOURCES
    # attach_file: the prompt names it only in the phone note, which already says how to find it
    assert "attach_file" not in arslan._ANSWER_STABLE_PREFIX and "find_tools" in arslan.PHONE_NOTE


async def test_the_turn_reads_the_switch_and_defaults_on(execution_db):
    assert await arslan._status_route_named() is True
    async with execution_db() as db:
        await settings_service._set_raw(db, "status_route_in_prompt", "false")
        await db.commit()
    assert await arslan._status_route_named() is False


# -- (3) promise_guard's triggers ---------------------------------------------------------------------------------------

ORDINARY = ["I'm working on it right now", "The deck is Generating, hang tight", "your report is in progress"]
KEPT = ["它正在生成中", "稍等", "现在我把完整的 PPT 交给 Deck Master 来生成", "I'll get that over to the team",
        "I’ll have it ready"]


@pytest.mark.parametrize("text", ORDINARY)
def test_ordinary_words_are_not_promises_by_default_and_are_when_the_switch_is_off(text):
    assert promise_guard.PROMISE_RE.search(text) is None
    assert promise_guard.find_promise(text) is None
    assert promise_guard.find_promise(text, legacy_words=True) is not None
    assert promise_guard.LEGACY_PROMISE_RE.search(text)


@pytest.mark.parametrize("text", KEPT)
def test_real_promises_still_match_both_ways(text):
    assert promise_guard.find_promise(text) is not None
    assert promise_guard.find_promise(text, legacy_words=True) is not None


def test_the_legacy_list_is_the_old_pattern_byte_for_byte():
    assert promise_guard.LEGACY_PROMISE_RE.pattern == (
        r"正在生成|正在为你|稍等|马上(?:就好|给你)|已交给"
        r"|交给.{0,20}?(?:生成|制作|处理|来做)"
        r"|working on|generating|in progress"
        r"|I(?:'|’)ll (?:get|have)")


class _Reply:
    def __init__(self, content):
        self.content = content


class _Adapter:
    def __init__(self, content):
        self.content, self.calls = content, 0

    async def chat(self, system, user):
        self.calls += 1
        return _Reply(self.content)


async def _correct(monkeypatch, text, candidate):
    from server.orchestrator import tool_loop
    adapter = _Adapter(candidate)

    async def get(**_kw):
        return adapter
    monkeypatch.setattr(tool_loop, "_adapter_for_turn", get)
    return await promise_guard.correct(text), adapter


async def test_correct_on_a_status_word_stays_quiet_by_default(execution_db, monkeypatch):
    out, adapter = await _correct(monkeypatch, "Your report is in progress.", "x")
    assert out is None and adapter.calls == 0


async def test_correct_with_the_switch_off_fires_on_it(execution_db, monkeypatch):
    async with execution_db() as db:
        await settings_service._set_raw(db, "promise_guard_trim_words", "false")
        await db.commit()
    out, adapter = await _correct(monkeypatch, "Your report is in progress.", "I wrote that myself; nothing runs.")
    assert out is not None and out["pattern"] == "in progress" and out["corrected"] is True and adapter.calls == 1
    # OFF also judges the re-synthesis by the old list
    out, _ = await _correct(monkeypatch, "Your report is in progress.", "still in progress")
    assert out["corrected"] is False


async def test_correct_still_catches_a_real_promise_by_default(execution_db, monkeypatch):
    out, _ = await _correct(monkeypatch, "它正在生成中,稍等", "我自己写的,没有后台任务。")
    assert out is not None and out["pattern"] == "正在生成"


# -- the switches ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("key,reader", [("status_route_in_prompt", settings_service.status_route_in_prompt),
                                        ("promise_guard_trim_words", settings_service.promise_guard_trim_words)])
async def test_each_switch_defaults_on_and_only_an_explicit_false_turns_it_off(key, reader, monkeypatch):
    stored: dict = {}

    async def raw(_db, name):
        return stored.get(name)
    monkeypatch.setattr(settings_service, "_get_raw", raw)
    assert key in settings_service._PLAIN_KEYS
    assert await reader(object()) is True
    for value, expected in (("false", False), ("False", False), ("true", True), ("", True)):
        stored[key] = value
        assert await reader(object()) is expected, value


async def test_the_switches_round_trip_through_settings_independently(client):
    r = await client.put("/api/v1/settings", json={"promise_guard_trim_words": "false"})
    assert r.status_code == 200, r.text
    got = (await client.get("/api/v1/settings")).json()
    assert got["promise_guard_trim_words"] == "false" and got["status_route_in_prompt"] != "false"
