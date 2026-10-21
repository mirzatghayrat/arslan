"""K7 (v0.1.63): tools reached on demand, so a request does not carry every tool it could use.

Every request carries the resident table (arslan.RESIDENT) plus two tools of its own:
- `find_tools {query}` ranks the tools this turn may call but was not shown, and returns each one's
  first sentence and full parameters;
- `use_tool {name, arguments}` calls one of them. Arslan checks the arguments against that tool's own
  parameters, then the call goes on under the tool's real name: the same approval, trace and receipts
  as a direct call.

The table never changes inside a turn: Anthropic renders tools before the system text, so any change
there invalidates the whole cached prefix (K3). A tool used on demand joins the table from the next
turn of the same conversation, appended in first-use order and never sorted in or removed. That costs
one cache miss on the turn after a new tool is first used. The list lives in this process; after a
restart the model searches again.
"""
from __future__ import annotations

import json
import re
from collections import OrderedDict

CAP_PER_CONVERSATION = 12          # ⓪Plan, Q6: past this a tool stays reachable through use_tool only
_CONVERSATIONS = 128
_used: OrderedDict[str, list[str]] = OrderedDict()

FIND_TOOLS = {"key": "find_tools", "description":
    "Find a tool that is not in your list: other built-in tools (schedules, charts, memory notes, "
    "Shortcuts, SSH, …) and the tools of the user's connected MCP servers. args: {query} — a few English "
    "keywords, e.g. \"github issue\", \"schedule recurring\", \"calendar event\" (tool descriptions are "
    "in English). Returns up to 5 tools with what each does and its parameters; then call one with "
    "use_tool."}
USE_TOOL = {"key": "use_tool", "description":
    "Call a tool that find_tools returned. args: {name, arguments} — arguments exactly as that tool's "
    "parameters say. It runs as a direct call would, with the same approvals. From the next turn the tool "
    "is in your list and you call it directly."}
OWN = frozenset({"find_tools", "use_tool"})

_WORD = re.compile(r"[a-z0-9]+")
_CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯]+")


def note_used(conversation_id: str | None, key: str) -> None:
    if not conversation_id:
        return
    keys = _used.setdefault(conversation_id, [])
    _used.move_to_end(conversation_id)
    if key not in keys and len(keys) < CAP_PER_CONVERSATION:
        keys.append(key)
    while len(_used) > _CONVERSATIONS:
        _used.popitem(last=False)


def used(conversation_id: str | None) -> list[str]:
    return list(_used.get(conversation_id or "", ()))


def _words(text: str) -> set[str]:
    text = (text or "").lower().replace("_", " ")
    words = set(_WORD.findall(text))
    for run in _CJK.findall(text):
        words |= {run[i:i + 2] for i in range(len(run) - 1)} or {run}
    return words


def _first_sentence(text: str) -> str:
    text = " ".join((text or "").split())
    end = re.search(r"(?<=[.!?。！？])\s", text)
    return (text[:end.start()] if end else text)[:240]


def find(query: str, candidates: list[dict], params_of, *, limit: int = 5) -> dict:
    """Rank `candidates` (the callable tools the request was not shown) against `query`: words of the
    name count twice, words of the description once. Ties keep the candidates' order (built-ins as
    `_every_tool` lists them, MCP tools by Tool.key), so the same query always answers the same way."""
    from server.orchestrator.untrusted import wrap_external
    wanted = _words(query)
    scored = []
    for index, tool in enumerate(candidates):
        score = 2 * len(wanted & _words(tool["key"])) + len(wanted & _words(tool.get("description", "")))
        if score:
            scored.append((-score, index, tool))
    scored.sort(key=lambda row: (row[0], row[1]))
    found = []
    for _, _, tool in scored[:limit]:
        entry = {"about": _first_sentence(tool.get("description", "")), "parameters": params_of(tool)}
        if tool["key"].startswith("mcp_"):
            # A server wrote this text: data, never instructions (tool poisoning).
            found.append({"name": tool["key"], "from_server": wrap_external(json.dumps(entry, ensure_ascii=False))})
        else:
            found.append({"name": tool["key"], **entry})
    if found:
        return {"ok": True, "external": False, "tools": found,
                "summary": f"{len(found)} tool(s) found",
                "note": "Call one with use_tool {name, arguments}."}
    names = [t["key"] for t in candidates]
    return {"ok": True, "external": False, "tools": [], "summary": "no tool matched",
            "note": "No tool matched those words. Try other English keywords. Tools you can reach: "
                    + ", ".join(names[:30]) + (f" and {len(names) - 30} more" if len(names) > 30 else "")}


def unwrap(args: dict, callable_by_key: dict[str, dict], shown: set[str], params_of, schema_problem):
    """(name, arguments, None) for a valid use_tool call, else (None, None, the refusal's result)."""
    name = str(args.get("name") or "").strip()
    arguments = args.get("arguments") if isinstance(args.get("arguments"), dict) else {}

    def refuse(code: str, error: str):
        return None, None, {"ok": False, "external": False, "code": code, "error": error}
    if name in OWN:
        return refuse("tool_unavailable", f"{name} cannot be called through use_tool.")
    if name in shown:
        return refuse("tool_unavailable", f"{name} is already in your tool list: call it directly.")
    tool = callable_by_key.get(name)
    if tool is None:
        return refuse("tool_unavailable",
                      f"There is no tool named {name!r} that you can use here. Use find_tools to look one up.")
    problem = schema_problem(arguments, params_of(tool))
    if problem:
        return refuse("invalid_arguments", f"Invalid arguments for {name}: {problem}. Nothing was executed; "
                                           "send use_tool again with corrected arguments.")
    return name, arguments, None


def conversation(fallback: str | None) -> str | None:
    """The conversation a turn's on-demand tools are kept under: the one `_arslan_tools` reads."""
    from server.services import personal_context
    context = personal_context.current()
    return (context.conversation_id if context else None) or fallback
