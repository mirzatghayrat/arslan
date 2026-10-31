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
from contextvars import ContextVar
from typing import TYPE_CHECKING

from arslan.execution_budget import BudgetExceeded, governed
from arslan.llm import tool_names, trajectory, usage_sink
from arslan.runtime_policy import FailureKind, ProgressPolicy, bounded_history, exception_kind

from server.orchestrator import run_trace
from server.orchestrator.answer_contract import GROUNDED_ANSWER_RULES
from server.orchestrator.json_protocol import first_json_object, parse_json_object
from server.orchestrator import on_demand, parallel_reads, turn_context
from server.services import terminal_exec
from server.orchestrator.untrusted import GUARD_NOTE, wrap_external
from server.registry.executors import EXECUTORS, resolve_executor
from server.services import replay_safety, steering
from server.services.llm_factory import build_adapter
from arslan.aio import within

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from server.orchestrator.tool_caller import ToolCaller

TOOL_TIMEOUT_S = 20.0
# 0.1.62 F1: run_command's backstop stops this much before the turn's own timeout, so the order
# is fixed: the command's limit first (with its output), this backstop next, the turn last.
_RUN_COMMAND_BACKSTOP_RESERVE_S = 10.0
# The in-turn history's bound on a provider that doesn't clear old results itself (rendered characters).
# K4a gate (⓪Plan's DeepSeek run, T2): over the bound, the history is trimmed to half of it in one go.
# Trimmed back under the bound one message at a time, the start of the history changed on every step,
# and the provider's prefix cache missed everything after the system prompt (about 60k uncached tokens a
# step); now the cache breaks once per chunk and the steps in between only append (the K3b family).
_IN_TURN_CHARS = 64_000
_IN_TURN_CHARS_RESEARCH = 96_000
# Task-record refusals that end one call, never the turn or the job (_dispatch_tool): what the model is told.
_REFUSED_STEP = {
    "task_reconciliation_required": "This exact action already ran and its outcome is unknown. Do not repeat it; "
                                    "tell the user to check whether it happened.",
    "task_action_already_completed": "This exact action already succeeded in this task. Do not repeat it.",
    # D6 (K3's Claude run, T2 r2): it used to stop the whole background job.
    "task_action_arguments_not_journalable": (
        "This step did not run: its arguments can't go into the task record. They are over 256 KB, or contain "
        "something that looks like a secret (a password, key, token or cookie value). Don't put secrets in files "
        "or commands: read them from an environment variable or a file the user names. Split a very long write "
        "into several smaller ones."),
}

# The T1 write tools, gated as a category (P1b). Kept as a set here — the tool
# list in _arslan_tools decides what is OFFERED, this decides what is GATED, and
# a tool that slips out of this set would be a silently ungated writer.
_WORKSPACE_WRITE_TOOLS = frozenset({"write_file", "edit_file"})



ResolveTools = Callable[[], Awaitable[list[dict]]]
# (command, argv, *, remote_host=, fingerprints=, sandbox=, why=) -> approved
ConfirmCommand = Callable[..., Awaitable[bool]]


def _get_adapter():
    """Indirection so tests can stub adapter construction."""
    return build_adapter(role="execute")


async def _adapter_for_turn(*, has_images: bool, conversation_id: str | None = None):
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
    # 0.1.58 §6: the model chosen for this conversation, when there is one.
    if conversation_id:
        from server.services.llm_factory import build_conversation_adapter
        try:
            chosen = await build_conversation_adapter(conversation_id)
        except Exception:  # noqa: BLE001 — a broken choice must never take the turn down
            chosen = None
        if chosen is not None:
            return chosen
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
    # K8a: 没查到 / 未查到 says nothing was found, not that a search ran.
    r"我搜索|搜索了|(?<![没未])查到了?|获取到(了|的)?数据|我已搜|i (just )?searched|let me search|i looked it up",
    re.IGNORECASE)


def _claims_chart(text: str) -> bool:
    return bool(_CLAIMS_CHART_RE.search(text or ""))


def _claims_search(text: str) -> bool:
    return bool(_CLAIMS_SEARCH_RE.search(text or ""))


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
    r"|调用\s*(web_search|web_extract|render_chart)"
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
    return (f"⚠ This MCP tool has failed {n} times in a row this turn. Use the equivalent built-in tool "
            "instead (web_extract to read a page, web_search to search); do not retry this MCP tool.")


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


# 0.1.63 K1b: set for each step of a turn whose provider clears old context itself (Claude's native
# path): what was sent is never edited again, so screenshots are not turned into stubs here.
_SENT_IS_FINAL: ContextVar[bool] = ContextVar("sent_is_final", default=False)


def _server_trims(a, state) -> bool:
    """Whether this step goes natively to a provider that clears old tool results server-side."""
    use_native = getattr(a, "native_trajectory", None)
    trims = getattr(getattr(a, "_provider", None), "trims_context_server_side", None)
    return bool(not state.legacy and callable(use_native) and use_native() and callable(trims) and trims())


def _record_tool_result(tool_key, args, result, emit, tool_trace, assistant_content, convo,
                        mcp_fail_counts: dict | None = None) -> dict:
    # Hands v2 screenshots (spec 2026-10-08-0157 §4.2-4.5): `images` go to the model as image
    # parts of this result and nowhere else - not the payload text, the trace, the run trace,
    # the UI event or any file. The result everyone else sees says only that one was taken.
    images = result.get("images") if isinstance(result.get("images"), list) else None
    image_label = str(result.get("image_label") or tool_key)
    if "images" in result or "image_label" in result:
        result = {k: v for k, v in result.items() if k not in ("images", "image_label")}
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
    from server.services import tool_review
    emit({"type": "tool_result", "tool": tool_key, "ok": bool(result.get("ok")),
          "summary": _summarize_result(result), "artifact": result.get("artifact"),
          "artifacts": result.get("artifacts") or [],
          # The phone's quick review (mobile bridge): recorded with the step, never framed.
          "review": tool_review.capture(tool_key, args, result)})
    tool_trace.append({"tool": tool_key, "args": args, "result": result})
    run_trace.record(tool=tool_key, args=args, result=result,
                      ok=bool(result.get("ok")), error=result.get("error"), ms=None)
    from server.orchestrator import untrusted as _untrusted
    framed = (raw_payload if result.get("external") is False else wrap_external(raw_payload)
              if _untrusted.from_the_web(tool_key, args) else _untrusted.wrap_tool_output(raw_payload))
    # S64-0c: a failure counts once the call reached the outside (an MCP server's error, a network command's
    # output on a non-zero exit); only a result that says it never left (`executed: False`) does not.
    reached = result.get("executed") is not False
    if reached and (_untrusted.counts_as_external(tool_key, args)
                    or (tool_key in ("read_skill", "background_status", "find_tools")  # S64-0b/0c: per result
                        and result.get("external") is True)):
        _untrusted.mark_external()           # 0.1.52: this turn read outside content
    if not _untrusted.known_local_call(tool_key, result):
        _untrusted.mark_off_the_list()       # INB2 (#475 F2): any call off the user's allowlist, run or not
    # PB-3 degrade hint. Placement is deliberate: `framed` ends with its frame's close, so the
    # hint sits AFTER the data frame — it is OUR trusted framing (like the
    # "TOOL RESULT for X" header and the "Use this to continue" trailer), never inside
    # the untrusted region the GUARD_NOTE tells the model to distrust.
    hint = ""
    if mcp_fail_counts is not None:
        if result.get("ok"):
            mcp_fail_counts.pop(tool_key, None)          # success resets the streak
        elif tool_key.startswith("mcp_") and result.get("executed") is not False:
            # S1: a refusal (a card's no, nobody to ask) never reached the server: not a failure of the tool.
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
                                        synthetic=True, legacy_call=assistant_content,
                                        images=images, image_label=image_label))
    if images and not _SENT_IS_FINAL.get():
        trajectory.keep_latest_images(convo)
    return result


def _planned_read(call: dict, neutral_call: dict, wired_keys: set, params_by_key: dict) -> tuple[str, dict] | None:
    """K9a: the call's name and arguments as the batch loop will see them, when it is called by its own name
    with arguments that parse and fit its table; otherwise None (it cannot run next to others)."""
    fn = call.get("function") or {}
    name = str(fn.get("name") or "")
    args = fn.get("arguments")
    if not isinstance(args, dict):
        args, bad_json = _parse_arguments(neutral_call["arguments_raw"])
        if bad_json is not None or not isinstance(args, dict):
            return None
    if name not in wired_keys or name in ("use_tool", "find_tools"):
        return None
    if name in params_by_key and _schema_problem(args, params_by_key[name]):
        return None
    return name, args


def _read_steers(steers: list, convo: list[dict], pending: list) -> None:
    """K9b: the messages sent while the turn worked join it after the batch's results (K1's order: tool
    results, then the user's text). They become part of the turn when the next request carries them
    (_commit_steers); until then `pending` holds them, and run_native hands back what no request carried."""
    for steer in steers:
        convo.append({"role": "user", "content": steer.content})
        pending.append(steer)


async def _commit_steers(pending: list, conversation_id: str) -> None:
    """K9b: the request about to go carries these messages: each is stored as a user message tagged with this
    run (so the undo of the turn, S3b, takes it with the turn and never counts it as a later one), one from the
    iPhone is shown in the Mac windows as today (never journaled: it is in the history; never echoed to its own
    sender, the Bridge, whose next turn would read as the phone's), and its sender hears `dequeued` with
    `inserted`. Each leaves `pending` before it is stored: a stop landing as it is stored counts it as stored (it
    is never run twice); a store that fails puts it back, to go back with the rest."""
    from server.orchestrator import memory
    from server.services import personal_context, run_registry
    from server.ws import protocol
    current = personal_context.current()
    run_id = current.source_run_id if current is not None else None
    while pending:
        steer = pending.pop(0)
        try:
            message_id = await memory.add_message(conversation_id, "user", steer.content, source=steer.source,
                                                  run_id=run_id)
        except asyncio.CancelledError:
            steer.settle()
            raise
        except Exception:
            pending.insert(0, steer)
            raise
        steer.settle()
        if steer.source == "phone":
            run_registry.make_emit(conversation_id, skip=steer.sink)(
                protocol.message(message_id, steer.content, "user") | {"source": "phone"})
        try:
            await steer.tell({"type": "dequeued", "inserted": True})
        except Exception:  # noqa: BLE001 — its socket closed; the message is in the turn anyway
            pass


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
    return (f"\n[Host note: no new progress — {policy.count} of {policy.limit} steps without "
            "progress before this turn stops. Change approach, or answer with what you have.]")


_OFFLINE_NOTE = (" Files you already fetched can still be processed with run_command (it runs without "
                 "network now).")

CONTINUE_PROMPT = ("Your previous reply was cut off by the output limit. Continue exactly where it "
                   "stopped, without repeating anything already written and without any preamble.")
# K9b: a call of the batch not started when the user sent a message (it is read right after these results).
SKIPPED_FOR_MESSAGE = ("Not run: the user sent a message while you were working. It comes right after these "
                       "results; read it first, then call this again only if it still makes sense.")
TRUNCATED_CALL_ERROR = (
    "The output limit was reached while writing this call's arguments; nothing was executed. "
    "Split the work: write the first part with write_file, then append each further part with "
    "edit_file (replace the file's current last line with that line plus the next part), "
    "or shorten the payload.")


# Hands v2 §4.4: model configurations that refused an image this process. Their screenshots are
# read by this Mac's text recognition before sending, instead of failing again.
_REFUSES_IMAGES: set[tuple[str, str, str]] = set()


# 0.1.62 F3: (model, tool key, sha256 of the schema as the server wrote it) for MCP schemas a
# provider refused this process. A changed schema hashes differently and is tried again.
_BAD_TOOLS: set[tuple[tuple[str, str, str], str, str]] = set()


def _model_key(a) -> tuple[str, str, str]:
    provider = getattr(a, "_provider", None)
    return (type(provider).__name__, str(getattr(provider, "model", "")), str(getattr(provider, "base_url", "")))


# ── 0.1.62 F3: a refused MCP schema costs that tool, at worst every MCP tool, never the turn ──
# A fallback for what arslan/llm/tool_schema.normalise does not cover. Delete with _BAD_TOOLS
# once the M2 weekly report shows zero `mcp_schema_relaxed` four weeks running (v0.1.65 at the
# earliest; docs/plans/0162/F3-mcp-schema.md).
_SCHEMA_WORDS = re.compile(r"\b(tools?|functions?|schema|parameters)\b", re.I)


