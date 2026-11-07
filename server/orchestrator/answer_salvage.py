"""When a turn has no usable answer: write one from what it found, re-ask for a plain one, or say so honestly (split from
tool_loop, LOOP1 c1a)."""
from __future__ import annotations

import asyncio
import json

from arslan.aio import within
from arslan.execution_budget import BudgetExceeded
from arslan.runtime_policy import FailureKind, exception_kind

from server.orchestrator.answer_contract import GROUNDED_ANSWER_RULES
from server.orchestrator.answer_guards import _embeds_protocol, _is_deferral_stub
from server.orchestrator.untrusted import GUARD_NOTE, wrap_external


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
        return "这个任务这一轮还没做完。回复“继续”我就接着做;也可以把范围缩小一点,会更快。"  # lang-check: allow
    return ("I didn't finish this one in a single round. Reply \"continue\" and I'll keep "
            "going — or narrow the scope a little for a faster answer.")


def _evidence_digest(tool_trace: list, *, max_items: int = 8, snippet: int = 240,
                     total: int = 2600) -> str:
    """Deterministic (no-LLM) salvage of a spent round: compress the OK tool results
    into a findings block. Without this, a continuation restarts research from ZERO —
    live incident: 3 rounds × 8 searches on the same task, nothing ever accumulated,
    the user kept being asked to press 「继续」. The digest rides inside the round's final
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
    """Fallback message + whatever evidence this round actually gathered. The 「【阶段性发现】」
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
            # raw-dump digest floor + a bogus 「继续」 nudge (which reads as "still working" when the
            # tool already returned everything needed).
            payload = {k: v for k, v in res.items()
                       if k not in ("ok", "artifact", "external", "error")}
            if payload:
                lines.append(f"{step.get('tool')} returned: {json.dumps(payload, ensure_ascii=False)[:900]}")
    return "\n".join(lines)[:limit]


async def _synthesize_from_findings(a, system: str, user_content: str, tool_trace: list, *,
                                    or_none: bool = False) -> str | None:
    """Forced-step / salvage synthesis. Instead of asking the model to answer from the messy
    tool-loop convo (which DeepSeek resists — it keeps wanting to search), hand it its OWN gathered
    findings in a CLEAN, isolated prompt and demand the finished answer. Falls back to an honest
    findings digest only if even this refuses (or_none: None instead, for a caller with a better fallback)."""
    digest = _clean_findings(tool_trace)
    if not digest.strip():
        if or_none:
            return None
        from server.services import runtime_messages
        return _fallback_with_digest(user_content, tool_trace, locale=await runtime_messages.selected_locale())
    # ROUTE1 (v0.1.64): synthesis runs on the tool loop's own adapter `a`, the conversation's model; there is no
    # final-answer slot.
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
    if or_none:
        return None
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
    and nothing 'unfinished', so we must NOT show the research 「继续」 nudge — re-ask for a plain,
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
