"""0.1.62 F3: an MCP tool's parameter schema is reshaped to what all three provider families
accept before it is sent, and a schema a provider still refuses costs that tool (then, at
worst, every MCP tool) for the turn — never the turn itself.

Fixtures are synthetic, shaped like the 2026-10-14 field failure (Anthropic: "tools.N.custom.
input_schema: input_schema does not support oneOf, allOf, or anyOf at the top level";
DeepSeek: a `pattern` it called "not a regex"). Nothing from that server is used."""
import json

import pytest

from arslan.llm.tool_schema import normalise

PROVIDERS = ("anthropic", "openai", "gemini")

TOP_ANYOF = {"anyOf": [
    {"type": "object", "properties": {"url": {"type": "string"}, "wait": {"type": "number"}},
     "required": ["url"]},
    {"type": "object", "properties": {"url": {"type": "string"}, "selector": {"type": "string"}},
     "required": ["url", "selector"]},
]}
NESTED_PATTERN = {"type": "object", "properties": {
    "env": {"type": "string", "pattern": "^[^=\\0]+$", "description": "NAME=value"}}}
REF_TO_DEFS = {"type": "object", "properties": {"target": {"$ref": "#/$defs/Target"}},
               "$defs": {"Target": {"type": "object", "properties": {"pid": {"type": "integer"}}}}}
CYCLIC_REF = {"type": "object", "properties": {"node": {"$ref": "#/$defs/Node"}},
              "$defs": {"Node": {"type": "object", "properties": {"child": {"$ref": "#/$defs/Node"}}}}}
NULLABLE = {"type": "object", "properties": {"note": {"type": ["string", "null"]},
                                             "n": {"type": ["string", "number", "null"]}}}
WITH_DOLLAR_SCHEMA = {"$schema": "http://json-schema.org/draft-07/schema#", "type": "object",
                      "properties": {"q": {"type": "string"}}}
PLAIN = {"type": "object", "properties": {"q": {"type": "string", "description": "query"}},
         "required": ["q"]}


def _walk(schema):
    yield schema
    if isinstance(schema, dict):
        for value in schema.values():
            yield from _walk(value)
    elif isinstance(schema, list):
        for value in schema:
            yield from _walk(value)


def _keys(schema) -> set[str]:
    return {k for node in _walk(schema) if isinstance(node, dict) for k in node}


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_top_level_anyof_becomes_one_object(provider):
    out = normalise(TOP_ANYOF, provider)
    assert not {"anyOf", "oneOf", "allOf"} & set(out)
    assert out["type"] == "object"
    assert set(out["properties"]) == {"url", "wait", "selector"}   # union
    assert out["required"] == ["url"]                                # intersection
    assert "selector" in out["description"]                         # the lost rule, in words


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_top_level_allof_requires_every_branch(provider):
    out = normalise({"allOf": [{"properties": {"a": {"type": "string"}}, "required": ["a"]},
                               {"properties": {"b": {"type": "string"}}, "required": ["b"]}]}, provider)
    assert out["type"] == "object" and "allOf" not in out
    assert out["required"] == ["a", "b"]


@pytest.mark.parametrize("provider", PROVIDERS)
def test_local_refs_are_inlined(provider):
    out = normalise(REF_TO_DEFS, provider)
    assert "$ref" not in _keys(out) and "$defs" not in _keys(out)
    assert out["properties"]["target"]["properties"]["pid"] == {"type": "integer"}


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_cyclic_ref_ends_in_a_loose_object(provider):
    out = normalise(CYCLIC_REF, provider)
    assert "$ref" not in _keys(out)
    child = out["properties"]["node"]["properties"]["child"]
    assert child["type"] == "object" and "recursive" in child["description"]


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_nullable_type_becomes_one_type(provider):
    out = normalise(NULLABLE, provider)
    note = out["properties"]["note"]
    assert note["type"] == "string" and "null" in note["description"]
    several = out["properties"]["n"]
    assert "type" not in several and "string" in several["description"] and "number" in several["description"]