def _schema_hash(params) -> str:
    return hashlib.sha256(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()


class _SchemaDrops:
    """The MCP tools one turn leaves out: refused by name this turn, every one after a second
    refusal, and any this model refused earlier in this process (_BAD_TOOLS)."""

    def __init__(self, a):
        self.model = _model_key(a)
        self.names: set[str] = set()
        self.every = False
        self.changed = False

    def hides(self, key: str, params) -> bool:
        return key.startswith("mcp_") and (
            self.every or key in self.names or (self.model, key, _schema_hash(params)) in _BAD_TOOLS)

    def keep(self, wired: list[dict]) -> list[dict]:
        return [t for t in wired if not self.hides(t["key"], _tool_params(t))]

    def keep_schemas(self, schemas):
        if schemas is None:
            return None
        return [t for t in schemas
                if not self.hides(t["function"]["name"], t["function"].get("parameters"))] or None


def _hiding(resolve_tools: ResolveTools, drops: _SchemaDrops) -> ResolveTools:
    """resolve_tools as this turn sees it: the step's tool list, the capability refresh and the
    executor's `live` check all go through it, so a left-out tool answers `tool_unavailable`."""
    async def resolve() -> list[dict]:
        return drops.keep(await resolve_tools())
    return resolve


def _refused_tool(a, sent: list[dict], text: str) -> str | None:
    """The MCP tool a refusal points at, only ever one this request carried: the provider reads
    its own error against its own payload order, else the longest MCP name the text mentions.
    NAME1: the provider wrote the names it was sent (tool_names.wire); both lead back to the key."""
    mcp = {t["function"]["name"] for t in sent if t["function"]["name"].startswith("mcp_")}
    named = getattr(a, "named_tool", None) or getattr(getattr(a, "_provider", None), "named_tool", None)
    name = named(sent, text) if callable(named) else None
    if name in mcp:
        return name
    mentioned = {n: max(len(form) for form in (n, tool_names.wire(n)) if form in text)
                 for n in mcp if n in text or tool_names.wire(n) in text}
    return max(sorted(mentioned), key=mentioned.get) if mentioned else None


async def _images_to_text(convo: list[dict]) -> int:
    """Tier 2 (spec §4.4, server/services/ocr_fallback.py): every screenshot in this turn becomes
    the text macOS Vision reads off it, framed as untrusted like the window it came from.
    In place; returns how many were read."""
    import asyncio
    import base64
    from server.services import ocr_fallback
    ui_language, chosen = await ocr_fallback.current_ui_language(), await ocr_fallback.current_ocr_languages()
    read = 0
    for message in convo:
        images = message.pop("_images", None)
        if not images:
            continue
        label = message.pop("_image_label", None) or message.get("name") or "screenshot"
        texts = []
        for image in images:
            try:
                data = base64.b64decode(image["data"])
            except (KeyError, ValueError):
                continue
            text, _status = await asyncio.to_thread(ocr_fallback.read_locally, data, ui_language=ui_language,
                                                    chosen_languages=chosen)
            texts.append(text)
            read += 1
        body = "\n".join(t for t in texts if t) or "(no text could be read off it)"
        message["content"] = (f"{message.get('content', '')}\n[screenshot of {label}: this model cannot take "
                              f"images; the text this Mac read off it follows]\n{wrap_external(body)}")
    return read


async def _model_call(a, system: str, convo: list[dict], current_request: dict, *,
                      tools, schemas, forced: bool, state, status: str = "",
                      drops: _SchemaDrops | None = None, conversation_id: str | None = None,
                      step: "_StepStream | None" = None):
    """The one model call of a run_native step, with recovery (0.1.49 S6).

    Native adapters (OpenAI-compatible and Gemini; Claude from K1b;
    ARSLAN_TOOL_PROTOCOL not "legacy") get the trajectory in their own tool
    protocol; a forced step keeps the SAME tools with tool_choice "none".
    Everything else (test doubles, rollback) gets the legacy rendering, unchanged.

    Recovery (server/orchestrator/model_call.py): classified transport retries;
    a protocol rejection switches this turn to the legacy rendering; a context
    overflow compacts once; a finish_reason "length" cut is re-sent with the
    endpoint's ceiling, then a cut answer is continued. A cut tool call is
    returned as is: run_native never executes it. `state` is per turn.

    `status` (0.1.50 S1) is appended to the last message of the step's base
    messages in both renderings (on a provider with APPENDS_STATUS natively: stored
    once in the trajectory as its own block, K1); continuation turns follow it, so a
    continuation request shares the original request's exact prefix.

    `step` (K8a) gets the answer's text as it arrives, where the endpoint streams. Once some of it was
    shown, nothing re-sends the request (a retry, a protocol switch, a compaction or a raised output limit
    would show it twice): TextShown ends the turn instead. A cut answer is still continued."""
    from server.orchestrator import agent_status
    from server.orchestrator import model_call as mc

    def build_messages():
        return convo if any(item is current_request for item in convo) else [current_request, *convo]

    if trajectory.image_count(convo) and _model_key(a) in _REFUSES_IMAGES:
        await _images_to_text(convo)          # known not to take images: read them first
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
    # 0.1.63 K1: a provider that must never see history edited (Claude's preserved thinking; Gemini
    # too) keeps each step's status in the trajectory, as its own block after the step's results,
    # instead of having it glued onto the last message for one request and gone the next.
    status_record = None
    if native and status and getattr(getattr(a, "_provider", None), "APPENDS_STATUS", False):
        status_record = trajectory.status(status)
        convo.append(status_record)
        messages = build_messages()

    async def request(extra=None, max_tokens=None):
        base = list(messages) if status_record is not None and native else agent_status.attach(messages, status)
        sent = base + list(extra or [])
        kwargs = {"max_tokens": max_tokens} if max_tokens else {}
        if native:
            step_tools = schemas if forced else tools
            # tool_choice only with tools: leaving every MCP tool out (0.1.62 F3) can empty the list.
            if step is not None:
                kwargs["on_text"] = step.feed
            return await a.chat_trajectory(system, sent, tools=step_tools,
                                           tool_choice="none" if forced and step_tools else None, **kwargs)
        # One legacy entry point (_render_request) for every request of the step.
        rendered = _render_request(convo, current_request, status) + trajectory.to_legacy(list(extra or []))
        return await a.chat(system, rendered[-1]["content"], history=rendered[:-1], tools=tools, **kwargs)

    async def relax(exc, *, last: bool = False) -> bool:
        """0.1.62 F3: an `input` refusal of a request carrying MCP tools that names one (or reads
        like a schema problem): leave it out (`last`, or none named: every MCP tool) and say so."""
        nonlocal tools, schemas, status, status_record, messages
        sent = ((schemas if forced else tools) if native else tools) or []
        if (drops is None or exc.kind not in ("input", "protocol") or state.exhausted
                or not any(t["function"]["name"].startswith("mcp_") for t in sent)):
            return False
        text = exc.excerpt or ""        # the provider's own words; str(exc) also carries our recovery notes
        name = _refused_tool(a, sent, text)
        # 0.1.63 K1a: a refusal naming an MCP tool whose name holds a protocol word
        # (mcp_1__get_tool_result) classifies as "protocol"; it is still that tool's schema.
        if exc.kind == "protocol" and name is None:
            return False
        if name is None and not _SCHEMA_WORDS.search(text):
            return False
        if name is not None:            # remembered even when this is the last try and every tool goes
            params = next(t["function"].get("parameters") for t in sent if t["function"]["name"] == name)
            drops.names.add(name)
            _BAD_TOOLS.add((drops.model, name, _schema_hash(params)))
        if name is None or last:
            drops.every, left_out = True, "all"
        else:
            left_out = name
        drops.changed = True
        tools, schemas = drops.keep_schemas(tools), drops.keep_schemas(schemas)
        what = "every MCP tool" if left_out == "all" else f"the MCP tool {left_out}"
        state.note(f"left out {what} (the provider refused its parameter schema)")
        shown = "every MCP tool" if left_out == "all" else f"the MCP tool {tool_names.wire(left_out)}"  # NAME1
        status = (f"{status}\n\n" if status else "") + (
            f"Note: {shown} is not available in this turn: the model provider refused its parameter "
            "schema. Use the other tools, or tell the user that capability cannot be used right now.")
        if status_record is not None:
            status_record["content"] = status       # not accepted by the provider yet: still editable
        elif native and getattr(getattr(a, "_provider", None), "APPENDS_STATUS", False):
            status_record = trajectory.status(status)
            convo.append(status_record)
            messages = build_messages()
        provider = getattr(a, "_provider", None)
        reported = getattr(a, "report_provider", None) or getattr(provider, "provider_name", type(provider).__name__)
        try:
            from server.services import recap_service
            await recap_service.log_event(
                conversation_id, "mcp_schema_relaxed", {"tool_key": left_out, "provider": str(reported)},
                f"left out {what}: the provider refused its parameter schema")
        except Exception:  # noqa: BLE001 — observability is never fatal
            pass
        return True

    remaining = _remaining_seconds()
    relaxed = False
    try:
        resp = await mc.call_with_recovery(_once_shown(request, step), state, remaining_s=remaining)
    except mc.ModelCallError as exc:
        from server.services import ocr_fallback
        if step is not None and step.released:
            raise TextShown(exc.excerpt) from exc
        # First: an image refusal can also look like a protocol rejection; switching protocols
        # would send the same screenshots again and fail the same way.
        if (trajectory.image_count(convo) and not state.images_read_locally
                and ocr_fallback.model_refused_the_image(f"{exc.excerpt} {exc}")):
            # §4.4: the model refused the screenshots as images (vision_errors' narrow match, never
            # a rate limit or a bad key). Read them locally, remember this model, ask once more.
            state.images_read_locally = True
            _REFUSES_IMAGES.add(_model_key(a))
            await _images_to_text(convo)
            messages = build_messages()
            state.note("read screenshots as text (this model cannot take images)")
        elif await relax(exc):
            relaxed = True
        elif exc.kind == "protocol" and native and not state.exhausted:
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
            if _SENT_IS_FINAL.get():
                # K1b: the one edit of sent history this path allows; thinking blocks after it drop.
                from arslan.execution_budget import current
                if (budget := current()) is not None:
                    budget.note_context("compacted", reason="context_overflow", count=1)
        else:
            raise
        try:
            resp = await mc.call_with_recovery(_once_shown(request, step), state, remaining_s=remaining)
        except mc.ModelCallError as again:
            # Refused again after one tool was left out: every MCP tool goes, for one last try.
            if not (relaxed and await relax(again, last=True)):
                raise
            resp = await mc.call_with_recovery(_once_shown(request, step), state, remaining_s=remaining)
    return await _recover_truncation(a, resp, request, state, remaining, step)


def _once_shown(make, step: "_StepStream | None"):
    """K8a: `make` for call_with_recovery, whose retries resend the whole request. A retry goes out only
    while nothing of the failed attempt was shown; otherwise TextShown (never classified, never retried)."""
    tries = 0

    async def attempt():
        nonlocal tries
        tries += 1
        if tries > 1 and step is not None and not step.retry_ok():
            raise TextShown("the model stopped after part of the answer was shown")
        return await make()
    return attempt


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


async def _recover_truncation(a, resp, request, state, remaining, step=None):
    """finish_reason == "length": raise to the endpoint's ceiling once, then
    continue a cut answer. A cut caused by the work budget is not raised (that
    would spin: raise -> clamp -> cut). Per-turn caps live on `state`. Once the
    answer was shown as it was written (K8a), only continuing it is allowed."""
    from server.orchestrator import model_call as mc
    if getattr(resp, "finish_reason", None) != "length" or _output_clamped():
        return resp
    provider = getattr(a, "_provider", None)
    ceiling, current_max = getattr(provider, "output_ceiling", None), getattr(provider, "max_tokens", None)
    raise_to = ceiling if isinstance(ceiling, int) and isinstance(current_max, int) and ceiling > current_max else None
    if raise_to and state.output_raises < 2 and not state.exhausted and not (step is not None and step.released):
        state.output_raises += 1
        state.note(f"raised output limit to {raise_to}")
        resp = await mc.call_with_recovery(_once_shown(lambda: request(max_tokens=raise_to), step), state,
                                           remaining_s=remaining)
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
        last = await mc.call_with_recovery(_once_shown(lambda: request(extra=extra, max_tokens=raise_to), step),
                                           state, remaining_s=remaining)
        text += last.content or ""
        if getattr(last, "finish_reason", None) != "length" or getattr(last, "tool_calls", None) \
                or _output_clamped():
            break
    # The joined text is no single reply's output: no continuation state.
    return _replaced(resp, content=text, finish_reason=getattr(last, "finish_reason", None),
                     tool_calls=[], continuation=None)


def _context_parts(system: str, schemas: list[dict] | None, convo: list[dict], current_request: dict,
                   status: str) -> dict[str, int]:
    """0.1.63 K4b: what the request about to be sent is made of, estimated with the one estimator, for
    the composer's ring breakdown (its total stays the provider's last_input): the system text, the
    tools, the turn's reference block (memory and context), earlier turns, and this turn (the user's
    words, tool calls and results, kept and current status blocks)."""
    from arslan.context_budget import IMAGE_TOKEN_GUESS, estimate_tokens

    def size(messages: list[dict]) -> int:
        rendered = json.dumps(trajectory.to_legacy(messages, images=False), ensure_ascii=False, default=str)
        kept = "".join(m.get("content") or "" for m in messages if m.get("_status"))
        return (estimate_tokens(rendered) + estimate_tokens(kept)
                + IMAGE_TOKEN_GUESS * trajectory.image_count(messages))
    at = next((i for i, m in enumerate(convo) if m is current_request), None)
    history, after = (convo[:at], convo[at + 1:]) if at is not None else ([], convo)
    content = current_request.get("content")
    words = estimate_tokens(turn_context.users_words(content))
    return {"system": estimate_tokens(system),
            "tools": estimate_tokens(json.dumps(schemas, ensure_ascii=False)) if schemas else 0,
            "context": max(0, estimate_tokens(content) - words),
            "history": size(history),
            "turn": words + size(after) + estimate_tokens(status)}


def _rendered_size(messages: list[dict]) -> int:
    """Context size of what is actually sent, not of local bookkeeping. Kept status blocks
    (trajectory.status, K1) are sent natively though the legacy rendering leaves them out."""
    kept = sum(len(m.get("content") or "") for m in messages if m.get("_status"))
    return (len(json.dumps(trajectory.to_legacy(messages, images=False), ensure_ascii=False, default=str))
            + trajectory.IMAGE_SIZE_CHARS * trajectory.image_count(messages) + kept)


async def _log_degrade_hint(conversation_id, tool_key, count) -> None:
    """PB-3 observability: one conversation_events row the FIRST time the degrade hint
    fires for a tool this turn (PB-4's warning wiring reads these). Fail-open — logging
    must never touch the turn."""
    try:
        from server.services import recap_service
        await recap_service.log_event(
            conversation_id, "mcp_degrade_hint",
            {"tool_key": tool_key, "count": count},
            f"MCP tool {tool_key} failed {count} times in a row this turn; suggested the built-in equivalent")
    except Exception:  # noqa: BLE001 — observability is never fatal
        pass


#: 0.1.63 K4b (decision D4, ⓪Plan Q1 = A): a chat turn this long (its own time: a card's wait doesn't
#: count) is told once, in its status block, that it may continue the rest as background work, and the
#: user's reply gets one `note` line. A suggestion, never forced. No setting: nothing interrupts the user,
#: so the card's "can be switched off" was dropped with that decision.
LONG_TURN_S = 600
_LONG_TURN_NOTE = (f"This turn has been working for {LONG_TURN_S // 60} minutes. If what remains is long and "
                   "doesn't need the user meanwhile, you may continue it as background work: call "
                   "start_background_work with a goal that says what is already done in this turn and what "
                   "remains, then tell the user. Otherwise keep going here.")


#: 0.1.63 K5 (⓪Plan's Q5/Q6): once a turn has had two steps whose calls are not only update_plan, its status
#: block asks for four closing lines. Arslan's own turns only (never a delegated worker, which answers in
#: JSON). "Unverified" in the reply's language, never 没查到: _CLAIMS_SEARCH_RE reads that as a claim to
#: have searched (K8 fixes the pattern).
_CLOSING_NOTE = ("This turn used tools in several steps. End your final reply with four short lines, in the "
                 "reply's language: what you did; how you checked it; what you did not check (call it "
                 "unverified, in the reply's language, e.g. 未核对 in Chinese); what the user should watch.")


#: 0.1.63 K4b: a live run has no allowance of its own any more (it was 25); a web read is one tool
#: call under the run's limits (K4a), and K4a's tool-call limit and dollar cap bound a web-heavy turn.
#: What stays is the eval/replay allowance below. The tools it covers: capping web_extract alone
#: would be bypassed by alternating with web_search, so they share ONE allowance.
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


async def _check_fetch_budget(tool_key: str, *, conversation_id: str | None) -> dict | None:
    """None to proceed, or an explicit refusal dict once an eval/replay attempt has spent its allowance.

    🔴 SCOPE. A live run has no fetch allowance since 0.1.63 K4b: its reads count as tool calls.
    A hermetic eval/replay gets HERMETIC_FETCH_BUDGET for the WHOLE ATTEMPT, which is the only shape that
    bounds anything there: `web_search` and `web_extract` are both in
    REPLAY_SAFE_BUILTINS (sealing keeps read-only web and drops WRITE tools plus
    anything non-allowlisted), and the gate dispatches roughly
    `pairs x 2 arms x (epochs*lr_budget + 1)` times — so a per-dispatch cap would
    multiply rather than limit. This was registered as FU-2b and is now in.

    The refusal is EXPLICIT rather than a silent drop: a swallowed fetch looks to the
    model like a page with no content, and it will simply try the next URL.
    """
    if tool_key not in _FETCH_TOOLS:
        return None
    if replay_safety.is_hermetic_context(conversation_id):
        return _check_hermetic_fetch_budget(conversation_id)
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


def _declined(refused: str, subject: str) -> str:
    """What a "no" from a card tells the model (0.1.61): the decision's own text when there is
    one (the user's note, or "nobody answered — NOT a refusal"), never "declined" for a card
    that simply ran out (seen 2026-10-04 on a phone task)."""
    from server.services import approvals, permissions
    decision = permissions.LAST_DECISION.get()
    if decision is not None and not decision.allowed and decision.model_text:
        return decision.model_text
    if approvals.LAST_OUTCOME.get() == "expired":
        return (f"Nobody answered the card for {subject} in 30 minutes. This is NOT a refusal. "
                "Don't retry it in this turn. Finish what you can and tell the user what is waiting.")
    return refused


async def _writing_in_own_folder() -> bool:
    """Unknown means ask: if the setting cannot be read, treat the folder as the user's."""
    from server.db import session as db_session
    from server.services import settings_service
    try:
        async with db_session.AsyncSessionLocal() as db:
            return await settings_service.workspace_is_default(db)
    except Exception:  # noqa: BLE001
        return False


async def _workspace_root_or_none():
    """The workspace folder for a refusal's ledger row; unreadable means unnamed ("*")."""
    from server.registry import file_tools
    try:
        return await file_tools._workspace_root()
    except Exception:  # noqa: BLE001 — the row names the folder when it can; the refusal stands either way
        return None


async def _unattended(error: str, req, conversation_id: str | None) -> str:
    """S1 (U14 c): a step refused for want of a card callback. With nobody to ask (a scheduled run) the
    refusal is listed in the Inbox and the model is told what decide() tells it; a turn with someone to
    ask (none today lacks the callback) keeps `error` and writes no row."""
    from server.services import background_jobs, permissions
    if permissions.current_asker() is not None:
        return error
    return await permissions.refuse_unattended(
        req, permissions.Context(conversation_id, job_id=background_jobs._inside_job.get()))


def _nobody_to_ask(confirm_command) -> bool:
    """A run with no card callback and no card surface: a scheduled run (the heartbeat is one)."""
    from server.services import permissions
    return confirm_command is None and permissions.current_asker() is None


#: What the model is told when a run with nobody to ask names run_command (v0.1.63; DELETE-BY: v0.1.64, with
#: S2a-3 and PR4).
SCHEDULED_COMMAND_NOTE = ("Scheduled runs don't run commands. Save what you found with write_file (it writes in "
                          "Arslan's own folder), or tell the user what to run themselves.")


async def _scheduled_command_refused(args: dict, conversation_id: str | None) -> dict:
    """The refusal of a command in a run with nobody to ask, listed in the Inbox as the card would have read under
    "ask for every command" (U14 c): policy, deny, no "Always"."""
    from server.services import approvals, terminal_policy
    command = terminal_policy.as_shell(args.get("command"), args.get("argv"))
    return {"ok": False, "error": await _unattended("a scheduled run runs no commands",
                                                    approvals._command_request(command, [], None, ask_all=True),
                                                    conversation_id),
            "note": SCHEDULED_COMMAND_NOTE}


def _outside_request(command: str):
    """S4a: what running `command` outside the sandbox asks: every command of the conversation may (`outside`
    / `*`), the card's "In this conversation" (command_confirm)."""
    from server.services import permissions
    return permissions.Request(kind="outside", target="*", detail=command,
                               title=f"Run `{command[:80]}` outside the sandbox?")


async def _outside_grant(conversation_id: str | None, command: str):
    """S4a: this conversation's stored grant to run its commands outside the sandbox (`permissions.standing`,
    which finds nothing where nobody can be asked), or None. No ledger row yet: `note_standing` writes it."""
    from server.services import background_jobs, permissions
    return await permissions.standing(_outside_request(command), permissions.Context(
        conversation_id, job_id=background_jobs._inside_job.get()))


async def _network_after_outside_content(command: str, args: dict, *, sandbox_on: bool, run_outside: bool,
                                         unwrapped: bool, conversation_id: str | None) -> dict:
    """S2a-1 piece 2. After this turn read outside content (a page, a file, an MCP tool), a command
    runs offline under the kernel's rule — in the sandbox, and outside it under the minimal profile,
    which carries the same rule (card, piece 4; the internal review's case: a script refused inside for
    reading a secret, let out by the retry card, must not get the network with it). One that reaches the
    network (by its text, or the model's `network: true`) asks first: this time or this conversation
    inside the sandbox, this time only outside it, where the user's secrets are readable (a stored grant
    does not count there). The island never answers it. With nobody to ask: offline. An approved plain
    osascript (U11) runs with no wrapper and is not a network command; an approved bare Shortcut asks for
    the network, this time only, and does not run without it. Where seatbelt cannot start nothing is
    wrapped, so only the card holds.

    Returns {"offline": bool, "note": str} or {"refused": model text}."""
    from server.orchestrator import untrusted as _untrusted
    from server.services import background_jobs, command_sandbox, permissions, task_service
    if not _untrusted.external_seen():
        return {}
    if unwrapped:
        # ⓪Plan's S-gate review: a bare osascript (one of four apps, no URL) is not a network command,
        # but a Shortcut can do anything, the network included, and a bare run has no offline rule. It
        # asks first, this time only; with nobody to ask, or on a no, it does not run.
        if not task_service.bare_shortcut(command):
            return {}
        request = permissions.Request(
            kind="network", target="network:*", title=f"Let the Shortcut `{command[:80]}` use the network?",
            detail=command, why=str(args.get("why") or "").strip()[:300], conversation_ok=False, once_only=True)
        if permissions.current_asker() is None:
            return {"refused": await _unattended("", request, conversation_id)}
        decision = await permissions.decide(request, permissions.Context(
            conversation_id, job_id=background_jobs._inside_job.get()))
        return {} if decision.allowed else {
            "refused": decision.model_text or "the user did not allow this Shortcut to use the network"}
    wrapped = command_sandbox.available()
    inside = sandbox_on and not run_outside and wrapped
    if not (args.get("network") is True or _untrusted.reaches_network(command)):
        return {"offline": True} if wrapped else {}
    if wrapped and permissions.current_asker() is None:
        return {"offline": True, "note": "ran without network: this turn read outside content, and there was "
                                         "nobody to allow the network for it"}
    decision = await permissions.decide(permissions.Request(
        kind="network", target="network:*", title=f"Let `{command[:80]}` use the network?", detail=command,
        why=str(args.get("why") or "").strip()[:300], conversation_ok=inside, once_only=not inside),
        permissions.Context(conversation_id, job_id=background_jobs._inside_job.get()))
    if decision.allowed:
        return {}
    return {"refused": decision.model_text or "the user did not allow this command to use the network"}


def _network_card_due(command: str, args: dict) -> bool:
    """S2a-2: whether `_network_after_outside_content` would ask for the network, known before the
    command's own card, so that card asks for both (one card, not two). A click on it stands for the
    network this time; a grant or rule that answers it does not, and the network card still comes."""
    from server.orchestrator import untrusted as _untrusted
    from server.services import task_service
    if not _untrusted.external_seen():
        return False
    if task_service.unwrapped_once(command):
        return task_service.bare_shortcut(command)       # a bare osascript is not a network command
    return args.get("network") is True or _untrusted.reaches_network(command)


def _bare_once(command: str, *, by_user: bool) -> tuple[bool, bool]:
    """S2a-1 piece 4, decision U11: (run with no wrapper, kept wrapped) for an approved command. Only
    a command with an Apple Events or Shortcuts rule, approved by the user's click on its card (a
    once-only card: no grant or rule ever answers it), and one plain call runs bare, this once.
    Approved but not plain (a script that acts beyond its app): kept under the sandbox's profiles."""
    from server.services import task_service, terminal_policy
    if not (by_user and terminal_policy.ask_rules(command) & terminal_policy.BARE_RULES):
        return False, False
    bare = task_service.unwrapped_once(command)
    return bare, not bare


async def _sandbox_enabled() -> bool:
    """Settings → Advanced → "Run commands in a sandbox" (0.1.51 P3), default on."""
    from server.db import session as db_session
    from server.services import settings_service
    try:
        async with db_session.AsyncSessionLocal() as db:
            return await settings_service.terminal_sandbox_enabled(db)
    except Exception:  # noqa: BLE001 — unreadable means the default: sandboxed
        return True


async def _unavailable(tool_key: str, live: set[str]) -> dict:
    """The answer to a call this turn cannot run."""
    if tool_key.startswith("mcp_"):
        # 0.1.61 §B1: a server that stopped since this turn's tool list was built answers with its
        # state and reason, not "not available to you" — the call never left Arslan.
        from server.mcp.executor import not_ready_for_key
        not_ready = await not_ready_for_key(tool_key)
        if not_ready is not None:
            return not_ready
    import difflib
    callable_as = {tool_names.wire(key): key for key in live}      # NAME1: the names the model can call
    near = difflib.get_close_matches(tool_key, sorted(callable_as), n=5, cutoff=0.3) or sorted(callable_as)[:5]
    result = {"ok": False, "external": False, "code": "tool_unavailable",
              "error": f"tool '{tool_key}' is not available to you"
                       + (f"; available tools include: {', '.join(near)}" if near else "")
                       + "; you may escalate a need instead"}
    from server.orchestrator import untrusted
    if any(untrusted.odd_mcp_key(key) for key in live if tool_names.wire(key) in near):
        # S64-0c: a key it lists carries a server's odd tool name: framed (no external: False), and marked.
        untrusted.mark_external()
        del result["external"]
    return result


async def _dispatch_tool(tool_key, args, assistant_content, *, resolve_tools, emit,
                         tool_timeout_s, tool_trace, convo, confirm_command=None,
                        confirm_workspace_write=None,
                        confirm_schedule=None,
                         mcp_fail_counts: dict | None = None,
                         mcp_hint_logged: set | None = None,
                         conversation_id: str | None = None,
                         log_events: bool = True,
                         caller: ToolCaller | None = None,
                         turn_adapter=None,
                         resolve_callable=None) -> dict:
    """Execute one tool (gated), emit its frames, record the trace, and append one
    framed tool-result record into convo. Returns the raw result dict.

    run_command is special: it requires per-command user confirmation via the injected
    confirm_command(command, argv) -> bool callback. No callback → refuse (safety default).
    Since 0.1.51 it also runs inside the workspace sandbox; leaving it is a click
    (confirm_command(..., sandbox="outside"|"retry")), never the model's say-so."""
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
    from server.services import desktop_status
    emit({"type": "tool_call", "tool": tool_key,
          "args_summary": json.dumps(args, ensure_ascii=False)[:200],
          # The one short thing that names the step (a host, a file, a command): a job's
          # "now doing" line and the phone's step titles. Never framed to a window.
          "target": desktop_status.step_target(tool_key, args)})
    desktop_status.note_step(tool_key, args)   # the island's "now doing" line (0.1.51)

    # v0.1.63 (the user's decision until S2a-3 lands): a run with nobody to ask (a scheduled run) runs no command
    # at all, whatever rule, grant or "always" answer stands. Refused here, before whether this turn could run it
    # is read: run_command is not offered there, and naming it anyway (or through use_tool) must still be listed in
    # the Inbox and explained, not answered "not available". DELETE-BY: v0.1.64, with S2a-3 and PR4.
    if tool_key == "run_command" and _nobody_to_ask(confirm_command):
        return _record_tool_result(tool_key, args, await _scheduled_command_refused(args, conversation_id), emit,
                                   tool_trace, assistant_content, convo, mcp_fail_counts=mcp_fail_counts)

    # K7: what this turn can run is settled before any card or file I/O (⓪Plan, Q4): a call to a tool
    # the turn cannot run never shows the user an approval card. The set is every reachable tool,
    # shown in this request or found on demand.
    live = {t["key"] for t in await (resolve_callable or resolve_tools)()}
    if tool_key not in live:
        return _record_tool_result(tool_key, args, await _unavailable(tool_key, live), emit, tool_trace,
                                   assistant_content, convo, mcp_fail_counts=mcp_fail_counts)

    # FU-2b: the eval/replay allowance (live reads have none since 0.1.63 K4b).
    refusal = await _check_fetch_budget(tool_key, conversation_id=conversation_id)
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
            from server.services import permissions
            error = "writing to the workspace needs your permission, which is not available on this channel"
            if permissions.current_asker() is None:
                root = await _workspace_root_or_none()
                error = await _unattended(error, permissions.Request(
                    kind="workspace_write", target=str(root) if root else "*", detail=str(args.get("path") or ""),
                    title=f"Let Arslan write in {root.name if root else 'the workspace'}?"), conversation_id)
            result = {"ok": False, "error": error}
            return _record_tool_result(tool_key, args, result, emit, tool_trace,
                                        assistant_content, convo,
                                        mcp_fail_counts=mcp_fail_counts)
        granted = await confirm_workspace_write(tool_key, str(args.get("path") or ""))
        if not granted:
            result = {"ok": False, "error": _declined("user declined workspace write access", "writing to the workspace")}
            return _record_tool_result(tool_key, args, result, emit, tool_trace,
                                        assistant_content, convo,
                                        mcp_fail_counts=mcp_fail_counts)

    # Creating a scheduled task spends future money on the user's key, so it
    # asks once per session — same shape as a workspace write (裁决① 2026-08-20).
    # Listing and cancelling are deliberately NOT gated: refusing to let someone
    # see or undo what was created is the worse failure.
    if tool_key == "schedule_task":
        if confirm_schedule is None:
            from server.services import permissions
            name = str(args.get("name") or "")
            result = {"ok": False, "error": await _unattended(
                "scheduling needs your permission, which is not available on this channel",
                permissions.Request(kind="schedule", target="*", title=f"Schedule “{name}”?",
                                    detail=str(args.get("when") or "")), conversation_id)}
            return _record_tool_result(tool_key, args, result, emit, tool_trace,
                                        assistant_content, convo,
                                        mcp_fail_counts=mcp_fail_counts)
        from server.ws import protocol as _protocol
        prompt = str(args.get("prompt") or "").strip()
        if len(prompt) > _protocol.DETAIL_MAX:
            # S1 (U14 d): the card shows the task's text in full or not at all (as an MCP call's arguments).
            result = {"ok": False, "code": "too_long_to_show",
                      "error": f"Not scheduled: the task's text is {len(prompt)} characters, more than a card "
                               f"can show the user ({_protocol.DETAIL_MAX}). Shorten it."}
            return _record_tool_result(tool_key, args, result, emit, tool_trace,
                                        assistant_content, convo,
                                        mcp_fail_counts=mcp_fail_counts)
        granted = await confirm_schedule(str(args.get("name") or ""),
                                         str(args.get("when") or ""), prompt=prompt)
        if not granted:
            result = {"ok": False, "error": _declined("user declined to schedule this task", "scheduling this task")}
            return _record_tool_result(tool_key, args, result, emit, tool_trace,
                                        assistant_content, convo,
                                        mcp_fail_counts=mcp_fail_counts)

    run_outside = False          # 0.1.51 P3: this command leaves the sandbox (a click said so)
    outside_grant = None         # S4a: this conversation's stored grant to leave the sandbox, as first read
    by_grant = False             # S4a: that grant is what lets this command run outside (read again at execute)
    sandbox_on = False
    unwrapped = kept_wrapped = False   # S2a-1 piece 4 (U11): an approved AE/Shortcut call runs bare
    network: dict = {}                 # S2a-1 piece 2: {"offline", "note"} for a command after outside content
    if tool_key == "run_command":
        # 0.1.48: one shell string; a forbidden command is refused here, before any
        # card, so nobody is ever asked to approve wiping the disk.
        from server.services import command_sandbox, terminal_policy
        command = terminal_policy.as_shell(args.get("command"), args.get("argv"))
        argv = []
        # S2a-3 c: read off the event loop, within a time limit. Every later call for this command (the card,
        # the approvals, the Island) gets this same answer from terminal_policy's cache.
        verdict = await terminal_policy.assess_async(command)
        if verdict.level == "forbid":
            result = {"ok": False, "error": f"Arslan never runs this: {verdict.reason}",
                      "note": "Tell the user what you wanted to do and let them run it themselves."}
            return _record_tool_result(tool_key, args, result, emit, tool_trace,
                                        assistant_content, convo,
                                        mcp_fail_counts=mcp_fail_counts)
        if terminal_policy.other_osa_language(command):
            # S2a-2 (K5's gate, T1): a JXA script cannot reach an app from here, inside the sandbox or out (its
            # Apple Events are blocked; only plain AppleScript runs bare, U11), so no card is shown for it.
            result = {"ok": False, "error": "JXA (osascript -l JavaScript) cannot control apps from run_command: "
                      "Apple Events are blocked in the sandbox and outside it, and only plain AppleScript runs "
                      "outside the sandbox.",
                      "note": "Write it as plain AppleScript (osascript -e or a heredoc) for Reminders, Calendar, "
                              "Notes or Contacts, without outside_sandbox; or use mac_applescript."}
            return _record_tool_result(tool_key, args, result, emit, tool_trace,
                                        assistant_content, convo,
                                        mcp_fail_counts=mcp_fail_counts)
        sandbox_on = await _sandbox_enabled()
        from server.services import task_service as _task_service
        # S2a-2: a plain osascript that U11 runs bare takes its own card, the one way it works; asking to run it
        # outside the sandbox would show a card that cannot help (its Apple Events stay blocked there).
        wants_out = (sandbox_on and args.get("outside_sandbox") is True
                     and not _task_service.unwrapped_once(command))
        # S4a: this conversation's stored grant to run its commands outside the sandbox (the outside card
        # answered "In this conversation"), found as decide finds one: in a chat turn and a background job
        # alike. With nobody to ask (a scheduled run) nothing stands, and the command starts inside the
        # sandbox. Its ledger row is written below, once the command is cleared to run.
        outside_grant = await _outside_grant(conversation_id, command)
        run_outside = sandbox_on and outside_grant is not None
        by_grant = run_outside            # the grant is what lets this command run outside the sandbox
        net_due = _network_card_due(command, args)
        net_kw = {"network": True} if net_due else {}
        net_clicked = False                # the command's own card, clicked, asked for the network too
        if wants_out and not run_outside:
            # Asked up front: always a card, even for a command that would just run,
            # and one card covers the command's own reason too.
            if confirm_command is None:
                from server.services import permissions
                result = {"ok": False, "error": await _unattended(
                              "running a command outside the sandbox needs the user's click, which is not "
                              "available here",
                              _outside_request(command),
                              conversation_id),
                          "note": "Run it without outside_sandbox, or tell the user what you needed."}
                return _record_tool_result(tool_key, args, result, emit, tool_trace,
                                            assistant_content, convo,
                                            mcp_fail_counts=mcp_fail_counts)
            why = str(args.get("why") or "").strip()[:300]
            from server.services import approvals as _approvals
            _approvals.LAST_OUTCOME.set(None)          # S2a-1: an earlier card's click never counts here
            _approvals.LAST_ANSWERED_BY.set(None)
            if not await confirm_command(command, argv, sandbox="outside", why=why, **net_kw):
                result = {"ok": False, "error": _declined("user declined running this command outside the sandbox", "running this command outside the sandbox")}
                return _record_tool_result(tool_key, args, result, emit, tool_trace,
                                            assistant_content, convo,
                                            mcp_fail_counts=mcp_fail_counts)
            run_outside = True
            # ⓪Plan review, fix 2: the network is answered only by the user's own click on this card (as below for
            # the command's card), never by whatever else let the command out.
            from server.services import permissions
            decided = permissions.LAST_DECISION.get()
            net_clicked = net_due and decided is not None and decided.by == "user"
            # S2a-1: the plain outside card records whose click approved it (approvals.LAST_ANSWERED_BY);
            # only the asking window's own ("mac") unlocks a bare run. A conversation grant shows no card.
            unwrapped, kept_wrapped = _bare_once(
                command, by_user=_approvals.LAST_OUTCOME.get() == "approved"
                and _approvals.LAST_ANSWERED_BY.get() == "mac")
        elif (verdict.level == "run" and not await _asks_for_everything()
              and (outside_grant is not None or (sandbox_on and command_sandbox.available()))):
            # S2a-2 layer ③: no card, and decided here only. In the sandbox only when it can start (R4: with
            # seatbelt unavailable the command would run unwrapped). Outside it under this conversation's
            # stored grant to leave the sandbox, which is the user's yes (S4a) — with the sandbox switched
            # off or unable to start too: that card asks the same thing (⓪Plan, S4a Q3). A layer ② card and
            # "ask for every command" still ask, whatever the grant.
            by_grant = outside_grant is not None
        else:
            if confirm_command is None:
                # Layer ②, `unreadable`, "ask for every command", or layer ③ with no sandbox to run it in.
                # Listed as the card would have read (approvals._command_request), U14 c.
                from server.services import approvals as _approvals
                ask_all = await _asks_for_everything()
                result = {"ok": False, "error": await _unattended(
                    "run_command requires user confirmation, which is not available in this context"
                    if verdict.level == "ask" or ask_all else
                    "this command would run outside the sandbox here (it is switched off or cannot start), "
                    "which needs the user's OK, and nobody can be asked here",
                    _approvals._command_request(command, sorted(terminal_policy.ask_rules(command)), None,
                                                ask_all=ask_all),
                    conversation_id)}
                return _record_tool_result(tool_key, args, result, emit, tool_trace,
                                            assistant_content, convo,
                                            mcp_fail_counts=mcp_fail_counts)
            from server.services import permissions
            permissions.LAST_DECISION.set(None)        # S2a-1: only this call's own decision counts below
            approved = await confirm_command(command, argv, **net_kw)
            if not approved:
                result = {"ok": False, "error": _declined("user declined this command", "this command")}
                return _record_tool_result(tool_key, args, result, emit, tool_trace,
                                            assistant_content, convo,
                                            mcp_fail_counts=mcp_fail_counts)
            # S2a-1 (the user, via ⓪Plan): only an explicitly recorded click unlocks the bare run — decide's
            # record of this card, answered by the user. Nothing recorded (a yes from any other path) keeps
            # the command wrapped.
            decided = permissions.LAST_DECISION.get()
            unwrapped, kept_wrapped = _bare_once(
                command, by_user=confirm_command is not None and decided is not None and decided.by == "user")
            run_outside = run_outside or unwrapped
            by_grant = by_grant and not unwrapped     # a bare run is the user's click on its card, not the grant
            net_clicked = net_due and decided is not None and decided.by == "user"
        network = {} if net_clicked else await _network_after_outside_content(
            command, args, sandbox_on=sandbox_on, run_outside=run_outside, unwrapped=unwrapped,
            conversation_id=conversation_id)
        if network.get("refused"):
            result = {"ok": False, "error": network["refused"]}
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
            from server.services import command_confirm, permissions
            host, remote = str(args.get("host") or "*")[:200], str(args.get("command") or "")
            result = {"ok": False, "error": await _unattended(
                "running a command on another machine requires your confirmation, which is not available "
                "in this context",
                permissions.Request(kind="remote", target=command_confirm.remote_target(host),
                                    title=f"Run `{remote[:80]}` on {host}?", detail=remote), conversation_id)}
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
            fingerprints=prep["fingerprints"], host=prep["host"])
        if not approved:
            # Un-stage: a declined command must not leave an approved host key
            # sitting where the next call would silently consume it.
            ssh_exec.take(prep["host"])
            result = {"ok": False, "error": _declined("user declined this remote command", "this remote command")}
            return _record_tool_result(tool_key, args, result, emit, tool_trace,
                                        assistant_content, convo,
                                        mcp_fail_counts=mcp_fail_counts)

    # Enrolling a machine (P3c). This tool never writes: it reaches the machine,
    # reads its host key, and paints a card whose button does the enrolment over
    # REST. So the safety here is not a callback but the absence of any write on
    # this path at all.
    #
    # It is still refused with no confirm callback, which is a proxy for "no
    # socket". An unattended turn painting a proposal card nobody asked for is
    # not dangerous, but this is the highest-consequence surface in the feature
    # and a card that appears while the user is asleep is a card they meet out of
    # context.
    if tool_key == "enroll_node":
        if confirm_command is None:
            from server.services import command_confirm, permissions
            host = str(args.get("host") or "*")[:200]
            result = {"ok": False, "error": await _unattended(
                "enrolling a machine has to be proposed to you directly, and there is nobody on this "
                "channel to propose it to",
                permissions.Request(kind="remote", target=command_confirm.remote_target(host), title=f"Enrol {host}?"),
                conversation_id)}
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

    executor = await resolve_executor(tool_key)
    if executor is None:
        result = await _unavailable(tool_key, live)
    else:
        # Caller identity (brain-P2 Task 1): set ONLY around the executor call so a
        # memory-write executor can read who is calling (host vs. spawn) and fail-closed
        # (refuse) when no caller was threaded through. Reset in finally — zero residual
        # pollution across dispatches/turns, including on the exception paths below.
        from server.orchestrator import tool_caller, turn_model
        _ct = tool_caller.set_caller(caller) if caller is not None else None
        # 0.1.63 D5: the model THIS turn runs on, for web_search's choice of the provider's own search. Always set
        # (None included) so a value from an outer context can't stand in for this turn's.
        _mt = turn_model.set_model(turn_adapter)
        try:
            from server.services.task_service import current as current_task
            from server.services.task_repository import TaskError
            # S4a (⓪Plan review, fixes 2 and 3, follow-up B): the grant was read before any card and may have been taken
            # back since. Read it again now — after every card, and before the task runtime's admission fence, inside
            # which nothing is awaited (task_service.execute_tool). Gone: the command runs in the sandbox, or, where none
            # can start (switched off, seatbelt unavailable), not at all. Its ledger row is written only once the
            # executor was invoked: never for a command that did not run.
            grant_use = {"found": None, "invoked": False}
            ran_outside, result = run_outside, None
            if by_grant:
                grant_use["found"] = await _outside_grant(conversation_id, command)
                if grant_use["found"] is None:
                    ran_outside = False
                    if not (sandbox_on and command_sandbox.available()):
                        result = {"ok": False, "executed": False,
                                  "error": "this conversation's permission to run commands outside the sandbox was "
                                           "taken back while this one waited; it did not run",
                                  "note": "Ask the user again if it is still needed."}

            async def execute(admitted_args):
                grant_use["invoked"] = True            # the executor is invoked now (no await before this line)
                # A tool that waits for the user's card or a slow app declares its own limit
                # (`timeout_s`): the default cut a Notes look mid-card on a real Mac (0.1.53).
                own = getattr(executor, "timeout_s", None)
                if tool_key == "run_command" and isinstance(own, (int, float)):
                    # 0.1.62 F1: the command's own limit decides, not the loop's 20 s default.
                    timeout = (max(0.0, min(float(own), budget.remaining_seconds() - _RUN_COMMAND_BACKSTOP_RESERVE_S))
                               if budget else float(own))
                else:
                    timeout = (budget.remaining_seconds() if tool_key == "delegate_work" and budget
                               else max(tool_timeout_s, float(own)) if isinstance(own, (int, float)) else tool_timeout_s)
                return await within(executor.execute(admitted_args), timeout=timeout)
            runtime = current_task()

            async def run_once(outside: bool) -> dict:
                from server.services import terminal_exec
                token = terminal_exec.OUTSIDE_SANDBOX.set(outside)
                bare = terminal_exec.UNWRAPPED.set(outside and unwrapped)
                # S2a-1 piece 2: offline after outside content (wrap-up may have set it too).
                cut = terminal_exec.OFFLINE.set(True) if network.get("offline") else None
                try:
                    return await runtime.execute_tool(tool_key, args, execute) if runtime else await execute(args)
                finally:
                    if cut is not None:
                        terminal_exec.OFFLINE.reset(cut)
                    terminal_exec.UNWRAPPED.reset(bare)
                    terminal_exec.OUTSIDE_SANDBOX.reset(token)
            if result is None:
                try:
                    async with parallel_reads.executing():      # K9a: the next read's gates may start now
                        result = await run_once(ran_outside)
                except asyncio.CancelledError:
                    grant_use["found"] = None          # a stop: no row written while the task is being cancelled
                    raise
                finally:
                    found, grant_use["found"] = grant_use["found"], None
                    if found is not None and grant_use["invoked"]:
                        from server.services import background_jobs, permissions
                        await permissions.note_standing(_outside_request(command), permissions.Context(
                            conversation_id, job_id=background_jobs._inside_job.get()), found)
                if by_grant and not ran_outside and isinstance(result, dict):
                    result["grant_note"] = ("this conversation's permission to run commands outside the sandbox was "
                                            "taken back; it ran in the sandbox")
            if (tool_key == "run_command" and sandbox_on and not ran_outside and confirm_command is not None
                    and isinstance(result, dict) and result.get("sandbox_denied")):
                # Stopped by the sandbox: offer ONE re-run outside it, from the start.
                if await confirm_command(command, argv, sandbox="retry"):
                    # S2a-1: outside, the network rule is decided again as for an outside run (this time
                    # only, a stored grant does not count): the retry card is about files.
                    network = await _network_after_outside_content(
                        command, args, sandbox_on=sandbox_on, run_outside=True, unwrapped=False,
                        conversation_id=conversation_id)
                    if network.get("refused"):
                        result = {"ok": False, "error": network["refused"]}
                    else:
                        result = await run_once(True)
                    if isinstance(result, dict) and not network.get("refused"):
                        result["ran_outside_sandbox"] = True
            elif tool_key == "run_command" and ran_outside and isinstance(result, dict):
                result["ran_outside_sandbox"] = True
            if tool_key == "run_command" and kept_wrapped and isinstance(result, dict):
                result["kept_wrapped"] = True      # the hint names mac_applescript (recovery_hints)
            if tool_key == "run_command" and network.get("note") and isinstance(result, dict):
                result["network_note"] = network["note"]
        except TaskError as exc:
            if exc.code not in _REFUSED_STEP:
                raise
            # 0.1.44: refuse the repeat, never the turn. The model is told why. D6: a step whose
            # arguments can't go into the task record is refused alone, before it runs; the task goes on.
            result = {"ok": False, "external": False, "code": exc.code, "error": _REFUSED_STEP[exc.code]}
        except BudgetExceeded:
            raise
        except TimeoutError:
            # M2 counts the run_command wording (0.1.62 F1): keep it as it is.
            result = ({"ok": False, "code": "time_limit", "error": "stopped by the time limit; no output was captured"}
                      if tool_key == "run_command" else {"ok": False, "error": f"tool '{tool_key}' timed out"})
        except Exception as exc:  # noqa: BLE001
            result = {"ok": False, "error": f"tool '{tool_key}' failed: {exc}"}
        finally:
            turn_model.reset_model(_mt)
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



