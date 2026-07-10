"""Bounded mini agent-loop, spawn-agnostic (Phase 1 of the capability/MCP layer).

Output protocol per step (model replies with ONE of):
  plain text                                      -> final answer
  {"tool": "<key>", "args": {...}}                -> tool call
  {"escalate": {"kind","need","context"}}         -> end turn, raise to caller
"""
from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable

from server.orchestrator import run_trace
from server.orchestrator.json_protocol import first_json_object, parse_json_object
from server.orchestrator.untrusted import GUARD_NOTE, wrap_external
from server.registry.executors import EXECUTORS, resolve_executor
from server.services.llm_factory import build_adapter

# P4 tuning: 5 was too tight for real research turns (the finance-primer live run burned
# 4 searches + 1 extract + 1 chart and hit the forced step). 8 gives long tasks headroom
# while a runaway loop stays bounded; the budget-exhausted salvage guard still backstops.
MAX_TOOL_CALLS = 8
TOOL_TIMEOUT_S = 20.0

_PROTOCOL = (
    "\n\nTOOL PROTOCOL: To use a tool, reply with ONLY this JSON and nothing else — NO text "
    "before or after it, not even '好的' / 'let me search'; the JSON object must be the ENTIRE "
    "message: "
    '{{"tool": "<name>", "args": {{...}}}}. Available tools:\n{tool_lines}\n'
    "To escalate a missing capability or missing data, reply with ONLY: "
    '{{"escalate": {{"kind": "data" or "capability", "need": "<what outcome you need>", '
    '"context": "<why>"}}}} — describe the OUTCOME you need, never an operation to run.\n'
    "If a tool reports it is not configured, tell the user plainly and answer with what you know.\n"
    "Otherwise reply with your final answer as normal text.\n\n"
    f"{GUARD_NOTE}"
)

ResolveTools = Callable[[], Awaitable[list[dict]]]
ConfirmCommand = Callable[[str, list], Awaitable[bool]]


def _get_adapter():
    """Indirection so tests can stub adapter construction."""
    return build_adapter(role="execute")


def _summarize_result(result: dict) -> str:
    if not result.get("ok"):
        return str(result.get("error") or "failed")
    if result.get("summary"):
        return str(result["summary"])
    if "results" in result:
        return f"{len(result['results'])} results"
    if "text" in result:
        return f"{len(result['text'])} chars extracted"
    return "ok"


_CLAIMS_CHART_RE = re.compile(
    r"上图|已生成图|已为您生成|已绘制|图表已|chart (is )?(generated|ready|done)|here('s| is) (the|your) chart",
    re.IGNORECASE)
_CLAIMS_SEARCH_RE = re.compile(
    r"我搜索|搜索了|查到了?|获取到(了|的)?数据|我已搜|i (just )?searched|let me search|i looked it up",
    re.IGNORECASE)
# Widened after two live evasions ("PPT 已正式生成并交付", "共10页…可直接下载"): allow filler
# between the deck-noun, the 已/成功/正式 marker, and the delivery verb — in either order.
_CLAIMS_DECK_RE = re.compile(
    r"(PPTX?|pptx|deck|幻灯片?|演示文稿)[^\n。;]{0,12}(已|成功|正式)[^\n。;]{0,8}(生成|交付|完成|创建|做好|输出)"
    r"|已[^\n。;]{0,6}生成[^\n。;]{0,8}(PPTX?|pptx|deck|幻灯|演示)"
    r"|已生成并交付"
    r"|(可|供)(直接)?下载[^\n。;]{0,10}(PPTX?|pptx|\.pptx|deck|幻灯|演示文稿)"
    r"|(PPTX?|pptx|deck|幻灯片?|演示文稿)[^\n。;]{0,16}可(直接)?下载"
    r"|(deck|pptx|presentation)[^\n.;]{0,24}(generated|created|ready|done|delivered)",
    re.IGNORECASE)


def _claims_chart(text: str) -> bool:
    return bool(_CLAIMS_CHART_RE.search(text or ""))


def _claims_search(text: str) -> bool:
    return bool(_CLAIMS_SEARCH_RE.search(text or ""))


def _claims_deck(text: str) -> bool:
    return bool(_CLAIMS_DECK_RE.search(text or ""))


# Chart-as-code-fence: instead of calling render_chart, the model draws a DATA chart by writing a
# Markdown code block (```mermaid xychart-beta / ```mermaid pie / ```chart / bare ```xychart-beta).
# The UI shows a raw code block with a "Copy" button, not a real ECharts chart. Distinct from
# _claims_chart (which catches "上图已生成" claims): here the model neither claims nor promises — it
# literally hands over chart source. Matches ONLY data charts render_chart can produce; a mermaid
# flowchart / sequenceDiagram is a legit diagram render_chart CANNOT draw, so it must not trip this.
_DRAWS_CHART_FENCE_RE = re.compile(
    r"```\s*chart\b"                                       # ```chart generic fence
    r"|```\s*(?:mermaid\s+)?xychart[\w-]*"                 # ```xychart-beta or ```mermaid xychart...
    r"|```\s*mermaid\b[\s\S]{0,80}?"                       # ```mermaid then, in the block head,
    r"(?:xychart-beta|\bpie\s+(?:title|showData))",        #   an xychart/pie declaration
    re.IGNORECASE)


def _draws_chart_fence(text: str) -> bool:
    return bool(_DRAWS_CHART_FENCE_RE.search(text or ""))


