"""An MCP tool's parameter schema, reshaped to what the providers accept (0.1.62 F3).

Field report 2026-10-14: one MCP server's schemas failed every chat. Anthropic refused a
top-level `anyOf` ("input_schema does not support oneOf, allOf, or anyOf at the top level"),
DeepSeek refused a `pattern` it could not compile; one bad tool rejects the whole request.
Servers write full JSON Schema; providers accept a subset, and each a different one.

`normalise` is pure (no network, no database) and only ever applied to `mcp_*` tools as they
are sent: what discovery stored stays verbatim. Built-in tools are never passed through it.
For every provider family:

- a top-level anyOf / oneOf / allOf becomes one object: properties joined, `required` the
  keys every branch requires (allOf: any branch requires), the lost rule kept in words;
- local `$ref`s (`#/$defs/…`, `#/definitions/…`) are inlined; a cycle ends in a loose object;
- `type: [X, "null"]` becomes X ("may be null" in the description); two or more non-null
  types drop `type` and name them in the description;
- `$schema` goes.

OpenAI-compatible endpoints (DeepSeek and others) also lose every `pattern`, written into the
description instead. Which other keywords a given endpoint refuses is not known (not checked
against each vendor); `pattern` is the one seen in the field.

The same input always gives the same output, keys sorted: a changed tool block changes the
prompt-cache prefix.
"""
from __future__ import annotations

import json
from typing import Any

_COMBINERS = ("anyOf", "oneOf", "allOf")
# Keys whose value is one subschema, a list of subschemas, or a map of name → subschema.
_ONE = ("items", "additionalProperties", "not", "contains", "propertyNames", "if", "then", "else",
        "additionalItems", "unevaluatedProperties", "unevaluatedItems")
_MANY = ("anyOf", "oneOf", "allOf", "prefixItems")
_MAP = ("properties", "patternProperties", "dependentSchemas")
_OPENAI_DROPPED = ("pattern",)


def for_tool(name: Any, params: Any, provider: str) -> Any:
    """What a provider sends as one tool's parameters: an `mcp_*` tool's normalised, any other
    tool's exactly as given (built-in schemas are written for every provider already)."""
    return normalise(params, provider) if isinstance(name, str) and name.startswith("mcp_") else params


def index_in(text: str, pattern) -> int | None:
    """The tool position a provider's error names (`pattern` has one group), or None."""
    match = pattern.search(text or "")
    return int(match.group(1)) if match else None


def normalise(schema: Any, provider: str) -> dict:
    """`schema` reshaped for `provider` ("anthropic", "openai" or "gemini"); never the same
    object, never raises. Anything that is not a non-empty object becomes an empty object."""
    if not isinstance(schema, dict) or not schema:
        return {"type": "object", "properties": {}}
    schema = json.loads(json.dumps(schema))           # a private copy; the input stays as it was
    defs = {**(schema.get("definitions") or {}), **(schema.get("$defs") or {})}
    out = _inline(schema, defs, ())
    out.pop("$defs", None)
    out.pop("definitions", None)
    out = _merge_top(out)
    out = _walk(out, provider)
    out.setdefault("type", "object")
    return _sorted(out)


def _note(schema: dict, text: str) -> None:
    schema["description"] = f"{schema.get('description', '')} {text}".strip()


def _inline(node: Any, defs: dict, seen: tuple[str, ...]) -> Any:
    if isinstance(node, list):
        return [_inline(item, defs, seen) for item in node]
    if not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if isinstance(ref, str):
        name = ref.rsplit("/", 1)[-1]
        if ref.startswith(("#/$defs/", "#/definitions/")) and name in defs:
            if name in seen:
                return {"type": "object", "description": f"(recursive: another {name}, any shape accepted)"}
            target = _inline(defs[name], defs, (*seen, name))
            rest = {k: _inline(v, defs, seen) for k, v in node.items() if k != "$ref"}
            return {**target, **rest} if isinstance(target, dict) else target
    return {k: _inline(v, defs, seen) for k, v in node.items()}


def _merge_top(schema: dict) -> dict:
    found = [key for key in _COMBINERS if isinstance(schema.get(key), list)]
    if not found:
        return schema
    out = {k: v for k, v in schema.items() if k not in _COMBINERS}
    properties = dict(out.get("properties") or {})
    required = list(out.get("required") or [])
    words = []
    for key in found:
        branches = [b for b in schema[key] if isinstance(b, dict)]
        for branch in branches:
            for name, sub in (branch.get("properties") or {}).items():
                properties.setdefault(name, sub)
        sets = [list(b.get("required") or []) for b in branches]
        if key == "allOf":
            joined = [name for s in sets for name in s]
        else:
            joined = [name for name in (sets[0] if sets else []) if all(name in s for s in sets[1:])]
        required += [name for name in joined if name not in required]
        if key != "allOf" and branches:
            shapes = " | ".join(", ".join(s) or "(nothing required)" for s in sets)
            words.append(f"Give exactly the fields of one of these shapes ({'any' if key == 'anyOf' else 'one'} "
                         f"of): {shapes}.")
    out["type"], out["properties"] = "object", properties
    if required:
        out["required"] = required
    else:
        out.pop("required", None)
    for text in words:
        _note(out, text)
    return out


def _walk(node: Any, provider: str) -> Any:
    if not isinstance(node, dict):
        return node
    out = dict(node)
    out.pop("$schema", None)
    kind = out.get("type")
    if isinstance(kind, list):
        others = [t for t in kind if t != "null"]
        if len(others) == 1:
            out["type"] = others[0]
            if "null" in kind:
                _note(out, "May be null.")
        else:
            out.pop("type")
            _note(out, f"Type: {' or '.join(map(str, others))}" + (", or null." if "null" in kind else "."))
    if provider == "openai":
        for key in _OPENAI_DROPPED:
            if isinstance(out.get(key), str):
                _note(out, f"Must match the regular expression {out.pop(key)}.")
    for key in _ONE:
        if isinstance(out.get(key), dict):
            out[key] = _walk(out[key], provider)
        elif key == "items" and isinstance(out.get(key), list):
            out[key] = [_walk(item, provider) for item in out[key]]
    for key in _MANY:
        if isinstance(out.get(key), list):
            out[key] = [_walk(item, provider) for item in out[key]]
    for key in _MAP:
        if isinstance(out.get(key), dict):
            out[key] = {name: _walk(sub, provider) for name, sub in out[key].items()}
    return out


def _sorted(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _sorted(node[k]) for k in sorted(node)}
    if isinstance(node, list):
        return [_sorted(item) for item in node]
    return node
