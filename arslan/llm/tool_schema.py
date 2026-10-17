"""An MCP tool's parameter schema, reshaped to what the providers accept (0.1.62 F3).

Field report 2026-10-14: one MCP server's schemas failed every chat. Anthropic refused a
top-level `anyOf` ("input_schema does not support oneOf, allOf, or anyOf at the top level"),
DeepSeek refused a `pattern` it could not compile; one bad tool rejects the whole request.
Servers write full JSON Schema; providers accept a subset, and each a different one.

`normalise` is pure (no network, no database) and only ever applied to `mcp_*` tools as they
are sent: what discovery stored stays verbatim. Built-in tools are never passed through it.
For every provider family:

- a top-level anyOf / oneOf / allOf becomes one object: properties joined (a field the branches
  shape differently keeps every shape: its const/enum values merged into one enum, otherwise an
  anyOf at the field), `required` the keys every branch requires (allOf: any branch requires), the
  shapes kept in words;
- local `$ref`s (`#/$defs/…`, `#/definitions/…`) are inlined within a depth and size budget; a
  cycle, a ref it cannot resolve, or one past the budget becomes a loose object, said in words;
  `$defs` go everywhere;
- `type: [X, "null"]` becomes X ("may be null" in the description); two or more non-null
  types drop `type` and name them in the description;
- `$schema` goes.

OpenAI-compatible endpoints (DeepSeek and others) also lose every `pattern` and
`patternProperties` (both regular expressions), written into the description instead. Which other keywords a given endpoint refuses is not known (not checked
against each vendor); `pattern` is the one seen in the field.

The same input always gives the same output, keys sorted: a changed tool block changes the
prompt-cache prefix. Results are cached by the schema's hash (every request reshapes every MCP
tool, on the event loop).
"""
from __future__ import annotations

import hashlib
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
    raw = json.dumps(schema, sort_keys=True, default=str)
    key = (provider, hashlib.sha256(raw.encode()).hexdigest())
    if key not in _CACHE:
        if len(_CACHE) >= _CACHE_MAX:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[key] = json.dumps(_normalise(json.loads(raw), provider))
    return json.loads(_CACHE[key])                   # a private copy each time


_CACHE: dict[tuple[str, str], str] = {}
_CACHE_MAX = 2048
# `$ref` inlining budget: how many refs deep one path may go, and how many nodes the inlined schema
# may hold in all. A 1.8 KB schema whose levels each referenced the next twice grew to 17 MB.
_REF_DEPTH = 8
_NODE_BUDGET = 5_000


def _normalise(schema: dict, provider: str) -> dict:
    defs = {**(schema.get("definitions") or {}), **(schema.get("$defs") or {})}
    out = _inline(schema, defs, (), [_NODE_BUDGET])
    out = _merge_top(out)
    out = _walk(out, provider)
    out.setdefault("type", "object")
    return _sorted(out)


def _note(schema: dict, text: str) -> None:
    schema["description"] = f"{schema.get('description', '')} {text}".strip()


def _loose(why: str) -> dict:
    return {"type": "object", "description": f"({why}; any shape accepted)"}


def _inline(node: Any, defs: dict, seen: tuple[str, ...], budget: list[int]) -> Any:
    budget[0] -= 1
    if budget[0] < 0:
        return _loose("too large to spell out")
    if isinstance(node, list):
        return [_inline(item, defs, seen, budget) for item in node]
    if not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if isinstance(ref, str):
        prefix, _, name = ref.rpartition("/")
        if prefix not in ("#/$defs", "#/definitions") or name not in defs:
            return _loose(f"a reference that cannot be followed here: {ref[:80]}")
        if name in seen:
            return _loose(f"recursive: another {name}")
        if len(seen) >= _REF_DEPTH:
            return _loose(f"nested too deep: {name}")
        target = _inline(defs[name], defs, (*seen, name), budget)
        rest = {k: _inline(v, defs, seen, budget) for k, v in node.items() if k != "$ref"}
        return {**target, **rest} if isinstance(target, dict) else target
    return {k: _inline(v, defs, seen, budget) for k, v in node.items() if k not in ("$defs", "definitions")}


def _same_field(shapes: list) -> Any:
    """One field the branches describe differently: their const/enum values as one enum when that
    is all they say, otherwise every distinct shape under anyOf."""
    distinct = []
    for shape in shapes:
        if shape not in distinct:
            distinct.append(shape)
    if len(distinct) == 1:
        return distinct[0]
    if all(isinstance(d, dict) and ("const" in d or "enum" in d)
           and set(d) <= {"const", "enum", "type", "description"} for d in distinct):
        values = []
        for d in distinct:
            for value in ([d["const"]] if "const" in d else list(d.get("enum") or [])):
                if value not in values:
                    values.append(value)
        merged = {"enum": values}
        kinds = {d.get("type") for d in distinct}
        if len(kinds) == 1 and None not in kinds:
            merged["type"] = kinds.pop()
        return merged
    return {"anyOf": distinct}


def _merge_top(schema: dict) -> dict:
    found = [key for key in _COMBINERS if isinstance(schema.get(key), list)]
    if not found:
        return schema
    out = {k: v for k, v in schema.items() if k not in _COMBINERS}
    shapes: dict[str, list] = {name: [sub] for name, sub in (out.get("properties") or {}).items()}
    required = list(out.get("required") or [])
    words = []
    for key in found:
        branches = [b for b in schema[key] if isinstance(b, dict)]
        for branch in branches:
            for name, sub in (branch.get("properties") or {}).items():
                shapes.setdefault(name, []).append(sub)
        sets = [list(b.get("required") or []) for b in branches]
        if key == "allOf":
            joined = [name for s in sets for name in s]
        else:
            joined = [name for name in (sets[0] if sets else []) if all(name in s for s in sets[1:])]
        required += [name for name in joined if name not in required]
        if key != "allOf" and branches:
            described = []
            for branch, needed in zip(branches, sets):
                optional = [n for n in (branch.get("properties") or {}) if n not in needed]
                text = ", ".join(needed) or "nothing required"
                if optional:
                    text += f" (optional: {', '.join(optional)})"
                described.append(text)
            words.append(f"Accepts one of these shapes ({key}): {' | '.join(described)}.")
    properties = {name: _same_field(subs) for name, subs in shapes.items()}
    for name, merged in properties.items():
        if isinstance(merged, dict) and "enum" in merged and len(shapes[name]) > 1:
            words.append(f"`{name}` is one of: {', '.join(json.dumps(v) for v in merged['enum'])}.")
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
    out = {k: v for k, v in node.items() if k not in ("$schema", "$defs", "definitions")}
    kind = out.get("type")
    if isinstance(kind, list):
        others = [t for t in kind if t != "null"]
        if not others:
            out["type"] = "null"
        elif len(others) == 1:
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
        if isinstance(out.get("patternProperties"), dict):
            names = ", ".join(out.pop("patternProperties"))
            _note(out, f"Extra fields whose names match {names} are accepted.")
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