async def _propose_plan_change(args: dict, emit) -> dict:
    """Record Arslan's changed plan for this conversation's project and show it as a card
    ("计划要不要跟着改？"). The user keeps the old plan or takes the new one."""
    from server.db import session as db_session
    from server.db.models import Project
    from server.services import personal_context, project_plan
    ctx = personal_context.current()
    if ctx is None or not ctx.project_id:
        return {"ok": False, "error": "this conversation has no project"}
    try:
        async with db_session.AsyncSessionLocal() as db:
            project = await db.get(Project, ctx.project_id)
            if project is None or project.status != "active":
                return {"ok": False, "error": "the project is not available"}
            event = await project_plan.propose_plan(db, project, args.get("levels") or [], str(args.get("reason") or ""))
            await db.commit()
    except project_plan.PlanError as exc:
        return {"ok": False, "error": exc.code}
    emit({"type": "plan_proposed", "project_id": ctx.project_id, "proposal_id": event.id,
          "diff": event.payload["diff"], "reason": event.payload["reason"], "cleared": event.payload["cleared"]})
    return {"ok": True, "proposal_id": event.id,
            "note": "Shown to the user as a card. Nothing changed yet; they keep the plan or take this one."}


# Native tool-calling is the sole production execution loop.

# Minimal OpenAI-format parameter schemas per known tool key. The executor re-validates args,
# so these can be loose; they exist only to nudge the model toward the right shape.
from server.orchestrator.turn_plan import PARAMS as _PLAN_PARAMS  # noqa: E402