@pytest.mark.parametrize("provider", PROVIDERS)
def test_dollar_schema_is_dropped(provider):
    assert "$schema" not in normalise(WITH_DOLLAR_SCHEMA, provider)


def test_pattern_is_dropped_for_openai_compatible_endpoints_only():
    out = normalise(NESTED_PATTERN, "openai")
    env = out["properties"]["env"]
    assert "pattern" not in env and "^[^=\\0]+$" in env["description"]
    assert normalise(NESTED_PATTERN, "anthropic")["properties"]["env"]["pattern"] == "^[^=\\0]+$"


def test_a_property_named_like_a_keyword_is_kept():
    schema = {"type": "object", "properties": {"pattern": {"type": "string"}, "$schema": {"type": "string"}}}
    assert set(normalise(schema, "openai")["properties"]) == {"pattern", "$schema"}


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_plain_schema_keeps_its_meaning(provider):
    assert normalise(PLAIN, provider) == PLAIN


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("schema", [TOP_ANYOF, NESTED_PATTERN, REF_TO_DEFS, CYCLIC_REF, NULLABLE,
                                    WITH_DOLLAR_SCHEMA, PLAIN])
def test_the_same_input_gives_the_same_bytes(provider, schema):
    # A changed tool block changes the prompt-cache prefix (arslan.py's tool-order note).
    first = json.dumps(normalise(schema, provider))
    assert first == json.dumps(normalise(json.loads(json.dumps(schema)), provider))
    assert normalise(schema, provider) is not schema


@pytest.mark.parametrize("provider", PROVIDERS)
def test_the_input_is_not_changed(provider):
    before = json.dumps(TOP_ANYOF, sort_keys=True)
    normalise(TOP_ANYOF, provider)
    assert json.dumps(TOP_ANYOF, sort_keys=True) == before


@pytest.mark.parametrize("bad", [None, "not a schema", [], {}])
def test_no_schema_becomes_an_empty_object(bad):
    assert normalise(bad, "anthropic") == {"type": "object", "properties": {}}


# ── review fixes (⓪Plan on #198) ───────────────────────────────────────────────────────

DISCRIMINATED = {"oneOf": [
    {"type": "object", "properties": {"action": {"const": "create"}, "name": {"type": "string"}},
     "required": ["action", "name"]},
    {"type": "object", "properties": {"action": {"const": "delete"}, "id": {"type": "integer"}},
     "required": ["action", "id"]},
]}


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_discriminator_keeps_every_value(provider):
    action = normalise(DISCRIMINATED, provider)["properties"]["action"]
    assert action.get("enum") == ["create", "delete"] and "const" not in action
    assert normalise(DISCRIMINATED, provider)["required"] == ["action"]


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_shared_field_with_different_shapes_keeps_them_all(provider):
    out = normalise({"anyOf": [{"properties": {"x": {"type": "string"}}}, {"properties": {"x": {"type": "integer"}}}]},
                    provider)
    assert out["properties"]["x"] == {"anyOf": [{"type": "string"}, {"type": "integer"}]}


def test_the_shapes_are_described_with_their_optional_fields_and_without_exactly():
    words = normalise(TOP_ANYOF, "anthropic")["description"]
    assert "exactly" not in words and "wait" in words and "selector" in words


@pytest.mark.parametrize("ref", ["#/$defs/Missing", "#", "#/$defs/Target/properties/pid", "other.json#/x"])
def test_a_ref_that_cannot_be_inlined_becomes_a_loose_object(ref):
    out = normalise({"type": "object", "properties": {"p": {"$ref": ref}},
                     "$defs": {"Target": {"type": "object", "properties": {"pid": {"type": "integer"}}}}}, "anthropic")
    assert "$ref" not in _keys(out) and "$defs" not in _keys(out)
    assert out["properties"]["p"]["type"] == "object" and "description" in out["properties"]["p"]


def test_nested_defs_are_dropped_too():
    out = normalise({"type": "object", "properties": {"p": {"type": "object", "$defs": {"X": {"type": "string"}}}}},
                    "anthropic")
    assert "$defs" not in _keys(out)


