"""Budget-governed native execution and shared tool/evidence safety boundaries."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from arslan.execution_budget import BudgetExceeded, governed
from arslan.runtime_policy import FailureKind, ProgressPolicy, bounded_history, exception_kind

from server.orchestrator import run_trace
from server.orchestrator.json_protocol import first_json_object, parse_json_object
from server.orchestrator.untrusted import GUARD_NOTE, wrap_external
from server.registry.executors import EXECUTORS, resolve_executor
from server.services import replay_safety
from server.services.llm_factory import build_adapter

if TYPE_CHECKING:
    from server.orchestrator.tool_caller import ToolCaller

TOOL_TIMEOUT_S = 20.0

# The T1 write tools, gated as a category (P1b). Kept as a set here — the tool
# list in _arslan_tools decides what is OFFERED, this decides what is GATED, and
# a tool that slips out of this set would be a silently ungated writer.
_WORKSPACE_WRITE_TOOLS = frozenset({"write_file", "edit_file"})



ResolveTools = Callable[[], Awaitable[list[dict]]]
ConfirmCommand = Callable[[str, list], Awaitable[bool]]


def _get_adapter():
    """Indirection so tests can stub adapter construction."""
    return build_adapter(role="execute")


async def _adapter_for_turn(*, has_images: bool):
    """The adapter for this turn, honouring the vision slot ONLY when it carries an image.

    🔴 THE `has_images` CONDITION IS THE WHOLE POINT, not an optimization. Ruling ②B
    chose an explicit vision slot over gating on a capability flag, because that flag is
    hardcoded True for every Anthropic model, never set for Gemini or any
    OpenAI-compatible provider, and toggleable in localStorage where nothing
    server-side reads it — gating on it would block Gemini entirely while waving through
    models that cannot see. Explicit beats guessing.

    But "explicit" only holds if it applies where the user meant it. Without this
    condition, setting a vision model would silently move EVERY turn onto it — the
    silent model swap this spec exists to remove, arriving through the feature meant to
    prevent it. Image on this turn, the slot applies; no image, the ordinary execute
    adapter, unchanged.

    This does NOT gate on whether the chosen model can actually see. That decision stays
    where server/orchestrator/vision_errors.py left it: send, and make the failure
    legible.
    """
    if has_images:
        from server.services.llm_factory import build_slot_adapter

        slotted = await build_slot_adapter("vision_config_id")
        if slotted is not None:
            return slotted
    adapter = _get_adapter()
    return await adapter if hasattr(adapter, "__await__") else adapter


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



def _fallback_message(user_content: str, *, locale=None) -> str:
    """Honest last-resort answer when even the salvage attempt won't produce prose. Language
    inferred from the request so a Chinese user doesn't get an English apology (or vice-versa).
    Wording is deliberately PER-TURN ("这一轮") — a live incident showed 'session exhausted'
    phrasing poisons later turns: the model reads it in history and role-plays permanent
    exhaustion even though every dispatch starts with a fresh budget."""
    from server.services import runtime_messages
    if locale is not None:
        return runtime_messages.render("round_incomplete", locale)
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


def _fallback_with_digest(user_content: str, tool_trace: list, *, locale=None) -> str:
    """Fallback message + whatever evidence this round actually gathered. The 【阶段性发现】
    marker matters: arslan._looks_like_refusal treats a marked message as substantive
    (carried forward), not as a refusal to be dropped."""
    base = _fallback_message(user_content, locale=locale)
    digest = _evidence_digest(tool_trace)
    if not digest:
        return base
    if locale is not None:
        from server.services import runtime_messages
        header = runtime_messages.render("findings_header", locale)
    else:
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


def _web_read_feedback(tool_key, args, result):
    """Keep bounded read text AND its receipt intact across model transport.

    Generic tool JSON still has its historical cap. Valid web receipts need a
    larger, structured envelope; slicing their JSON hid both text and provenance.
    Escape-heavy inputs are shortened before hashing/logging, with partial status.
    """
    if tool_key != "web_extract":
        return None
    from arslan.companion.research import admitted_sources, receipt
    from server.registry.net_pin import _MAX_EXTRACT_CHAR_LIMIT
    sources = admitted_sources([{"tool": tool_key, "args": args, "result": result}])
    if not sources:
        return None
    source, original = next(iter(sources.values()))
    total = result.get("total_chars")
    total = total if type(total) is int and total >= len(original) else len(original)

    def envelope(length):
        text = original[:length]
        partial = source.truncated or length < len(original)
        delivered = receipt(source.url, text, truncated=partial).model_dump(mode="json")
        delivered["retrieved_at"] = source.retrieved_at.isoformat()
        value = {"ok": True, "url": source.url, "text": text, "source": delivered,
                 "returned_chars": len(text), "total_chars": total}
        if length < len(original):
            value["delivery_truncated"] = True
        return value, json.dumps(value, ensure_ascii=False)

    high = min(len(original), _MAX_EXTRACT_CHAR_LIMIT)
    prepared = envelope(high)
    if len(prepared[1]) <= 60_000:
        return prepared
    low = 0
    # Leave room for the untrusted frame inside bounded_history's 64k default.
    while low < high:
        mid = (low + high + 1) // 2
        if len(envelope(mid)[1]) <= 60_000:
            low = mid
        else:
            high = mid - 1
    return envelope(low)


def _record_tool_result(tool_key, args, result, emit, tool_trace, assistant_content, convo,
                        mcp_fail_counts: dict | None = None) -> dict:
    web_feedback = _web_read_feedback(tool_key, args, result)
    if web_feedback is not None:
        result, raw_payload = web_feedback
    else:
        feedback = {k: v for k, v in result.items() if k != "artifact"}
        raw_payload = json.dumps(feedback, ensure_ascii=False)[:8000]
    emit({"type": "tool_result", "tool": tool_key, "ok": bool(result.get("ok")),
          "summary": _summarize_result(result), "artifact": result.get("artifact"),
          "artifacts": result.get("artifacts") or []})
    tool_trace.append({"tool": tool_key, "args": args, "result": result})
    run_trace.record(tool=tool_key, args=args, result=result,
                      ok=bool(result.get("ok")), error=result.get("error"), ms=None)
    convo.append({"role": "assistant", "content": assistant_content})
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


#: Outbound fetches one LIVE run may make. Chosen to be far above ordinary research
#: behaviour (a few lookups per answer) and far below a loop; it is a circuit breaker,
#: not a quota. NOT derived from a real distribution — nothing measures fetch counts yet,
#: so this is an explicit judgement call, the same honesty caveat as any other default we
#: have not earned with data.
LIVE_FETCH_BUDGET = 25

#: The tools it covers. Capping web_extract alone would be bypassed by alternating with
#: web_search, so they share ONE allowance.
_FETCH_TOOLS = frozenset({"web_search", "web_extract"})


#: FU-2b. The eval/replay allowance, and it is deliberately NOT per dispatch.
#:
#: The gate dispatches roughly `pairs x 2 arms x (epochs*lr_budget + 1)` times —
#: a few hundred for one candidate. Giving each of those its own 25 would be a
#: cap in name only: 25 x 224 is not a bound, it is a multiplier with a label.
#: So the allowance spans the whole attempt, and it is smaller than the live one
#: because an evaluation is not supposed to be doing research — a candidate that
#: needs fifty pages is a candidate worth refusing.
HERMETIC_FETCH_BUDGET = 50

#: Spent-so-far per hermetic sentinel. Module state rather than a threaded
#: parameter because every dispatch in an attempt already shares one sentinel
#: conversation id, and threading a budget object through the evaluator would
#: mean changing every layer between here and the watcher for a counter.
#:
#: If two spawns are evaluated at once they SHARE this allowance. That is the
#: conservative direction for a spend gate and is left deliberately: a shared
#: budget can only refuse earlier than a per-attempt one, never later.
#:
#: 🔴 That last sentence was FALSE, and the sharing was never why. The RESET
#: was: the watcher cleared the counter at the top of EVERY attempt, and
#: `_running_spawns` allows one attempt per SPAWN, not one overall. Attempt B
#: starting refunded attempt A mid-flight — 90 spent against a cap of 50 from a
#: single overlap, N x 50 for N overlaps, i.e. the gate loosened exactly when
#: evolution activity and therefore spend was highest.
#:
#: Passing the sentinel to the reset does NOT fix it, which is worth writing
#: down because it is the obvious fix and it is empty: every hermetic dispatch
#: shares the one id, so popping that key and clearing the dict are the same
#: operation. What restores the promise is refcounting the attempts in flight —
#: a fresh allowance when the first one starts, and nothing but sharing after.
#: Covered by tests/server/test_hermetic_budget_refund.py.
_hermetic_fetches: dict[str, int] = {}


#: How many hermetic attempts are in flight. The allowance is refreshed when
#: this goes 0 -> 1 and never while it is above zero, so concurrent attempts
#: SHARE one allowance (conservative, and what the comment above has always
#: claimed) instead of refunding each other (what actually happened).
_hermetic_attempts_inflight = 0


def begin_hermetic_attempt() -> None:
    """Claim the allowance for an attempt that is starting.

    Production callers use this instead of `reset_hermetic_fetch_budget`, which
    is unconditional and therefore unsafe while anything else is running.

    Deliberately NOT called by `skill_forge.evaluate_candidate` or
    `evolution_loop.refresh_proposal`: those run on whatever the last attempt
    left, and that stays true. Giving them their own refresh would turn one
    shared 50 into 50 per caller per watcher tick, per open proposal — a
    loosening dressed as a fix.
    """
    global _hermetic_attempts_inflight
    if _hermetic_attempts_inflight == 0:
        _hermetic_fetches.clear()
    _hermetic_attempts_inflight += 1


def end_hermetic_attempt() -> None:
    """Release one in-flight claim. Must run even when the attempt raised."""
    global _hermetic_attempts_inflight
    _hermetic_attempts_inflight = max(0, _hermetic_attempts_inflight - 1)


def hermetic_attempts_inflight() -> int:
    """For tests and diagnostics; never a control-flow input."""
    return _hermetic_attempts_inflight


def reset_hermetic_fetch_budget(conversation_id: str | None = None) -> None:
    """Start a fresh allowance. Called by the watcher at the top of an attempt.

    Without this the counter would be process-lifetime and the first attempt
    after a restart would get the budget while every later one got nothing —
    a gate that tightens silently over uptime, which is worse than no gate
    because it looks like a broken feature rather than a limit."""
    if conversation_id is None:
        _hermetic_fetches.clear()
    else:
        _hermetic_fetches.pop(conversation_id, None)


def hermetic_fetches_used(conversation_id: str) -> int:
    """For tests and diagnostics; never a control-flow input."""
    return _hermetic_fetches.get(conversation_id, 0)


def _check_hermetic_fetch_budget(conversation_id: str | None) -> dict | None:
    key = conversation_id or "evolution"
    used = _hermetic_fetches.get(key, 0)
    if used >= HERMETIC_FETCH_BUDGET:
        return {"ok": False,
                "error": f"evaluation fetch budget reached ({HERMETIC_FETCH_BUDGET} "
                         "web_search/web_extract calls for this attempt) — judge the "
                         "candidate on what has already been gathered"}
    _hermetic_fetches[key] = used + 1
    return None


async def _check_fetch_budget(tool_key: str, *, conversation_id: str | None,
                              budget: dict) -> dict | None:
    """None to proceed, or an explicit refusal dict once a run has spent its allowance.

    🔴 SCOPE — BOTH HALVES ARE NOW COVERED, BY TWO DIFFERENT ALLOWANCES.
    A live run gets LIVE_FETCH_BUDGET per run. A hermetic eval/replay gets
    HERMETIC_FETCH_BUDGET for the WHOLE ATTEMPT, which is the only shape that
    bounds anything there: `web_search` and `web_extract` are both in
    REPLAY_SAFE_BUILTINS (sealing keeps read-only web and drops WRITE tools plus
    anything non-allowlisted), and the gate dispatches roughly
    `pairs x 2 arms x (epochs*lr_budget + 1)` times — so a per-dispatch cap would
    multiply rather than limit. This was registered as FU-2b and is now in.

    The honest statement changes with it: it was "live fetches are capped, never
    network use is capped". test_live_fetch_budget pinned that wording to a test
    precisely so the claim and the code would move together, and they now have.

    The refusal is EXPLICIT rather than a silent drop: a swallowed fetch looks to the
    model like a page with no content, and it will simply try the next URL.
    """
    if tool_key not in _FETCH_TOOLS:
        return None
    if replay_safety.is_hermetic_context(conversation_id):
        return _check_hermetic_fetch_budget(conversation_id)
    used = budget.get("fetches", 0)
    if used >= LIVE_FETCH_BUDGET:
        return {"ok": False,
                "error": f"fetch budget reached for this run ({LIVE_FETCH_BUDGET} "
                         "web_search/web_extract calls) — answer with what you have "
                         "instead of fetching more"}
    budget["fetches"] = used + 1
    return None


async def _dispatch_tool(tool_key, args, assistant_content, *, resolve_tools, emit,
                         tool_timeout_s, tool_trace, convo, confirm_command=None,
                        confirm_workspace_write=None,
                        confirm_schedule=None,
                         mcp_fail_counts: dict | None = None,
                         mcp_hint_logged: set | None = None,
                         conversation_id: str | None = None,
                         log_events: bool = True,
                         fetch_budget: dict | None = None,
                         caller: ToolCaller | None = None) -> dict:
    """Execute one tool (gated), emit its frames, record the trace, and append the
    assistant turn + framed tool result into convo. Returns the raw result dict.

    run_command is special: it requires per-command user confirmation via the injected
    confirm_command(command, argv) -> bool callback. No callback → refuse (safety default)."""
    from arslan.execution_budget import BudgetExceeded, current
    budget = current()
    if budget is not None:
        try:
            budget.tool()
        except BudgetExceeded:
            from server.services.task_service import current as current_task
            if current_task():
                current_task().pause_reason = "task_budget_exhausted"
            raise
    from arslan.execution_checkpoint import save
    await save("tool_admitted")
    # Screen before emitting argument previews or recording traces. The durable
    # task journal also screens, but that later boundary cannot protect UI/logs.
    from arslan.companion.content_policy import contains_credential_data
    if contains_credential_data(args):
        result = {"ok": False, "external": False, "code": "credentials_not_tool_data",
                  "error": "Credentials cannot be passed as ordinary tool arguments. Use an approved connection."}
        safe_call = json.dumps({"tool": tool_key, "args": {}}, ensure_ascii=False)
        return _record_tool_result(tool_key, {}, result, emit, tool_trace, safe_call, convo,
                                   mcp_fail_counts=mcp_fail_counts)
    from server.services.task_workers import current as current_worker
    worker = current_worker()
    if worker is not None:
        from server.services.task_service import current as current_task
        task = current_task()
        if task is None or task.task_id != worker.task_id or tool_key not in worker.allowed_tools:
            return _record_tool_result(tool_key, {}, {"ok": False, "external": False,
                "code": "worker_tool_scope_denied", "error": "This collaborator cannot use that tool."},
                emit, tool_trace, json.dumps({"tool": tool_key, "args": {}}), convo)
    emit({"type": "tool_call", "tool": tool_key,
          "args_summary": json.dumps(args, ensure_ascii=False)[:200]})

    # FU-2 (live runs only — see _check_fetch_budget for why eval is out of scope).
    # `fetch_budget` is the per-run dict the caller threads through; absent it, no cap
    # applies, which keeps every existing caller and test working unchanged.
    if fetch_budget is not None:
        refusal = await _check_fetch_budget(
            tool_key, conversation_id=conversation_id, budget=fetch_budget)
        if refusal is not None:
            return _record_tool_result(tool_key, args, refusal, emit, tool_trace,
                                       assistant_content, convo,
                                       mcp_fail_counts=mcp_fail_counts)

    # Missing model arguments are not a user's refusal. Validate their shape
    # before requesting permission or performing any file I/O; path scope and
    # symlinks remain the executor's independently enforced responsibility.
    if tool_key in {"read_file", "write_file"} and (
        not isinstance(args.get("path"), str) or not args["path"].strip()
        or (tool_key == "write_file" and not isinstance(args.get("content"), str))
    ):
        result = {"ok": False, "code": "invalid_file_arguments",
                  "error": "A non-empty string path is required; write_file also requires string content. "
                           "No permission decision was requested and no file was accessed."}
        return _record_tool_result(tool_key, args, result, emit, tool_trace,
                                   assistant_content, convo, mcp_fail_counts=mcp_fail_counts)

    # T1 workspace writes (P1b): ONE grant per session, not per file. The unit
    # differs from run_command deliberately — a user approving "Arslan may write
    # in my workspace" is answering a question about a capability, not about a
    # filename, and asking again per file would train them to click through.
    # The remembering lives on the WS connection; here we only ask.
    if tool_key in _WORKSPACE_WRITE_TOOLS:
        if confirm_workspace_write is None:
            result = {"ok": False,
                      "error": "writing to the workspace needs your permission, which "
                               "is not available on this channel"}
            return _record_tool_result(tool_key, args, result, emit, tool_trace,
                                        assistant_content, convo,
                                        mcp_fail_counts=mcp_fail_counts)
        granted = await confirm_workspace_write(tool_key, str(args.get("path") or ""))
        if not granted:
            result = {"ok": False, "error": "user declined workspace write access"}
            return _record_tool_result(tool_key, args, result, emit, tool_trace,
                                        assistant_content, convo,
                                        mcp_fail_counts=mcp_fail_counts)

    # Creating a scheduled task spends future money on the user's key, so it
    # asks once per session — same shape as a workspace write (裁决① 2026-08-20).
    # Listing and cancelling are deliberately NOT gated: refusing to let someone
    # see or undo what was created is the worse failure.
    if tool_key == "schedule_task":
        if confirm_schedule is None:
            result = {"ok": False,
                      "error": "scheduling needs your permission, which is not "
                               "available on this channel"}
            return _record_tool_result(tool_key, args, result, emit, tool_trace,
                                        assistant_content, convo,
                                        mcp_fail_counts=mcp_fail_counts)
        granted = await confirm_schedule(str(args.get("name") or ""),
                                         str(args.get("when") or ""))
        if not granted:
            result = {"ok": False, "error": "user declined to schedule this task"}
            return _record_tool_result(tool_key, args, result, emit, tool_trace,
                                        assistant_content, convo,
                                        mcp_fail_counts=mcp_fail_counts)

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

    # Reaching another machine (P3b). Every call asks, with no session memory and
    # no ask_risky exemption — see ssh_tools for why remote is graded HIGH even
    # when the same command is LOW locally.
    #
    # The no-callback refusal comes FIRST, deliberately: an unattended turn has no
    # socket and therefore no confirm callback, so it must not so much as probe the
    # network before being told no. That ordering is what makes "a scheduled task
    # cannot SSH" structural rather than a rule someone has to remember.
    if tool_key == "ssh_run":
        if confirm_command is None:
            result = {"ok": False,
                      "error": "running a command on another machine requires your "
                               "confirmation, which is not available in this context"}
            return _record_tool_result(tool_key, args, result, emit, tool_trace,
                                        assistant_content, convo,
                                        mcp_fail_counts=mcp_fail_counts)
        from server.registry.ssh_tools import prepare_confirmation
        from server.services import ssh_exec
        prep = await prepare_confirmation(args)
        if not prep.get("ok"):
            result = {"ok": False, "error": prep.get("error") or "cannot reach that machine"}
            return _record_tool_result(tool_key, args, result, emit, tool_trace,
                                        assistant_content, convo,
                                        mcp_fail_counts=mcp_fail_counts)
        # An enrolled machine is named on the card. "studio" is what the user
        # calls it; the address alone makes them re-derive which machine that is
        # every single time, and a decision people have to re-derive is one they
        # start making by reflex.
        label = (f"{prep['user']}@{prep['host']}" if not prep.get("node_name")
                 else f"{prep['node_name']} ({prep['user']}@{prep['host']})")
        approved = await confirm_command(
            prep["command"], prep["argv"],
            remote_host=label,
            fingerprints=prep["fingerprints"])
        if not approved:
            # Un-stage: a declined command must not leave an approved host key
            # sitting where the next call would silently consume it.
            ssh_exec.take(prep["host"])
            result = {"ok": False, "error": "user declined this remote command"}
            return _record_tool_result(tool_key, args, result, emit, tool_trace,
                                        assistant_content, convo,
                                        mcp_fail_counts=mcp_fail_counts)

    # Enrolling a machine (P3c). This tool never writes: it reaches the machine,
    # reads its host key, and paints a card whose button does the enrolment over
    # REST — the propose_connect_mcp shape. So the safety here is not a callback
    # but the absence of any write on this path at all.
    #
    # It is still refused with no confirm callback, which is a proxy for "no
    # socket". An unattended turn painting a proposal card nobody asked for is
    # not dangerous, but this is the highest-consequence surface in the feature
    # and a card that appears while the user is asleep is a card they meet out of
    # context.
    if tool_key == "enroll_node":
        if confirm_command is None:
            result = {"ok": False,
                      "error": "enrolling a machine has to be proposed to you directly, "
                               "and there is nobody on this channel to propose it to"}
            return _record_tool_result(tool_key, args, result, emit, tool_trace,
                                        assistant_content, convo,
                                        mcp_fail_counts=mcp_fail_counts)
        from server.registry.ssh_tools import prepare_enrollment
        from server.ws import protocol as _protocol
        prep = await prepare_enrollment(args)
        if not prep.get("ok"):
            result = {"ok": False, "error": prep.get("error") or "cannot enrol that machine"}
            return _record_tool_result(tool_key, args, result, emit, tool_trace,
                                        assistant_content, convo,
                                        mcp_fail_counts=mcp_fail_counts)
        emit(_protocol.propose_enroll_node(
            call_id=uuid.uuid4().hex, name=prep["name"], host=prep["host"],
            user=prep["user"], fingerprints=prep["fingerprints"]))
        result = {"ok": True, "proposed": True,
                  "summary": f"asked the user to enrol {prep['host']} as '{prep['name']}'",
                  "note": "Nothing is enrolled yet. The user has to confirm it on the "
                          "card, after checking the fingerprint against the machine."}
        return _record_tool_result(tool_key, args, result, emit, tool_trace,
                                    assistant_content, convo,
                                    mcp_fail_counts=mcp_fail_counts)

    # Fail-closed hermetic backstop (eval sealing): in an evolution eval/replay context,
    # refuse ANY tool that isn't read-only-safe, independent of resolve_tools() and the
    # replay flag. This is the throat every tool call passes through (model-driven AND the
    # force_tools pre-run), so a forgotten upstream replay=True cannot silently re-open a
    # side-effecting tool. run_python's unsandboxed escape valve is also refused here — a
    # networked run_python is not hermetic.
    from server.services.replay_safety import is_hermetic_context, is_replay_safe
    if is_hermetic_context(conversation_id):
        # Honest, model-readable refusal: the model's behavior here is scored by the judge,
        # so name the eval context explicitly and tell it not to retry side-effecting tools
        # (a generic "failed" would make it flail with compensatory actions that pollute the
        # score). The refusal itself is deterministic and identical across arms.
        if not is_replay_safe(tool_key):
            result = {"ok": False, "external": False,
                      "error": f"evaluation context: '{tool_key}' is unavailable here. This "
                               "run is a hermetic evaluation replay that exposes read-only "
                               "tools only (no side-effecting or external tools). Do not retry "
                               "this tool — answer with the read-only tools you have."}
            return _record_tool_result(tool_key, args, result, emit, tool_trace,
                                        assistant_content, convo,
                                        mcp_fail_counts=mcp_fail_counts)
        if tool_key == "run_python" and os.environ.get("ARSLAN_ALLOW_UNSANDBOXED_PY"):
            result = {"ok": False, "external": False,
                      "error": "evaluation context: run_python is unavailable because the "
                               "unsandboxed escape valve (ARSLAN_ALLOW_UNSANDBOXED_PY) is set; "
                               "a networked run_python is not hermetic. Answer without it."}
            return _record_tool_result(tool_key, args, result, emit, tool_trace,
                                        assistant_content, convo,
                                        mcp_fail_counts=mcp_fail_counts)

    live = {t["key"] for t in await resolve_tools()}
    executor = (await resolve_executor(tool_key)) if tool_key in live else None
    if executor is None:
        result = {"ok": False,
                  "error": f"tool '{tool_key}' is not available to you; you may escalate a need instead"}
    else:
        # Caller identity (brain-P2 Task 1): set ONLY around the executor call so a
        # memory-write executor can read who is calling (host vs. spawn) and fail-closed
        # (refuse) when no caller was threaded through. Reset in finally — zero residual
        # pollution across dispatches/turns, including on the exception paths below.
        from server.orchestrator import tool_caller
        _ct = tool_caller.set_caller(caller) if caller is not None else None
        try:
            from server.services.task_service import current as current_task
            from server.services.task_repository import TaskError
            async def execute(admitted_args):
                timeout = budget.remaining_seconds() if tool_key == "delegate_work" and budget else tool_timeout_s
                return await asyncio.wait_for(executor.execute(admitted_args), timeout=timeout)
            runtime = current_task()
            result = await runtime.execute_tool(tool_key, args, execute) if runtime else await execute(args)
        except (BudgetExceeded, TaskError):
            raise
        except TimeoutError:
            result = {"ok": False, "error": f"tool '{tool_key}' timed out"}
        except Exception as exc:  # noqa: BLE001
            result = {"ok": False, "error": f"tool '{tool_key}' failed: {exc}"}
        finally:
            if _ct is not None:
                tool_caller.reset_caller(_ct)
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



# Native tool-calling is the sole production execution loop.

# Minimal OpenAI-format parameter schemas per known tool key. The executor re-validates args,
# so these can be loose; they exist only to nudge the model toward the right shape.
_NATIVE_PARAM_SCHEMAS: dict[str, dict] = {
    "read_file": {"type": "object", "properties": {
        "path": {"type": "string", "minLength": 1,
                 "description": "File path within the approved readable roots or workspace."}},
        "required": ["path"], "additionalProperties": False},
    "write_file": {"type": "object", "properties": {
        "path": {"type": "string", "minLength": 1,
                 "description": "Destination file path within the configured workspace."},
        "content": {"type": "string", "description": "Complete UTF-8 text to write."}},
        "required": ["path", "content"], "additionalProperties": False},
    "delegate_work": {"type": "object", "properties": {"jobs": {
        "type": "array", "minItems": 1, "maxItems": 4, "items": {
            "type": "object", "properties": {
                "method": {"type": "string", "enum": ["research", "apple-growth", "product-design"]},
                "objective": {"type": "string", "maxLength": 4000},
                "context": {"type": "string", "maxLength": 8000},
                "tools": {"type": "array", "maxItems": 2, "items": {
                    "type": "string", "enum": ["web_search", "web_extract"]}}},
            "required": ["method", "objective"], "additionalProperties": False}}},
        "required": ["jobs"], "additionalProperties": False},
    "task_progress": {"type": "object", "properties": {"run_id": {"type": "integer", "minimum": 1}},
                      "additionalProperties": False},
    "web_search": {"type": "object",
                   "properties": {"query": {"type": "string"}},
                   "required": ["query"]},
    "web_extract": {"type": "object",
                    "properties": {"url": {"type": "string"},
                                   "max_chars": {"type": "integer", "minimum": 1, "maximum": 40_000,
                                                 "default": 12_000,
                                                 "description": "Maximum extracted characters. Request a larger bounded read only when needed; check source.truncated."}},
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
    "recall": {"type": "object",
               "properties": {"query": {"type": "string"},
                              "kind": {"type": "string",
                                       "enum": ["fact", "material", "learning", "note"]}},
               "required": ["query"]},
    "remember": {"type": "object",
                 "properties": {
                     "kind": {"type": "string",
                              "enum": ["fact", "learning", "note", "preference"]},
                     "action": {"type": "string",
                                "enum": ["append", "supersede", "mark_stale", "delete"]},
                     "content": {"type": "string"},
                     "target_id": {"type": "integer"},
                 },
                 "required": ["kind", "action", "content"]},
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


def _unverified_claim(text: str, tool_trace: list, wired_keys: set[str]) -> str | None:
    """Claims are not receipts. Check this before displaying a proposed answer."""
    if "<!doctype html" in text.lower() and "</html>" in text.lower():
        return None
    succeeded = {step.get("tool") for step in tool_trace if (step.get("result") or {}).get("ok")}
    if _claims_deck(text) and "render_deck" not in succeeded:
        return "render_deck"
    if (_claims_chart(text) or (_draws_chart_fence(text) and "render_chart" in wired_keys)) and "render_chart" not in succeeded:
        return "render_chart"
    if _claims_search(text) and "web_search" not in succeeded:
        return "web_search"
    return None


async def _synthesize_from_findings(a, system: str, user_content: str, tool_trace: list) -> str:
    """Forced-step / salvage synthesis. Instead of asking the model to answer from the messy
    tool-loop convo (which DeepSeek resists — it keeps wanting to search), hand it its OWN gathered
    findings in a CLEAN, isolated prompt and demand the finished answer. Falls back to an honest
    findings digest only if even this refuses."""
    digest = _clean_findings(tool_trace)
    if not digest.strip():
        from server.services import runtime_messages
        return _fallback_with_digest(user_content, tool_trace, locale=await runtime_messages.selected_locale())
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
    except BudgetExceeded:
        raise
    except Exception as exc:  # noqa: BLE001
        from server.services.task_repository import TaskError
        if isinstance(exc, TaskError):
            raise
        pass
    from server.services import runtime_messages
    return _fallback_with_digest(user_content, tool_trace, locale=await runtime_messages.selected_locale())


_CHAT_TIMEOUT_S = 75.0  # per model call — DeepSeek's API can be slow and occasionally stalls.


async def _chat_retry(a, system: str, user: str, *, history=None, tools=None):
    """One bounded retry for known transient transport failures, never for denial."""
    last: Exception | None = None
    from arslan.execution_budget import BudgetExceeded
    for attempt in range(2):
        try:
            return await asyncio.wait_for(
                a.chat(system, user, history=history, tools=tools), timeout=_CHAT_TIMEOUT_S)
        except BudgetExceeded:
            from server.services.task_service import current as current_task
            if current_task():
                current_task().pause_reason = "task_budget_exhausted"
            raise
        except Exception as exc:  # noqa: BLE001
            last = exc
            if exception_kind(exc) != FailureKind.RETRYABLE or attempt:
                raise
            await asyncio.sleep(0.2)
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
        if s and not _embeds_protocol(s) and not _is_deferral_stub(s) and not getattr(resp, "tool_calls", None):
            return s
    except BudgetExceeded:
        raise
    except Exception as exc:  # noqa: BLE001
        from server.services.task_repository import TaskError
        if isinstance(exc, TaskError):
            raise
        pass
    return None


def _chat_miss_message(user_content: str, *, locale=None) -> str:
    """Gentle honest miss for a chat turn that produced nothing usable — distinct from the research
    'reply 继续' nudge (there is no work in progress to continue here)."""
    if locale is not None:
        from server.services import runtime_messages
        return runtime_messages.render("chat_miss", locale)
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


@governed
async def run_native(
    *,
    system: str,
    user_content: str,
    history: list[dict],
    emit: Callable[[dict], None],
    on_chunk: Callable[[str], None],
    resolve_tools: ResolveTools,
    allow_escalation: bool = True,
    max_tool_calls: int | None = None,
    tool_timeout_s: float = TOOL_TIMEOUT_S,
    force_tools: bool = False,
    confirm_command: ConfirmCommand | None = None,
    confirm_workspace_write=None,
    confirm_schedule=None,
    conversation_id: str | None = None,
    log_events: bool = True,
    caller: ToolCaller | None = None,
    has_images: bool = False,
    adapter_override=None,
    stream_without_tools: bool = False,
    progress_lane=None,
) -> dict:
    """Canonical native tool loop. Same signature and core return shape
    ({"final": str|None, "escalation": dict|None, "tool_trace": list}).

    Each step calls adapter.chat(..., tools=schemas) → LLMResponse{content, tool_calls}:
      - tool_calls non-empty → dispatch each through the shared gate; content is narration
        ONLY, never surfaced as the answer; continue.
      - escalate tool call → return {"escalation": {...}} (when allow_escalation).
      - no tool_calls → content IS the final answer; stream it and return.
      - no progress or no remaining tools → one text-only synthesis if request budget permits.

    Production calls use the shared task budget, with no fixed eight-round cap.
    max_tool_calls is an optional explicit compatibility ceiling, never a default.
    """
    # The vision slot needs to know whether this turn carries an image, and this
    # signature is the only place that fact is available — hence a parameter rather
    # than something guessed further down.
    a = adapter_override if adapter_override is not None else await _adapter_for_turn(has_images=has_images)
    from arslan.execution_budget import current as current_budget
    from server.services.task_service import current as current_task
    budget = current_budget()
    runtime = progress_lane or current_task()
    acceptance_runtime = current_task() if progress_lane is None else None
    if acceptance_runtime is not None:
        checks = [check.model_dump(mode="json", exclude_none=True) for check in acceptance_runtime.spec.acceptance
                  if check.evaluator != "human"]
        if checks:
            system += ("\nTask acceptance criteria (these do not grant tools or permissions):\n" +
                       json.dumps(checks, ensure_ascii=False)[:12_000])
    policy = ProgressPolicy(seen=set(runtime.progress.loop_fingerprints) if runtime else set())
    request_ceiling = max(0, budget.limits.model_requests - budget.model_requests)
    stop_reason = None
    history_compacted = False
    if max_tool_calls is not None and (type(max_tool_calls) is not int or max_tool_calls < 0):
        raise ValueError("max_tool_calls must be a non-negative explicit ceiling")

    wired = await resolve_tools()
    wired_keys = {t["key"] for t in wired}
    if stream_without_tools:
        if wired or allow_escalation:
            raise ValueError("plain streaming requires an explicitly empty tool set")
        conversation, compacted = bounded_history(list(history) + [{"role": "user", "content": user_content}])
        pieces = []
        # Partial streams are never replayed automatically. Provider admission,
        # cancellation and the enclosing task-wide timeout are the same boundary.
        async with asyncio.timeout(min(_CHAT_TIMEOUT_S, budget.remaining_seconds())):
            async for piece in a.chat_stream(system + "\n\n" + GUARD_NOTE,
                                             conversation[-1]["content"], history=conversation[:-1]):
                pieces.append(piece)
                if acceptance_runtime is None:
                    on_chunk(piece)
        if acceptance_runtime is not None:
            from server.services import task_validation
            report = await task_validation.validate_output(acceptance_runtime, "".join(pieces), [], model_adapter=a)
            if task_validation.failures(report):
                acceptance_runtime.pause_reason = "task_validation_failed"
                pieces = [task_validation.failure_output("".join(pieces), report, acceptance_runtime.spec.locale)]
            await _reveal_streamed("".join(pieces), on_chunk)
        return {"final": "".join(pieces), "escalation": None, "tool_trace": [],
                "stop_reason": None, "history_compacted": compacted}
    schemas = _native_tool_schemas(wired, allow_escalation=allow_escalation)
    # _NATIVE_EFFICIENCY = research discipline; GUARD_NOTE = injection defense (wrapped tool/web
    # content is untrusted DATA, not instructions) — same guard the old loop carried.
    system = system + _NATIVE_EFFICIENCY + "\n\n" + GUARD_NOTE

    # History and tool result turns are appended via
    # _record_tool_result (assistant turn + framed "TOOL RESULT for X" user turn), so tool
    # outputs re-enter context IDENTICALLY to the old loop.
    current_request = {"role": "user", "content": user_content}
    convo: list[dict] = list(history) + [current_request]
    tool_trace: list[dict] = []
    # PB-3 (条件2): consecutive-failure counts per mcp_* tool key. These are LOCALS of this
    # run_native invocation — one invocation = one turn — so a new turn starts at zero by
    # construction; nothing persists or is shared. mcp_hint_logged bounds the observability
    # row to once per turn per tool.
    mcp_fail_counts: dict[str, int] = {}
    mcp_hint_logged: set[str] = set()
    # FU-2: the per-run outbound-fetch allowance. A LOCAL of this invocation for exactly
    # the reason spelled out above — one run_native call is one turn, so the allowance
    # resets by construction and cannot leak between turns or between spawns. Created
    # here, BEFORE the force_tools block below, so the proactive web_search counts too;
    # creating it any deeper (inside the step loop, or inside _dispatch_tool) would reset
    # it per tool call and the cap would never bind.
    fetch_budget: dict[str, int] = {}
    unseen_start = len(convo)

    # Deterministic pre-search uses the same admission and progress boundaries.
    if force_tools and "web_search" in wired_keys and "web_search" in EXECUTORS:
        from server.services import tool_intent
        try:
            intent = await tool_intent.classify(user_content, sorted(wired_keys))
        except Exception:  # noqa: BLE001
            intent = None
        if intent is not None and intent.needs and intent.tool == "web_search":
            q = (intent.query or user_content)[:400]
            result = await _dispatch_tool(
                "web_search", {"query": q},
                json.dumps({"tool": "web_search", "args": {"query": q}}, ensure_ascii=False),
                resolve_tools=resolve_tools, emit=emit, tool_timeout_s=tool_timeout_s,
                tool_trace=tool_trace, convo=convo, confirm_command=confirm_command,
                confirm_workspace_write=confirm_workspace_write,
                confirm_schedule=confirm_schedule,
                mcp_fail_counts=mcp_fail_counts, mcp_hint_logged=mcp_hint_logged,
                conversation_id=conversation_id, log_events=log_events,
                fetch_budget=fetch_budget, caller=caller)
            policy.observe("web_search", {"query": q}, result)

    pending_feedback = len(convo) - unseen_start
    for step in range(request_ceiling):
        budget.check()
        if budget.model_requests >= budget.limits.model_requests:
            if runtime:
                runtime.pause_reason = "task_budget_exhausted"
            budget.stop("model_requests")
        forced = (policy.stopped or budget.tool_calls >= budget.limits.tool_calls or
                  (max_tool_calls is not None and step >= max_tool_calls))
        if forced:
            stop_reason = "task_no_progress" if policy.stopped else "task_budget_exhausted"
            if runtime:
                runtime.pause_reason = stop_reason
        sys_now = system if not forced else (
            system + ("\n\nRepeated actions made no progress. Explain what was verified and what is blocked. Text only."
                      if policy.stopped else "\n\nTool budget exhausted: report the verified results and remaining work. Text only."))
        # Deliver one new tool batch atomically before normal old-history
        # eviction. Keep the 64k rolling target; apply extra protection only
        # to batches <=96k, never permanently pin sources or widen task budgets.
        # Existing opaque-provider pair retention is otherwise unchanged.
        oversized_feedback = pending_feedback and len(json.dumps(
            convo[-pending_feedback:], ensure_ascii=False, default=str)) > 96_000
        convo, compacted = bounded_history(convo, preserve_tail=0 if oversized_feedback else pending_feedback)
        pending_feedback = 0
        if oversized_feedback:
            sys_now += ("\nThe newest tool-result batch exceeded the bounded delivery window. Some newly fetched "
                        "content may have been omitted before you saw it. Do not claim to have inspected omitted "
                        "content; request smaller sequential reads or disclose the limitation within remaining budgets.")
        history_compacted = history_compacted or compacted
        if history_compacted:
            sys_now += ("\nEarlier conversation turns were compacted. Saved task progress and owned outputs "
                        "remain available through task_progress. Do not repeat completed effects.")
        # On the forced step pass tools=None so the model CANNOT call a tool and MUST produce
        # prose from the accumulated TOOL RESULTs — never an empty turn.
        # Rolling evidence eviction must not erase this turn's task or its
        # restrictions. Restore the exact request at user priority, not as a
        # system instruction or an invented summary, only in this payload.
        request_history = convo[:-1]
        if not any(item is current_request for item in convo):
            request_history = [current_request] + request_history
        resp = await _chat_retry(a, sys_now, convo[-1]["content"],
                                 history=request_history,
                                 tools=(None if forced else schemas))
        tool_calls = list(getattr(resp, "tool_calls", None) or [])

        if not forced and tool_calls:
            provider_content = getattr(resp, "provider_content", None)
            history_start = len(convo)
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
                # A neutral trace record, not a prompt-level execution protocol.
                assistant_content = json.dumps({"tool": name, "args": args}, ensure_ascii=False)
                if policy.stopped:
                    _record_tool_result(name, {}, {"ok": False, "external": False,
                        "code": "task_no_progress", "error": "Execution paused after repeated work without progress."},
                        emit, tool_trace, json.dumps({"tool": name, "args": {}}), convo)
                    continue
                # PA-3 terminal tool: a VALID ask_user_choice call ends the turn — the
                # caller emits the clarify_options card and waits for the user's click.
                # Gated on the RESOLVED toolset so loops that don't wire it (spawns)
                # fall through to the normal "tool not available" dispatch error.
                if name == "ask_user_choice" and "ask_user_choice" in wired_keys:
                    clarify, err = _parse_clarify_args(args)
                    if err is not None:
                        result = _record_tool_result(
                            name, args, {"ok": False, "external": False, "error": err},
                            emit, tool_trace, assistant_content, convo)
                        policy.observe(name, args, result)
                        continue
                    if runtime:
                        runtime.pause_reason = "task_input_required"
                    return {"final": None, "escalation": None, "clarify": clarify,
                            "tool_trace": tool_trace}
                result = await _dispatch_tool(
                    name, args, assistant_content, resolve_tools=resolve_tools, emit=emit,
                    tool_timeout_s=tool_timeout_s, tool_trace=tool_trace, convo=convo,
                    confirm_command=confirm_command,
                    confirm_workspace_write=confirm_workspace_write,
                    confirm_schedule=confirm_schedule, mcp_fail_counts=mcp_fail_counts,
                    mcp_hint_logged=mcp_hint_logged, conversation_id=conversation_id,
                    log_events=log_events, fetch_budget=fetch_budget, caller=caller)
                policy.observe(name, args, result)
                if runtime:
                    runtime.progress = runtime.progress.model_copy(update={
                        "loop_fingerprints": tuple(sorted(policy.seen))[-256:]})
                    await runtime.checkpoint("loop_progress")
            if provider_content:
                # Native Gemini needs the original model parts (including opaque
                # signatures) followed by functionResponse parts, not a textified
                # call transcript. Keep the same already-framed tool feedback.
                added = convo[history_start:]
                responses = []
                for index in range(0, len(added), 2):
                    invocation = json.loads(added[index]["content"])
                    response = {"type": "function_response", "name": invocation["tool"],
                                "response": {"result": added[index + 1]["content"]}}
                    call_index = index // 2
                    if call_index < len(tool_calls) and tool_calls[call_index].get("provider_id"):
                        response["id"] = tool_calls[call_index]["provider_id"]
                    responses.append(response)
                del convo[history_start:]
                convo.append({"role": "assistant", "content": [
                    {"type": "provider_content", **provider_content}]})
                convo.append({"role": "user", "content": responses})
            # resp.content is narration — surface it as an ephemeral note ONLY, never final.
            if (resp.content or "").strip():
                emit({"type": "note", "text": (resp.content or "").strip()[:400]})
            pending_feedback = len(convo) - history_start
            continue

        # No tool calls (or forced) → resp.content should be the FINAL answer. GUARD: the model
        # (esp. on the forced step) may ignore "answer now" and instead narrate or write a TEXT
        # tool-call in its content. Never surface that. Salvage once with a hard no-tools prompt,
        # then synthesize from the accumulated TOOL RESULTs so we NEVER end empty or with a fake
        # tool-call. Native content separation alone does not prevent malformed output.
        # Even a provider ignoring tools=None still marks narration with tool_calls.
        # Never turn that narration into a final answer on a forced synthesis step.
        final_text = "" if tool_calls else (resp.content or "").strip()
        claimed = _unverified_claim(final_text, tool_trace, wired_keys)
        deferred = _is_deferral_stub(final_text)
        if not forced and (claimed or (deferred and wired_keys)):
            policy.observe("answer_validation", {}, {"ok": False, "code": "unverified_answer"})
            convo.extend([{"role": "assistant", "content": final_text}, {"role": "user", "content":
                (f"The proposed answer lacks a successful {claimed} receipt. " if claimed else
                 "The proposed answer only promises future action. ") +
                "Use an available native tool if needed, or give an honest answer stating the limitation. "
                "Do not claim an action or artifact exists without evidence. Do not output tool-call JSON as text."}])
            continue
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
        if (not final_text) or _embeds_protocol(final_text) or deferred or claimed:
            from server.services import runtime_messages
            notice_locale = await runtime_messages.selected_locale()
            if tool_trace:
                final_text = await _synthesize_from_findings(a, system, user_content, tool_trace)
            else:
                final_text = (await _salvage_plain(a, system, user_content)
                              or _chat_miss_message(user_content, locale=notice_locale))
            if _unverified_claim(final_text, tool_trace, wired_keys):
                final_text = (_fallback_with_digest(user_content, tool_trace, locale=notice_locale)
                              if tool_trace else _chat_miss_message(user_content, locale=notice_locale))
        if acceptance_runtime is not None:
            from server.services import task_validation
            report = await task_validation.validate_output(acceptance_runtime, final_text, tool_trace, model_adapter=a)
            validation_failures = task_validation.failures(report)
            if validation_failures:
                repair_fingerprint = hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest()
                prior_repairs = acceptance_runtime.progress.validation_repairs
                if not forced and len(prior_repairs) < 2 and repair_fingerprint not in prior_repairs:
                    acceptance_runtime.progress = acceptance_runtime.progress.model_copy(update={
                        "validation_repairs": (*prior_repairs, repair_fingerprint)})
                    await acceptance_runtime.checkpoint("validation_repair")
                    convo.extend([{"role": "assistant", "content": final_text}, {"role": "user", "content":
                        "Deterministic validation failed: " + "; ".join(validation_failures)[:3000] +
                        ". Repair only within the existing task scope, permissions and remaining budget. "
                        "Do not repeat successful or uncertain external writes. If repair is unavailable, "
                        "state the failed checks and remaining work; do not claim acceptance."}])
                    continue
                acceptance_runtime.pause_reason = "task_validation_failed"
                final_text = task_validation.failure_output(final_text, report, acceptance_runtime.spec.locale)
        if final_text:
            await _reveal_streamed(final_text, on_chunk)
        return {"final": final_text, "escalation": None, "tool_trace": tool_trace,
                "stop_reason": stop_reason, "history_compacted": history_compacted}

    if runtime:
        runtime.pause_reason = "task_budget_exhausted"
    budget.stop("model_requests")