# Forward-promise patterns: the model ends its turn PROMISING a future tool action instead of
# emitting the tool JSON ("数据正在路上", "马上为您绘制…", "我这就去搜索", "STEP 2: 调用 web_extract",
# "let me search"). Distinct from the _CLAIMS_* regexes above, which catch the inverse — claiming
# a result already produced. Tight on purpose (anchored on first-person / imperative + a tool-action
# verb) so a complete answer that merely mentions next steps doesn't trip it.
_PROMISES_ACTION_RE = re.compile(
    r"正在(为您|帮您|努力)?\s*(路上|搜索|查询|抓取|获取|拉取|加载|生成|绘制|出图|制作)"
    r"|数据\s*(正在|马上|即将|这就)\s*(路上|赶来|送达|生成|呈现)"
    r"|(马上|这就|现在就|立刻|立即|即将)\s*(去|来)?\s*(为您|帮您|给您)?\s*(搜索|查询|查一下|抓取|获取|拉取|生成|绘制|出图|画|制作|呈现|调用)"
    # first-person promise: 我来/让我/现在让我(继续) + a tool-action verb. Anchored on 我/让我 so a
    # completed answer that says "接下来你可以自行搜索" (second-person) never trips it.
    r"|(现在)?\s*(我|让我)\s*(来|去|先|这就|马上|现在就|继续)?\s*(为您|帮您)?\s*"
    r"(搜索|查|查询|抓取|获取|拉取|绘制|生成|画|制作|调用)"
    # promising a chart/figure: 生成/绘制/画/制作 … a NAMED chart type. Must be a specific chart noun
    # (图表/趋势图/柱状图/…), NOT the bare "图" — bare "画图" is the render_chart CAPABILITY's common
    # name and legitimately appears in capability answers (e.g. "我有内置的…画图"); matching it there
    # falsely rejects a good answer into the digest/继续 floor.
    r"|(以便|接着|然后)?\s*(生成|绘制|画|制作|输出)\s*[^。\n]{0,8}(图表|趋势图|全景图|示意图|柱状图|折线图|饼图|散点图)"
    # STEP narration: 'STEP <anything-short> 调取/搜索/获取/生成…' — the icon/number between STEP and
    # the verb is arbitrary (we saw 'STEP <icon> 调取各项目详情'), so match loosely.
    r"|STEP\s*\S{0,4}\s*(调用|调取|搜索|抓取|获取|查询|绘制|生成|call|search|fetch|generate)"
    r"|第\s*[一二三四五六七八九十\d]+\s*步\s*[:：]?\s*(调用|调取|搜索|抓取|获取)"
    r"|(下一步|接下来)\s*[，,：:]?\s*(我|让我)\s*(会|要|将|就|继续)?\s*(搜索|查询|抓取|获取|绘制|生成|调用)"
    r"|调用\s*(web_search|web_extract|render_chart|render_deck)"
    r"|(生成|制作|输出|导出)\s*[^。\n]{0,6}(deck|pptx|\.pptx|幻灯|演示|ppt)"
    r"|let me (search|look this up|fetch|pull|grab|draw|generate|chart|get the data)"
    r"|i(?:'ll| will| am going to|'m going to)\s+(?:now\s+|quickly\s+|go\s+)?"
    r"(search|fetch|pull|retrieve|draw|generate|chart|look up|gather)",
    re.IGNORECASE)


def _promises_action(text: str) -> bool:
    return bool(_PROMISES_ACTION_RE.search(text or ""))


# A genuine deferral ("让我继续查各项目的 star 数" with no tool call and no real content) is SHORT.
# A substantive answer that merely MENTIONS action verbs — a capability rundown ("我能搜索、抓取网页、
# 画图表"), a plan, a summary that describes what tools do — is long and IS the answer. Rejecting the
# latter as "still promising action" was the bug behind: capability answers → digest/继续 floor, and
# good synthesized answers bounced. So only treat a promise as a deferral to reject when it's ALSO
# short/stub-like; keep any substantive answer regardless of the action words in it.
_DEFERRAL_MAX = 160


def _is_deferral_stub(text: str) -> bool:
    t = (text or "").strip()
    return len(t) < _DEFERRAL_MAX and _promises_action(t)


def _is_protocol_json(text: str) -> bool:
    """True if `text` IS a tool/escalate protocol object (a whole-message tool call/escalation),
    rather than prose. INVARIANT: such JSON must never be surfaced to the user as an answer —
    it means the model emitted a tool call where prose was required (typically the forced
    'answer now' step, or a malformed/truncated tool call the parser couldn't dispatch)."""
    s = (text or "").lstrip()
    if not s.startswith("{"):
        return False
    obj = first_json_object(s) or parse_json_object(s)
    if isinstance(obj, dict) and (obj.get("tool") or isinstance(obj.get("escalate"), dict)):
        return True
    # unparseable but clearly a protocol fragment (e.g. a stream cut off mid tool call)
    head = s[:160]
    return '"tool"' in head or '"escalate"' in head


# Appended to the system prompt for the one text-only salvage attempt (below). The model has
# already ignored 'answer now, text only' at least once, so this is maximally explicit.
_SALVAGE_SYS = (
    "\n\nYou have NO tools left and cannot call any tool. Reply with your FINAL answer as plain "
    "text ONLY. Do NOT output JSON, a tool call, or an escalation of any kind. Use the TOOL "
    "RESULTs already in this conversation; if the data is incomplete, say so briefly and give "
    "your best answer with what you have."
)


def _fallback_message(user_content: str) -> str:
    """Honest last-resort answer when even the salvage attempt won't produce prose. Language
    inferred from the request so a Chinese user doesn't get an English apology (or vice-versa).
    Wording is deliberately PER-TURN ("这一轮") — a live incident showed 'session exhausted'
    phrasing poisons later turns: the model reads it in history and role-plays permanent
    exhaustion even though every dispatch starts with a fresh budget."""
    cjk = any("一" <= ch <= "鿿" for ch in (user_content or ""))
    if cjk:
        # User-facing copy: NO internal mechanics. "工具调用次数用完" confused a live tester
        # ("什么意思?误导性很强") and reads like a permanent outage. Just: unfinished + how
        # to continue.
        return "这个任务这一轮还没做完。回复“继续”我就接着做;也可以把范围缩小一点,会更快。"
    return ("I didn't finish this one in a single round. Reply \"continue\" and I'll keep "
            "going — or narrow the scope a little for a faster answer.")


def _evidence_digest(tool_trace: list, *, max_items: int = 8, snippet: int = 240,
                     total: int = 2600) -> str:
    """Deterministic (no-LLM) salvage of a spent round: compress the OK tool results
    into a findings block. Without this, a continuation restarts research from ZERO —
    live incident: 3 rounds × 8 searches on the same task, nothing ever accumulated,
    the user kept being asked to press 继续. The digest rides inside the round's final
    message, so the next round sees the evidence in chat history."""
    lines: list[str] = []
    for step in tool_trace[-max_items:]:
        res = step.get("result") or {}
        if not res.get("ok"):
            continue
        args = step.get("args") or {}
        head = str(args.get("query") or args.get("url") or "")[:60]
        payload = {k: v for k, v in res.items() if k not in ("ok", "artifact", "external")}
        body = json.dumps(payload, ensure_ascii=False)[:snippet]
        lines.append(f"- {step.get('tool')}({head}): {body}")
    return "\n".join(lines)[:total]


def _fallback_with_digest(user_content: str, tool_trace: list) -> str:
    """Fallback message + whatever evidence this round actually gathered. The 【阶段性发现】
    marker matters: arslan._looks_like_refusal treats a marked message as substantive
    (carried forward), not as a refusal to be dropped."""
    base = _fallback_message(user_content)
    digest = _evidence_digest(tool_trace)
    if not digest:
        return base
    cjk = any("一" <= ch <= "鿿" for ch in (user_content or ""))
    header = ("【阶段性发现】(本轮已查到的资料,尚未成稿)" if cjk
              else "[Findings so far] (gathered this round, not yet written up)")
    return f"{header}\n{digest}\n\n{base}"


