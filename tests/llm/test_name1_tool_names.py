"""NAME1 (v0.1.64): `wire(key)`, the name a tool goes by on every provider (arslan/llm/tool_names.py).

The name is a pure function of the key: the same every turn, after a restart and on every provider,
and never one two keys share. The providers' rules are the patterns in test_name1_provider_safe_names.
"""
import json
import os
import random
import subprocess
import sys
from pathlib import Path

import pytest

from arslan.llm import tool_names
from arslan.llm.adapter import LLMAdapter
from server.mcp.discovery import mcp_tool_key
from server.orchestrator import tool_loop
from server.registry import executors
from tests.llm.test_name1_provider_safe_names import DOTTED, RULES, SPACED

ROOT = Path(__file__).resolve().parents[2]
ODD = [DOTTED, SPACED, "mcp_7__line\nbreak", "mcp_7__读文件", "mcp_7__a:b", "9lives", "-dash", "", "x" * 65,
       "mcp_12__" + "a." * 21, "mcp_7__ok_h1a2b3c4d"]


def schemas(*keys):
    return [{"type": "function", "function": {"name": key, "description": "", "parameters": {}}} for key in keys]


def takes(name: str) -> bool:
    return all(rule.fullmatch(name) for rule in RULES.values())


def test_every_built_in_name_is_sent_as_it_is():
    """Built-in keys keep their names, so their part of a cached prompt doesn't change."""
    keys = {*executors.EXECUTORS, *tool_loop._NATIVE_PARAM_SCHEMAS, "escalate", "find_tools", "use_tool"}
    assert keys and all(takes(key) for key in keys)
    assert [key for key in sorted(keys) if tool_names.wire(key) != key] == []


@pytest.mark.parametrize("key", ["mcp_3__list_files", "mcp_12__get-page", mcp_tool_key(3, "a_very_long_name" * 4)])
def test_an_mcp_key_every_provider_takes_is_sent_as_it_is(key):
    assert takes(key) and tool_names.wire(key) == key


@pytest.mark.parametrize("key", ODD)
def test_a_key_some_provider_refuses_gets_a_name_all_four_take(key):
    name = tool_names.wire(key)
    assert takes(name) and name != key


def test_the_name_depends_on_the_key_alone():
    """Another process with another hash seed (a restart) gives every key the same name."""
    code = ("import json, sys; from arslan.llm.tool_names import wire; "
            "print(json.dumps([wire(k) for k in json.loads(sys.argv[1])]))")
    for seed in ("0", "1"):
        out = subprocess.run([sys.executable, "-c", code, json.dumps(ODD)], cwd=ROOT, check=True, text=True,
                             capture_output=True, env={**os.environ, "PYTHONHASHSEED": seed})
        assert json.loads(out.stdout) == [tool_names.wire(key) for key in ODD]


def test_no_two_keys_share_a_name():
    renamed = tool_names.wire(DOTTED)
    keys = {*ODD, renamed, tool_names.wire(renamed), "mcp_7__read_file-v2", "mcp_7__read file-v2",
            "mcp_7__read:file-v2", "mcp_7__read_file-v2" + renamed[-10:]}
    rng = random.Random(0)
    keys |= {"mcp_7__" + "".join(rng.choice("ab._ -:") for _ in range(rng.randint(1, 10))) for _ in range(5000)}
    assert len({tool_names.wire(key) for key in keys}) == len(keys)
    assert tool_names.wire(renamed) != renamed           # a key shaped like a new name is renamed itself


def test_a_reply_maps_back_to_the_key():
    names = tool_names.Names(schemas(DOTTED, "web_search"))
    assert [t["function"]["name"] for t in names.tools(schemas(DOTTED, "web_search"))] == \
        [tool_names.wire(DOTTED), "web_search"]
    assert names.real(tool_names.wire(DOTTED)) == DOTTED and names.real("web_search") == "web_search"
    assert names.real(DOTTED) == DOTTED and names.real("mcp_7__other") == "mcp_7__other"   # unknown: unchanged