# INB2 (#475 F4): Arslan's own mark on a memory write; it only ever makes the write stricter.
_SENSITIVE_FLAG = {"type": "boolean", "description": "true if private"}

# Hands v2 §6.3: the one way the model asks for the front. FRONT1 (the user, 2026-10-30): an action the app
# ignored in the background reads as `sent_unconfirmed` (a click or a press never says `no_effect`: Hands'
# outcome.rs), then as a look with no change (hands_tools.NOTHING_CHANGED). A POLICY_DENIED refusal is no
# reason: a borrow never lets agent-desktop take focus (hands_contract's `needs_focus`, `keys_refused`).
_FRONT = ("only if this action, done in the background, came back sent_unconfirmed and your next desktop_look "
          "said “Nothing changed since your last look.”: Arslan borrows the app's front for about a "
          "second, waiting for the user to pause typing")

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
    # 0.1.53 Mac apps through Arslan Hands
    "desktop_apps": {"type": "object", "properties": {}, "additionalProperties": False},
    "desktop_look": {"type": "object", "properties": {
        "app": {"type": "string", "minLength": 1, "maxLength": 120, "description": "app name or bundle id"},
        "ref": {"type": "string", "maxLength": 200, "description": "open this part of the last outline"},
        "text": {"type": "string", "maxLength": 200, "description": "find elements containing this text"},
        "role": {"type": "string", "maxLength": 40, "description": "find elements of this role (button, textfield…)"},
        "wait_for_text": {"type": "string", "maxLength": 200, "description": "wait up to 10 s for this text first"},
        "window": {"type": "string", "maxLength": 200, "description": "look at the window whose title contains this"}},
        "required": ["app"], "additionalProperties": False},
    "desktop_click": {"type": "object", "properties": {
        "app": {"type": "string", "minLength": 1, "maxLength": 120},
        "element": {"type": "string", "maxLength": 300, "description": "what the element is, in words"},
        "ref": {"type": "string", "maxLength": 200, "description": "the ref from your latest desktop_look"},
        "front": {"type": "boolean", "description": _FRONT}},
        "required": ["app", "element", "ref"], "additionalProperties": False},
    "desktop_type": {"type": "object", "properties": {
        "app": {"type": "string", "minLength": 1, "maxLength": 120},
        "element": {"type": "string", "maxLength": 300, "description": "what the field is, in words"},
        "ref": {"type": "string", "maxLength": 200},
        "text": {"type": "string", "maxLength": 20000},
        "mode": {"type": "string", "enum": ["replace", "append"]},
        "submit": {"type": "boolean"}},
        "required": ["app", "element", "ref", "text"], "additionalProperties": False},
    "desktop_select": {"type": "object", "properties": {
        "app": {"type": "string", "minLength": 1, "maxLength": 120},
        "element": {"type": "string", "maxLength": 300},
        "ref": {"type": "string", "maxLength": 200},
        "value": {"type": "string", "minLength": 1, "maxLength": 200}},
        "required": ["app", "element", "ref", "value"], "additionalProperties": False},
    "desktop_scroll": {"type": "object", "properties": {
        "app": {"type": "string", "minLength": 1, "maxLength": 120},
        "element": {"type": "string", "maxLength": 300},
        "ref": {"type": "string", "maxLength": 200},
        "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
        "amount": {"type": "integer", "minimum": 1, "maximum": 20}},
        "required": ["app", "element", "ref"], "additionalProperties": False},
    "desktop_press": {"type": "object", "properties": {
        "app": {"type": "string", "minLength": 1, "maxLength": 120},
        "keys": {"type": "string", "minLength": 1, "maxLength": 40, "description": "return, escape, tab, cmd+n…"},
        "front": {"type": "boolean", "description": _FRONT}},
        "required": ["app", "keys"], "additionalProperties": False},
    "desktop_access": {"type": "object", "properties": {
        "apps": {"type": "array", "minItems": 1, "maxItems": 8, "items": {"type": "string", "maxLength": 120},
                 "description": "the apps this task needs, by name"},
        "why": {"type": "string", "minLength": 1, "maxLength": 300, "description": "what you will do, in words"}},
        "required": ["apps", "why"], "additionalProperties": False},
    "desktop_takeover": {"type": "object", "properties": {
        "why": {"type": "string", "minLength": 1, "maxLength": 300,
                "description": "what you will do with the screen, in the user's words"},
        "minutes": {"type": "integer", "minimum": 1, "maximum": 30}},
        "required": ["why", "minutes"], "additionalProperties": False},
    "desktop_open": {"type": "object", "properties": {
        "app": {"type": "string", "minLength": 1, "maxLength": 120, "description": "the app's name, e.g. TextEdit"},
        "path": {"type": "string", "minLength": 1, "maxLength": 1000,
                 "description": "a file or folder to open in that app (optional)"}},
        "required": ["app"], "additionalProperties": False},
    "desktop_batch": {"type": "object", "properties": {
        "app": {"type": "string", "minLength": 1, "maxLength": 120},
        "steps": {"type": "array", "minItems": 1, "maxItems": 8, "items": {
            "type": "object", "properties": {
                "action": {"type": "string", "enum": ["click", "type", "select", "scroll", "press", "menu"]},
                "element": {"type": "string", "maxLength": 300}, "ref": {"type": "string", "maxLength": 200},
                "text": {"type": "string", "maxLength": 20000}, "mode": {"type": "string", "enum": ["replace", "append"]},
                "submit": {"type": "boolean"}, "value": {"type": "string", "maxLength": 200},
                "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
                "amount": {"type": "integer", "minimum": 1, "maximum": 20},
                "keys": {"type": "string", "maxLength": 40},
                "path": {"type": "array", "minItems": 2, "maxItems": 4, "items": {"type": "string", "maxLength": 120}}},
            "required": ["action"], "additionalProperties": False}}},
        "required": ["app", "steps"], "additionalProperties": False},
    "desktop_menu": {"type": "object", "properties": {
        "app": {"type": "string", "minLength": 1, "maxLength": 120},
        "path": {"type": "array", "minItems": 2, "maxItems": 4,
                 "items": {"type": "string", "minLength": 1, "maxLength": 120},
                 "description": "the menu's titles as the app shows them, top level first: [\"Format\", \"Font\", \"Bold\"]"}},
        "required": ["app", "path"], "additionalProperties": False},
    "start_background_work": {"type": "object", "properties": {
        "goal": {"type": "string", "minLength": 1, "maxLength": 4000,
                 "description": "The work to do, in the user's own words and language."},
        "criteria": {"type": "array", "minItems": 1, "maxItems": 5, "items": {
            "type": "object", "properties": {
                "description": {"type": "string", "minLength": 1, "maxLength": 300,
                                "description": "One check, in the user's language."},
                "kind": {"type": "string", "enum": ["file_saved", "sources_read", "mentions", "judgement"]},
                "target": {"type": "string", "maxLength": 240,
                           "description": "file_saved: the file or folder's full path (~/… or /…); "
                                          "sources_read: optional, a file name or site the sources must include; "
                                          "mentions: the phrase"},
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
    "run_command": {"type": "object",
                    "properties": {"command": {"type": "string",
                                               "description": "The full shell command line, e.g. "
                                                              "\"ls -la ~/Downloads | head -20\"."},
                                   "timeout_s": {"type": "integer", "minimum": terminal_exec.MIN_TIMEOUT_S,
                                                 "maximum": terminal_exec.MAX_TIMEOUT_S,
                                                 "description": "Stop after this many seconds (default "
                                                                f"{terminal_exec.DEFAULT_TIMEOUT_S})."},
                                   "outside_sandbox": {"type": "boolean",
                                                       "description": "Only when the command must write outside "
                                                                      "the working folder (moving the user's files, "
                                                                      "installing software). The user is asked."},
                                   "network": {"type": "boolean",
                                               "description": "The command needs the network (a download, an "
                                                              "API). After you read outside content in this turn, "
                                                              "commands run offline unless the user allows it."},
                                   "why": {"type": "string", "maxLength": 300,
                                           "description": "With outside_sandbox or network: one short sentence "
                                                          "the user reads on the card."}},
                    "required": ["command"]},
    "conversation_search": {"type": "object",
                            "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 200,
                                                     "description": "Words to find, e.g. \"weekly report\" or \"landlord\"."},
                                           "since": {"type": "string", "description": "YYYY-MM-DD, optional."},
                                           "until": {"type": "string", "description": "YYYY-MM-DD, optional."},
                                           "limit": {"type": "integer", "minimum": 1, "maximum": 20}},
                            "required": ["query"], "additionalProperties": False},
    "memory_note": {"type": "object",
                    "properties": {"action": {"type": "string", "enum": ["add", "replace", "remove"]},
                                   "set": {"type": "string", "enum": ["about_you", "notes"]},
                                   "id": {"type": "string", "description": "Entry id, for replace or remove."},
                                   "text": {"type": "string", "maxLength": 600,
                                            "description": "The entry, for add or replace. One short line."},
                                   "sensitive": _SENSITIVE_FLAG},
                    "required": ["action", "set"], "additionalProperties": False},
    # v0.1.64 CAP2a: the user sees the whole SKILL.md on a card and decides (skill_forge.propose).
    "create_skill": {"type": "object",
                     "properties": {"key": {"type": "string", "maxLength": 60,
                                            "description": "Lowercase letters, digits and hyphens, e.g. weekly-report."},
                                    "name": {"type": "string", "maxLength": 100},
                                    "description": {"type": "string", "maxLength": 300,
                                                    "description": "One line: what the skill is for."},
                                    "body": {"type": "string",
                                             "description": "The SKILL.md body: a '## Trigger' section (when to "
                                                            "use it), then the method. Text only, at most 15 KB."},
                                    "why": {"type": "string", "maxLength": 300,
                                            "description": "What the user asked for, in a few words."}},
                     "required": ["key", "name", "description", "body"], "additionalProperties": False},
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
                     "sensitive": _SENSITIVE_FLAG,
                 },
                 "required": ["kind", "action", "content"]},
    "update_plan": _PLAN_PARAMS,
    # 0.1.63 K7: the two tools that reach everything a request is not shown (on_demand.py).
    "find_tools": {"type": "object",
                   "properties": {"query": {"type": "string", "maxLength": 200,
                                            "description": "English keywords, e.g. \"send file\"."}},
                   "required": ["query"], "additionalProperties": False},
    "use_tool": {"type": "object",
                 "properties": {"name": {"type": "string", "maxLength": 120,
                                         "description": "As find_tools returned it."},
                                "arguments": {"type": "object",
                                              "description": "Its arguments, as its parameters say."}},
                 "required": ["name"], "additionalProperties": False},
    # 0.1.57 §3: propose one candidate find_capability returned (the card is the server's).
    "propose_capability": {
        "type": "object",
        "properties": {
            "candidate_id": {"type": "string", "description": "An id from find_capability's candidates."},
            "why": {"type": "string", "description": "What failed and why this helps, in one sentence."},
            "retry": {"type": "string", "description": "The step you will retry with it."},
            "folders": {"type": "array", "maxItems": 3, "items": {"type": "string"},
                        "description": "Folders it needs (e.g. the folder of the file you work on)."}},
        "required": ["candidate_id", "why"]},
    # 0.1.57 §2: find a capability for what the turn could not do.
    "find_capability": {
        "type": "object",
        "properties": {
            "need": {"type": "string", "description": "What could not be done, in one sentence."},
            "keywords": {"type": "array", "minItems": 1, "maxItems": 4, "items": {"type": "string"},
                         "description": "1-4 short English search words, e.g. [\"excel\", \"xlsx\"]."},
            "kinds": {"type": "array", "items": {"type": "string", "enum": ["mcp", "skill", "project"]}}},
        "required": ["need", "keywords"]},
    # 0.1.56 §7: a changed plan for the project, proposed — the user decides on the card.
    "propose_plan_change": {
        "type": "object",
        "properties": {
            "reason": {"type": "string", "description": "What changed, in the user's words."},
            "levels": {"type": "array", "minItems": 1, "maxItems": 15, "description":
                       "Every level NOT cleared yet, as it should be after the change, in order.",
                       "items": {"type": "object", "properties": {
                           "name": {"type": "string"},
                           "band": {"type": "string", "enum": ["shaping", "doing", "done"]},
                           "clear_condition": {"type": "string"},
                           "checkpoints": {"type": "array", "maxItems": 12,
                                           "items": {"type": "object", "properties": {"text": {"type": "string"}},
                                                     "required": ["text"]}}},
                                 "required": ["name", "band"]}}},
        "required": ["levels", "reason"]},
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
    # 0.1.63 D1: hand an existing file to the user (window card + paired iPhone).
    "attach_file": {"type": "object", "properties": {
        "path": {"type": "string", "minLength": 1,
                 "description": "The file: absolute, ~/ or relative to the workspace, in a readable folder."},
        "title": {"type": "string", "maxLength": 200,
                  "description": "Optional name the user sees; the file's extension is kept."}},
        "required": ["path"], "additionalProperties": False},
    # 0.1.63 K5: the 14 offered tools that had no schema (and fell back to _PERMISSIVE_PARAMS), matching
    # each executor's real arguments. Built-in schemas go to every provider verbatim (F3's normaliser is for
    # MCP tools only): no `pattern`, no top-level `anyOf`, no type arrays (tests/server/test_k5_tool_schemas.py).
    "edit_file": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "minLength": 1, "description": "File path within the configured workspace."},
            "old_string": {"type": "string", "minLength": 1,
                           "description": "The exact text to replace; it must appear exactly once in the file."},
            "new_string": {"type": "string", "description": "The text to put in its place."},
        },
        "required": ["path", "old_string", "new_string"],
        "additionalProperties": False,
    },
    "list_dir": {
        "type": "object",
        "properties": {"path": {"type": "string", "description": (
            "Absolute or ~/ folder path in Desktop, Documents, Downloads or the workspace; leave it out to list "
            "the folders you can see.")}},
        "additionalProperties": False,
    },
    "search_files": {
        "type": "object",
        "properties": {"query": {"type": "string", "minLength": 1,
                                 "description": "Literal text to find in the readable folders' text files."}},
        "required": ["query"],
        "additionalProperties": False,
    },
    "whats_new": {
        "type": "object",
        "properties": {"count": {"type": "integer", "minimum": 1, "maximum": 6,
                                 "description": "How many recent versions' notes (default 3)."}},
        "additionalProperties": False,
    },
    "list_my_capabilities": {"type": "object", "properties": {}, "additionalProperties": False},
    "schedule_task": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "minLength": 1, "maxLength": 80, "description": "A short name for the task."},
            "prompt": {"type": "string", "minLength": 1, "description": "What to do each time it runs."},
            "when": {"type": "string", "minLength": 1, "description": (
                "'every: <seconds>' (at least 900) or 'cron: <expression>', e.g. 'every: 3600' or 'cron: 0 9 * * *'.")},
        },
        "required": ["name", "prompt", "when"],
        "additionalProperties": False,
    },
    "list_my_tasks": {"type": "object", "properties": {}, "additionalProperties": False},
    "cancel_task": {
        "type": "object",
        # No "type": a number and the string "3" are both accepted (⓪Plan's Q9: no type arrays).
        "properties": {"task_id": {"description": "The task id from list_my_tasks (a number, e.g. 3)."}},
        "required": ["task_id"],
        "additionalProperties": False,
    },
    "read_skill": {
        "type": "object",
        "properties": {
            "key": {"type": "string", "minLength": 1,
                    "description": "The skill's key from the list in this tool's description."},
            "section": {"type": "string", "description": (
                "Optional: one part only, a '## Heading' of the skill or 'references/<file>.md' (or .txt).")},
        },
        "required": ["key"],
        "additionalProperties": False,
    },
    "scan_local_network": {"type": "object", "properties": {}, "additionalProperties": False},
    "ssh_probe": {
        "type": "object",
        "properties": {"host": {"type": "string", "minLength": 1,
                                "description": "An IPv4 address on the local network, e.g. 192.168.1.8."}},
        "required": ["host"],
        "additionalProperties": False,
    },
    "ssh_run": {
        "type": "object",
        "properties": {
            "host": {"type": "string", "minLength": 1, "description": "The machine's IPv4 address."},
            "user": {"type": "string", "minLength": 1, "description": "The username to log in as."},
            "command": {"type": "string", "minLength": 1, "description": "One whitelisted program name, e.g. 'uptime'."},
            "argv": {"type": "array", "items": {"type": "string"}, "description": "Its arguments, one per item."},
        },
        "required": ["host", "user", "command"],
        "additionalProperties": False,
    },
    "list_nodes": {"type": "object", "properties": {}, "additionalProperties": False},
    "enroll_node": {
        "type": "object",
        "properties": {
            "host": {"type": "string", "minLength": 1, "description": "The machine's IPv4 address."},
            "user": {"type": "string", "minLength": 1, "description": "The username to log in as."},
            "name": {"type": "string", "minLength": 1, "maxLength": 60, "description": "A name for the machine."},
        },
        "required": ["host", "user", "name"],
        "additionalProperties": False,
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
# 0.1.63 K5: the research rules ("RESEARCH DISCIPLINE") used to be appended to every run_native system,
# tools or not; they now live in web_search's and web_extract's descriptions (arslan._arslan_tools).

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
    permissive one (executor re-validates args). Adds `escalate` when allowed.

    0.1.63 K3: sorted by name, `escalate` last. The table renders before Claude's cached system, so its
    order is part of the cache key; tools loaded later (K7) are appended after it, never sorted in."""
    from server.orchestrator import untrusted
    if any(untrusted.odd_mcp_key(t["key"]) for t in wired):
        untrusted.mark_external()       # S64-0c: a key in the table carries a server's odd tool name
    schemas: list[dict] = []
    resident = sorted((t for t in wired if not t.get("appended")), key=lambda tool: tool["key"])
    for t in resident + [t for t in wired if t.get("appended")]:
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


# What a tool call written as text looks like, in every provider's shape. One list: _embeds_protocol
# judges a whole answer with it, and K8a's streaming holds back the tail of a reply against it.
_PROTOCOL_PATTERNS = (
    # Some providers render a proposed call as XML instead of native tool_calls, including an unfinished
    # opening tag.
    re.compile(r'<\s*/?\s*(?:tool_call|tool_calls|function_call)(?=[\s>/]|$)', re.I),
    # DeepSeek's own chat-template tokens leaking into content instead of native tool_calls (seen in the
    # 0.1.49 bench: "<｜｜DSML｜｜tool_calls>", and V3's "<｜tool▁calls▁begin｜>").
    re.compile(r'[｜|]\s*DSML\s*[｜|]|<\s*[｜|]+\s*(?:DSML\s*[｜|]+\s*)?/?\s*(?:tool[▁_ ]?calls?|invoke)', re.I),
    re.compile(r'\{\s*"(?:tool|tool_calls|function_call|functionCall|escalate)"\s*:'),
)


def _embeds_protocol(text: str) -> bool:
    """True if `text` is / EMBEDS a tool-call or escalate JSON in ANY provider's shape (even behind
    a prose prefix like 'Let me search…{…}'). Covers OpenAI/DeepSeek ({"tool"} / {"tool_calls"} /
    {"function_call"}), Gemini ({"functionCall"}), and our escalate object. A finished answer is
    prose — it never surfaces one of these as the reply."""
    # Detection is deliberately stricter than parsing for dispatch: malformed
    # quotes or an interrupted object must not turn a proposed action into an
    # answer. This only rejects text; it never repairs JSON or executes a call,
    # nor grants the proposed action permission.
    if any(pattern.search(text or "") for pattern in _PROTOCOL_PATTERNS):
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
                lines.append(f"{step.get('tool')} returned: {json.dumps(payload, ensure_ascii=False)[:900]}")
    return "\n".join(lines)[:limit]


def _unverified_claim(text: str, tool_trace: list, wired_keys: set[str]) -> str | None:
    """Claims are not receipts. Check this before displaying a proposed answer."""
    if "<!doctype html" in text.lower() and "</html>" in text.lower():
        return None
    succeeded = {step.get("tool") for step in tool_trace if (step.get("result") or {}).get("ok")}
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
    except Exception as exc:  # noqa: BLE001 — synthesis falls back to the tool-loop adapter, as when none is set
        logger.warning("synthesis adapter unavailable, keeping the tool-loop model: %s", type(exc).__name__)
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


async def _chat_retry(a, system: str, user: str, *, history=None, tools=None):
    """One bounded retry for known transient transport failures, never for denial."""
    return await _with_retry(lambda: a.chat(system, user, history=history, tools=tools))


async def _with_retry(request):
    last: Exception | None = None
    from arslan.execution_budget import BudgetExceeded
    for attempt in range(2):
        try:
            return await within(request(), timeout=_CHAT_TIMEOUT_S)
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


# 0.1.63 K8a–K8c: the answer goes out while it is written (OpenAI-compatible endpoints that stream, Claude
# on Anthropic's host, Gemini on Google's). An answer that was not streamed (an endpoint that cannot, the
# "show answers when complete" setting, a wrap-up written whole) goes out as one piece, at once: K8c removed
# the simulated typing (_reveal_streamed) that used to pace it out. A step's text is held until it passes
# _DEFERRAL_MAX (a short answer is judged whole, exactly as before), then shown as it arrives, except:
_STREAM_HOLD = 64      # the tail kept back: longer than any text _PROTOCOL_PATTERNS need to decide
_JSON_HOLD = 1500      # a JSON object kept back until it closes (at most this long): its keys decide
_JSON_START = re.compile(r'\{\s*"')
#: Model names whose steps are shown only when complete (the guards bounce instead of correcting), as
#: M1 decides (D6). Empty: every streaming model streams. Reviewed in v0.1.65; deleted when still empty.
BUFFERED_MODELS: frozenset[str] = frozenset()


#: K8a (⓪Plan Q4): an answer that claims what no tool did is sent back at most this often per turn, then
#: written from the findings (the same-failure count of policy.observe used to end it; guards no longer
#: count toward "no progress").
_UNVERIFIED_BOUNCES = 2


def _shown(turn_text: "_TurnText | None") -> str | None:
    """What this turn already showed, for an answer that ends another way (a choice card, an escalation)."""
    return turn_text.text if turn_text is not None and turn_text.parts else None


async def _correct(turn_text: "_TurnText | None", shown: bool) -> None:
    """K8a: once a step's text went out, a guard that sends it back says so to the user first."""
    if shown and turn_text is not None:
        from server.services import runtime_messages
        turn_text.append(runtime_messages.render("stream_correction", await runtime_messages.selected_locale()))