# PB-3: turn-scoped MCP degradation. When an `mcp_*` tool fails this many times
# CONSECUTIVELY within one run_native invocation, its recorded tool result gains a
# deterministic hint steering the model to the equivalent BUILTIN tool. Guide, never
# hard-switch — the model stays free to disagree. 条件2: the counter dict lives in
# run_native's locals (a fresh invocation = a fresh turn = count 0), and a success
# resets that tool's streak.
_MCP_FAIL_HINT_AT = 2


def _mcp_degrade_hint(n: int) -> str:
    return (f"⚠ 此 MCP 工具本回合已连续失败 {n} 次。请改用等价的内置工具完成任务"
            "(网页抓取用 web_extract,搜索用 web_search);不要再重试该 MCP 工具。")


def _record_tool_result(tool_key, args, result, emit, tool_trace, assistant_content, convo,
                        mcp_fail_counts: dict | None = None) -> dict:
    emit({"type": "tool_result", "tool": tool_key, "ok": bool(result.get("ok")),
          "summary": _summarize_result(result), "artifact": result.get("artifact")})
    tool_trace.append({"tool": tool_key, "args": args, "result": result})
    run_trace.record(tool=tool_key, args=args, result=result,
                      ok=bool(result.get("ok")), error=result.get("error"), ms=None)
    convo.append({"role": "assistant", "content": assistant_content})
    feedback = {k: v for k, v in result.items() if k != "artifact"}
    raw_payload = json.dumps(feedback, ensure_ascii=False)[:8000]
    framed = raw_payload if result.get("external") is False else wrap_external(raw_payload)
    # PB-3 degrade hint. Placement is deliberate: `framed` ends with DELIM_CLOSE, so the
    # hint sits AFTER the wrap_external data frame — it is OUR trusted framing (like the
    # "TOOL RESULT for X" header and the "Use this to continue" trailer), never inside
    # the untrusted region the GUARD_NOTE tells the model to distrust.
    hint = ""
    if mcp_fail_counts is not None:
        if result.get("ok"):
            mcp_fail_counts.pop(tool_key, None)          # success resets the streak
        elif tool_key.startswith("mcp_"):
            n = mcp_fail_counts[tool_key] = mcp_fail_counts.get(tool_key, 0) + 1
            if n >= _MCP_FAIL_HINT_AT:
                hint = "\n" + _mcp_degrade_hint(n)
    convo.append({"role": "user",
                  "content": f"TOOL RESULT for {tool_key}:\n{framed}{hint}"
                             "\nUse this to continue: call another tool, escalate, or give your final answer."})
    return result


async def _log_degrade_hint(conversation_id, tool_key, count) -> None:
    """PB-3 observability: one conversation_events row the FIRST time the degrade hint
    fires for a tool this turn (PB-4's warning wiring reads these). Fail-open — logging
    must never touch the turn."""
    try:
        from server.services import recap_service
        await recap_service.log_event(
            conversation_id, "mcp_degrade_hint",
            {"tool_key": tool_key, "count": count},
            f"MCP 工具 {tool_key} 本回合连续失败 {count} 次,已提示改用内置等价工具")
    except Exception:  # noqa: BLE001 — observability is never fatal
        pass


async def _dispatch_tool(tool_key, args, assistant_content, *, resolve_tools, emit,
                         tool_timeout_s, tool_trace, convo, confirm_command=None,
                         mcp_fail_counts: dict | None = None,
                         mcp_hint_logged: set | None = None,
                         conversation_id: str | None = None,
                         log_events: bool = True) -> dict:
    """Execute one tool (gated), emit its frames, record the trace, and append the
    assistant turn + framed tool result into convo. Returns the raw result dict.

    run_command is special: it requires per-command user confirmation via the injected
    confirm_command(command, argv) -> bool callback. No callback → refuse (safety default)."""
    emit({"type": "tool_call", "tool": tool_key,
          "args_summary": json.dumps(args, ensure_ascii=False)[:200]})

    if tool_key == "run_command":
        command = str(args.get("command") or "")
        argv = args.get("argv") if isinstance(args.get("argv"), list) else []
        if confirm_command is None:
            result = {"ok": False,
                      "error": "run_command requires user confirmation, which is not "
                               "available in this context"}
            return _record_tool_result(tool_key, args, result, emit, tool_trace,
                                        assistant_content, convo,
                                        mcp_fail_counts=mcp_fail_counts)
        approved = await confirm_command(command, argv)
        if not approved:
            result = {"ok": False, "error": "user declined this command"}
            return _record_tool_result(tool_key, args, result, emit, tool_trace,
                                        assistant_content, convo,
                                        mcp_fail_counts=mcp_fail_counts)

    live = {t["key"] for t in await resolve_tools()}
    executor = (await resolve_executor(tool_key)) if tool_key in live else None
    if executor is None:
        result = {"ok": False,
                  "error": f"tool '{tool_key}' is not available to you; you may escalate a need instead"}
    else:
        try:
            result = await asyncio.wait_for(executor.execute(args), timeout=tool_timeout_s)
        except TimeoutError:
            result = {"ok": False, "error": f"tool '{tool_key}' timed out"}
        except Exception as exc:  # noqa: BLE001
            result = {"ok": False, "error": f"tool '{tool_key}' failed: {exc}"}
    out = _record_tool_result(tool_key, args, result, emit, tool_trace,
                              assistant_content, convo, mcp_fail_counts=mcp_fail_counts)
    if (log_events and mcp_fail_counts is not None and mcp_hint_logged is not None
            and mcp_fail_counts.get(tool_key, 0) >= _MCP_FAIL_HINT_AT
            and tool_key not in mcp_hint_logged):
        # log_events=False (E3 hermetic replay): the degrade counter still advances (the
        # guard runs), only the ConversationEvent write is suppressed. In replay MCP tools
        # are filtered out anyway, so this is belt-and-suspenders against a hallucinated key.
        mcp_hint_logged.add(tool_key)
        await _log_degrade_hint(conversation_id, tool_key, mcp_fail_counts[tool_key])
    return out