def test_null_alone_is_the_null_type():
    out = normalise({"type": "object", "properties": {"n": {"type": ["null"]}}}, "anthropic")
    assert out["properties"]["n"]["type"] == "null" and "Type: ," not in json.dumps(out)


def test_pattern_properties_go_for_openai_compatible_endpoints():
    schema = {"type": "object", "patternProperties": {"^x-": {"type": "string"}}}
    out = normalise(schema, "openai")
    assert "patternProperties" not in out and "^x-" in out["description"]
    assert "patternProperties" in normalise(schema, "anthropic")


def test_a_ref_bomb_is_bounded_and_fast():
    import time
    defs = {f"L{i}": {"type": "object", "properties": {"a": {"$ref": f"#/$defs/L{i + 1}"},
                                                      "b": {"$ref": f"#/$defs/L{i + 1}"}}} for i in range(24)}
    defs["L24"] = {"type": "string"}
    bomb = {"type": "object", "properties": {"root": {"$ref": "#/$defs/L0"}}, "$defs": defs}
    started = time.monotonic()
    out = normalise(bomb, "anthropic")
    assert time.monotonic() - started < 1.0
    assert len(json.dumps(out)) < 200_000
    again = time.monotonic()
    assert normalise(bomb, "anthropic") == out                        # cached by the schema's hash
    assert time.monotonic() - again < 0.05


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_large_schema_without_refs_is_kept_whole(provider):
    # The budget is for expanding refs only: a big but plain schema must come through intact.
    schema = {"type": "object", "required": ["p0"],
              "properties": {f"p{i}": {"type": "string"} for i in range(2000)}}
    schema["properties"]["choice"] = {"type": "string", "enum": [f"v{i}" for i in range(6000)]}
    out = normalise(schema, provider)
    assert out["type"] == "object" and out["required"] == ["p0"]
    assert len(out["properties"]) == 2001 and out["properties"]["p1999"] == {"type": "string"}
    assert out["properties"]["choice"]["enum"][-1] == "v5999"


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_field_named_definitions_is_kept(provider):
    schema = {"type": "object", "required": ["definitions", "$defs"],
              "properties": {"definitions": {"type": "string"}, "$defs": {"type": "string"}}}
    out = normalise(schema, provider)
    assert set(out["properties"]) == {"definitions", "$defs"} and out["required"] == ["definitions", "$defs"]


# ── the providers: MCP tools reshaped, built-in tools untouched, errors read back ────

from arslan.llm.providers.anthropic_provider import AnthropicProvider  # noqa: E402
from arslan.llm.providers.gemini_provider import GeminiProvider  # noqa: E402
from arslan.llm.providers.openai_provider import OpenAIProvider  # noqa: E402

# A built-in schema carrying the very keywords an MCP schema loses: built-ins must be sent
# byte for byte as written.
BUILTIN_PARAMS = {"type": "object", "properties": {"path": {"type": "string", "pattern": "^[^/].*"}},
                  "anyOf": [{"required": ["path"]}]}


def _fn(name, params):
    return {"type": "function", "function": {"name": name, "description": name, "parameters": params}}


TOOLS = [_fn("read_file", BUILTIN_PARAMS), _fn("mcp_6__inspect", TOP_ANYOF), _fn("mcp_6__run", NESTED_PATTERN)]
MESSAGES = [{"role": "user", "content": "hi"}]


def test_anthropic_sends_mcp_schemas_reshaped_and_builtins_as_written():
    sent = {t["name"]: t["input_schema"] for t in
            AnthropicProvider(model="claude-x", api_key="k")._payload(MESSAGES, 0.2, tools=TOOLS)["tools"]}
    assert json.dumps(sent["read_file"]) == json.dumps(BUILTIN_PARAMS)
    assert "anyOf" not in sent["mcp_6__inspect"]