async def _not_verified(turn_text: "_TurnText", links: list[str]) -> None:
    from server.services import runtime_messages
    new = [link for link in links if link not in turn_text.listed]
    if new:
        turn_text.listed.update(new)
        turn_text.append(runtime_messages.render("links_not_verified", await runtime_messages.selected_locale(),
                                                 links=", ".join(new)))


class TextShown(Exception):
    """K8a: a model request failed after part of its answer was shown. It is never sent again (the text
    would show twice); the turn ends with what was shown and says it was interrupted."""


class _TurnText:
    """K8a: everything this turn showed through on_chunk, corrections included: the stored answer is this
    (every joiner, the window, the phone's Bridge and the run record, concatenates the chunks)."""

    def __init__(self, on_chunk: Callable[[str], None]):
        self.on_chunk, self.parts = on_chunk, []
        self.listed: set[str] = set()       # links already said to be unverified

    def show(self, text: str) -> None:
        if text:
            self.on_chunk(text)
            self.parts.append(text)

    def append(self, text: str) -> None:
        """A new part of the answer (a step's text, a correction): after a blank line."""
        self.show(("\n\n" if self.parts and text else "") + text)

    @property
    def text(self) -> str:
        return "".join(self.parts)


def _json_end(text: str, start: int) -> int | None:
    """Just past the JSON object opening at `start`, or None while it is still open."""
    depth, in_string, escaped = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            escaped, in_string = (False, True) if escaped else (ch == "\\", ch != '"')
        elif ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    return None