async def run(
    *,
    system: str,
    user_content: str,
    history: list[dict],
    emit: Callable[[dict], None],
    on_chunk: Callable[[str], None],
    resolve_tools: ResolveTools,
    allow_escalation: bool = True,
    max_tool_calls: int = MAX_TOOL_CALLS,
    tool_timeout_s: float = TOOL_TIMEOUT_S,
    force_tools: bool = False,
    confirm_command: ConfirmCommand | None = None,
) -> dict:
    """Run the loop. Returns {"final": str|None, "escalation": dict|None, "tool_trace": list}.
    Exactly one of final/escalation is non-None. resolve_tools() returns the currently
    live tool descriptors [{"key","description"}] — re-awaited per call so grants can expire.

    PB-3 note: the MCP consecutive-failure degrade hint is wired in run_native ONLY —
    every production path (Arslan answer path + spawn_loop) runs run_native; this legacy
    text-protocol loop survives for its regression tests and stays byte-identical."""
    adapter = _get_adapter()
    a = await adapter if hasattr(adapter, "__await__") else adapter

    wired = await resolve_tools()
    tool_lines = "\n".join(f"- {t['key']}: {t['description']}" for t in wired) or "- (none live)"
    system = system + _PROTOCOL.format(tool_lines=tool_lines)

    convo = list(history) + [{"role": "user", "content": user_content}]
    tool_trace: list[dict] = []
    fired: set[str] = set()          # tool keys actually executed this run
    forced_retry: set[str] = set()   # tools we've already forced a retry for (bound the loop)
    promise_retries = 0              # forward-promise nudges issued this run (bounded below)
    wired_keys = {t["key"] for t in wired}

    # Proactive deterministic forcing (spawn path only): when force_tools=True and the
    # classifier says the task needs web_search, run it ourselves before the model's first
    # turn — no model dependence. Only web_search is force-run (its call is a deterministic
    # {"query": ...} we can build from the task); other tools still go through the model.
    if force_tools and "web_search" in wired_keys and "web_search" in EXECUTORS:
        from server.services import tool_intent
        try:
            intent = await tool_intent.classify(user_content, sorted(wired_keys))
        except Exception:  # noqa: BLE001
            intent = None
        if intent is not None and intent.needs and intent.tool == "web_search":
            q = (intent.query or user_content)[:400]
            await _dispatch_tool("web_search", {"query": q},
                                 json.dumps({"tool": "web_search", "args": {"query": q}}, ensure_ascii=False),
                                 resolve_tools=resolve_tools, emit=emit, tool_timeout_s=tool_timeout_s,
                                 tool_trace=tool_trace, convo=convo)
            fired.add("web_search")

    for step in range(max_tool_calls + 1):
        forced = step == max_tool_calls
        sys_now = system if not forced else (
            system + "\n\nTool budget exhausted: answer now with what you have. Text only."
        )
        raw = ""
        shown = 0  # chars already forwarded to on_chunk — never includes a '{'-led tool/escalate JSON
        async for piece in a.chat_stream(sys_now, convo[-1]["content"], history=convo[:-1]):
            raw += piece
            if not raw.lstrip():
                continue                           # still only whitespace; keep accumulating
            # Structural separation (no first-char guessing): stream visible prose ONLY up to the
            # first '{'. Any tool/escalate JSON — even when the model prepends prose like '好的我去搜'
            # — is buffered from the '{' onward and never shown. parse_json_object (below) rescues an
            # embedded object, so the tool still fires; the raw JSON just never reaches the user.
            brace = raw.find("{")
            visible_end = brace if brace != -1 else len(raw)
            if visible_end > shown:
                on_chunk(raw[shown:visible_end])
                shown = visible_end
        content = raw.strip()
        # first_json_object extracts the FIRST balanced {...} (handles prose + multiple objects,
        # e.g. '好我去搜{tool a}{tool b}' → dispatch tool a now, the rest on a later step).
        parsed = first_json_object(content) or parse_json_object(content)

        if not forced and isinstance(parsed, dict) and isinstance(parsed.get("escalate"), dict):
            if not allow_escalation:
                convo.append({"role": "assistant", "content": content})
                convo.append({"role": "user",
                              "content": "Escalation is not available right now; answer "
                                         "with what you have."})
                continue
            esc = parsed["escalate"]
            return {"final": None, "tool_trace": tool_trace,
                    "escalation": {"kind": str(esc.get("kind") or "data"),
                                   "need": str(esc.get("need") or "").strip(),
                                   "context": str(esc.get("context") or "").strip()}}

        if not forced and isinstance(parsed, dict) and parsed.get("tool"):
            tool_key = str(parsed["tool"])
            args = parsed.get("args") if isinstance(parsed.get("args"), dict) else {}
            await _dispatch_tool(tool_key, args, content, resolve_tools=resolve_tools,
                                 emit=emit, tool_timeout_s=tool_timeout_s,
                                 tool_trace=tool_trace, convo=convo,
                                 confirm_command=confirm_command)
            fired.add(tool_key)
            continue

        # A complete HTML document IN the reply IS the deliverable (HTML-first decks/
        # reports). Any "you claimed but didn't do it" retry would make the model re-answer
        # and the shorter second turn would REPLACE the doc as the persisted final — live
        # incident: a 7-slide HTML deck streamed fine, then a guard reprompt wiped it from
        # history. With the doc present, claims about it are true: skip all reactive guards.
        has_html_doc = "<!doctype html" in content.lower() and "</html>" in content.lower()

        # Reactive hallucination guard: the model claims a tool result it never produced this run,
        # or draws a chart as Markdown code instead of calling render_chart.
        if not forced and not has_html_doc:
            claimed = None
            reprompt = None
            chart_free = ("render_chart" in wired_keys and "render_chart" not in fired
                          and "render_chart" not in forced_retry)
            if _claims_chart(content) and chart_free:
                claimed = "render_chart"
                reprompt = (
                    "You claimed to have produced a chart, but you did NOT actually call render_chart "
                    "this turn — so there is no chart. Emit ONLY the render_chart tool JSON now, or "
                    "answer honestly WITHOUT claiming you made a chart.")
            elif _draws_chart_fence(content) and chart_free:
                claimed = "render_chart"
                reprompt = (
                    "You drew a chart as a Markdown code block (```mermaid xychart/pie or ```chart). "
                    "The user CANNOT see that as a real chart — it shows as raw code. Emit ONLY the "
                    "render_chart tool JSON now with this SAME data (args: {type, x:[labels], "
                    "series:[{name, values:[numbers]}]}); do NOT draw charts in markdown/mermaid.")
            elif (_claims_deck(content) and "render_deck" in wired_keys
                    and "render_deck" not in fired and "render_deck" not in forced_retry):
                claimed = "render_deck"
                reprompt = (
                    "You claimed the PPTX/deck was generated, but you did NOT actually call "
                    "render_deck this turn — so there is NO file and nothing to download. Emit ONLY "
                    "the render_deck tool JSON now (slides=[{layout, ...}]), or answer honestly "
                    "WITHOUT claiming a deck was produced.")
            elif _claims_deck(content) and "render_deck" not in wired_keys \
                    and "deck_honesty" not in forced_retry:
                # No deck tool at all — the claim is a pure fabrication. Force honesty
                # ("deck_honesty" is a pseudo-key that just bounds this retry to once).
                claimed = "deck_honesty"
                reprompt = (
                    "You claimed a PPTX/deck was produced, but you DO NOT have a deck tool — no "
                    "file exists and none can be made here. Answer honestly: say you cannot "
                    "produce a PPT file yourself, deliver the content as structured text, and "
                    "suggest asking an agent equipped with the Deck/PPTX capability. Respond in "
                    "the user's language. NEVER claim a file was generated.")
            elif (_claims_search(content) and "web_search" in wired_keys
                    and "web_search" not in fired and "web_search" not in forced_retry):
                claimed = "web_search"
                reprompt = (
                    "You claimed to have searched, but you did NOT actually call web_search this turn "
                    "— so there is no result. Emit ONLY the web_search tool JSON now, or answer "
                    "honestly WITHOUT claiming you used a tool.")
            if claimed:
                forced_retry.add(claimed)
                convo.append({"role": "assistant", "content": content})
                convo.append({"role": "user", "content": reprompt})
                continue

        # Forward-promise guard: the model ended its turn PROMISING a tool action ("数据正在路上",
        # "马上为您绘制", "现在让我获取…", "STEP 2: 调取…", "let me search") but emitted NO tool call —
        # so nothing ran and the user is left waiting on a promise. Only nag when a wired tool is still
        # unused (pure-chat spawns are never pushed to use tools), and at most twice per run (a single
        # nudge isn't enough for a model that narrates step-by-step before acting).
        if (not forced and not has_html_doc and promise_retries < 2
                and (wired_keys - fired) and _promises_action(content)):
            promise_retries += 1
            convo.append({"role": "assistant", "content": content})
            convo.append({"role": "user", "content":
                "You ended your turn PROMISING to do something ('正在路上' / '马上为您…' / 'STEP N: 调用…' "
                "/ 'let me search') but emitted NO tool call — so nothing actually ran and the user is left "
                "waiting on a promise. Do it NOW: emit ONLY the tool JSON to run it this turn, OR give your "
                "COMPLETE final answer with no promise of future action."})
            continue

        # INVARIANT (root-cause guard): the model may end its turn — especially the forced
        # 'answer now' step — emitting a tool/escalate JSON instead of prose (deepseek does this
        # after a web_extract timeout). The stream loop above withheld everything from the first
        # '{', so nothing has been shown yet. NEVER surface raw protocol JSON as the answer: make
        # ONE text-only salvage attempt, then fall back to an honest message. Covers web_extract
        # and every other tool, on any step, incl. malformed/truncated tool calls the parser
        # couldn't dispatch. (Prose-then-JSON never trips this: _is_protocol_json needs the
        # message to START with the object, and such prose already streamed via `shown`.)
        if _is_protocol_json(content):
            salvage = ""
            async for piece in a.chat_stream(sys_now + _SALVAGE_SYS, convo[-1]["content"],
                                             history=convo[:-1]):
                salvage += piece
            salvage = salvage.strip()
            final_text = (salvage if salvage and not _is_protocol_json(salvage)
                          else _fallback_with_digest(user_content, tool_trace))
            on_chunk(final_text)
            return {"final": final_text, "escalation": None, "tool_trace": tool_trace}

        # plain text = final answer (parsed was not a dispatchable tool/escalate)
        if isinstance(parsed, dict):
            # The model emitted a real JSON object that we did NOT dispatch (a non-tool dict, or
            # extra/garbled tool blobs after the first). It is protocol output, not prose — drop
            # it from BOTH display and the persisted final. The answer is the prose before it
            # (already streamed up to the first '{').
            brace = raw.find("{")
            final_text = raw[:brace].strip() if brace != -1 else content
            if not final_text:
                # nothing but a JSON object and no prose → show it rather than an empty reply
                final_text = content
                if shown < len(raw):
                    on_chunk(raw[shown:])
        else:
            # no valid JSON object: any '{' was ordinary prose → flush the unshown remainder
            if shown < len(raw):
                on_chunk(raw[shown:])
            final_text = content
        return {"final": final_text, "escalation": None, "tool_trace": tool_trace}

    raise AssertionError("unreachable")  # forced branch always returns