def test_openai_compatible_sends_mcp_schemas_without_pattern_and_builtins_as_written():
    sent = {t["function"]["name"]: t["function"]["parameters"] for t in
            OpenAIProvider(model="deepseek-chat", api_key="k")._payload(MESSAGES, TOOLS, 0.2)["tools"]}
    assert json.dumps(sent["read_file"]) == json.dumps(BUILTIN_PARAMS)
    assert "pattern" not in json.dumps(sent["mcp_6__run"])
    assert "anyOf" not in sent["mcp_6__inspect"]


def test_gemini_sends_mcp_schemas_reshaped_and_builtins_as_written():
    payload = GeminiProvider(model="gemini-x", api_key="k")._payload(MESSAGES, 0.2, tools=TOOLS)
    sent = {d["name"]: d["parametersJsonSchema"] for d in payload["tools"][0]["functionDeclarations"]}
    assert json.dumps(sent["read_file"]) == json.dumps(BUILTIN_PARAMS)
    assert "anyOf" not in sent["mcp_6__inspect"]


def test_anthropic_counts_positions_after_skipping_tools_without_a_name():
    tools = [{"type": "function", "function": {"description": "no name"}}, *TOOLS]
    error = "tools.2.custom.input_schema: input_schema does not support oneOf, allOf, or anyOf at the top level"
    assert AnthropicProvider(model="claude-x", api_key="k").named_tool(tools, error) == "mcp_6__run"


def test_gemini_counts_positions_in_its_one_declaration_list():
    error = "Invalid JSON payload received. tools[0].function_declarations[1].parameters: bad"
    assert GeminiProvider(model="gemini-x", api_key="k").named_tool(TOOLS, error) == "mcp_6__inspect"


def test_openai_compatible_reads_a_function_name_or_a_position():
    provider = OpenAIProvider(model="deepseek-chat", api_key="k")
    assert provider.named_tool(TOOLS, "Invalid schema for function 'mcp_6__run': bad") == "mcp_6__run"
    assert provider.named_tool(TOOLS, "Invalid 'tools[1].function.parameters': not a regex") == "mcp_6__inspect"
    assert provider.named_tool(TOOLS, "insufficient balance") is None


# ── the turn: a refused schema costs a tool (at worst every MCP tool), never the turn ────

import httpx  # noqa: E402

from server.orchestrator import model_call as mc  # noqa: E402
from server.orchestrator import tool_loop  # noqa: E402
from tests.server import test_trajectory_golden as golden  # noqa: E402

ANTHROPIC_REFUSAL = ("tools.{n}.custom.input_schema: input_schema does not support oneOf, allOf, "
                     "or anyOf at the top level")


def _refusal(text: str) -> httpx.HTTPStatusError:
    return httpx.HTTPStatusError(f"Client error '400 Bad Request'\n{{\"error\": {{\"message\": \"{text}\"}}}}",
                                 request=httpx.Request("POST", "https://api.example.test/v1/messages"),
                                 response=httpx.Response(400))


class Refuser:
    """A model behind Anthropic's wire shape: refuses any request carrying a tool in `bad`,
    naming it the way Anthropic does (or not at all), otherwise answers from `replies`."""

    def __init__(self, bad=(), *, model="model-a", replies=("done",), named=True, text=None):
        from arslan.llm.providers.anthropic_provider import AnthropicProvider
        self._provider = AnthropicProvider(model=model, api_key="k")
        self.bad, self.named, self.text = set(bad), named, text
        self.replies = [r if not isinstance(r, str) else golden._Resp(r) for r in replies]
        self.calls: list[list[str]] = []

    async def chat(self, system, user, history=None, tools=None, **kw):
        names = [t["function"]["name"] for t in tools or []]
        self.calls.append(names)
        if self.text is not None:
            raise _refusal(self.text)
        hit = [i for i, name in enumerate(names) if name in self.bad]
        if hit:
            raise _refusal(ANTHROPIC_REFUSAL.format(n=hit[0]) if self.named
                           else "tool input schema is not valid")
        return self.replies.pop(0)