class _StepStream:
    """K8a: one model step's text on its way out. Held until it passes the window; then shown as it
    arrives, except a tool call written as text (_PROTOCOL_PATTERNS: never shown, and this step's stream
    stops there) and host bookkeeping (agent_status.ECHO_BLOCK: dropped)."""

    def __init__(self, turn: _TurnText, window: int = _DEFERRAL_MAX):
        self.turn, self.window = turn, window
        self.held = self.pending = ""
        self.released = self.stopped = False
        self._started = False

    def feed(self, piece: str) -> None:
        if self.stopped:
            return
        if not self.released:
            self.held += piece
            if len(self.held) < self.window:
                return
            self.released, self.pending, self.held = True, self.held, ""
        else:
            self.pending += piece
        self._drain(final=False)

    def retry_ok(self) -> bool:
        """A failed request may be sent again only while nothing of it went out (what it held is dropped)."""
        if self.released:
            return False
        self.held = ""
        return True

    def finish(self) -> None:
        if self.released and not self.stopped:
            self._drain(final=True)

    def _show(self, text: str) -> None:
        if text:
            if self._started:
                self.turn.show(text)
            else:
                self._started = True
                self.turn.append(text)

    def _drain(self, final: bool) -> None:
        from server.orchestrator import agent_status
        text = agent_status.ECHO_BLOCK.sub("", self.pending)
        opened = [i for tag in agent_status.ECHO_TAGS if (i := text.find(tag)) >= 0]
        cut = min(opened) if opened else len(text)   # a block still open: never shown; dropped if it never closes
        hits = [m.start() for pattern in _PROTOCOL_PATTERNS if (m := pattern.search(text)) is not None]
        start = 0
        while (opening := _JSON_START.search(text, start)) is not None and opening.start() < cut:
            end = _json_end(text, opening.start())
            if end is None:
                if not final and len(text) - opening.start() < _JSON_HOLD:
                    cut = opening.start()
                break
            if _embeds_protocol(text[opening.start():end]):
                hits.append(opening.start())
                break
            start = end
        if hits and min(hits) < cut:
            self._show(text[:min(hits)])
            self.pending, self.stopped = "", True
            return
        if not final:
            cut = min(cut, max(0, len(text) - _STREAM_HOLD))
        self._show(text[:cut])
        self.pending = "" if final else text[cut:]


# Claude's documented stand-in for an update a limit cut short (claude-api model-migration guide): not news.
_UPDATE_CUT = "This part of the response was interrupted before it finished."


def _progress_updates(a, resp) -> list[str]:
    """K8b: the non-empty thinking blocks of a Claude step whose answered request carried
    `display: "updates"` (the provider marks the continuation): under that display such a block is an
    update, never the model's reasoning."""
    continuation = getattr(resp, "continuation", None) or {}
    if continuation.get("protocol") != "anthropic" or not continuation.get("updates"):
        return []
    texts = [str(b.get("thinking") or "").strip() for b in continuation.get("content") or []
             if b.get("type") == "thinking"]
    return [text for text in texts if text and text != _UPDATE_CUT]


async def _streams_answer(a, acceptance_runtime) -> bool:
    """K8a: whether this turn's answer is shown as it is written. Not for work with explicit acceptance
    criteria (background jobs and the like: a failed check rewrites what was written; ⓪Plan Q1), not for
    a model in BUFFERED_MODELS, not when the user chose to see answers only when complete."""
    from server.db import session as db_session
    from server.services import settings_service, task_service
    if (acceptance_runtime is not None and not task_service.answer_only()) or _model_key(a)[1] in BUFFERED_MODELS:
        return False
    try:
        async with db_session.AsyncSessionLocal() as db:
            return not await settings_service.answer_when_complete(db)
    except Exception:  # noqa: BLE001 — an unreadable setting is the default: stream
        return True


# Tools a job may still use while wrapping up: saving the deliverable.
WRAP_UP_TOOLS = frozenset({"write_file", "edit_file"})


def _stop_for_limit(runtime, reason: str, trace: list[dict], *, finishing: bool = False) -> None:
    """0.1.62 F2 ④: a work limit stops this turn. With a deliverable saved this turn, it is only
    noted (`limit_reason`): the task holds for it only if the finish-time checks do not pass a
    saved file (task_service._run). Otherwise it holds the task, as before. `finishing`: the limit
    opened the wrap-up steps, which are there to save; only noted, and the forced step after them
    (or _run) decides."""
    if finishing or any(item.get("tool") in WRAP_UP_TOOLS and (item.get("result") or {}).get("ok") is True
                        for item in trace):
        runtime.limit_reason = reason
    else:
        runtime.pause_reason = reason
# What a wrapping-up run may still call (0.1.50): the save tools, plus run_command
# to process files it already fetched — run without network (terminal_exec.OFFLINE).
FINISH_TOOLS = WRAP_UP_TOOLS | {"run_command"}
# K3: refused calls while wrapping up before the next step is text only (the table never narrows).
WRAP_REFUSALS_BEFORE_TEXT = 2