# ---------------------------------------------------------------------------
# Native tool-calling loop (run_native)
# ---------------------------------------------------------------------------
# Root-cause fix (spec: 2026-07-05-arslan-native-toolcall-loop-design.md): the old run()
# drives the model over a hand-rolled text protocol ("reply with ONLY JSON") and regex-parses
# the reply. DeepSeek prepends narration ("让我继续查…") which (1) leaks into the message and
# (2) gets mistaken for the final answer, ending the turn empty. Native tool-calling returns
# `content` (narration) and `tool_calls` (structured action) as SEPARATE fields on LLMResponse,
# so narration can NEVER be confused with the answer.
#
# This lives ALONGSIDE run() — run() and its 38 tests are untouched.

# Minimal OpenAI-format parameter schemas per known tool key. The executor re-validates args,
# so these can be loose; they exist only to nudge the model toward the right shape.
_NATIVE_PARAM_SCHEMAS: dict[str, dict] = {
    "web_search": {"type": "object",
                   "properties": {"query": {"type": "string"}},
                   "required": ["query"]},
    "web_extract": {"type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"]},
    "render_chart": {"type": "object",
                     "properties": {"type": {"type": "string"},
                                    "x": {"type": "array"},
                                    "series": {"type": "array"},
                                    "title": {"type": "string"}}},
    "render_deck": {"type": "object",
                    "properties": {"title": {"type": "string"},
                                   "slides": {"type": "array"}}},
    "run_command": {"type": "object",
                    "properties": {"command": {"type": "string"},
                                   "argv": {"type": "array"}},
                    "required": ["command"]},
    "create_skill": {"type": "object",
                     "properties": {"key": {"type": "string"},
                                    "name": {"type": "string"},
                                    "description": {"type": "string"},
                                    "body": {"type": "string"}}},
    "run_python": {"type": "object",
                   "properties": {"code": {"type": "string"}}},
    "ask_user_choice": {
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "options": {"type": "array", "minItems": 2, "maxItems": 4,
                        "items": {"type": "object",
                                  "properties": {"label": {"type": "string"},
                                                 "hint": {"type": "string"}},
                                  "required": ["label"]}},
        },
        "required": ["question", "options"],
    },
}

# PA-3: ask_user_choice is a TERMINAL tool (same pattern as `escalate`): a VALID call
# ends the turn — the caller renders a structured choice card (`clarify_options`) and
# the user's click advances the conversation. Validation is recoverable: a malformed
# call gets a tool error the model can react to (retry with 2-4 options, or answer).
CLARIFY_MIN_OPTIONS = 2
CLARIFY_MAX_OPTIONS = 4