def test_a_name_two_keys_share_is_sent_for_neither_and_maps_back_to_neither(monkeypatch):
    monkeypatch.setattr(tool_names, "_digest", lambda key: "00000000")   # every renamed key collides
    a, b = "mcp_7__x.y", "mcp_7__x y"                                     # both clean to mcp_7__x_y
    assert tool_names.wire(a) == tool_names.wire(b)
    sent = schemas(a, b, "mcp_7__z.w", "web_search")
    names = tool_names.Names(sent)
    assert [t["function"]["name"] for t in names.tools(sent)] == [tool_names.wire("mcp_7__z.w"), "web_search"]
    assert names.real(tool_names.wire(a)) not in (a, b)
    # F3 reads a provider's index against the list it sent, not the one it was given.
    adapter = LLMAdapter("anthropic", "claude-sonnet-5", api_key="k")
    assert adapter.named_tool(sent, "tools.0.custom.input_schema: JSON schema is invalid") == "mcp_7__z.w"


def test_renaming_a_trajectory_edits_nothing_in_place():
    call = {"id": "c1", "name": DOTTED, "arguments": {}, "arguments_raw": "{}"}
    messages = [{"role": "user", "content": "go"}, {"role": "assistant", "content": None, "tool_calls": [call]},
                {"role": "tool", "tool_call_id": "c1", "name": DOTTED, "content": "x"},
                {"role": "user", "content": [{"type": "function_response", "name": DOTTED, "response": {}}]}]
    before = json.dumps(messages)
    out = tool_names.messages(messages)
    assert json.dumps(messages) == before and out[0] is messages[0]
    assert out[1]["tool_calls"][0]["name"] == out[2]["name"] == out[3]["content"][0]["name"] == tool_names.wire(DOTTED)


def test_f3_finds_the_refused_tool_by_the_index_of_the_list_it_sent(monkeypatch):
    """A shared name is left off the wire list, so a provider's index counts the list it was sent."""
    monkeypatch.setattr(tool_names, "_digest", lambda key: "00000000")
    sent = schemas("mcp_7__x.y", "mcp_7__x y", "mcp_7__z.w", "web_search")
    adapter = LLMAdapter("anthropic", "claude-sonnet-5", api_key="k")
    assert tool_loop._refused_tool(adapter, sent, "tools.0.custom.input_schema: JSON schema is invalid") == "mcp_7__z.w"


def test_f3_finds_a_tool_the_error_names_by_its_wire_name():
    """An endpoint whose error has no shape named_tool knows: the text names the tool as it was sent."""
    sent = schemas(DOTTED, "mcp_7__list_files", "web_search")
    adapter = LLMAdapter("openai", "x", api_key="k", base_url="https://llm.example/v1")
    text = f"{tool_names.wire(DOTTED)}: parameters schema is invalid"
    assert tool_loop._refused_tool(adapter, sent, text) == DOTTED


async def test_a_stream_gets_the_same_names():
    seen = {}
    adapter = LLMAdapter("openai", "x", api_key="k", base_url="https://llm.example/v1")

    async def chat_stream(messages, tools=None, temperature=0.7):
        seen.update(messages=messages, tools=tools)
        yield "ok"
    adapter._provider.chat_stream = chat_stream
    history = [{"role": "assistant", "content": None,
                "tool_calls": [{"id": "c1", "type": "function", "function": {"name": DOTTED, "arguments": "{}"}}]}]
    assert [piece async for piece in adapter.chat_stream("S", "hi", history=history, tools=schemas(DOTTED))] == ["ok"]
    assert seen["tools"][0]["function"]["name"] == tool_names.wire(DOTTED)
    assert seen["messages"][1]["tool_calls"][0]["function"]["name"] == tool_names.wire(DOTTED)
