"""Function names every provider takes (v0.1.64 NAME1, docs/plans/0164/README.md).

A tool's key is Arslan's name for it, and an MCP tool's key keeps its server's tool name
(server/mcp/discovery.py `mcp_tool_key`). MCP lets that name hold dots (`mcp_7__read.file-v2`), and some
servers send spaces or worse. The providers take less (their references, read 2026-10-30, are listed in
tests/llm/test_name1_provider_safe_names.py): OpenAI letters, digits, `_` and `-`, at most 64; DeepSeek and
Anthropic the same characters, at most 128; Gemini `.` and `:` too, a letter or `_` first, at most 128. One
name outside a provider's rule refuses the whole request.

`wire(key)` is the name a tool goes by on every provider: the key itself when all four rules take it, else
the key with every other character made `_`, cut to fit, then `_h` and 8 hex digits of the key's sha256. It
depends on the key alone, so it is the same every turn, after a restart and on every provider, and a
conversation that switches providers keeps its names. A key the rules take that already ends like a new name
(`…_h1a2b3c4d`) gets one too, so a key sent as it is never equals another key's new name. Two new names are
the same only if the keys clean to the same text and share those 32 bits; `Names` sends neither then.

Arslan keeps the real keys everywhere else. LLMAdapter renames on the way out (the tool list, earlier calls,
the results and function responses that answer them) and maps the reply's calls back.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

_TAKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{0,63}")     # what all four providers take
_RENAMED = re.compile(r".*_h[0-9a-f]{8}", re.S)          # what wire() makes of a key it renames
_OTHER = re.compile(r"[^A-Za-z0-9_-]")
_SUFFIX = 10                                             # "_h" and 8 hex digits


def _digest(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8", "surrogatepass")).hexdigest()[:8]


def wire(key: str) -> str:
    """The name `key` goes by on every provider."""
    key = str(key)
    if _TAKEN.fullmatch(key) and not _RENAMED.fullmatch(key):
        return key
    cleaned = _OTHER.sub("_", key)
    if not re.match(r"[A-Za-z_]", cleaned):
        cleaned = "_" + cleaned                          # Gemini: a letter or `_` first
    return f"{cleaned[:64 - _SUFFIX]}_h{_digest(key)}"


def _function(tool: Any) -> dict | None:
    function = tool.get("function") if isinstance(tool, dict) else None
    return function if isinstance(function, dict) and isinstance(function.get("name"), str) else None


class Names:
    """One request's tool names: each tool's wire name, and the way back from a reply's call."""

    def __init__(self, tools: list[dict[str, Any]] | None):
        self._back: dict[str, str] = {}
        self.shared: set[str] = set()
        for tool in tools or []:
            function = _function(tool)
            if function is None:
                continue
            key = function["name"]
            if self._back.setdefault(wire(key), key) != key:
                self.shared.add(wire(key))
        for name in self.shared:
            del self._back[name]

    def tools(self, tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        """The tool list as sent: each function under its wire name. A name two keys share is sent for
        neither (a server aiming two of its own tools at one name loses both, never gets one's calls)."""
        if not tools:
            return tools
        out = []
        for tool in tools:
            function = _function(tool)
            name = wire(function["name"]) if function else None
            if name in self.shared:
                continue
            out.append(tool if function is None or name == function["name"]
                       else {**tool, "function": {**function, "name": name}})
        return out

    def real(self, name: str) -> str:
        """The key a call by `name` means: the tool sent under it, else `name` itself (no tool this request
        carried, so the executor answers it as an unknown tool)."""
        return self._back.get(name, name)

    def reply(self, response):
        """`response` with each call under the key it means. Everything else stays as the provider sent it:
        Claude's blocks and Gemini's parts go back to that provider byte for byte."""
        calls = list(getattr(response, "tool_calls", None) or [])
        back = []
        for call in calls:
            function = _function(call)
            if function is not None and self.real(function["name"]) != function["name"]:
                call = {**call, "function": {**function, "name": self.real(function["name"])}}
            back.append(call)
        if back != calls:
            response.tool_calls = back
        return response


def messages(history: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    """A trajectory or a legacy history as sent: its tool calls, the results that answer them and Gemini's
    function responses under wire names. The caller's messages are never edited; a message with no name in
    it is passed on as it is."""
    if not history:
        return history
    out = []
    for message in history:
        if not isinstance(message, dict):
            out.append(message)
            continue
        renamed = message
        calls = message.get("tool_calls")
        if isinstance(calls, list) and calls:
            renamed = {**renamed, "tool_calls": [_call(call) for call in calls]}
        if message.get("role") == "tool" and isinstance(message.get("name"), str):
            renamed = {**renamed, "name": wire(message["name"])}
        content = message.get("content")
        if isinstance(content, list) and any(_responds(block) for block in content):
            renamed = {**renamed, "content": [{**block, "name": wire(block["name"])} if _responds(block) else block
                                              for block in content]}
        out.append(renamed)
    return out


def _call(call: Any) -> Any:
    if not isinstance(call, dict):
        return call
    if isinstance(call.get("name"), str):                 # the neutral trajectory's call
        return {**call, "name": wire(call["name"])}
    function = _function(call)                            # a wire-shaped call
    return {**call, "function": {**function, "name": wire(function["name"])}} if function else call


def _responds(block: Any) -> bool:
    return isinstance(block, dict) and block.get("type") == "function_response" and isinstance(block.get("name"), str)