async def _tools():
    return [*(await golden._resolve()),
            {"key": "mcp_1__good", "description": "good", "input_schema": PLAIN},
            {"key": "mcp_1__bad", "description": "bad", "input_schema": TOP_ANYOF},
            {"key": "mcp_1__worse", "description": "worse", "input_schema": CYCLIC_REF}]


@pytest.fixture
def events(monkeypatch):
    tool_loop._BAD_TOOLS.clear()
    seen: list[tuple] = []

    async def log_event(conversation_id, kind, ref, summary):
        seen.append((kind, ref))
    from server.services import recap_service
    monkeypatch.setattr(recap_service, "log_event", log_event)

    async def no_state(tool_key):
        return None
    from server.mcp import executor
    monkeypatch.setattr(executor, "not_ready_for_key", no_state)
    yield seen
    tool_loop._BAD_TOOLS.clear()


async def _turn(adapter, cid="c1"):
    return await tool_loop.run_native(system="S", user_content="t", history=[], emit=lambda e: None,
                                      on_chunk=lambda c: None, resolve_tools=_tools, adapter_override=adapter,
                                      conversation_id=cid)


def _mcp(names):
    return {n for n in names if n.startswith("mcp_")}


async def test_a_refused_tool_is_left_out_and_the_turn_finishes(events):
    adapter = Refuser({"mcp_1__bad"})
    result = await _turn(adapter)
    assert result["final"] == "done"
    assert "mcp_1__bad" in adapter.calls[0] and _mcp(adapter.calls[1]) == {"mcp_1__good", "mcp_1__worse"}
    assert ("mcp_schema_relaxed", {"tool_key": "mcp_1__bad", "provider": "anthropic"}) in events


async def test_a_second_refused_tool_leaves_every_mcp_tool_out(events):
    adapter = Refuser({"mcp_1__bad", "mcp_1__worse"})
    result = await _turn(adapter)
    assert result["final"] == "done"
    assert len(adapter.calls) == 3 and _mcp(adapter.calls[2]) == set()
    assert "web_search" in adapter.calls[2]                      # built-ins stay
    assert [ref["tool_key"] for kind, ref in events if kind == "mcp_schema_relaxed"] == ["mcp_1__bad", "all"]


async def test_a_refusal_naming_no_tool_leaves_every_mcp_tool_out(events):
    adapter = Refuser({"mcp_1__bad"}, named=False)
    result = await _turn(adapter)
    assert result["final"] == "done"
    assert _mcp(adapter.calls[1]) == set()
    assert ("mcp_schema_relaxed", {"tool_key": "all", "provider": "anthropic"}) in events


async def test_a_left_out_tool_stays_out_for_the_rest_of_the_turn(events):
    call = golden._tc("mcp_1__bad", "{}")
    adapter = Refuser({"mcp_1__bad"}, replies=[golden._Resp(None, [call]), "done"])
    result = await _turn(adapter)
    assert result["final"] == "done"
    assert all("mcp_1__bad" not in names for names in adapter.calls[1:])
    assert result["tool_trace"][0]["result"]["code"] == "tool_unavailable"


async def test_the_same_model_skips_the_tool_next_turn_and_another_model_does_not(events):
    await _turn(Refuser({"mcp_1__bad"}))
    same = Refuser({"mcp_1__bad"})
    await _turn(same, cid="c2")
    assert len(same.calls) == 1 and "mcp_1__bad" not in same.calls[0]
    other = Refuser(set(), model="model-b")
    await _turn(other, cid="c3")
    assert "mcp_1__bad" in other.calls[0]


async def test_a_refusal_with_nothing_to_do_with_tools_is_not_retried(events):
    adapter = Refuser(text="invalid x-api-key")
    with pytest.raises(mc.ModelCallError):
        await _turn(adapter)
    assert len(adapter.calls) == 1 and events == []



# ── review fixes, the turn ─────────────────────────────────────────────────────────────