def _host_turn(caller, progress_lane) -> bool:
    """Arslan's own turn (a chat turn or a background job), not a delegated worker.
    The chat path and jobs pass ToolCaller(actor="host"); tests and older paths pass none."""
    return progress_lane is None and (caller is None or getattr(caller, "actor", None) == "host")


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
    from server.orchestrator import untrusted as _untrusted
    from server.services import tool_outputs
    seen = _untrusted.track_turn()
    if _untrusted.history_from_outside(kwargs.get("history")) or _untrusted.context_from_outside(
            kwargs.get("user_content")):
        _untrusted.mark_external()       # S64-0b: a job's result framed as outside content, or a summary of one
    sent_is_final = _SENT_IS_FINAL.set(False)
    # S2a-1 piece 5: the saved outputs of this turn belong to its conversation (a command may read them).
    copies_of = tool_outputs.conversation.set(kwargs.get("conversation_id"))
    try:
        result = await _run_native(**kwargs, _facts=facts)
        if isinstance(result, dict):
            result["external_seen"] = _untrusted.external_seen()
            _learn_after(kwargs, facts, result)
        return result
    except BudgetExceeded:
        from server.services import background_jobs
        trace = facts.get("tool_trace") or []
        # 0.1.52: the chat path passes ToolCaller(actor="host"); checking for no caller
        # at all left this closing message unreachable from a real chat turn.
        host_turn = _host_turn(kwargs.get("caller"), kwargs.get("progress_lane"))
        if not host_turn or background_jobs.inside_job() \
                or not any((t.get("result") or {}).get("ok") for t in trace):
            raise                       # workers and jobs record the stop themselves
        text = await _budget_closing(trace, facts.get("ws_root"), facts.get("started", 0.0))
        from server.services.task_service import current as current_task
        task = current_task()
        if task is not None:
            _stop_for_limit(task, "task_budget_exhausted", trace)
        if (turn_text := facts.get("turn_text")) is not None and turn_text.parts:
            turn_text.append(text)              # K8a: after what this turn already showed
            text = turn_text.text
        elif text:
            kwargs["on_chunk"](text)
        return {"final": text, "escalation": None, "tool_trace": trace,
                "stop_reason": "task_budget_exhausted", "history_compacted": False,
                "external_seen": _untrusted.external_seen()}
    finally:
        # K9b: a message read after the last batch that no request carried (the turn stopped, hit its limit
        # or failed first) goes back to its sender, to run once as a turn of its own.
        for steer in facts.pop("steers", None) or []:
            steer.hand_back()
        known_local = _untrusted.known_local()      # read before end_turn drops the holder
        _untrusted.end_turn(seen)
        run_trace.record_outside(not known_local)   # INB2: the run's own record (runs.read_outside), the allowlist
        _SENT_IS_FINAL.reset(sent_is_final)
        tool_outputs.conversation.reset(copies_of)