def _parse_clarify_args(args: dict) -> tuple[dict | None, str | None]:
    """Validate + clamp ask_user_choice args.

    Returns ({question, options: [{label, hint}] (2-4)}, None) on success, or
    (None, recoverable-error-text) when the question is missing or fewer than
    2 distinct labelled options survive cleaning. Over-long lists clamp to 4."""
    question = str(args.get("question") or "").strip()
    options: list[dict] = []
    raw = args.get("options")
    if isinstance(raw, list):
        for o in raw:
            if isinstance(o, str):                 # some models send bare strings
                label, hint = o.strip(), ""
            elif isinstance(o, dict):
                label = str(o.get("label") or "").strip()
                hint = str(o.get("hint") or "").strip()
            else:
                continue
            if label and not any(x["label"] == label for x in options):
                options.append({"label": label, "hint": hint})
    if not question or len(options) < CLARIFY_MIN_OPTIONS:
        return None, ("ask_user_choice needs a question plus 2-4 DISTINCT options "
                      "(each {label, hint?}). Give at least 2 real options, or just "
                      "answer the user directly.")
    return {"question": question, "options": options[:CLARIFY_MAX_OPTIONS]}, None

_ESCALATE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "escalate",
        "description": "Raise a missing capability or missing data you cannot get with your "
                       "tools. Describe the OUTCOME you need, never an operation to run.",
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["data", "capability"]},
                "need": {"type": "string"},
                "context": {"type": "string"},
            },
            "required": ["need"],
        },
    },
}

# Appended to `system` in native mode. Curbs the "N tiny searches" pattern the old text loop
# suffered from — see spec §效率.
# General research discipline (domain-agnostic) — converges any gather-then-answer task with any
# single model, instead of fumbling N snippet searches on noisy results.
_NATIVE_EFFICIENCY = (
    "\n\nRESEARCH DISCIPLINE — be efficient and converge:\n"
    "1. web_search returns short SNIPPETS, not full data. Use it to LOCATE the best source, not to "
    "collect facts one query at a time.\n"
    "2. Do at most 1–2 broad searches, then web_extract the most authoritative page you found to get "
    "the real content — extracting one good source beats many snippet searches.\n"
    "3. Do NOT run several similar searches for the same thing, and do NOT chase individual data "
    "points with a separate search each. As soon as you can answer, ANSWER — stop searching.\n"
    "4. If the data you gathered is incomplete, give your best synthesis and note the gap in one "
    "line — never keep searching in circles."
)

# Framework-level convergence cap: after this many web_searches in one turn, further searches are
# refused and the model is pushed to extract a source or answer. Deterministic — it makes even a
# fumble-prone model stop the snippet spiral. (web_extract does not count; extracting IS the goal.)
_SEARCH_CAP = 3


_PERMISSIVE_PARAMS = {"type": "object", "properties": {}, "additionalProperties": True}


def _tool_params(t: dict) -> dict:
    """Resolve the OpenAI `parameters` schema for one tool dict.

    Precedence: built-in hardcoded schema (never clobbered) > the tool's stored
    `input_schema` (the JSON Schema captured at MCP discovery — an MCP tool with a
    real schema stops the model guessing arg names) > permissive fallback. `input_schema`
    is a JSON column (already a dict), but a stringified schema is parsed defensively;
    anything empty/None/malformed degrades to permissive — never raises."""
    key = t.get("key")
    if key in _NATIVE_PARAM_SCHEMAS:               # built-ins keep their hardcoded schema
        return _NATIVE_PARAM_SCHEMAS[key]
    raw = t.get("input_schema")
    if isinstance(raw, str):                       # defensive: a schema stored as JSON text
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            raw = None
    if isinstance(raw, dict) and raw:              # non-empty stored schema → hand it to the model
        return raw
    return _PERMISSIVE_PARAMS                       # genuinely no schema → executor re-validates args


def _native_tool_schemas(wired: list[dict], *, allow_escalation: bool) -> list[dict]:
    """Turn resolve_tools()'s [{key, description, input_schema}] into OpenAI function schemas.
    Tools carrying a stored `input_schema` expose it as `parameters`; keys with no schema get a
    permissive one (executor re-validates args). Adds `escalate` when allowed."""
    schemas: list[dict] = []
    for t in wired:
        key = t["key"]
        schemas.append({
            "type": "function",
            "function": {"name": key,
                         "description": t.get("description", ""),
                         "parameters": _tool_params(t)},
        })
    if allow_escalation:
        schemas.append(_ESCALATE_SCHEMA)
    return schemas


def _embeds_protocol(text: str) -> bool:
    """True if `text` is / EMBEDS a tool-call or escalate JSON in ANY provider's shape (even behind
    a prose prefix like 'Let me search…{…}'). Covers OpenAI/DeepSeek ({"tool"} / {"tool_calls"} /
    {"function_call"}), Gemini ({"functionCall"}), and our escalate object. A finished answer is
    prose — it never surfaces one of these as the reply."""
    obj = first_json_object(text or "") or parse_json_object(text or "")
    if not isinstance(obj, dict):
        return False
    return bool(obj.get("tool") or obj.get("tool_calls") or obj.get("function_call")
                or obj.get("functionCall") or isinstance(obj.get("escalate"), dict))


def _clean_findings(tool_trace: list, *, limit: int = 4000) -> str:
    """Human-readable findings for the synthesis step — plain facts, NOT tool-call logs. Feeding
    the model 'web_search(q): {json}' makes it imitate and emit more tool-calls; clean prose gives
    it nothing to imitate, so it just writes the answer."""
    lines: list[str] = []
    for step in tool_trace:
        res = step.get("result") or {}
        if not res.get("ok"):
            continue
        if isinstance(res.get("results"), list):          # web_search
            for r in res["results"][:5]:
                if not isinstance(r, dict):
                    continue
                title = str(r.get("title") or "").strip()
                snip = str(r.get("snippet") or r.get("content") or r.get("text") or "").strip()
                if title or snip:
                    lines.append(f"- {title}: {snip}".strip(" -:"))
        elif res.get("text"):                              # web_extract
            lines.append(str(res["text"])[:700].strip())
        elif res.get("summary"):
            lines.append(str(res["summary"]).strip())
        else:
            # Any OTHER tool (e.g. list_my_capabilities returns {builtin, mcp}) — its result is
            # itself the answer material, not web findings. Render the meaningful payload as data
            # so synthesis can write a real answer from it, instead of falling through to the
            # raw-dump digest floor + a bogus 继续 nudge (which reads as "still working" when the
            # tool already returned everything needed).
            payload = {k: v for k, v in res.items()
                       if k not in ("ok", "artifact", "external", "error")}
            if payload:
                lines.append(f"{step.get('tool')} 返回:{json.dumps(payload, ensure_ascii=False)[:900]}")
    return "\n".join(lines)[:limit]