class Scripted(Refuser):
    """Answers each request from a script: an exception text to raise, or a reply."""

    def __init__(self, script, **kw):
        super().__init__(**kw)
        self.script = list(script)

    async def chat(self, system, user, history=None, tools=None, **kw):
        self.calls.append([t["function"]["name"] for t in tools or []])
        step = self.script.pop(0)
        if isinstance(step, str) and step.startswith("400:"):
            raise _refusal(step[4:])
        return golden._Resp(step) if isinstance(step, str) else step


async def test_an_unrelated_refusal_after_a_schema_one_is_not_read_as_one(events):
    # Our own recovery note ("…refused its parameter schema") is in str(exc); only the provider's
    # words decide.
    adapter = Scripted([f"400:{ANTHROPIC_REFUSAL.format(n=5)}", "400:invalid x-api-key", "done"])
    with pytest.raises(mc.ModelCallError):
        await _turn(adapter)
    assert len(adapter.calls) == 2
    assert [ref["tool_key"] for kind, ref in events if kind == "mcp_schema_relaxed"] == ["mcp_1__bad"]


async def test_both_refused_tools_are_remembered(events):
    await _turn(Refuser({"mcp_1__bad", "mcp_1__worse"}))
    same = Refuser({"mcp_1__bad", "mcp_1__worse"})
    await _turn(same, cid="c2")
    assert len(same.calls) == 1 and _mcp(same.calls[0]) == {"mcp_1__good"}


async def test_a_capability_refresh_does_not_bring_a_left_out_tool_back(events, monkeypatch):
    from server.services import capability_flow

    async def installed(args, **kw):
        return {"ok": True, "refresh": True}
    monkeypatch.setattr(capability_flow, "propose", installed)

    async def tools():
        return [*(await _tools()), {"key": "propose_capability", "description": "install"}]
    call = golden._tc("propose_capability", '{"candidate_id": "c1", "why": "needed"}')
    adapter = Refuser({"mcp_1__bad"}, replies=[golden._Resp(None, [call]), "done"])
    result = await tool_loop.run_native(system="S", user_content="t", history=[], emit=lambda e: None,
                                        on_chunk=lambda c: None, resolve_tools=tools, adapter_override=adapter,
                                        conversation_id="c1")
    assert result["final"] == "done" and len(adapter.calls) == 3
    assert result["tool_trace"][0]["result"]["ok"] is True          # the refresh really ran
    assert "mcp_1__bad" not in adapter.calls[2] and "mcp_1__good" in adapter.calls[2]


class OpenAIRefuser:
    """A model behind an OpenAI-compatible endpoint on the native protocol (chat_trajectory)."""

    def __init__(self, bad, *, by_name):
        from arslan.llm.providers.openai_provider import OpenAIProvider
        self._provider = OpenAIProvider(model="deepseek-chat", api_key="k", base_url="https://api.deepseek.com")
        self.report_provider = "deepseek"
        self.bad, self.by_name = set(bad), by_name
        self.calls: list[list[str]] = []

    def native_trajectory(self):
        return True

    async def chat_trajectory(self, system, messages, tools=None, tool_choice=None, **kw):
        from types import SimpleNamespace
        names = [t["function"]["name"] for t in tools or []]
        self.calls.append(names)
        hit = [i for i, name in enumerate(names) if name in self.bad]
        if hit:
            raise _refusal(f"Invalid schema for function '{names[hit[0]]}': bad" if self.by_name
                           else f"Invalid 'tools[{hit[0]}].function.parameters': is not a regex")
        return SimpleNamespace(content="done", tool_calls=[], finish_reason="stop", continuation=None,
                               provider_content=None)


@pytest.mark.parametrize("by_name", [True, False])
async def test_an_openai_compatible_refusal_on_the_native_protocol_leaves_the_tool_out(events, by_name):
    adapter = OpenAIRefuser({"mcp_1__bad"}, by_name=by_name)
    result = await _turn(adapter)
    assert result["final"] == "done"
    assert "mcp_1__bad" in adapter.calls[0] and _mcp(adapter.calls[1]) == {"mcp_1__good", "mcp_1__worse"}
    assert ("mcp_schema_relaxed", {"tool_key": "mcp_1__bad", "provider": "deepseek"}) in events