def _learn_after(kwargs: dict, facts: dict, result: dict) -> None:
    """0.1.52 S5: after a host turn, off the reply path — counters for the lessons this
    turn recalled, then any detour worth keeping (lessons.after_turn)."""
    if not _host_turn(kwargs.get("caller"), kwargs.get("progress_lane")):
        return
    from server.services import lessons, personal_context
    ctx = personal_context.current()
    lessons.note_turn(kwargs.get("conversation_id"), list(facts.get("tool_trace") or []))
    lessons.later(lessons.after_turn(
        conversation_id=kwargs.get("conversation_id"), user_request=(ctx.query if ctx else "") or "",
        trace=list(facts.get("tool_trace") or []), external_seen=bool(result.get("external_seen")),
        recalled=list(facts.get("recalled_lessons") or []),
        ok=bool(result.get("final")) and not result.get("stop_reason"), emit=kwargs.get("emit")))


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
    resolve_callable: ResolveTools | None = None,
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
    turn_notes: list[str] | None = None,
    steerable: bool = False,
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
    a = adapter_override if adapter_override is not None else await _adapter_for_turn(
        has_images=has_images, conversation_id=conversation_id)
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

    drops = _SchemaDrops(a)
    resolve_tools = _hiding(resolve_tools, drops)
    # K7: what the turn may run, shown or found on demand. Paths without on-demand tools pass none.
    resolve_callable = _hiding(resolve_callable, drops) if resolve_callable is not None else resolve_tools
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
            if pieces:
                on_chunk("".join(pieces))
        return {"final": "".join(pieces), "escalation": None, "tool_trace": [],
                "stop_reason": None, "history_compacted": compacted}
    schemas = _native_tool_schemas(wired, allow_escalation=allow_escalation)
    params_by_key = {t["key"]: _tool_params(t) for t in wired}
    # GUARD_NOTE = injection defense (wrapped tool/web content is untrusted DATA, not instructions) — the
    # same guard the old loop carried. (K5: the research rules moved to the web tools' descriptions.)
    system = system + "\n\n" + GUARD_NOTE

    # convo is the neutral in-turn trajectory (arslan/llm/trajectory.py): one
    # assistant message per model reply that called tools, one tool record per
    # handled call. It is rendered per request (_render_request); compaction
    # evicts whole call groups.
    current_request = trajectory.request(user_content)
    convo: list[dict] = list(history) + [current_request]
    tool_trace: list[dict] = []
    if _facts is not None:
        _facts["tool_trace"] = tool_trace
    # 0.1.52 S5: practices learned before that match this request ride in the status
    # block (never the system prompt). Host turns only; recall applies memory's permissions.
    lesson_notes: list[str] = []
    if _host_turn(caller, progress_lane):
        from server.services import lessons, personal_context
        ctx_now = personal_context.current()
        recalled = await lessons.recall((ctx_now.query if ctx_now else "") or turn_context.users_words(user_content))
        lesson_notes = lessons.status_lines(recalled)
        if not all(item["users"] for item in recalled):
            from server.orchestrator import untrusted as _untrusted
            _untrusted.mark_off_the_list()   # #475 H1: a practice in view that came from a run off the list
        if _facts is not None:
            _facts["recalled_lessons"] = recalled
    research_source_feedback: list = []
    # PB-3 (条件2): consecutive-failure counts per mcp_* tool key. These are LOCALS of this
    # run_native invocation — one invocation = one turn — so a new turn starts at zero by
    # construction; nothing persists or is shared. mcp_hint_logged bounds the observability
    # row to once per turn per tool.
    mcp_fail_counts: dict[str, int] = {}
    mcp_hint_logged: set[str] = set()
    call_ids: set[str] = set()
    from server.orchestrator import agent_status
    from server.orchestrator.model_call import TurnRecovery
    from server.orchestrator.turn_plan import Plan
    turn_state = TurnRecovery()
    plan = Plan()
    turn_started = agent_status.now()
    ws_root, own_folder = await _status_workspace(wired_keys)
    # K8a: what this turn shows as it is written (None: every answer shown whole, as before).
    turn_text = _TurnText(on_chunk) if on_chunk is not None and await _streams_answer(a, acceptance_runtime) else None
    if _facts is not None:
        _facts.update(ws_root=ws_root, started=turn_started, turn_text=turn_text)
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
                conversation_id=conversation_id, log_events=log_events, caller=caller, turn_adapter=a,
                resolve_callable=resolve_callable)
            policy.observe("web_search", {"query": q}, result)

    pending_feedback = len(convo) - unseen_start
    # 0.1.50 completion first after a stop (S6 bench, T2): repeated failure ends RESEARCH, not the
    # deliverable. The run enters finish mode once (sticky): up to two steps where only the save tools
    # run (K3: the table stays, other calls are refused), then text only. Without save tools a
    # no-progress stop forces an answer at once, as before. (0.1.63 K4b: a spent web-read allowance
    # no longer starts it; live reads have none.)
    finish_reason: str | None = None
    finish_from = 0
    finish_steps = 0
    # Wrap-up keeps the FULL tool list (an unchanged list keeps the provider's prompt
    # cache: a narrowed one re-sent ~28k tokens uncached in the S6 bench). K3: it no
    # longer narrows after a refused research call either; refusals say why, and after
    # the second refused call the next step is text only (the same table, tool_choice
    # none), so a model that keeps reaching for research still delivers.
    wrap_refused = 0
    long_turn_told = False
    tool_steps = 0              # K5: steps whose calls are not only update_plan
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
        saved = any(item.get("tool") in WRAP_UP_TOOLS and (item.get("result") or {}).get("ok") is True
                    for item in tool_trace[finish_from:]) if finish_reason else False
        finishing = finish_reason is not None and can_save and finish_steps < 3 and not saved
        finish_done = finish_reason is not None and not finishing
        forced = (finish_done or (policy.stopped and not finishing) or truncation_stop
                  or budget.tool_calls >= budget.limits.tool_calls
                  or (max_tool_calls is not None and step >= max_tool_calls)
                  or wrap_refused >= WRAP_REFUSALS_BEFORE_TEXT)
        no_progress = policy.stopped or finish_reason == "no_progress"
        if forced or (finishing and no_progress):
            stop_reason = "task_no_progress" if no_progress or truncation_stop else "task_budget_exhausted"
            if runtime:
                _stop_for_limit(runtime, stop_reason, tool_trace, finishing=finishing and no_progress and not forced)
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
                         "Research is over and the calls outside wrapping up were refused: give the final answer "
                         "now from what you have, marking what is unverified. Text only."
                         if wrap_refused >= WRAP_REFUSALS_BEFORE_TEXT else
                         "Tool budget exhausted: report the verified results and remaining work. Text only.")
        # 0.1.43 completion first: past the soft limit (or, 0.1.50, in finish mode),
        # stop gathering and FINISH. Research tools are withdrawn; saving the
        # deliverable stays possible. Not a failure: the completion checks decide
        # the outcome as usual.
        wrap_up = not forced and (finishing or budget.soft_reached())
        # K3: the tool table stays as it is (narrowing it would rewrite Claude's cache from the tools
        # on); the status says what still runs, and dispatch refuses the rest with its reason.
        still_run = sorted(FINISH_TOOLS & wired_keys)
        allowed_note = (f" Tools that still run: {', '.join(still_run)}; any other call is refused."
                        if still_run else " No tool runs any more: answer in text.") if wrap_up else ""
        if finishing:
            finish_steps += 1
            notes.append("Repeated actions made no progress, so research has stopped."
                         " Using only what you already have, save the deliverable now if one was asked for "
                           "(write_file), marking anything missing or unverified; then give the final answer: "
                           "what was done, what is blocked." + allowed_note + offline_note)
        elif wrap_up:
            notes.append("Work budget nearly used: stop researching now. Using only what you already have, "
                         "produce the complete deliverable the user asked for (save it if a file was asked for), "
                         "clearly marking anything you could not verify. Then give the final answer."
                         + allowed_note + offline_note)
        # K4b: once a turn, only where start_background_work is offered (never inside a job), and only in
        # the status block, so the system text and the tools (K3's cached prefix) stay as they are.
        if (not long_turn_told and not forced and not wrap_up and "start_background_work" in wired_keys
                and budget.elapsed() >= LONG_TURN_S):
            long_turn_told = True
            notes.append(_LONG_TURN_NOTE)
            from server.services import runtime_messages
            emit({"type": "note", "text": runtime_messages.render(
                "turn_long", await runtime_messages.selected_locale(), minutes=LONG_TURN_S // 60)})
        if tool_steps >= 2 and _host_turn(caller, progress_lane):
            notes.append(_CLOSING_NOTE)
        # Deliver one new tool batch atomically before normal old-history
        # eviction. Keep a bounded 96k research window so a <=96k source batch
        # can survive the following save/readback steps, not just one request.
        # Other turns retain the 64k target. Apply extra protection only
        # to batches <=96k, never permanently pin sources or widen task budgets.
        # Existing opaque-provider pair retention is otherwise unchanged.
        # 0.1.63 K1b: Claude's native path never edits what it sent; the API clears old tool results
        # (context editing). After a refusal of that, local trimming resumes (screenshots too).
        server_trims = _server_trims(a, turn_state)
        _SENT_IS_FINAL.set(server_trims)
        if not server_trims:
            trajectory.keep_latest_images(convo)
        oversized_feedback = (not server_trims and pending_feedback
                              and _rendered_size(convo[-pending_feedback:]) > 96_000)
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
        in_turn = _IN_TURN_CHARS_RESEARCH if has_web_evidence else _IN_TURN_CHARS
        convo, compacted = (convo, False) if server_trims else bounded_history(
            convo, max_chars=in_turn, trim_to=in_turn // 2,
            preserve_tail=0 if oversized_feedback else pending_feedback, size_of=_rendered_size)
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
        # K3: the same tool table on every step of the turn, wrapping up included (a narrowed table was a
        # cache miss from the tools on, K1b). Exceptions, one miss each: a capability added mid-turn, an
        # MCP schema the provider refused, relax() on a retry.
        step_tools = None if forced else schemas
        offered = {t["function"]["name"] for t in step_tools or []}
        # Nothing done, planned or noted yet (a plain chat turn, or step 0): no
        # block — the request goes out as the user wrote it. Step 0's write
        # facts live in the tool descriptions (S5); the block starts with work.
        # 0.1.63 D1: turn_notes are host facts about this whole turn (a turn from the iPhone).
        turn_lines = list(turn_notes or ())
        status = "" if not (tool_trace or notes or plan.items or lesson_notes or turn_lines) else agent_status.render(
            workspace=agent_status.home_relative(ws_root) if ws_root is not None else None,
            writers=[k for k in ("write_file", "edit_file", "run_command") if k in offered],
            own_folder=own_folder, saved=agent_status.owned_outputs(tool_trace, ws_root, turn_started),
            plan=plan.render(), tool_calls=budget.tool_calls, model_calls=budget.model_requests,
            wrap_up_at=budget.soft.tool_calls if budget.soft is not None else None,
            notes=lesson_notes + turn_lines + notes)
        try:
            usage_sink.note_context_parts(_context_parts(system, schemas, convo, current_request, status))
        except Exception:  # noqa: BLE001 — the ring's breakdown is telemetry: it never fails a turn
            logger.warning("context parts not measured", exc_info=True)
            usage_sink.note_context_parts(None)      # say nothing rather than show an older request's
        if _facts is not None and _facts.get("steers"):
            # K9b: this request carries them, once it is sure to go (its tokens and dollars too, which the
            # provider checks as it sends; a stop here hands them back).
            budget.check_request()
            await _commit_steers(_facts["steers"], conversation_id)
        step = _StepStream(turn_text) if turn_text is not None else None
        try:
            resp = await _model_call(a, system, convo, current_request, tools=step_tools,
                                     schemas=schemas, forced=forced, state=turn_state, status=status,
                                     drops=drops, conversation_id=conversation_id, step=step)
        except TextShown:
            # K8a (⓪Plan Q2): part of the answer is out; resending would show it twice. The turn ends with
            # what was shown and says so, and the run records a failure (no `error` frame: the window
            # would drop the text the phone kept).
            from server.services import host_run, runtime_messages
            step.finish()
            turn_text.append(runtime_messages.render("stream_interrupted", await runtime_messages.selected_locale()))
            host_run.note_failure("model_error_after_text")
            if acceptance_runtime is not None:
                acceptance_runtime.pause_reason = "model_error_after_text"
            return {"final": turn_text.text, "escalation": None, "tool_trace": tool_trace,
                    "stop_reason": "model_error_after_text", "history_compacted": history_compacted}
        if step is not None:
            step.finish()
        if drops.changed:              # a refused MCP schema was left out: the rest of the turn too
            drops.changed = False
            wired = drops.keep(wired)
            wired_keys = {t["key"] for t in wired}
            schemas = _native_tool_schemas(wired, allow_escalation=allow_escalation)
            params_by_key = {t["key"]: _tool_params(t) for t in wired}
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
            # K8b: Claude's progress updates, shown as notes before the calls they introduce; never part of the
            # answer, never spoken, not on the phone (the Bridge maps no `note`).
            for update in _progress_updates(a, resp):
                emit({"type": "note", "text": update[:400]})
            # A reply cut by the output limit may carry incomplete arguments in
            # ANY of its calls: execute none of them (0.1.49 S6).
            cut_off = getattr(resp, "finish_reason", None) == "length"
            if cut_off:
                turn_state.truncated_calls += 1
            elif any((call.get("function") or {}).get("name") != "update_plan" for call in tool_calls):
                tool_steps += 1
            # K9a: consecutive reads of this reply run together (parallel_reads); never in a reply cut off
            # or while wrapping up.
            reads = None if cut_off or wrap_up else await parallel_reads.plan(
                [_planned_read(call, neutral_call, wired_keys, params_by_key)
                 for call, neutral_call in zip(tool_calls, calls)])
            steered = False                     # K9b: a message sent meanwhile waits: the rest is not started
            for index, (call, neutral_call) in enumerate(zip(tool_calls, calls)):
                marks.append((len(convo), neutral_call["id"]))
                fn = call.get("function") or {}
                name = str(fn.get("name") or "")
                # K9b: the boundary after the previous call (or group of reads): a message sent meanwhile is
                # read before anything else runs. A call not started is not run, and still gets a result. The
                # message is taken after the batch, right as it is read (nothing can fall between the two).
                # A reply cut off by the output limit runs none of its calls and reads nothing after them: each
                # keeps its truncation note.
                if not steered and index and steerable and conversation_id and not cut_off \
                        and steering.waiting(conversation_id):
                    steered = True
                if steered and not (reads is not None and reads.has(index)):
                    _record_tool_result(name, {}, {"ok": False, "external": False, "code": "skipped_for_message",
                                                   "error": SKIPPED_FOR_MESSAGE},
                                        emit, tool_trace, json.dumps({"tool": name, "args": {}}), convo)
                    continue
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
                    return {"final": _shown(turn_text), "tool_trace": tool_trace,
                            "escalation": {"kind": str(args.get("kind") or "data"),
                                           "need": str(args.get("need") or "").strip(),
                                           "context": str(args.get("context") or "").strip()}}
                # K7: find_tools ranks what this turn can run but was not shown. use_tool, or a direct call
                # of such a tool, goes on under the tool's real name once its arguments check out against
                # its own table, so the approval, the trace and the receipts are a direct call's.
                on_demand_call = False
                if name == "find_tools" and "find_tools" in wired_keys:
                    emit({"type": "tool_call", "tool": name, "args_summary": json.dumps(args, ensure_ascii=False)[:200]})
                    unseen = [t for t in await resolve_callable() if t["key"] not in wired_keys]
                    result = _record_tool_result(name, args, on_demand.find(str(args.get("query") or ""), unseen, _tool_params),
                                                 emit, tool_trace, json.dumps({"tool": name, "args": args}, ensure_ascii=False),
                                                 convo)
                    policy.observe(name, args, result)
                    continue
                if (name == "use_tool" and str(args.get("name") or "").strip() == "run_command"
                        and _nobody_to_ask(confirm_command)):
                    # v0.1.63: refused (and listed) as a direct call is, not "no tool named run_command".
                    inner = args.get("arguments")
                    name, args = "run_command", inner if isinstance(inner, dict) else {}
                elif "use_tool" in wired_keys and (name == "use_tool" or name not in wired_keys):
                    reachable = {t["key"]: t for t in await resolve_callable()}
                    if name == "use_tool" or name in reachable:
                        wanted = args if name == "use_tool" else {"name": name, "arguments": args}
                        real, inner, refusal = on_demand.unwrap(wanted, reachable, wired_keys, _tool_params,
                                                                _schema_problem)
                        if refusal is not None:
                            result = _record_tool_result(name, args, refusal, emit, tool_trace,
                                                         json.dumps({"tool": name, "args": args}, ensure_ascii=False), convo)
                            policy.observe(name, args, result)
                            continue
                        name, args, on_demand_call = real, inner, True
                        on_demand.note_used(on_demand.conversation(conversation_id), name)
                # A neutral trace record, not a prompt-level execution protocol.
                assistant_content = json.dumps({"tool": name, "args": args}, ensure_ascii=False)
                # 0.1.50 S2: the plan is host bookkeeping — no executor, no tool
                # budget, no progress signal; allowed during wrap-up too.
                if name == "propose_plan_change" and (name in wired_keys or on_demand_call):
                    # 0.1.56 §7: bookkeeping like update_plan — the proposal waits for the
                    # user on a card; nothing in the plan changes here.
                    emit({"type": "tool_call", "tool": name,
                          "args_summary": json.dumps(args, ensure_ascii=False)[:200]})
                    outcome = await _propose_plan_change(args, emit)
                    _record_tool_result(name, args, outcome, emit, tool_trace, assistant_content, convo)
                    continue
                if name in ("propose_capability", "create_skill") and (name in wired_keys or on_demand_call):
                    # 0.1.57 §3: the install-and-retry card; v0.1.64 CAP2a: the save-a-skill card, on the
                    # same channel (DELETE-BY: v0.1.65, when "for you to look at" takes a written skill). A blocking ask in THIS window (confirm_command carries it); a job or a
                    # turn nobody watches adds nothing. On success the tools are read again, so the new
                    # capability (or read_skill's list) is there for the rest of this turn.
                    emit({"type": "tool_call", "tool": name,
                          "args_summary": json.dumps(args, ensure_ascii=False)[:200]})
                    from server.services import background_jobs, capability_flow, skill_forge
                    ask = None if background_jobs.inside_job() else getattr(confirm_command, "ask_capability", None)
                    if name == "create_skill":
                        outcome = await skill_forge.propose(args, conversation_id=conversation_id, ask=ask)
                    else:
                        outcome = await capability_flow.propose(args, conversation_id=conversation_id, ask=ask,
                                                                emit=emit)
                    refresh = bool(outcome.pop("refresh", False))
                    _record_tool_result(name, args, outcome, emit, tool_trace, assistant_content, convo)
                    if refresh:
                        wired = await resolve_tools()
                        wired_keys = {t["key"] for t in wired}
                        schemas = _native_tool_schemas(wired, allow_escalation=allow_escalation)
                        params_by_key = {t["key"]: _tool_params(t) for t in wired}
                    continue
                if name == "update_plan" and "update_plan" in wired_keys:
                    emit({"type": "tool_call", "tool": name,
                          "args_summary": json.dumps(args, ensure_ascii=False)[:200]})
                    outcome = plan.update(args)
                    _record_tool_result(name, args, outcome, emit, tool_trace, assistant_content, convo)
                    if outcome.get("ok"):
                        from server.services import desktop_status
                        desktop_status.note_plan(plan.items)
                    continue
                ran = reads is not None and reads.has(index)    # K9a: it already ran with the reads next to it
                if policy.stopped and not (finishing and name in FINISH_TOOLS) and not ran:
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
                    return {"final": _shown(turn_text), "escalation": None, "clarify": clarify,
                            "tool_trace": tool_trace}
                if budget.tool_calls >= budget.limits.tool_calls and not ran:
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
                    gated = dict(resolve_tools=resolve_tools, tool_timeout_s=tool_timeout_s,
                                 confirm_command=confirm_command,
                                 confirm_workspace_write=confirm_workspace_write,
                                 confirm_schedule=confirm_schedule, mcp_fail_counts=mcp_fail_counts,
                                 mcp_hint_logged=mcp_hint_logged, conversation_id=conversation_id,
                                 log_events=log_events, caller=caller, turn_adapter=a,
                                 resolve_callable=resolve_callable)
                    if reads is not None and reads.launchable(index):
                        await reads.run(index, lambda key, arguments, **own: _dispatch_tool(
                            key, arguments, json.dumps({"tool": key, "args": arguments}, ensure_ascii=False),
                            **gated, **own),
                            exhausted=lambda: budget.tool_calls >= budget.limits.tool_calls)
                    if reads is not None and reads.has(index):
                        result = reads.take(index, emit=emit, tool_trace=tool_trace, convo=convo)
                    else:
                        result = await _dispatch_tool(name, args, assistant_content, emit=emit,
                                                      tool_trace=tool_trace, convo=convo, **gated)
                finally:
                    if offline is not None:
                        terminal_exec.OFFLINE.reset(offline)
                if not policy.observe(name, args, result) and policy.count >= 2 and convo \
                        and convo[-1].get("role") == "tool":
                    convo[-1]["content"] += _progress_note(policy)
                # 0.1.50: a saved table of links gets the host link check (link_check).
                if name in WRAP_UP_TOOLS and result.get("ok") is True and convo \
                        and convo[-1].get("role") == "tool":
                    note = await _link_check_note(name, args, result, tool_trace, link_hints)
                    if note:
                        convo[-1]["content"] += note
                if not provider_content:
                    if name == "web_extract" and _web_read_feedback(name, args, result) is not None:
                        research_source_feedback.append((convo[-1], result))
                    elif (name == "write_file" and result.get("ok") is True and not _SENT_IS_FINAL.get()
                          and len(research_source_feedback) >= 2
                          and str(args.get("path", "")).lower().endswith((".md", ".txt"))):
                        # K3b: never on a provider that clears old results itself (Claude's native path):
                        # editing what was sent sends the prompt cache back to the system prompt, and the
                        # request rewrites the whole history (45k tokens in K3's Claude run, T2 r1).
                        from server.orchestrator import saved_context
                        history_compacted = saved_context.compact_saved_context(
                            convo, research_source_feedback, args.get("content")) or history_compacted
                if runtime:
                    runtime.progress = runtime.progress.model_copy(update={
                        "loop_fingerprints": tuple(sorted(policy.seen))[-256:]})
                    await runtime.checkpoint("loop_progress")
            # Each handled call appended one record; bind them to the call ids. The
            # Gemini provider pair and the old "invocation completed" text are now
            # renderings of this trajectory (trajectory.to_legacy), not rewrites.
            _claim_results(convo, marks)
            if steerable and conversation_id and not cut_off and _facts is not None:
                # The boundary after the batch: what waits joins the turn (no await between take and read).
                _read_steers(steering.take(conversation_id), convo, _facts.setdefault("steers", []))
            # resp.content is narration — surface it as an ephemeral note ONLY, never final. K8a: unless it
            # passed the window and went out as the answer, where it stays (and in the stored answer).
            narration = agent_status.strip_echo((resp.content or "").strip())
            if narration and not (step is not None and step.released):
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
        # The reply's continuation replays its own text verbatim (Claude: byte for byte); once the host
        # changed that text (an echo stripped, tool-call text replaced) it goes, as at the repair below.
        own_continuation = getattr(resp, "continuation", None) if final_text == (resp.content or "").strip() else None
        streamed = step is not None and step.released          # K8a: this step's text already went out
        claimed = _unverified_claim(final_text, tool_trace, wired_keys)
        deferred = _is_deferral_stub(final_text)
        protocol_text = _embeds_protocol(final_text) or (step is not None and step.stopped)
        # 0.1.50: an answer that denies a capability this turn had (bench: "no file
        # write ability" with write_file offered) gets one correction.
        from server.orchestrator import capability_truth
        denied = (None if forced or turn_state.capability_bounced or claimed or deferred or protocol_text
                  else capability_truth.denied_capability(final_text, wired_keys, tool_trace))
        if denied:
            turn_state.capability_bounced = True
            await _correct(turn_text, streamed)
            convo.extend([trajectory.assistant(final_text, continuation=own_continuation),
                          {"role": "user", "content": capability_truth.correction(denied, wired_keys)}])
            continue
        if not forced and (claimed or ((deferred or protocol_text) and wired_keys)) \
                and turn_state.unverified_bounces < _UNVERIFIED_BOUNCES:
            turn_state.unverified_bounces += 1
            await _correct(turn_text, streamed)
            # Never execute rescued JSON, nor echo a malformed invocation back
            # as an example to imitate. Permit a new structured call only through
            # the normal tool resolver, permission gate and existing budgets.
            convo.extend([trajectory.assistant(
                "Non-executable tool-call text omitted." if protocol_text else final_text,
                continuation=None if protocol_text else own_continuation), {"role": "user", "content":
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
        replaced = (not final_text) or protocol_text or deferred or claimed
        if replaced:
            from server.services import runtime_messages
            notice_locale = await runtime_messages.selected_locale()
            await _correct(turn_text, streamed)
            if tool_trace:
                final_text = await _synthesize_from_findings(a, system, user_content, tool_trace)
            else:
                final_text = (await _salvage_plain(a, system, user_content)
                              or _chat_miss_message(user_content, locale=notice_locale))
            if _unverified_claim(final_text, tool_trace, wired_keys):
                final_text = (_fallback_with_digest(user_content, tool_trace, locale=notice_locale)
                              if tool_trace else _chat_miss_message(user_content, locale=notice_locale))
        # K8a: what is still to be shown at the end (nothing when this step's text already went out), and
        # the whole answer as the user will have read it.
        to_show = final_text if replaced or not streamed else ""
        answer = final_text if turn_text is None else turn_text.text + ("\n\n" if turn_text.parts and to_show else "") + to_show
        if acceptance_runtime is not None:
            from server.services import task_validation
            report = await task_validation.validate_output(acceptance_runtime, answer, tool_trace, model_adapter=a)
            validation_failures = task_validation.failures(report)
            if validation_failures:
                repair_fingerprint = hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest()
                prior_repairs = acceptance_runtime.progress.validation_repairs
                links = task_validation.unverified_links(answer, report)
                if not forced and len(prior_repairs) < 2 and repair_fingerprint not in prior_repairs:
                    acceptance_runtime.progress = acceptance_runtime.progress.model_copy(update={
                        "validation_repairs": (*prior_repairs, repair_fingerprint)})
                    await acceptance_runtime.checkpoint("validation_repair")
                    if streamed and links:      # K8a Q1: what went out is never rewritten; the repair follows
                        await _not_verified(turn_text, links)
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
                if turn_text is not None and (streamed or turn_text.parts):
                    turn_text.append(to_show)           # K8a Q1: appended to, never rewritten
                    to_show = ""
                    await _not_verified(turn_text, links)
                else:
                    final_text = task_validation.failure_output(final_text, report, acceptance_runtime.spec.locale)
        if turn_text is not None and (streamed or turn_text.parts):
            turn_text.append(to_show)
            return {"final": turn_text.text, "escalation": None, "tool_trace": tool_trace,
                    "stop_reason": stop_reason, "history_compacted": history_compacted}
        if final_text:
            on_chunk(final_text)
        return {"final": final_text, "escalation": None, "tool_trace": tool_trace,
                "stop_reason": stop_reason, "history_compacted": history_compacted}

    if runtime:
        runtime.pause_reason = "task_budget_exhausted"
    budget.stop("model_requests")