async def _synthesize_from_findings(a, system: str, user_content: str, tool_trace: list) -> str:
    """Forced-step / salvage synthesis. Instead of asking the model to answer from the messy
    tool-loop convo (which DeepSeek resists — it keeps wanting to search), hand it its OWN gathered
    findings in a CLEAN, isolated prompt and demand the finished answer. Falls back to an honest
    findings digest only if even this refuses."""
    digest = _clean_findings(tool_trace)
    if not digest.strip():
        return _fallback_with_digest(user_content, tool_trace)
    # Synthesis may run on a dedicated stronger model (DeepSeek synthesizes weakly). Use it ONLY
    # when configured; otherwise keep the tool-loop adapter `a`.
    try:
        from server.services.llm_factory import build_synthesis_adapter
        synth = await build_synthesis_adapter()
        if synth is not None:
            a = synth
    except Exception:  # noqa: BLE001
        pass
    synth_system = (
        "You are writing the FINAL answer for the user. You have no tools and cannot search — that "
        "phase is over. Reference notes gathered by a researcher are given below. Write the complete, "
        "well-structured answer to the user's question NOW, using ONLY those notes. If they asked for "
        "a ranking/top-N, output a clean numbered list or table with the details. Be decisive: if a "
        "few numbers are uncertain, give your best synthesis and note it in one line. Output ONLY the "
        "prose answer — never JSON, never a tool call, never 'let me…' or 'I'll search'.")
    synth_user = f"The user asked:\n{user_content}\n\nReference notes:\n{digest}\n\nNow write the final answer."
    try:
        resp = await _chat_retry(a, synth_system, synth_user, history=[], tools=None)
        s = (resp.content or "").strip()
        if s and not _embeds_protocol(s) and not _is_deferral_stub(s):
            return s
    except Exception:  # noqa: BLE001
        pass
    return _fallback_with_digest(user_content, tool_trace)


_CHAT_TIMEOUT_S = 75.0  # per model call — DeepSeek's API can be slow and occasionally stalls.


