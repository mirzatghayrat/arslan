"""Budget-governed native execution and shared tool/evidence safety boundaries."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from arslan.execution_budget import BudgetExceeded, governed
from arslan.llm import trajectory
from arslan.runtime_policy import FailureKind, ProgressPolicy, bounded_history, exception_kind

from server.orchestrator import run_trace
from server.orchestrator.answer_contract import GROUNDED_ANSWER_RULES
from server.orchestrator.json_protocol import first_json_object, parse_json_object
from server.orchestrator.untrusted import GUARD_NOTE, wrap_external
from server.registry.executors import EXECUTORS, resolve_executor
from server.services import replay_safety
from server.services.llm_factory import build_adapter

logger = logging.getLogger(__name__)

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
        raw_payload = json.dumps(feedback, ensure_ascii=False)
        if len(raw_payload) > 8000:
            # 0.1.49 S9: never a silent cut. Keep head and tail in context and
            # the full result on disk where read_file can page through it.
            from server.services import tool_outputs
            try:
                saved = tool_outputs.save(raw_payload, label=tool_key)
            except OSError:
                saved = None
            raw_payload = tool_outputs.excerpt(raw_payload, saved)
    emit({"type": "tool_result", "tool": tool_key, "ok": bool(result.get("ok")),
          "summary": _summarize_result(result), "artifact": result.get("artifact"),
          "artifacts": result.get("artifacts") or []})
    tool_trace.append({"tool": tool_key, "args": args, "result": result})
    run_trace.record(tool=tool_key, args=args, result=result,
                      ok=bool(result.get("ok")), error=result.get("error"), ms=None)
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
    # 0.1.50: a concrete alternative at the moment of failure (recovery_hints).
    from server.orchestrator.recovery_hints import hint_for
    recovery = hint_for(tool_key, result)
    if recovery:
        hint += f"\n[Host hint: {recovery}]"
    # 0.1.49: one neutral tool record (arslan/llm/trajectory.py). It starts as a
    # host-run result carrying its invocation text; run_native claims it for the
    # model's tool call (_claim_results). Rendering per provider happens at
    # request time; trajectory.to_legacy reproduces the old "TOOL RESULT for X"
    # user turn byte for byte.
    convo.append(trajectory.tool_result(None, tool_key, f"{framed}{hint}",
                                        synthetic=True, legacy_call=assistant_content))
    return result


def _claim_results(convo: list[dict], marks: list[tuple[int, str]]) -> None:
    """Bind each call's result record to the model's tool call id.

    marks: (len(convo) before the call was handled, call id), in order. Every
    handled call appends exactly one record, and nothing moves inside a batch,
    so a call owns the record at its mark when exactly one message follows it."""
    for index, (mark, call_id) in enumerate(marks):
        end = marks[index + 1][0] if index + 1 < len(marks) else len(convo)
        if end != mark + 1:
            continue
        record = convo[mark]
        if record.get("role") == "tool" and record.get("_synthetic"):
            record.pop("_synthetic", None)
            record.pop("_legacy_call", None)
            record["tool_call_id"] = call_id


def _render_request(convo: list[dict], current_request: dict, status: str = "") -> list[dict]:
    """The model input for this step. Rolling eviction must not erase this
    turn's task: restore the exact request at user priority (not a summary,
    not a system instruction) in this payload only. The step's <agent_status>
    rides at the end of the last message (agent_status.attach), never stored."""
    from server.orchestrator import agent_status
    messages = convo if any(item is current_request for item in convo) else [current_request, *convo]
    rendered = trajectory.to_legacy(messages)
    # Last means last: after the legacy trailer too. A Gemini function-response
    # turn (list content) carries it inside the newest result instead.
    if status and rendered and isinstance(rendered[-1].get("content"), str):
        return agent_status.attach(rendered, status)
    return trajectory.to_legacy(agent_status.attach(messages, status))


def _parse_arguments(raw: str | None) -> tuple[dict | None, str | None]:
    """(arguments, problem) for a call whose arguments did not parse upstream.

    One repair only: strict=False, which accepts raw control characters (e.g.
    newlines) inside strings, a common slip in long write payloads. Anything
    else is reported back to the model, never guessed at (0.1.49 S8)."""
    text = (raw or "").strip()
    if not text:
        return {}, None                      # a no-argument call
    try:
        value = json.loads(text, strict=False)
    except json.JSONDecodeError as exc:
        return None, f"{exc.msg} at character {exc.pos}"
    if not isinstance(value, dict):
        return None, f"expected a JSON object, got {type(value).__name__}"
    return value, None


_JSON_TYPES = {"string": (str,), "integer": (int,), "number": (int, float), "boolean": (bool,),
               "array": (list,), "object": (dict,)}


def _schema_problem(args: dict, schema: dict | None) -> str | None:
    """Missing required fields and wrong top-level types, stated so the model
    can fix the call; None when the schema says nothing checkable."""
    if not isinstance(schema, dict):
        return None
    props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    problems = []
    for name in schema.get("required") or []:
        if name not in args:
            kind = (props.get(name) or {}).get("type")
            problems.append(f"missing required '{name}'" + (f" ({kind})" if isinstance(kind, str) else ""))
    for name, value in args.items():
        kind = (props.get(name) or {}).get("type")
        kinds = [kind] if isinstance(kind, str) else kind if isinstance(kind, list) else []
        accepted = tuple(t for k in kinds for t in _JSON_TYPES.get(k, ()))
        if not accepted or value is None and "null" in kinds:
            continue
        if isinstance(value, bool) and bool not in accepted or not isinstance(value, accepted):
            problems.append(f"'{name}' must be {' or '.join(kinds)}")
    return "; ".join(problems) or None


def _progress_note(policy) -> str:
    """Trusted host note appended to a result that made no progress, so the
    model sees the loop detector before it stops the turn."""
    return (f"\n[Host note: no new progress — {policy.stalled} of {policy.max_stalled} steps without "
            "progress before this turn stops. Change approach, or answer with what you have.]")


_OFFLINE_NOTE = (" Files you already fetched can still be processed with run_command (it runs without "
                 "network now).")

CONTINUE_PROMPT = ("Your previous reply was cut off by the output limit. Continue exactly where it "
                   "stopped, without repeating anything already written and without any preamble.")
TRUNCATED_CALL_ERROR = (
    "The output limit was reached while writing this call's arguments; nothing was executed. "
    "Split the work: write the first part with write_file, then append each further part with "
    "edit_file (replace the file's current last line with that line plus the next part), "
    "or shorten the payload.")


async def _model_call(a, system: str, convo: list[dict], current_request: dict, *,
                      tools, schemas, forced: bool, state, status: str = ""):
    """The one model call of a run_native step, with recovery (0.1.49 S6).

    Native adapters (OpenAI-compatible, ARSLAN_TOOL_PROTOCOL not "legacy") get
    the trajectory in their own tool protocol; a forced step keeps the SAME
    tools with tool_choice "none". Everything else (test doubles, Anthropic,
    Gemini, rollback) gets the legacy rendering, unchanged.

    Recovery (server/orchestrator/model_call.py): classified transport retries;
    a protocol rejection switches this turn to the legacy rendering; a context
    overflow compacts once; a finish_reason "length" cut is re-sent with the
    endpoint's ceiling, then a cut answer is continued. A cut tool call is
    returned as is: run_native never executes it. `state` is per turn.

    `status` (0.1.50 S1) is appended to the last message of the step's base
    messages in both renderings; continuation turns follow it, so a
    continuation request shares the original request's exact prefix."""
    from server.orchestrator import agent_status
    from server.orchestrator import model_call as mc

    def build_messages():
        return convo if any(item is current_request for item in convo) else [current_request, *convo]

    messages = build_messages()
    native = False
    use_native = getattr(a, "native_trajectory", None)
    if not state.legacy and callable(use_native) and use_native():
        try:
            trajectory.validate(messages)
            native = True
        except trajectory.TrajectoryError as exc:
            # Never send a malformed native history; the legacy rendering of the
            # same trajectory is always well-formed. Sticky for this turn.
            state.legacy, state.reason = True, f"invalid trajectory: {exc}"
            logger.warning("native tool protocol degraded to legacy: %s", exc)

    async def request(extra=None, max_tokens=None):
        sent = agent_status.attach(messages, status) + list(extra or [])
        kwargs = {"max_tokens": max_tokens} if max_tokens else {}
        if native:
            return await a.chat_trajectory(system, sent, tools=schemas if forced else tools,
                                           tool_choice="none" if forced else None, **kwargs)
        # One legacy entry point (_render_request) for every request of the step.
        rendered = _render_request(convo, current_request, status) + trajectory.to_legacy(list(extra or []))
        return await a.chat(system, rendered[-1]["content"], history=rendered[:-1], tools=tools, **kwargs)

    remaining = _remaining_seconds()
    try:
        resp = await mc.call_with_recovery(request, state, remaining_s=remaining)
    except mc.ModelCallError as exc:
        if exc.kind == "protocol" and native and not state.exhausted:
            native = False
            state.legacy, state.reason = True, f"endpoint rejected native history: {exc.excerpt[:200]}"
            state.note("switched to the legacy tool protocol")
            logger.warning("native tool protocol degraded to legacy: %s", exc.excerpt[:200])
        elif exc.kind == "context" and not state.context_retry_used and not state.exhausted:
            state.context_retry_used = True
            convo[:], _ = bounded_history(convo, max_chars=max(8_000, _rendered_size(convo) // 2),
                                          size_of=_rendered_size)
            messages = build_messages()
            state.note("compacted context")
        else:
            raise
        resp = await mc.call_with_recovery(request, state, remaining_s=remaining)
    return await _recover_truncation(a, resp, request, state, remaining)


def _remaining_seconds():
    from arslan.execution_budget import current
    budget = current()
    return budget.remaining_seconds if budget is not None else None


def _output_clamped() -> bool:
    from arslan.execution_budget import current
    budget = current()
    return bool(budget is not None and budget.last_output_clamped)


def _replaced(resp, **fields):
    if hasattr(resp, "model_copy"):
        return resp.model_copy(update=fields)
    import copy
    clone = copy.copy(resp)
    for key, value in fields.items():
        setattr(clone, key, value)
    return clone


async def _recover_truncation(a, resp, request, state, remaining):
    """finish_reason == "length": raise to the endpoint's ceiling once, then
    continue a cut answer. A cut caused by the work budget is not raised (that
    would spin: raise -> clamp -> cut). Per-turn caps live on `state`."""
    from server.orchestrator import model_call as mc
    if getattr(resp, "finish_reason", None) != "length" or _output_clamped():
        return resp
    provider = getattr(a, "_provider", None)
    ceiling, current_max = getattr(provider, "output_ceiling", None), getattr(provider, "max_tokens", None)
    raise_to = ceiling if isinstance(ceiling, int) and isinstance(current_max, int) and ceiling > current_max else None
    if raise_to and state.output_raises < 2 and not state.exhausted:
        state.output_raises += 1
        state.note(f"raised output limit to {raise_to}")
        resp = await mc.call_with_recovery(lambda: request(max_tokens=raise_to), state, remaining_s=remaining)
        if getattr(resp, "finish_reason", None) != "length" or _output_clamped():
            return resp
    text = resp.content or ""
    if getattr(resp, "tool_calls", None) or not text.strip():
        return resp     # cut tool call (never executed) or reasoning-only cut: caller handles
    last = resp
    while state.continuations < 2 and not state.exhausted:
        state.continuations += 1
        state.note("continued a cut-off answer")
        # Reasoning belongs to one reply's own text; joined text has none.
        extra = [trajectory.assistant(text, continuation=getattr(last, "continuation", None)
                                      if last is resp else None),
                 {"role": "user", "content": CONTINUE_PROMPT}]
        last = await mc.call_with_recovery(lambda: request(extra=extra, max_tokens=raise_to),
                                           state, remaining_s=remaining)
        text += last.content or ""
        if getattr(last, "finish_reason", None) != "length" or getattr(last, "tool_calls", None) \
                or _output_clamped():
            break
    # The joined text is no single reply's output: no continuation state.
    return _replaced(resp, content=text, finish_reason=getattr(last, "finish_reason", None),
                     tool_calls=[], continuation=None)


def _rendered_size(messages: list[dict]) -> int:
    """Context size of what is actually sent, not of local bookkeeping."""
    return len(json.dumps(trajectory.to_legacy(messages), ensure_ascii=False, default=str))


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


async def _asks_for_everything() -> bool:
    """The user chose 'ask for every command'. Unknown counts as yes (then nothing runs unasked)."""
    from server.db import session as db_session
    from server.services import settings_service
    try:
        async with db_session.AsyncSessionLocal() as db:
            return await settings_service.shell_confirm_policy(db) == "ask_all"
    except Exception:  # noqa: BLE001
        return True


async def _status_workspace(wired_keys) -> tuple:
    """(workspace root, is Arslan's own folder) for the status block; (None,
    False) when no writer is wired or the setting cannot be read."""
    if not wired_keys & {"write_file", "edit_file", "run_command"}:
        return None, False
    from server.db import session as db_session
    from server.services import settings_service
    try:
        async with db_session.AsyncSessionLocal() as db:
            return (await settings_service.workspace_dir(db),
                    await settings_service.workspace_is_default(db))
    except Exception:  # noqa: BLE001
        return None, False


async def _link_check_note(name: str, args: dict, result: dict, tool_trace: list,
                           hints: dict[str, int]) -> str | None:
    """Host link check for a saved text file in a turn that researched; at most
    MAX_HINTS_PER_FILE per file, so a stubborn table cannot loop the turn."""
    from server.orchestrator import link_check
    path = str(result.get("path") or args.get("path") or "")
    if not link_check.applies(path) or hints.get(path, 0) >= link_check.MAX_HINTS_PER_FILE:
        return None
    seen = link_check.evidence(tool_trace)
    if not seen:
        return None
    content = args.get("content") if name == "write_file" else await _read_saved(path)
    found = link_check.review(content, seen) if isinstance(content, str) else None
    if not found:
        return None
    hints[path] = hints.get(path, 0) + 1
    return link_check.hint(path, found)


async def _read_saved(rel: str) -> str | None:
    """The file an edit_file just changed, read back inside the workspace boundary."""
    from server.db import session as db_session
    from server.services import settings_service
    from server.services.workspace_paths import resolve_in_workspace
    try:
        async with db_session.AsyncSessionLocal() as db:
            root = await settings_service.workspace_dir(db)
        return resolve_in_workspace(rel, root).read_text(encoding="utf-8", errors="replace")[:200_000]
    except Exception:  # noqa: BLE001 — a check that cannot read simply does not run
        return None


async def _writing_in_own_folder() -> bool:
    """Unknown means ask: if the setting cannot be read, treat the folder as the user's."""
    from server.db import session as db_session
    from server.services import settings_service
    try:
        async with db_session.AsyncSessionLocal() as db:
            return await settings_service.workspace_is_default(db)
    except Exception:  # noqa: BLE001
        return False


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
    """Execute one tool (gated), emit its frames, record the trace, and append one
    framed tool-result record into convo. Returns the raw result dict.

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
    from server.services import desktop_status
    desktop_status.note_step(tool_key, args)   # the island's "now doing" line (0.1.51)

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
    # 0.1.48: Arslan's own folder (~/Arslan, the default) is its desk: writing there
    # does not ask. A folder the user chose still asks once per session, because that
    # folder holds the user's own files.
    if tool_key in _WORKSPACE_WRITE_TOOLS and not await _writing_in_own_folder():
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
        # 0.1.48: one shell string; a forbidden command is refused here, before any
        # card, so nobody is ever asked to approve wiping the disk.
        from server.services import terminal_policy
        command = terminal_policy.as_shell(args.get("command"), args.get("argv"))
        argv = []
        verdict = terminal_policy.assess(command)
        if verdict.level == "forbid":
            result = {"ok": False, "error": f"Arslan never runs this: {verdict.reason}",
                      "note": "Tell the user what you wanted to do and let them run it themselves."}
            return _record_tool_result(tool_key, args, result, emit, tool_trace,
                                        assistant_content, convo,
                                        mcp_fail_counts=mcp_fail_counts)
        if confirm_command is None and verdict.level == "run" and not await _asks_for_everything():
            pass                      # a harmless command needs nobody to approve it
        elif confirm_command is None:
            result = {"ok": False,
                      "error": "run_command requires user confirmation, which is not "
                               "available in this context"}
            return _record_tool_result(tool_key, args, result, emit, tool_trace,
                                        assistant_content, convo,
                                        mcp_fail_counts=mcp_fail_counts)
        approved = True if confirm_command is None else await confirm_command(command, argv)
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
    # 0.1.48: offering a connector is a tool the agent calls, not a pre-turn router
    # verdict. Like enroll_node it only paints a card: the user connects (and types
    # any key) on the card, over REST. With no live socket there is nobody to offer
    # it to. An unknown name returns the real list, so the agent can say so honestly
    # and look for another way (a skill, the terminal, a Shortcut) instead of stopping.
    if tool_key == "suggest_connector":
        from server.mcp import catalog as _catalog
        from server.ws import protocol as _protocol
        conn = _catalog.find_connector(str(args.get("name") or ""))
        if confirm_command is None:
            result = {"ok": False, "error": "a connector has to be offered to the user directly; "
                                            "there is nobody on this channel"}
        elif conn is None:
            result = {"ok": False, "error": "no built-in connector by that name",
                      "available": [c["label"] for c in _catalog.list_connectors()],
                      "note": "Not a dead end: a skill, the terminal, a Shortcut or AppleScript may do it."}
        else:
            prereq = ("Needs: " + ", ".join(e["name"] for e in conn["env"])) if conn["env"] else ""
            emit(_protocol.propose_connect_mcp(
                call_id=uuid.uuid4().hex, key=conn["key"], label=conn["label"],
                label_key=conn.get("label_key"), transport=conn["transport"], command=conn["command"],
                argv=conn["args"], url=conn.get("url"), env_keys=conn["env"], prerequisites=prereq,
                requires_path=conn["requires_path"], path_placeholder=conn.get("path_placeholder")))
            result = {"ok": True, "proposed": True,
                      "summary": f"offered to connect {conn['label']}; nothing is connected until the user confirms"}
        return _record_tool_result(tool_key, args, result, emit, tool_trace,
                                    assistant_content, convo, mcp_fail_counts=mcp_fail_counts)

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
        import difflib
        near = difflib.get_close_matches(tool_key, sorted(live), n=5, cutoff=0.3) or sorted(live)[:5]
        result = {"ok": False, "external": False, "code": "tool_unavailable",
                  "error": f"tool '{tool_key}' is not available to you"
                           + (f"; available tools include: {', '.join(near)}" if near else "")
                           + "; you may escalate a need instead"}
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
        except TaskError as exc:
            if exc.code not in {"task_reconciliation_required", "task_action_already_completed"}:
                raise
            # 0.1.44: refuse the repeat, never the turn. The model is told why.
            result = {"ok": False, "external": False, "code": exc.code, "error": (
                "This exact action already ran and its outcome is unknown. Do not repeat it; tell the user "
                "to check whether it happened." if exc.code == "task_reconciliation_required" else
                "This exact action already succeeded in this task. Do not repeat it.")}
        except BudgetExceeded:
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
from server.orchestrator.turn_plan import PARAMS as _PLAN_PARAMS  # noqa: E402

_NATIVE_PARAM_SCHEMAS: dict[str, dict] = {
    "read_file": {"type": "object", "properties": {
        "path": {"type": "string", "minLength": 1,
                 "description": "File path within the approved readable roots or workspace."},
        "offset": {"type": "integer", "minimum": 0,
                   "description": "Lines to skip from the start (for paging a long file)."},
        "limit": {"type": "integer", "minimum": 1, "description": "Maximum lines to return."}},
        "required": ["path"], "additionalProperties": False},
    "write_file": {"type": "object", "properties": {
        "path": {"type": "string", "minLength": 1,
                 "description": "Destination file path within the configured workspace; "
                                "missing folders are created."},
        "content": {"type": "string", "description": "Complete UTF-8 text to write."}},
        "required": ["path", "content"], "additionalProperties": False},
    # 0.1.45 hands
    "browser_open": {"type": "object", "properties": {"url": {"type": "string", "maxLength": 4000}},
                     "required": ["url"], "additionalProperties": False},
    "browser_look": {"type": "object", "properties": {}, "additionalProperties": False},
    "browser_back": {"type": "object", "properties": {}, "additionalProperties": False},
    "browser_click": {"type": "object", "properties": {"element": {"type": "string", "maxLength": 300, "description": "what the element is, in words"}, "ref": {"type": "string", "maxLength": 200, "description": "the element ref from the latest page snapshot"}},
                      "required": ["element", "ref"], "additionalProperties": False},
    "browser_type": {"type": "object", "properties": {"element": {"type": "string", "maxLength": 300, "description": "what the element is, in words"}, "ref": {"type": "string", "maxLength": 200, "description": "the element ref from the latest page snapshot"},
                     "text": {"type": "string", "maxLength": 4000}, "submit": {"type": "boolean"}},
                     "required": ["element", "ref", "text"], "additionalProperties": False},
    "browser_select": {"type": "object", "properties": {"element": {"type": "string", "maxLength": 300, "description": "what the element is, in words"}, "ref": {"type": "string", "maxLength": 200, "description": "the element ref from the latest page snapshot"},
                       "values": {"type": "array", "items": {"type": "string"}, "maxItems": 20}},
                       "required": ["element", "ref", "values"], "additionalProperties": False},
    "browser_press": {"type": "object", "properties": {"key": {"type": "string", "maxLength": 40}},
                      "required": ["key"], "additionalProperties": False},
    "mac_list_shortcuts": {"type": "object", "properties": {}, "additionalProperties": False},
    "mac_run_shortcut": {"type": "object", "properties": {"name": {"type": "string", "maxLength": 200},
                         "input": {"type": "string", "maxLength": 20000}}, "required": ["name"],
                         "additionalProperties": False},
    "mac_applescript": {"type": "object", "properties": {"script": {"type": "string", "maxLength": 4000}},
                        "required": ["script"], "additionalProperties": False},
    "start_background_work": {"type": "object", "properties": {
        "goal": {"type": "string", "minLength": 1, "maxLength": 4000,
                 "description": "The work to do, in the user's words."},
        "criteria": {"type": "array", "minItems": 1, "maxItems": 5, "items": {
            "type": "object", "properties": {
                "description": {"type": "string", "minLength": 1, "maxLength": 300},
                "kind": {"type": "string", "enum": ["file_saved", "sources_read", "mentions", "judgement"]},
                "target": {"type": "string", "maxLength": 240,
                           "description": "file name for file_saved; phrase for mentions"},
                "minimum": {"type": "integer", "minimum": 1, "maximum": 20}},
            "required": ["description"], "additionalProperties": False}}},
        "required": ["goal", "criteria"], "additionalProperties": False},
    "background_status": {"type": "object", "properties": {}, "additionalProperties": False},
    "stop_background_work": {"type": "object", "properties": {"job_id": {"type": "string", "minLength": 1}},
                             "required": ["job_id"], "additionalProperties": False},
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
                    "properties": {"command": {"type": "string",
                                               "description": "The full shell command line, e.g. "
                                                              "\"ls -la ~/Downloads | head -20\"."},
                                   "timeout_s": {"type": "integer", "minimum": 5, "maximum": 600,
                                                 "description": "Stop after this many seconds (default 120)."}},
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
    "suggest_connector": {"type": "object",
                          "properties": {"name": {"type": "string",
                                                  "description": "The service, e.g. GitHub, Notion."}},
                          "required": ["name"]},
    "update_plan": _PLAN_PARAMS,
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
    "4. If the data you gathered is incomplete, answer only the supported portion and state the "
    "specific unknowns — never invent missing detail or keep searching in circles."
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
    # Detection is deliberately stricter than parsing for dispatch: malformed
    # quotes or an interrupted object must not turn a proposed action into an
    # answer. This only rejects text; it never repairs JSON or executes a call.
    # Some providers render a proposed call as XML instead of native tool_calls.
    # Treat that as the same protocol failure, including an unfinished opening
    # tag. Never parse its arguments or grant the proposed action permission.
    if re.search(r'<\s*/?\s*(?:tool_call|tool_calls|function_call)(?=[\s>/]|$)', text or "", re.I):
        return True
    # DeepSeek's own chat-template tokens leaking into content instead of
    # native tool_calls (seen in the 0.1.49 bench: "<｜｜DSML｜｜tool_calls>",
    # and V3's "<｜tool▁calls▁begin｜>"). Same failure, same refusal to execute.
    if re.search(r'[｜|]\s*DSML\s*[｜|]|<\s*[｜|]+\s*(?:DSML\s*[｜|]+\s*)?/?\s*(?:tool[▁_ ]?calls?|invoke)',
                 text or "", re.I):
        return True
    if re.search(r'\{\s*"(?:tool|tool_calls|function_call|functionCall|escalate)"\s*:', text or ""):
        return True
    obj = first_json_object(text or "") or parse_json_object(text or "")
    if not isinstance(obj, dict):
        return False
    return bool(obj.get("tool") or obj.get("tool_calls") or obj.get("function_call")
                or obj.get("functionCall") or isinstance(obj.get("escalate"), dict))


def _clean_findings(tool_trace: list, *, limit: int = 8000) -> str:
    """Human-readable findings for the synthesis step — plain facts, NOT tool-call logs. Feeding
    the model 'web_search(q): {json}' makes it imitate and emit more tool-calls; clean prose gives
    it nothing to imitate, so it just writes the answer.

    Links stay with their facts (0.1.50 S6): a bench answer built from these notes listed ten
    jobs with "link: not provided" because the URLs were dropped here — and the link was the
    field the user asked for."""
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
                url = str(r.get("url") or r.get("link") or "").strip()
                if title or snip:
                    head = f"{title} <{url}>" if url else title
                    lines.append(f"- {head}: {snip}".strip(" -:"))
        elif res.get("text"):                              # web_extract
            url = str(res.get("url") or (step.get("args") or {}).get("url") or "").strip()
            body = str(res["text"])[:700].strip()
            lines.append(f"[{url}] {body}" if url else body)
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
        "a ranking/top-N, include only entries supported by those notes and disclose any shortfall. "
        "Keep each item's link from the notes next to it (the <…> or […] address); never invent one. "
        "Output ONLY the prose answer — never JSON, never a tool call, never 'let me…' or 'I'll search'."
        + GROUNDED_ANSWER_RULES + "\n\n" + GUARD_NOTE)
    synth_user = (f"The user asked:\n{user_content}\n\nReference notes:\n{wrap_external(digest)}"
                  "\n\nNow write the final answer.")
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


def _saved_research_report(name: str, args, result: dict) -> bool:
    """A successful write_file of a text report with a stored artifact snapshot."""
    return (name == "write_file" and result.get("ok") is True and isinstance(args, dict)
            and isinstance(result.get("artifact"), dict)
            and str(args.get("path", "")).lower().endswith((".md", ".txt")))


async def _research_review_enabled() -> bool:
    """Settings toggle, default OFF. Fail closed: an unreadable setting is OFF,
    because the review spends a model request on the user's key."""
    try:
        from server.db import session as db_session
        from server.services import settings_service
        async with db_session.AsyncSessionLocal() as db:
            return await settings_service.research_review_enabled(db)
    except Exception:  # noqa: BLE001 — optional advice must never break a task
        return False


async def _review_saved_report(adapter, args: dict, result: dict, tool_trace: list, user_content,
                               cache: dict, emit) -> dict | None:
    """0.1.41: critique a report AFTER it was saved; advice only, never a gate.

    Nothing here reaches the writing model's conversation or changes the tool
    result, the task outcome or its stop/pause reason. The note is stored beside
    the artifact snapshot for the user. Only task control (cancellation) and a
    genuinely exhausted budget propagate; `affordable` makes the latter a race.
    """
    from server.orchestrator import research_review
    from server.services import artifact_store
    subject = research_review.subject("write_file", args, tool_trace, request=user_content)
    if subject is None:
        return None
    supports = getattr(adapter, "supports_bounded_critique", None)
    if not (callable(supports) and supports()):
        outcome = {"status": "unavailable", "code": "research_review_unsupported_provider"}
    elif not research_review.affordable(subject[1]):
        outcome = {"status": "unavailable", "code": "research_review_budget_reserved"}
    else:
        emit({"type": "note", "text": "Saved report source review · advice only · uses the current task budget"})
        outcome = await research_review.inspect(subject, adapter=adapter, chat=_chat_retry, cache=cache)
    stored = research_review.note(outcome, subject[2])
    try:
        artifact_store.write_review(result["artifact"], stored)
    except OSError:
        pass  # the report is saved; losing an advisory note must not fail the task
    emit({"type": "research_review", "run_id": result["artifact"].get("run_id"),
          "filename": result["artifact"].get("filename"), "status": stored["status"],
          "issues": len(stored["issues"])})
    return stored


async def _chat_retry(a, system: str, user: str, *, history=None, tools=None):
    """One bounded retry for known transient transport failures, never for denial."""
    return await _with_retry(lambda: a.chat(system, user, history=history, tools=tools))


async def _with_retry(request):
    last: Exception | None = None
    from arslan.execution_budget import BudgetExceeded
    for attempt in range(2):
        try:
            return await asyncio.wait_for(request(), timeout=_CHAT_TIMEOUT_S)
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


# Tools a job may still use while wrapping up: saving the deliverable.
WRAP_UP_TOOLS = frozenset({"write_file", "edit_file"})
# What a wrapping-up run may still call (0.1.50): the save tools, plus run_command
# to process files it already fetched — run without network (terminal_exec.OFFLINE).
FINISH_TOOLS = WRAP_UP_TOOLS | {"run_command"}


@governed
async def run_native(**kwargs) -> dict:
    """One answer turn: `_run_native` below, plus completion first at the hard stop
    (0.1.50, S6 bench T2 r2). A chat turn that reaches its hard work limit after
    doing real work ends with a closing message the host writes — what was saved,
    where, how many pages were read, how to continue — instead of an error that
    hides a deliverable already on disk. No model call: the limit is reached.
    Background jobs and delegated workers still raise; their machinery records
    the stop itself."""
    facts: dict = {}
    try:
        return await _run_native(**kwargs, _facts=facts)
    except BudgetExceeded:
        from server.services import background_jobs
        trace = facts.get("tool_trace") or []
        host_turn = kwargs.get("caller") is None and kwargs.get("progress_lane") is None
        if not host_turn or background_jobs.inside_job() \
                or not any((t.get("result") or {}).get("ok") for t in trace):
            raise                       # workers and jobs record the stop themselves
        text = await _budget_closing(trace, facts.get("ws_root"), facts.get("started", 0.0))
        from server.services.task_service import current as current_task
        task = current_task()
        if task is not None:
            task.pause_reason = "task_budget_exhausted"
        await _reveal_streamed(text, kwargs["on_chunk"])
        return {"final": text, "escalation": None, "tool_trace": trace,
                "stop_reason": "task_budget_exhausted", "history_compacted": False}


async def _budget_closing(trace: list, ws_root, started: float) -> str:
    from arslan.execution_budget import current
    from server.orchestrator import agent_status
    from server.services import runtime_messages
    locale = await runtime_messages.selected_locale()
    budget = current()
    reason = runtime_messages.render(f"limit_{budget.stop_reason}", locale) \
        if budget is not None and budget.stop_reason else "?"
    pages = sum(1 for t in trace if t.get("tool") in ("web_extract", "browser_open")
                and (t.get("result") or {}).get("ok"))
    saved = agent_status.owned_outputs(trace, ws_root, started)
    if not saved:
        return runtime_messages.render("budget_closing_unsaved", locale, reason=reason, sources=pages)
    where = f" ({agent_status.home_relative(ws_root)})" if ws_root is not None else ""
    return runtime_messages.render("budget_closing_saved", locale, reason=reason, sources=pages,
                                   files=", ".join(saved) + where)


async def _run_native(
    *,
    _facts: dict | None = None,
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
    params_by_key = {t["key"]: _tool_params(t) for t in wired}
    # _NATIVE_EFFICIENCY = research discipline; GUARD_NOTE = injection defense (wrapped tool/web
    # content is untrusted DATA, not instructions) — same guard the old loop carried.
    system = system + _NATIVE_EFFICIENCY + "\n\n" + GUARD_NOTE

    # convo is the neutral in-turn trajectory (arslan/llm/trajectory.py): one
    # assistant message per model reply that called tools, one tool record per
    # handled call. It is rendered per request (_render_request); compaction
    # evicts whole call groups.
    current_request = {"role": "user", "content": user_content}
    convo: list[dict] = list(history) + [current_request]
    tool_trace: list[dict] = []
    if _facts is not None:
        _facts["tool_trace"] = tool_trace
    research_review_cache: dict = {}
    review_enabled: bool | None = None  # read lazily, once, at the first saved report
    research_source_feedback: list = []
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
    call_ids: set[str] = set()
    from server.orchestrator import agent_status
    from server.orchestrator.model_call import TurnRecovery
    from server.orchestrator.turn_plan import Plan
    turn_state = TurnRecovery()
    plan = Plan()
    turn_started = agent_status.now()
    ws_root, own_folder = await _status_workspace(wired_keys)
    if _facts is not None:
        _facts.update(ws_root=ws_root, started=turn_started)
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
    # 0.1.50 completion first after a stop (S6 bench, T2): repeated failure or a
    # spent fetch allowance ends RESEARCH, not the deliverable. The run enters
    # finish mode once (sticky): up to two steps that offer only the save tools,
    # then text only. Without save tools a no-progress stop forces an answer at
    # once, as before; a spent fetch allowance then changes nothing.
    finish_reason: str | None = None
    finish_from = 0
    finish_steps = 0
    # Wrap-up keeps the FULL tool list while the model complies (an unchanged list
    # keeps the provider's prompt cache: a narrowed one re-sent ~28k tokens uncached
    # in the S6 bench); after its first refused research call, the list narrows.
    wrap_refused = 0
    link_hints: dict[str, int] = {}
    offline_note = _OFFLINE_NOTE if "run_command" in wired_keys else ""
    can_save = bool(WRAP_UP_TOOLS & wired_keys)
    for step in range(request_ceiling):
        budget.check()
        if budget.model_requests >= budget.limits.model_requests:
            if runtime:
                runtime.pause_reason = "task_budget_exhausted"
            budget.stop("model_requests")
        # Three batches of tool calls cut off by the output limit (none of which
        # ran): stop asking for tools and get an answer (0.1.49 S6 breaker).
        truncation_stop = turn_state.truncated_calls >= 3
        if finish_reason is None and not truncation_stop:
            if policy.stopped:
                finish_reason, finish_from = "no_progress", len(tool_trace)
            elif fetch_budget.get("fetches", 0) >= LIVE_FETCH_BUDGET:
                finish_reason, finish_from = "fetch_budget", len(tool_trace)
        saved = any(item.get("tool") in WRAP_UP_TOOLS and (item.get("result") or {}).get("ok") is True
                    for item in tool_trace[finish_from:]) if finish_reason else False
        finishing = finish_reason is not None and can_save and finish_steps < 3 and not saved
        finish_done = finish_reason is not None and not finishing and (can_save or finish_reason == "no_progress")
        forced = (finish_done or (policy.stopped and not finishing) or truncation_stop
                  or budget.tool_calls >= budget.limits.tool_calls
                  or (max_tool_calls is not None and step >= max_tool_calls))
        no_progress = policy.stopped or finish_reason == "no_progress"
        if forced or (finishing and no_progress):
            stop_reason = "task_no_progress" if no_progress or truncation_stop else "task_budget_exhausted"
            if runtime:
                runtime.pause_reason = stop_reason
        # 0.1.50 S1: the system prompt stays byte-identical for the whole turn
        # (prefix cache); this step's notes go to the <agent_status> block.
        notes: list[str] = []
        if forced:
            notes.append("The deliverable is saved. Give the final answer now: where it is, what is verified and "
                         "what is missing. Text only." if saved else
                         "Repeated actions made no progress. Explain what was verified and what is blocked. Text only."
                         if no_progress else
                         "Your tool calls kept exceeding the output limit and none of them ran. Report briefly what "
                         "was verified and what remains. Text only." if truncation_stop else
                         "The web reading allowance for this run is used up: report the verified results and "
                         "remaining work. Text only." if finish_reason == "fetch_budget" else
                         "Tool budget exhausted: report the verified results and remaining work. Text only.")
        # 0.1.43 completion first: past the soft limit (or, 0.1.50, in finish mode),
        # stop gathering and FINISH. Research tools are withdrawn; saving the
        # deliverable stays possible. Not a failure: the completion checks decide
        # the outcome as usual.
        wrap_up = not forced and (finishing or budget.soft_reached())
        if finishing:
            finish_steps += 1
            notes.append(("Repeated actions made no progress, so research has stopped."
                          if finish_reason == "no_progress" else
                          "The web reading allowance for this run is used up, so research has stopped.")
                         + " Using only what you already have, save the deliverable now if one was asked for "
                           "(write_file), marking anything missing or unverified; then give the final answer: "
                           "what was done, what is blocked." + offline_note)
        elif wrap_up:
            notes.append("Work budget nearly used: stop researching now. Using only what you already have, "
                         "produce the complete deliverable the user asked for (save it if a file was asked for), "
                         "clearly marking anything you could not verify. Then give the final answer." + offline_note)
        # Deliver one new tool batch atomically before normal old-history
        # eviction. Keep a bounded 96k research window so a <=96k source batch
        # can survive the following save/readback steps, not just one request.
        # Other turns retain the 64k target. Apply extra protection only
        # to batches <=96k, never permanently pin sources or widen task budgets.
        # Existing opaque-provider pair retention is otherwise unchanged.
        oversized_feedback = pending_feedback and _rendered_size(convo[-pending_feedback:]) > 96_000
        has_web_evidence = any(item.get("tool") == "web_extract" and
                               (item.get("result") or {}).get("ok") for item in tool_trace)
        if has_web_evidence:
            notes.append(
                "Research scope: deliver the smallest useful report answering the requested dimensions. "
                "For a question about one capability, do not expand into an inventory of unrelated README "
                "differences. Unless comprehensive coverage is requested, use at most six relevant comparison "
                "rows and short source quotations, with a concise conclusion and explicit unknowns. "
                "Do not add an exhaustive 'not mentioned' list that the user did not ask for. "
                "Omission from one quoted sentence is not absence from a document. Each shared claim must "
                "be supported by BOTH sources; otherwise attribute it only to the source that says it. "
                "A shared commit URL does not date a translation's baseline or prove why texts differ. "
                "Stay within the existing budget; extra detail is not a substitute for an accurate deliverable.")
        convo, compacted = bounded_history(convo, max_chars=96_000 if has_web_evidence else 64_000,
                                           preserve_tail=0 if oversized_feedback else pending_feedback,
                                           size_of=_rendered_size)
        pending_feedback = 0
        if oversized_feedback:
            notes.append("The newest tool-result batch exceeded the bounded delivery window. Some newly fetched "
                         "content may have been omitted before you saw it. Do not claim to have inspected omitted "
                         "content; request smaller sequential reads or disclose the limitation within remaining budgets.")
        history_compacted = history_compacted or compacted
        if history_compacted:
            notes.append("Earlier conversation turns were compacted. Do not repeat completed effects." + (
                " Saved task progress and owned outputs remain available through task_progress."
                if "task_progress" in wired_keys else
                " task_progress is not available in this turn; do not invent a call to it."))
        # On the forced step pass tools=None so the model CANNOT call a tool and MUST produce
        # prose from the accumulated TOOL RESULTs — never an empty turn.
        # Rolling evidence eviction must not erase this turn's task or its
        # restrictions. Restore the exact request at user priority, not as a
        # system instruction or an invented summary, only in this payload.
        step_tools = (None if forced else [t for t in schemas if t["function"]["name"] in FINISH_TOOLS]
                      or None if wrap_up and wrap_refused else schemas)
        offered = {t["function"]["name"] for t in step_tools or []}
        # Nothing done, planned or noted yet (a plain chat turn, or step 0): no
        # block — the request goes out as the user wrote it. Step 0's write
        # facts live in the tool descriptions (S5); the block starts with work.
        status = "" if not (tool_trace or notes or plan.items) else agent_status.render(
            workspace=agent_status.home_relative(ws_root) if ws_root is not None else None,
            writers=[k for k in ("write_file", "edit_file", "run_command") if k in offered],
            own_folder=own_folder, saved=agent_status.owned_outputs(tool_trace, ws_root, turn_started),
            plan=plan.render(), tool_calls=budget.tool_calls, model_calls=budget.model_requests,
            wrap_up_at=budget.soft.tool_calls if budget.soft is not None else None, notes=notes)
        resp = await _model_call(a, system, convo, current_request, tools=step_tools,
                                 schemas=schemas, forced=forced, state=turn_state, status=status)
        # A context-overflow recovery compacted convo in place (S6).
        history_compacted = history_compacted or turn_state.context_retry_used
        tool_calls = list(getattr(resp, "tool_calls", None) or [])

        if not forced and tool_calls:
            provider_content = getattr(resp, "provider_content", None)
            history_start = len(convo)
            calls = trajectory.unique_ids(
                [trajectory.call_from_response(call, f"call_{step}_{index}")
                 for index, call in enumerate(tool_calls)], call_ids, step)
            convo.append(trajectory.assistant(
                resp.content, calls,
                continuation=({"protocol": "gemini", "provider_content": provider_content}
                              if provider_content else getattr(resp, "continuation", None)),
                finish=getattr(resp, "finish_reason", None)))
            marks: list[tuple[int, str]] = []
            # A reply cut by the output limit may carry incomplete arguments in
            # ANY of its calls: execute none of them (0.1.49 S6).
            cut_off = getattr(resp, "finish_reason", None) == "length"
            if cut_off:
                turn_state.truncated_calls += 1
            for call, neutral_call in zip(tool_calls, calls):
                marks.append((len(convo), neutral_call["id"]))
                fn = call.get("function") or {}
                name = str(fn.get("name") or "")
                args = fn.get("arguments")
                bad_json = None
                if not isinstance(args, dict) and not cut_off:
                    args, bad_json = _parse_arguments(neutral_call["arguments_raw"])
                if not isinstance(args, dict):
                    args = {}
                if cut_off:
                    result = _record_tool_result(name, {}, {"ok": False, "external": False, "code": "output_truncated",
                        "error": TRUNCATED_CALL_ERROR}, emit, tool_trace, json.dumps({"tool": name, "args": {}}), convo)
                    policy.observe(name, {}, result)
                    continue
                if bad_json is not None:
                    result = _record_tool_result(name, {}, {"ok": False, "external": False,
                        "code": "invalid_arguments_json",
                        "error": f"The arguments for {name} were not valid JSON ({bad_json}); nothing was "
                                 "executed. Send the call again with a JSON object."},
                        emit, tool_trace, json.dumps({"tool": name, "args": {}}), convo)
                    policy.observe(name, {}, result)
                    continue
                schema_problem = _schema_problem(args, params_by_key.get(name)) if name in params_by_key else None
                if schema_problem:
                    result = _record_tool_result(name, args, {"ok": False, "external": False,
                        "code": "invalid_arguments",
                        "error": f"Invalid arguments for {name}: {schema_problem}. Nothing was executed; "
                                 "send the call again with corrected arguments."},
                        emit, tool_trace, json.dumps({"tool": name, "args": args}, ensure_ascii=False), convo)
                    policy.observe(name, args, result)
                    continue
                if name == "escalate" and allow_escalation:
                    return {"final": None, "tool_trace": tool_trace,
                            "escalation": {"kind": str(args.get("kind") or "data"),
                                           "need": str(args.get("need") or "").strip(),
                                           "context": str(args.get("context") or "").strip()}}
                # A neutral trace record, not a prompt-level execution protocol.
                assistant_content = json.dumps({"tool": name, "args": args}, ensure_ascii=False)
                # 0.1.50 S2: the plan is host bookkeeping — no executor, no tool
                # budget, no progress signal; allowed during wrap-up too.
                if name == "update_plan" and "update_plan" in wired_keys:
                    emit({"type": "tool_call", "tool": name,
                          "args_summary": json.dumps(args, ensure_ascii=False)[:200]})
                    outcome = plan.update(args)
                    _record_tool_result(name, args, outcome, emit, tool_trace, assistant_content, convo)
                    if outcome.get("ok"):
                        from server.services import desktop_status
                        desktop_status.note_plan(plan.items)
                    continue
                if policy.stopped and not (finishing and name in FINISH_TOOLS):
                    wrap_refused += bool(wrap_up)
                    _record_tool_result(name, {}, {"ok": False, "external": False,
                        "code": "task_no_progress", "error": "Execution paused after repeated work without progress."},
                        emit, tool_trace, json.dumps({"tool": name, "args": {}}), convo)
                    continue
                if wrap_up and name not in FINISH_TOOLS:
                    wrap_refused += 1
                    _record_tool_result(name, {}, {"ok": False, "external": False, "code": "wrap_up",
                        "error": "Wrapping up: no more research. Write the deliverable from what you have."
                                 + offline_note},
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
                if budget.tool_calls >= budget.limits.tool_calls:
                    # The batch crossed the hard tool budget: record the rest as
                    # not run and let the next step (forced) deliver what was
                    # gathered, instead of aborting the turn with an empty reply.
                    result = _record_tool_result(name, {}, {"ok": False, "external": False,
                        "code": "task_budget_exhausted",
                        "error": "The tool budget for this turn is used up: this call did not run. "
                                 "Answer with what you already have."},
                        emit, tool_trace, json.dumps({"tool": name, "args": {}}), convo)
                    continue
                from server.services import terminal_exec
                offline = terminal_exec.OFFLINE.set(True) if wrap_up and name == "run_command" else None
                try:
                    result = await _dispatch_tool(
                        name, args, assistant_content, resolve_tools=resolve_tools, emit=emit,
                        tool_timeout_s=tool_timeout_s, tool_trace=tool_trace, convo=convo,
                        confirm_command=confirm_command,
                        confirm_workspace_write=confirm_workspace_write,
                        confirm_schedule=confirm_schedule, mcp_fail_counts=mcp_fail_counts,
                        mcp_hint_logged=mcp_hint_logged, conversation_id=conversation_id,
                        log_events=log_events, fetch_budget=fetch_budget, caller=caller)
                finally:
                    if offline is not None:
                        terminal_exec.OFFLINE.reset(offline)
                if not policy.observe(name, args, result) and policy.stalled >= 2 and convo \
                        and convo[-1].get("role") == "tool":
                    convo[-1]["content"] += _progress_note(policy)
                # 0.1.50: a saved table of links gets the host link check (link_check).
                if name in WRAP_UP_TOOLS and result.get("ok") is True and convo \
                        and convo[-1].get("role") == "tool":
                    note = await _link_check_note(name, args, result, tool_trace, link_hints)
                    if note:
                        convo[-1]["content"] += note
                if name in wired_keys and _saved_research_report(name, args, result):
                    if review_enabled is None:
                        review_enabled = await _research_review_enabled()
                    if review_enabled:
                        await _review_saved_report(a, args, result, tool_trace, user_content,
                                                   research_review_cache, emit)
                if not provider_content:
                    if name == "web_extract" and _web_read_feedback(name, args, result) is not None:
                        research_source_feedback.append((convo[-1], result))
                    elif (name == "write_file" and result.get("ok") is True
                          and len(research_source_feedback) >= 2
                          and str(args.get("path", "")).lower().endswith((".md", ".txt"))):
                        from server.orchestrator import research_review
                        history_compacted = research_review.compact_saved_context(
                            convo, research_source_feedback, args.get("content")) or history_compacted
                if runtime:
                    runtime.progress = runtime.progress.model_copy(update={
                        "loop_fingerprints": tuple(sorted(policy.seen))[-256:]})
                    await runtime.checkpoint("loop_progress")
            # Each handled call appended one record; bind them to the call ids. The
            # Gemini provider pair and the old "invocation completed" text are now
            # renderings of this trajectory (trajectory.to_legacy), not rewrites.
            _claim_results(convo, marks)
            # resp.content is narration — surface it as an ephemeral note ONLY, never final.
            narration = agent_status.strip_echo((resp.content or "").strip())
            if narration:
                emit({"type": "note", "text": narration[:400]})
            pending_feedback = len(convo) - history_start
            continue

        # No tool calls (or forced) → resp.content should be the FINAL answer. GUARD: the model
        # (esp. on the forced step) may ignore "answer now" and instead narrate or write a TEXT
        # tool-call in its content. Never surface that. Salvage once with a hard no-tools prompt,
        # then synthesize from the accumulated TOOL RESULTs so we NEVER end empty or with a fake
        # tool-call. Native content separation alone does not prevent malformed output.
        # Even a provider ignoring tools=None still marks narration with tool_calls.
        # Never turn that narration into a final answer on a forced synthesis step.
        final_text = "" if tool_calls else agent_status.strip_echo((resp.content or "").strip())
        claimed = _unverified_claim(final_text, tool_trace, wired_keys)
        deferred = _is_deferral_stub(final_text)
        protocol_text = _embeds_protocol(final_text)
        # 0.1.50: an answer that denies a capability this turn had (bench: "no file
        # write ability" with write_file offered) gets one correction.
        from server.orchestrator import capability_truth
        denied = (None if forced or turn_state.capability_bounced or claimed or deferred or protocol_text
                  else capability_truth.denied_capability(final_text, wired_keys, tool_trace))
        if denied:
            turn_state.capability_bounced = True
            policy.observe("answer_validation", {}, {"ok": False, "code": "denied_capability"})
            convo.extend([trajectory.assistant(final_text, continuation=getattr(resp, "continuation", None)),
                          {"role": "user", "content": capability_truth.correction(denied, wired_keys)}])
            continue
        if not forced and (claimed or ((deferred or protocol_text) and wired_keys)):
            policy.observe("answer_validation", {}, {"ok": False, "code": "unverified_answer"})
            # Never execute rescued JSON, nor echo a malformed invocation back
            # as an example to imitate. Permit a new structured call only through
            # the normal tool resolver, permission gate and existing budgets.
            convo.extend([trajectory.assistant(
                "Non-executable tool-call text omitted." if protocol_text else final_text,
                continuation=getattr(resp, "continuation", None)), {"role": "user", "content":
                ("The proposed answer was tool-call text, not a native tool request; it executed no action. " if protocol_text else
                 f"The proposed answer lacks a successful {claimed} receipt. " if claimed else
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
        if (not final_text) or protocol_text or deferred or claimed:
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
                    # The reply's continuation belongs to its own text only; a
                    # synthesized/salvaged answer came from another request.
                    own = final_text == (resp.content or "").strip()
                    convo.extend([trajectory.assistant(
                        final_text, continuation=getattr(resp, "continuation", None) if own else None),
                                  {"role": "user", "content":
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