async def _chat_retry(a, system: str, user: str, *, history=None, tools=None):
    """One retry on a stalled/failed model call. DeepSeek's API occasionally hangs (a whole turn
    then produces nothing); a single retry recovers most transient stalls. Framework-general
    reliability — any BYOK provider can be flaky, so the loop shouldn't dead-hang on one bad call."""
    last: Exception | None = None
    for _ in range(2):
        try:
            return await asyncio.wait_for(
                a.chat(system, user, history=history, tools=tools), timeout=_CHAT_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001
            last = exc
    raise last if last else RuntimeError("chat failed")


_PLAIN_ANSWER_SYS = (
    "\n\nAnswer the user's message directly, in plain text, right NOW. Do NOT call a tool, output "
    "JSON, or say you will search / look into it / get back to them later — just give your actual "
    "answer using what you already know.")


async def _salvage_plain(a, system: str, user_content: str) -> str | None:
    """Direct-answer salvage for a turn where NO tool ran but the model's content was empty, a raw
    tool-call, or tripped the promises-action guard. With no findings there is nothing to synthesize
    and nothing 'unfinished', so we must NOT show the research 继续 nudge — re-ask for a plain,
    tool-free answer instead. Returns clean prose, or None if even this won't produce usable text."""
    try:
        resp = await _chat_retry(a, system + _PLAIN_ANSWER_SYS, user_content, history=[], tools=None)
        s = (resp.content or "").strip()
        if s and not _embeds_protocol(s):
            return s
    except Exception:  # noqa: BLE001
        pass
    return None


def _chat_miss_message(user_content: str) -> str:
    """Gentle honest miss for a chat turn that produced nothing usable — distinct from the research
    'reply 继续' nudge (there is no work in progress to continue here)."""
    cjk = any("一" <= ch <= "鿿" for ch in (user_content or ""))
    return ("抱歉,我刚没接住你的意思——能再说一次或换个说法吗?" if cjk
            else "Sorry, I didn't quite catch that — could you say it another way?")


# Progressive reveal of the final answer. run_native gets the whole answer at once (native
# tool-calling returns `content` complete, not token-streamed), so a single on_chunk() makes it
# POP into view. Slicing it into small paced chunks reproduces the old streaming loop's typed-out
# feel — gentler to read. Bounded: ~_REVEAL_TOTAL_S over at most _REVEAL_MAX_STEPS slices, so a
# long report reveals in ~the same time as a short one (never drags). Slices concatenate to
# exactly `text`, so callers/tests that assert "".join(chunks) == final still hold.
_REVEAL_TOTAL_S = 0.7
_REVEAL_MAX_STEPS = 60


async def _reveal_streamed(text: str, on_chunk: Callable[[str], None]) -> None:
    n = len(text)
    if n == 0:
        return
    steps = min(_REVEAL_MAX_STEPS, n)
    size = -(-n // steps)  # ceil division — no math import
    delay = _REVEAL_TOTAL_S / steps
    for i in range(0, n, size):
        on_chunk(text[i:i + size])
        if i + size < n:
            await asyncio.sleep(delay)


async def run_native(
    *,
    system: str,
    user_content: str,
    history: list[dict],
    emit: Callable[[dict], None],
    on_chunk: Callable[[str], None],
    resolve_tools: ResolveTools,
    allow_escalation: bool = True,
    max_tool_calls: int = MAX_TOOL_CALLS,
    tool_timeout_s: float = TOOL_TIMEOUT_S,
    force_tools: bool = False,
    confirm_command: ConfirmCommand | None = None,
    conversation_id: str | None = None,
    log_events: bool = True,
) -> dict:
    """Native tool-calling twin of run(). Same signature, same return shape
    ({"final": str|None, "escalation": dict|None, "tool_trace": list}).

    Each step calls adapter.chat(..., tools=schemas) → LLMResponse{content, tool_calls}:
      - tool_calls non-empty → dispatch each (gated, exactly like run()); content is narration
        ONLY, never surfaced as the answer; continue.
      - escalate tool call → return {"escalation": {...}} (when allow_escalation).
      - no tool_calls → content IS the final answer; stream it and return.
      - forced step (step == max_tool_calls) → call with tools=None so the model MUST answer in
        prose from accumulated tool results — guaranteeing a non-empty synthesized answer.
    """
    adapter = _get_adapter()
    a = await adapter if hasattr(adapter, "__await__") else adapter

    wired = await resolve_tools()
    wired_keys = {t["key"] for t in wired}
    schemas = _native_tool_schemas(wired, allow_escalation=allow_escalation)
    # _NATIVE_EFFICIENCY = research discipline; GUARD_NOTE = injection defense (wrapped tool/web
    # content is untrusted DATA, not instructions) — same guard the old loop carried.
    system = system + _NATIVE_EFFICIENCY + "\n\n" + GUARD_NOTE

    # convo mirrors run()'s message list: history + tool result turns are appended via
    # _record_tool_result (assistant turn + framed "TOOL RESULT for X" user turn), so tool
    # outputs re-enter context IDENTICALLY to the old loop.
    convo: list[dict] = list(history) + [{"role": "user", "content": user_content}]
    tool_trace: list[dict] = []
    searches_done = 0  # web_search count this turn — capped at _SEARCH_CAP to force convergence
    # PB-3 (条件2): consecutive-failure counts per mcp_* tool key. These are LOCALS of this
    # run_native invocation — one invocation = one turn — so a new turn starts at zero by
    # construction; nothing persists or is shared. mcp_hint_logged bounds the observability
    # row to once per turn per tool.
    mcp_fail_counts: dict[str, int] = {}
    mcp_hint_logged: set[str] = set()

    # force_tools (spawn proactive web_search): deterministic pre-run, mirrors run().
    if force_tools and "web_search" in wired_keys and "web_search" in EXECUTORS:
        from server.services import tool_intent
        try:
            intent = await tool_intent.classify(user_content, sorted(wired_keys))
        except Exception:  # noqa: BLE001
            intent = None
        if intent is not None and intent.needs and intent.tool == "web_search":
            q = (intent.query or user_content)[:400]
            await _dispatch_tool(
                "web_search", {"query": q},
                json.dumps({"tool": "web_search", "args": {"query": q}}, ensure_ascii=False),
                resolve_tools=resolve_tools, emit=emit, tool_timeout_s=tool_timeout_s,
                tool_trace=tool_trace, convo=convo, confirm_command=confirm_command,
                mcp_fail_counts=mcp_fail_counts, mcp_hint_logged=mcp_hint_logged,
                conversation_id=conversation_id, log_events=log_events)
            searches_done += 1

    for step in range(max_tool_calls + 1):
        forced = step == max_tool_calls
        sys_now = system if not forced else (
            system + "\n\nTool budget exhausted: answer now with what you have. Text only.")
        # On the forced step pass tools=None so the model CANNOT call a tool and MUST produce
        # prose from the accumulated TOOL RESULTs — never an empty turn.
        resp = await _chat_retry(a, sys_now, convo[-1]["content"],
                                 history=convo[:-1],
                                 tools=(None if forced else schemas))
        tool_calls = list(getattr(resp, "tool_calls", None) or [])

        if not forced and tool_calls:
            for call in tool_calls:
                fn = call.get("function") or {}
                name = str(fn.get("name") or "")
                args = fn.get("arguments")
                if not isinstance(args, dict):
                    args = {}
                if name == "escalate" and allow_escalation:
                    return {"final": None, "tool_trace": tool_trace,
                            "escalation": {"kind": str(args.get("kind") or "data"),
                                           "need": str(args.get("need") or "").strip(),
                                           "context": str(args.get("context") or "").strip()}}
                # assistant_content is a JSON string of the call so trace/convo read like run().
                assistant_content = json.dumps({"tool": name, "args": args}, ensure_ascii=False)
                # PA-3 terminal tool: a VALID ask_user_choice call ends the turn — the
                # caller emits the clarify_options card and waits for the user's click.
                # Gated on the RESOLVED toolset so loops that don't wire it (spawns)
                # fall through to the normal "tool not available" dispatch error.
                if name == "ask_user_choice" and "ask_user_choice" in wired_keys:
                    clarify, err = _parse_clarify_args(args)
                    if err is not None:
                        _record_tool_result(
                            name, args, {"ok": False, "external": False, "error": err},
                            emit, tool_trace, assistant_content, convo)
                        continue
                    return {"final": None, "escalation": None, "clarify": clarify,
                            "tool_trace": tool_trace}
                # Convergence cap: after _SEARCH_CAP searches, refuse more web_search and push the
                # model to extract a source or answer — deterministically ends the snippet spiral.
                if name == "web_search":
                    if searches_done >= _SEARCH_CAP:
                        nudge = {"ok": False, "external": False,
                                 "error": (f"search limit reached ({_SEARCH_CAP} searches). Do NOT "
                                           "search again — web_extract the most authoritative source "
                                           "you already found, or answer now with what you have.")}
                        _record_tool_result(name, args, nudge, emit, tool_trace, assistant_content, convo)
                        continue
                    searches_done += 1
                await _dispatch_tool(
                    name, args, assistant_content, resolve_tools=resolve_tools, emit=emit,
                    tool_timeout_s=tool_timeout_s, tool_trace=tool_trace, convo=convo,
                    confirm_command=confirm_command, mcp_fail_counts=mcp_fail_counts,
                    mcp_hint_logged=mcp_hint_logged, conversation_id=conversation_id,
                    log_events=log_events)
            # resp.content is narration — surface it as an ephemeral note ONLY, never final.
            if (resp.content or "").strip():
                emit({"type": "note", "text": (resp.content or "").strip()[:400]})
            continue

        # No tool calls (or forced) → resp.content should be the FINAL answer. GUARD: the model
        # (esp. on the forced step) may ignore "answer now" and instead narrate or write a TEXT
        # tool-call in its content. Never surface that. Salvage once with a hard no-tools prompt,
        # then synthesize from the accumulated TOOL RESULTs so we NEVER end empty or with a fake
        # tool-call. (Ports run()'s salvage; the native content field made the leak rarer, not gone.)
        final_text = (resp.content or "").strip()
        # A clean answer is prose. Reject content that is / embeds a tool-call or escalate object
        # (DeepSeek writes "Let me search…{\"tool\":…}" when it wants to keep going but can't), or a
        # SHORT deferral stub that promises action without delivering. A long, substantive answer is
        # KEPT even if it mentions action verbs — describing capabilities ("我能搜索、画图表") is not a
        # deferral (live bug: capability answers were bounced to the digest/继续 floor). When rejected,
        # repair — but HOW depends on whether any tool actually ran this turn:
        #   • tool_trace non-empty  → a real research round: synthesize the answer from the gathered
        #     findings (may honestly fall to a findings-digest + 继续 nudge — work WAS done).
        #   • tool_trace EMPTY      → a chat/meta turn (or a first-step narration stub). There are NO
        #     findings and NOTHING is unfinished, so the "还没做完，回复继续" research nudge would be a
        #     lie. Salvage a direct plain-text answer instead.
        if (not final_text) or _embeds_protocol(final_text) or _is_deferral_stub(final_text):
            if tool_trace:
                final_text = await _synthesize_from_findings(a, system, user_content, tool_trace)
            else:
                final_text = (await _salvage_plain(a, system, user_content)
                              or final_text or _chat_miss_message(user_content))
        if final_text:
            await _reveal_streamed(final_text, on_chunk)
        return {"final": final_text, "escalation": None, "tool_trace": tool_trace}

    raise AssertionError("unreachable")  # forced branch always returns
