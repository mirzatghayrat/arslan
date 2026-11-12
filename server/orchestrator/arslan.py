"""The orchestration loop for one user turn (transport-agnostic; emits event dicts)."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select

from server.orchestrator import llm_errors
from server.services import folder_rules, ocr_fallback, phone_ids
from server.db import session as db_session
from server.orchestrator import (
    env_snapshot,
    memory,
    promise_guard,
    run_trace,
    tool_loop,
    turn_context,
    turn_tools,
    untrusted,
)
# LOOP1 e: the prompt lives in answer_rules.py, one piece per rule. The old names stay here because tests read
# them as arslan._X; only _ANSWER_STABLE_PREFIX is used in this module.
from server.orchestrator.answer_rules import (  # noqa: F401
    ANSWER_STABLE_PREFIX as _ANSWER_STABLE_PREFIX,
    ANTI_FABRICATION as _ANTI_FABRICATION,
    ARSLAN_SYSTEM as _ARSLAN_SYSTEM,
    CAPABILITY_SELF as _CAPABILITY_SELF,
    CLARIFY_CHOICE_NUDGE as _CLARIFY_CHOICE_NUDGE,
    NO_BACKGROUND_EXEC as _NO_BACKGROUND_EXEC,
    NO_REPASTE as _NO_REPASTE,
    OUTPUT_RULES as _OUTPUT_RULES,
    VERSION_LINE as _VERSION_LINE,
    WEB_TOOL_GUIDANCE as _WEB_TOOL_GUIDANCE,
)
from server.orchestrator.tool_caller import ToolCaller
from server.ws import protocol
from arslan.llm import usage_sink
from arslan.execution_budget import governed
from arslan.llm import request_policy
from arslan.llm.cached_system import build_cached_system
from server.services.task_context import scoped_turn
from server.services.task_repository import TaskError
from server.services import runtime_messages

logger = logging.getLogger(__name__)

EventSink = Callable[[dict], None]


# 0.1.59: which language a turn answers in, said explicitly every turn. "Reply in the user's
# language" alone lost to everything else in the context: an English request came back in
# Chinese (2026-10-09, DeepSeek, a promo recording), and the background job's goal, checks and
# the lesson after it followed. The user's latest message decides; a message with no words
# (a path, a number) follows the interface language. Paths, URLs and code are ignored, so
# "copy 发票.pdf to ~/Docs" is still English.
_LANGUAGE_NAMES = {"en": "English", "zh": "Chinese", "ja": "Japanese", "es": "Spanish",
                   "de": "German", "fr": "French", "tr": "Turkish", "ko": "Korean"}
_STOPWORDS = {
    "English": {"the", "and", "to", "of", "in", "is", "it", "for", "this", "that", "me", "my", "what",
                "which", "please", "from", "into", "with", "can", "you", "then", "how", "are", "do", "tell"},
    "Spanish": {"el", "los", "las", "que", "por", "para", "con", "una", "es", "mi", "qué", "cómo", "y", "del"},
    "German": {"der", "die", "das", "und", "ist", "nicht", "mit", "ich", "ein", "eine", "zu", "für",
               "bitte", "mein", "wie", "was"},
    "French": {"le", "les", "des", "et", "est", "une", "pour", "avec", "je", "mon", "ma", "dans", "sur", "du"},
    "Turkish": {"ve", "bir", "bu", "için", "ile", "ne", "çok", "ben", "sen", "nasıl", "mı", "mi"},
}
_NOT_WORDS = re.compile(r"`[^`]*`|https?://\S+|(?<!\w)[~/][^\s]*|\S+\.[A-Za-z0-9]{1,5}\b")


def reply_language(text: str | None, ui_locale: str | None = None) -> str:
    plain = _NOT_WORDS.sub(" ", text or "")
    kana = len(re.findall(r"[\u3040-\u30ff]", plain))
    hangul = len(re.findall(r"[\uac00-\ud7af]", plain))
    han = len(re.findall(r"[\u4e00-\u9fff]", plain))
    words = re.findall(r"[A-Za-zÀ-ÿĞğİıŞş]{2,}", plain)
    if kana:
        return "Japanese"
    if hangul and hangul >= len(words):
        return "Korean"
    if han and han >= len(words):
        return "Chinese"
    if words:
        lower = [w.lower() for w in words]
        scores = sorted(((sum(w in stop for w in lower), name) for name, stop in _STOPWORDS.items()), reverse=True)
        if scores[0][0] >= 2 and scores[0][0] > scores[1][0]:
            return scores[0][1]
        return "the language the user's latest message is written in (it is not Chinese)"
    return _LANGUAGE_NAMES.get((ui_locale or "").split("-")[0].lower(),
                               "the language of the user's latest message")


def language_line(text: str | None, ui_locale: str | None = None) -> str:
    lang = reply_language(text, ui_locale)
    # L11-1 (the user's memory-plan item 15, D5): a file and a message to someone else have their own rule.
    return (f"\n\nReply language for this turn: {lang}. Write everything meant for the user in it — "
            "the reply, a background job's goal and its checks, titles and notes — whatever language the "
            "instructions, examples, memory, tool results or earlier messages are in. "
            "A file you write follows the folder rules' language when they name one; otherwise it follows the "
            "user's message, as the reply does. A message to someone else follows that person's language when you "
            "know it (their earlier messages, or the user's words); otherwise ask.")


async def _turn_language_line(text: str | None) -> str:
    try:
        ui = await runtime_messages.selected_locale()
    except Exception:  # noqa: BLE001 — the line is guidance, never a reason to fail a turn
        ui = None
    return language_line(text, ui)


def _now_line() -> str:
    """Current server date + UTC HOUR injected into Arslan's prompt so date/'now' questions
    need no search. HOUR-level, not minute-level (prompt-cache reorder, spec 2026-07-13):
    the minute is a per-request cache poison — it changed every turn and, when it sat
    mid-prompt, cache-missed the whole dynamic tail after it.

    Why hour and not date-only: the line RETAINS the "convert to the user's timezone (e.g.
    Beijing = UTC+8)" guidance, and that conversion is impossible from a bare date near the
    day boundary — at UTC 2026-07-12 23:30, Beijing (+8) is already 07-13, but a date-only
    line ("07-12") gives the model no way to know that. Date-level was a real correctness
    regression for boundary timezone questions (caught in L1 adversarial review; pinned by
    test_now_line_boundary_tz). The UTC hour is sufficient to get every user's LOCAL date
    right near midnight while still changing only once an hour (not once a request), and the
    line lives at the END of the volatile suffix — so its granularity is irrelevant to the
    Anthropic cache_control breakpoint (that's on the stable prefix, entirely upstream) and
    costs DeepSeek/OpenAI only the trailing ~30 tokens, re-cached once per hour.

    Known limit (accepted per the L1 decision): hour precision is exact for whole-hour zones.
    Half-hour / 45-min zones (India +5:30, Nepal +5:45, Newfoundland -3:30) can be a day off
    within the ~30-45 min around their local midnight — a rare edge traded for cache stability;
    minute precision would fix it but re-poison the trailing cache every request."""
    now = datetime.utcnow()
    return (
        f"\n\nCurrent date & time (server clock, UTC): {now:%Y-%m-%d %H}:00 ({now:%A}), to the hour. "
        "Use this directly for 'today' / 'now' / the current date; the UTC hour is enough to convert "
        "to the user's timezone when asked (e.g. Beijing = UTC+8) and get their LOCAL date right even "
        "near midnight. Do NOT search the web for the current date/time."
    )


# Prompt-cache reorder (spec 2026-07-13, D1/D2/D3): the answer system is assembled as a
# byte-stable STABLE PREFIX (the static guards, same order as before, minus the timestamp)
# + a VOLATILE SUFFIX (everything per-turn/per-conversation). Kept as a named pure helper so
# the stable-prefix byte-stability invariant is directly testable.
# LOOP1 e: the prefix is built from one piece per rule in answer_rules.py (the version line too).


def _build_answer_system(*, route: str = ""):
    """Arslan's answer system: the static guards, plus a route's fixed text (background work's).

    0.1.63 K3: nothing per turn is in it any more, so it is the same bytes from turn to turn and Claude
    reads its cache entry (breakpoint ①, tools included) instead of rewriting it. What changes per turn
    rides at the start of the turn's request (`_turn_context`). CachedSystem keeps its two parts until
    v0.1.64 (K3 card §5: merge them into one then); the provider marks the system's last block.
    """
    return build_cached_system(_ANSWER_STABLE_PREFIX, route)


def _turn_context(*, addendum: str = "", facts: str, summary: str, kb_block: str, mcp_line: str = "",
                  environment: str = "", language: str = "", rules: str = "") -> str:
    """This turn's reference block (server/orchestrator/turn_context.py: built once per turn, never
    saved), in the order the system prompt carried it before K3: a resumed
    task's notes → facts → summary → knowledge → the MCP status line → (K5) the environment snapshot →
    (K10-1) the folder's rules → the reply language → the time (floored to the UTC hour, still enough for timezone
    conversion)."""
    body = (f"\n\n{addendum}" if addendum else "") + (f"\n\n{facts}" if facts else "")
    if summary:
        body += f"\n\nConversation summary so far:\n{summary}"
    body += kb_block + mcp_line + environment + (f"\n\n{rules}" if rules else "") + language + _now_line()
    return turn_context.wrap(body)


_with_turn_context = turn_context.prepend   # the turn's request: its block first, then what the user sent


async def _mcp_status_line() -> str:
    """0.1.61 §B1: one clause per switched-on MCP server that is not ready, so the model knows why
    its tools are missing. Volatile (never in the cached prefix). Only Arslan's own wording reaches
    the system prompt: a reason outside the supervisor's vocabulary is left out (ruling 6), and the
    state is said in the words a call to it is answered with (`executor.state_words`), never a raw
    state word. A `ready` with no live session (`ready_now`) is still starting."""
    from server.db.models import MCPServer
    from server.mcp.executor import status_clauses
    try:
        async with db_session.AsyncSessionLocal() as db:
            rows = (await db.execute(select(MCPServer).where(MCPServer.host_allowed.is_(True))
                                     .order_by(MCPServer.id))).scalars().all()
    except Exception:  # noqa: BLE001 — a status line is context, never a reason to fail a turn
        logger.warning("mcp status line unavailable", exc_info=True)
        return ""
    clauses = status_clauses(rows)
    if not clauses:
        return ""
    return ("\n\nMCP servers not available right now: " + "; ".join(clauses) + ". Their tools are "
            "not in your list this turn. Don't edit config files or start them from the terminal; "
            "tell the user what is wrong and what they can do.")
















# ── vision (S4.2-e) ─────────────────────────────────────────────────────────
# Two pure functions so the two halves of an image turn can be tested without
# a provider: what the MODEL sees, and what gets PERSISTED. They differ on
# purpose — decision ③A: an image participates only in the turn it was sent.

def build_user_blocks(
    user_message: str,
    attached_context: str | None,
    images: list[dict] | None,
) -> str | list[dict]:
    """The user content handed to the LLM.

    Returns a plain STRING when there are no images — every text-only turn in
    the app must keep the exact payload it had, and a one-element block list
    would reshape all of them for nothing."""
    text = user_message
    if attached_context:
        text = f"[Attached material]\n{attached_context}\n\n[User message]\n{user_message}"
    if not images:
        return text
    blocks: list[dict] = [{"type": "text", "text": text}]
    for img in images:
        if isinstance(img.get("source_locator"), str):
            blocks.append({"type": "text", "text": "Image source locator (attachment data): " + img["source_locator"][:500]})
        blocks.append({
            "type": "image",
            "mime_type": img.get("mime_type") or "image/png",
            "data": img.get("data") or "",
        })
    return blocks


def persisted_user_text(user_message: str, images: list[dict] | None) -> str:
    """What goes into arslan_messages.

    NOT the image: `content` is a Text column, and base64 in it would bloat the
    database and every backup while still not surviving as a real image. The
    placeholder names the file so the transcript reads honestly, and so turn two
    does not imply the model can still see something it cannot."""
    if not images:
        return user_message
    names = "\n".join(f"[图片:{i.get('name') or 'image'}]" for i in images)
    return f"{user_message}\n{names}" if user_message else names


@governed
@scoped_turn
async def handle_user_message(
    conversation_id: str,
    user_message: str,
    emit: EventSink,
    *,
    attached_context: str | None = None,
    images: list[dict] | None = None,
    confirm_command=None, confirm_workspace_write=None, confirm_schedule=None,
    source: str | None = None,
) -> None:
    """Process one user turn end-to-end, emitting event dicts for the transport layer.
    `source` is "phone" for a message the Arslan Bridge forwarded from a paired iPhone."""
    # 1. persist the user turn — the PLACEHOLDER form when images rode along
    #    (decision ③A); base64 in a Text column would bloat the DB and backups
    #    while still not surviving as an image.
    stored_text = persisted_user_text(user_message, images)
    source_message_id = await memory.add_message(conversation_id, "user", stored_text, source=source)
    if source == "phone":
        # A Mac window open on this conversation did not type it — show it there live,
        # labelled "from iPhone". Raw emit, never journaled: it is in the history now.
        emit(protocol.message(source_message_id, stored_text, "user") | {"source": "phone"})
    from server.services.task_context import source_message
    source_message(source_message_id)
    from server.services import personal_context, task_context
    active_context = personal_context.current()
    if active_context is not None and task_context.precise_text_request(user_message):
        from dataclasses import replace
        with personal_context.bind(replace(active_context, no_memory=True)):
            await _handle_answer(conversation_id, user_message, emit, attached_context=attached_context,
                                 images=images, confirm_command=confirm_command,
                                 confirm_workspace_write=confirm_workspace_write, confirm_schedule=confirm_schedule,
                                 source=source, steerable=True)
        return

    # 0.1.48: one Arslan, one loop. Every message goes straight to the agent and its
    # tools; nothing decides beforehand what kind of message it is. The pre-turn router
    # this replaces was the expert-era dispatcher: an extra model call per message that
    # could answer in the agent's place. "Add today's to-dos to Reminders" came back as
    # a canned "no preset for that connector" and never reached a tool.
    reply = {"id": None, "run": None}    # K2b: the reply this turn ended with, as its stream_end said

    def watch(event: dict) -> None:
        if event.get("type") == "stream_end" and isinstance(event.get("message_id"), int):
            reply["id"] = event["message_id"]
        if reply["run"] is None and type(event.get("run_id")) is int:
            reply["run"] = event["run_id"]   # v0.1.64: the turn's run, which host_run puts on each of its events
        emit(event)
    await _handle_answer(conversation_id, user_message, watch, attached_context=attached_context,
                         images=images, confirm_command=confirm_command,
                         confirm_workspace_write=confirm_workspace_write, confirm_schedule=confirm_schedule,
                         source=source, steerable=True)
    # Durable facts, noticed after the answer (the router used to do this before it), and
    # compaction: both after the turn, outside its lock (K2b). The budget is the turn's, noted on
    # the turn's run as before.
    budget = await memory.turn_budget(conversation_id, has_images=bool(images))
    _after_turn_later(conversation_id, user_message, emit, active_context, budget=budget, reply_id=reply["id"],
                      run_id=reply["run"])


# K2b (U5 ①②): the post-turn jobs still running, and each conversation's latest one.
_AFTER_TURN: set[asyncio.Task] = set()
_after_turn_tail: dict[str, asyncio.Task] = {}
AFTER_TURN_SECONDS = 300


def _after_turn_later(conversation_id: str, user_message: str, emit: EventSink, turn_context,
                      *, budget: int, reply_id: int | None, run_id: int | None = None) -> None:
    """Look for facts and compact after the turn has returned, so its lock is free and the next
    message starts at once (K2b; U5 ①, M3 #11).

    Its own task, detached from the finished turn (`task_service.detached_context`: no turn
    checkpoint, its own budget; the model calls keep their ledger scopes `memory_facts` and
    `memory`), referenced until done. One conversation's jobs run in turn, so a job sees what the
    one before it saved. A job still pending when the process exits is lost: only that turn's
    facts, and the next compaction covers its history (K2 card, accepted risk). Deleting the
    conversation does not stop a pending job's facts either: memories outlive a conversation by
    design; its summary is not written back (memory.maybe_compact). What it judges belongs to the turn's run
    (`run_id`, v0.1.64: judgments.run_id); the turn's run is over by then, so the id is bound for the job."""
    from server.services import judgment, task_service
    loop = asyncio.get_running_loop()
    previous = _after_turn_tail.get(conversation_id)
    if previous is not None and previous.get_loop() is not loop:
        previous = None                 # left by a loop that has ended (tests run one loop each)
    with judgment.of_run(run_id):        # the job's context is copied from here
        job = loop.create_task(
            _after_turn(conversation_id, user_message, emit, turn_context, budget=budget, reply_id=reply_id,
                        after=previous),
            context=task_service.detached_context())
    _AFTER_TURN.add(job)
    _after_turn_tail[conversation_id] = job

    def done(finished: asyncio.Task) -> None:
        _AFTER_TURN.discard(finished)
        if _after_turn_tail.get(conversation_id) is finished:
            del _after_turn_tail[conversation_id]
    job.add_done_callback(done)


async def _after_turn(conversation_id: str, user_message: str, emit: EventSink, turn_context,
                      *, budget: int, reply_id: int | None, after: asyncio.Task | None) -> None:
    if after is not None:
        await asyncio.wait([after])
    try:
        async with asyncio.timeout(AFTER_TURN_SECONDS):
            try:
                context = await _job_context(conversation_id, user_message, turn_context)
            except Exception as exc:  # noqa: BLE001 — no context, no facts; compaction needs none
                logger.info("post-turn facts skipped: %s", type(exc).__name__)
                context, look = None, False
            else:
                # Not in a temporary conversation or one where memory or learning is switched off.
                look = context is None or not (context.temporary or context.no_memory or context.no_learning)
            from server.services import personal_context, turn_facts

            async def recheck():                # right before anything is saved: the model call takes seconds
                again = await _job_context(conversation_id, user_message, turn_context)
                return None if again is None or again.temporary or again.no_memory or again.no_learning else again
            if look:
                with personal_context.bind(context) if context is not None else contextlib.nullcontext():
                    await turn_facts.capture(conversation_id, user_message, _quiet(emit, reply_id),
                                             recheck=recheck if turn_context is not None else None)
            await memory.maybe_compact(conversation_id, budget=budget)
    except Exception as exc:  # noqa: BLE001 — a post-turn job never surfaces anywhere
        logger.warning("post-turn job failed for %s: %s", conversation_id, type(exc).__name__)


async def _job_context(conversation_id: str, user_message: str, turn):
    """The job's memory context. It keeps the turn's identity: task, run and message, which a saved
    fact cites as its source (deleting a memory entry suppresses later ones from the same source:
    memory_repository._not_suppressed). It takes the stricter of the turn's switches and the
    conversation's, read again now: one turned off while the answer ran is respected. None when the
    turn had none (memory not active)."""
    if turn is None:
        return None
    from dataclasses import replace

    from server.services import task_context
    now = await task_context.load(conversation_id, user_message=user_message)
    return replace(
        turn, lease=None,
        no_memory=turn.no_memory or now.no_memory, no_learning=turn.no_learning or now.no_learning,
        temporary=turn.temporary or now.temporary,
        model_is_local=turn.model_is_local and now.model_is_local,
        cloud_memory_allowed=turn.cloud_memory_allowed and now.cloud_memory_allowed,
        cloud_memory_default=turn.cloud_memory_default and now.cloud_memory_default,
        allow_sensitive=turn.allow_sensitive and now.allow_sensitive,
        auto_activate_noticed=turn.auto_activate_noticed and now.auto_activate_noticed,
    )


def _quiet(emit: EventSink, reply_id: int | None) -> EventSink:
    """The job's frames arrive after stream_end; the window may be gone by then. Nothing is retried.
    A remembered fact names the reply its turn ended with: the window puts the line under it."""
    def send(event: dict) -> None:
        if reply_id is not None and event.get("type") in {"fact_saved", "memory_proposed"}:
            event = {**event, "reply_message_id": reply_id}
        try:
            emit(event)
        except Exception:  # noqa: BLE001 — the window may be gone after stream_end; nothing is retried
            pass
    return send








def _frame_usd(buckets: list[dict]) -> float | None:
    """Review I2: USD for a turn = SUM of each (model, provider) bucket priced at
    ITS OWN rate — never the primary bucket's rate applied to summed tokens (a
    mixed-model turn would silently bill sonnet tokens at haiku prices). None
    (unknown, not free) when there are no buckets, any bucket is estimated
    (estimates are never priced — the existing gate, kept), or any bucket's
    model/provider has no known price (a partial sum would understate cost).
    K4a: a bucket's dollars are the sum of its responses' prices by cache tier
    (prices.usd_for_usage, reported with each response); input and output alone
    understated Anthropic's cache and overstated DeepSeek's hits."""
    if not buckets:
        return None
    total = 0.0
    for b in buckets:
        if b["estimated"] or b.get("usd") is None:
            return None
        total += b["usd"]
    return total


def _frame_models(buckets: list[dict]) -> list[dict]:
    """Every (model, provider) that ran this turn, busiest first.

    A bucket with no model name is DROPPED rather than rendered: usage_sink allows
    model=None, and printing "None" as a model would be a confident-looking lie on the
    one line meant to be trustworthy.
    """
    named = [b for b in buckets if b.get("model")]
    named.sort(key=lambda b: (b.get("tokens_in") or 0) + (b.get("tokens_out") or 0),
               reverse=True)
    return [{"model": b["model"], "provider": b.get("provider")} for b in named]


def _usage_frame(detail: dict) -> dict:
    """S3-M3 Task 5: per-turn usage payload for a terminal stream_end frame.

    MUST be built while the turn's ``usage_sink.collecting()`` scope is still open —
    both the passed ``detail()`` snapshot and ``usage_sink.total()`` read the active
    contextvars. ``estimated`` mirrors finalize's ``tokens_estimated`` rule
    (``tokens_in is None`` — detail() already blinds totals when any bucket is
    estimated). ``usd`` is per-bucket-summed (review I2, _frame_usd) and None
    whenever it can't be known honestly (unknown model / estimated tokens); the key
    is ALWAYS present so the frontend can tell "unknown cost" (null) apart from
    "free" ($0)."""
    return {
        "tokens_in": detail["tokens_in"],
        "tokens_out": detail["tokens_out"],
        "tokens_total": usage_sink.total(),
        "calls": usage_sink.calls(),
        # 0.1.58 §6: the last call's input — the composer's context ring. K3: the whole input, cache
        # reads and writes included (Anthropic's input_tokens leaves them out).
        "last_input": usage_sink.last_input(),
        # K4b: the last request's parts, estimated (system, tools, context, history, turn): the ring's
        # breakdown. None when no request was measured (a plain streamed answer).
        "context_parts": usage_sink.context_parts(),
        # K3: what this reply read from the provider's cache, of its whole input (the footer's hit rate);
        # cache_read is None when the provider reported nothing about its cache.
        "cache_read": detail.get("cache_read"),
        "input_total": detail.get("input_total"),
        "estimated": detail["tokens_in"] is None,
        "usd": _frame_usd(detail["buckets"]),
        # 🔴 Who answered. detail() has computed this every turn and _usage_frame threw
        # it away — Run rows carry model/provider, but the chat answer path writes no
        # Run row, so the surface a person actually watches has never said. Spec ② can
        # now route a task to a different model on purpose, and "no silently swapping
        # models and spending the user's money" is unenforceable if nothing reports it.
        #
        # ALL of them, biggest first — not usage_sink.primary(). primary() is the right
        # default for one label, and using it here would hide precisely the multi-model
        # turn this exists to reveal.
        "models": _frame_models(detail["buckets"]),
    }


async def _read_images_locally(images: list[dict]) -> str | None:
    """Tier 2 for a chat turn: hand the pictures to the system recogniser.

    Returns a block of text to append to the user's message, or None when
    nothing was read — None is the honest answer and the caller shows the
    "switch models" advice instead of inventing a recovery.

    The transcription is LABELLED. A retrieval hit renders as "[source] text"
    and this is the same problem in the turn itself: the model must not read
    characters lifted off a picture as if the user had typed them."""
    import base64

    from server.services import ocr_fallback, ocr_vision

    language = await ocr_fallback.current_ui_language()
    chosen = await ocr_fallback.current_ocr_languages()
    parts = []
    for img in images:
        try:
            raw = base64.b64decode(img.get("data") or "")
        except Exception as exc:  # noqa: BLE001 — a bad attachment is not fatal
            logger.warning("could not decode an attached image for OCR: %s", exc)
            continue
        text, status = ocr_fallback.read_locally(
            raw, ui_language=language, chosen_languages=chosen)
        if status == ocr_vision.OK and text.strip():
            parts.append(f"{ocr_fallback.ocr_source(img.get('name') or 'image')}\n{text}")
    return "\n\n".join(parts) if parts else None


async def _handle_answer(
    # extra_system: notes for this turn only (a resumed task's). Since K3 they ride in the turn's
    # reference block at the start of its request, not in the system prompt.
    conversation_id: str, user_message: str, emit: EventSink, *, extra_system: str = "",
    attached_context: str | None = None, images: list[dict] | None = None,
    confirm_command=None, confirm_workspace_write=None, confirm_schedule=None,
    source: str | None = None, steerable: bool = False,
) -> str | None:
    """`steerable` (K9b): this turn holds the conversation's turn lock with its steering box open (a socket's
    chat turn or a resumed task), so it reads what the user sends meanwhile; a scheduled run never does."""
    from server.services import host_run

    async def body(run_emit):
        return await _handle_answer_body(
            conversation_id, user_message, run_emit, extra_system=extra_system,
            attached_context=attached_context, images=images,
            confirm_command=confirm_command, confirm_workspace_write=confirm_workspace_write,
            confirm_schedule=confirm_schedule, source=source, steerable=steerable)

    return await host_run.execute(conversation_id, user_message, emit, body,
                                  has_images=bool(images))


# 0.1.63 D1: a turn from the paired iPhone. A host fact in the status block, never the system prompt
# (it stays byte-stable for the prompt cache, K3): a path on the Mac means nothing on the phone.
PHONE_NOTE = ("The user is on their iPhone: a path on this Mac is no use to them. A file they ask for "
              "(a screenshot, chart, export or document) reaches them only through attach_file (find it "
              "with find_tools), under your answer.")
#: v0.1.63 (the user's decision until S2a-3 lands): a run with nobody to ask runs no command; the model is told so
#: up front rather than finding out from a refusal. DELETE-BY: v0.1.64, with S2a-3 and PR4.
SCHEDULED_NOTE = ("This is a scheduled run and nobody is there to approve anything: it runs no commands "
                  "(run_command is not available here). Save what you make with write_file, in Arslan's own "
                  "folder; a step that needs the user's OK is refused and listed under the task on their Scheduled page.")


BACKGROUND_SYSTEM = (
    "\n\nYou are now doing a piece of work in the BACKGROUND. The user started it and is free to talk "
    "about other things; they are not watching this run. Work through it with your tools until the "
    "completion criteria are met. Do not ask chatty questions: if something essential is missing and "
    "cannot be found, stop and say exactly what is missing. Go deeper, not bigger: work from the raw "
    "material, run what can be run, and don't widen the scope yourself. End with a result for the user, "
    "written as a "
    "report (outcome first, one action per sentence, one name per thing, say who did it), in three parts: "
    "what you checked yourself, with the evidence (a file path, a command's result); what the user "
    "should look at, at most one or two things that need a person's judgment; and what you did not "
    "check (not run, failed, or only stated). Add a short fourth part, 'Suggestions, not done', only when "
    "there is something real to suggest beyond what was asked. Say where any output is.")


_LIVE_TURN_ONLY = frozenset({"ask_user_choice", "start_background_work", "background_status", "stop_background_work"})


async def _background_tools() -> list[dict]:
    """The host toolset minus anything that only makes sense inside a live turn."""
    return [tool for tool in await _arslan_tools() if tool["key"] not in _LIVE_TURN_ONLY]


async def _background_callable() -> list[dict]:
    """What a job may run (K7): the same, over every reachable tool."""
    return [tool for tool in await _callable_tools() if tool["key"] not in _LIVE_TURN_ONLY]


#: Q1 (v0.1.64): a quick question is shown, and may call, these four read-only tools and nothing else: an
#: allowlist over every tool, with no find_tools or use_tool. Read from the conversation's stored kind (migration
#: 0071), never from a frame, so a Bridge error can't widen it.
QUICK_TOOLS = frozenset({"web_search", "web_extract", "recall", "conversation_search"})
#: Short and sourced is said here, in the turn's own notes; the system prompt stays byte-stable (K3).
QUICK_NOTE = ("This is a quick question from the user's iPhone: answer in a few sentences and name your sources "
              "(links) when you used the web. Here you can only search the web, read a page, and look in the "
              "user's memory and earlier conversations.")


async def _quick_tools() -> list[dict]:
    return [tool for tool in await _every_tool() if tool["key"] in QUICK_TOOLS]


async def _stored_kind(conversation_id: str) -> str | None:
    """What the conversation is, as stored (0071): `quick`, `chat`, or None (worked out on each read)."""
    from sqlalchemy import select

    from server.db.companion_models import ConversationContext
    async with db_session.AsyncSessionLocal() as db:
        return await db.scalar(select(ConversationContext.kind).where(ConversationContext.id == conversation_id))


async def _with_project_card(facts: str) -> tuple[str, str]:
    """0.1.56 §8: in a project's conversation the model sees the project — name, finish
    line, current level and its open checkpoints — beside the memory block. Also returns the card itself
    (empty when none went in): INB2 counts it as project material (#475 H2)."""
    from server.services import personal_context, project_plan
    ctx = personal_context.current()
    if ctx is None or not ctx.project_id:
        return facts, ""
    try:
        async with db_session.AsyncSessionLocal() as db:
            card = await project_plan.card_text(db, ctx.project_id)
    except Exception:  # noqa: BLE001 — the card is context, never a reason to fail a turn
        logger.warning("project card unavailable", exc_info=True)
        return facts, ""
    return (f"{facts}\n\n{card}".strip(), card) if card else (facts, "")


async def _notes_from_off_the_list(personal) -> bool:
    """#475 H1: a note in the turn's memory block that came from a run off the list (memory_tools_v2). A
    lookup that fails counts as yes: the turn goes on, and only an "about you" entry it writes waits."""
    from server.services import memory_tools_v2
    try:
        return await memory_tools_v2.from_off_the_list(personal.receipt.used)
    except Exception:  # noqa: BLE001 — never a reason to fail a turn
        logger.warning("tracing the notes in view failed", exc_info=True)
        return True


async def _sub_session_tools() -> list[dict]:
    """SUB3: what a sub-session is shown, and all it may run: `sub_sessions.TOOLS`, with no find_tools or use_tool."""
    from server.services import sub_sessions
    return [tool for tool in await _every_tool() if tool["key"] in sub_sessions.TOOLS]


async def background_body(conversation_id: str, goal: str, emit: EventSink, confirmations, *,
                          sub_session: bool = False) -> str:
    """One background job's execution: the answer machinery without the chat stream. SUB3: a sub-session's job is
    offered its own few tools."""
    ctx = await memory.assemble_working_context(conversation_id, budget=await memory.turn_budget(conversation_id))
    from server.services import personal_context
    traced = False
    if personal_context.current() is not None:
        personal = await personal_context.assemble(goal)
        facts = personal.text
        await personal_context.record(personal)
        traced = await _notes_from_off_the_list(personal)
    else:
        facts = await memory.facts_text(include_sensitive=True)
    facts, card = await _with_project_card(facts)
    kb_block = ""
    try:
        from server.services import knowledge as _knowledge
        _kb = await _knowledge.retrieve_scoped(goal, spawn_id=None, used_ref=conversation_id)
        kb_block = _knowledge.knowledge_block(_kb)
    except Exception as exc:  # noqa: BLE001 — retrieval is never fatal
        logger.warning("background kb retrieve failed (non-fatal): %s", exc)
    asked = next((m.get("content") for m in reversed(ctx["history"]) if m.get("role") == "user"), None)
    system = _build_answer_system(route=BACKGROUND_SYSTEM)
    rules, rule_files = await folder_rules.for_turn(conversation_id)
    context = _turn_context(facts=facts, summary=ctx["summary"], kb_block=kb_block,
                            language=await _turn_language_line(asked if isinstance(asked, str) else goal),
                            mcp_line=await _mcp_status_line(),
                            environment=await env_snapshot.for_turn(conversation_id), rules=rules)
    run_trace.record_prompt(system_prompt=f"{system}\n\n{context}", injected_kb=kb_block or None)
    pieces: list[str] = []
    # K3: nobody is waiting on a background job, so its cache entries keep the default five minutes,
    # even when a chat turn started it. INB2 (#475 F2, H1, H2): its run's record counts the knowledge, the
    # project card and a note from off the list put in.
    # K10-1 (D3): a folder's rules are outside content, so a job that read them starts as having read some.
    with request_policy.prompt_cache(long=False), untrusted.off_list_in(bool(kb_block) or bool(card) or traced), \
            untrusted.carried(rule_files > 0):
        result = await tool_loop.run_native(
            system=system, user_content=_with_turn_context(context, goal), history=ctx["history"], emit=emit,
            on_chunk=pieces.append, resolve_tools=_sub_session_tools if sub_session else _background_tools,
            resolve_callable=_sub_session_tools if sub_session else _background_callable, allow_escalation=False,
            confirm_command=confirmations.command, confirm_workspace_write=confirmations.workspace_write,
            confirm_schedule=confirmations.schedule, conversation_id=conversation_id,
            caller=ToolCaller(actor="host", spawn_id=None, conversation_id=conversation_id),
        )
    final = result.get("final") if isinstance(result, dict) else None
    return final if isinstance(final, str) and final.strip() else "".join(pieces)


async def _handle_answer_body(
    conversation_id: str, user_message: str, emit: EventSink, *, extra_system: str = "",
    attached_context: str | None = None, images: list[dict] | None = None,
    confirm_command=None, confirm_workspace_write=None, confirm_schedule=None,
    source: str | None = None, steerable: bool = False,
) -> str | None:
    """One answer turn, in its phases (LOOP1 c3c): the turn's context, the dispatch through the tool loop, a choice
    card, or the reply stored with what follows it."""
    turn = await _answer_context(conversation_id, user_message, extra_system=extra_system,
                                 attached_context=attached_context, images=images)
    result = await _answer_dispatch(
        conversation_id, user_message, emit, turn, attached_context=attached_context, images=images,
        confirm_command=confirm_command, confirm_workspace_write=confirm_workspace_write,
        confirm_schedule=confirm_schedule, source=source, steerable=steerable)
    if result is _NO_REPLY:
        return None
    compact = await _answer_clarify(conversation_id, emit, result)
    if compact is not None:
        return compact
    return await _answer_reply(conversation_id, user_message, emit, result, attached_context)


@dataclass(frozen=True, slots=True)
class _AnswerContext:
    """What the turn's request carries, worked out before it goes out, and what of it is outside content."""
    ctx: dict
    system: str
    context: str
    llm_user: object
    kb_block: str
    card: str
    traced: bool
    rule_files: int


#: The dispatch sent an error frame instead of a reply: the turn ends with nothing stored.
_NO_REPLY = object()


async def _answer_context(conversation_id: str, user_message: str, *, extra_system: str,
                          attached_context: str | None, images: list[dict] | None) -> _AnswerContext:
    """The turn's history, memory, project card, knowledge, folder rules and system text, and its request."""
    # K2: history by the turn model's context window (context_window), not a fixed 3000.
    ctx = await memory.assemble_working_context(
        conversation_id, budget=await memory.turn_budget(conversation_id, has_images=bool(images)))
    from server.services import personal_context
    traced = False
    if personal_context.current() is not None:
        personal = await personal_context.assemble(user_message)
        facts = personal.text
        await personal_context.record(personal)
        traced = await _notes_from_off_the_list(personal)
    else:
        facts = await memory.facts_text(include_sensitive=True)
    facts, card = await _with_project_card(facts)
    # K3: the knowledge found for this request, like everything else per turn, goes in the turn's
    # reference block, never the system prompt.
    kb_block = ""
    try:
        from server.services import knowledge as _knowledge
        _kb = await _knowledge.retrieve_scoped(user_message, spawn_id=None, used_ref=conversation_id)
        kb_block = _knowledge.knowledge_block(_kb)
    except Exception as exc:  # noqa: BLE001 — retrieval is never fatal
        logger.warning("arslan kb retrieve failed (non-fatal): %s", exc)
    system = _build_answer_system()
    rules, rule_files = await folder_rules.for_turn(conversation_id)
    context = _turn_context(addendum=extra_system.strip(), facts=facts, summary=ctx["summary"], kb_block=kb_block,
                            language=await _turn_language_line(user_message), mcp_line=await _mcp_status_line(),
                            environment=await env_snapshot.for_turn(conversation_id), rules=rules)
    run_trace.record_prompt(system_prompt=f"{system}\n\n{context}", injected_kb=kb_block or None)

    # A plain string when there are no images; a neutral block list otherwise (providers translate it).
    llm_user = _with_turn_context(context, build_user_blocks(user_message, attached_context, images))
    return _AnswerContext(ctx=ctx, system=system, context=context, llm_user=llm_user, kb_block=kb_block, card=card,
                          traced=traced, rule_files=rule_files)


async def _answer_dispatch(conversation_id: str, user_message: str, emit: EventSink, turn: _AnswerContext, *,
                           attached_context: str | None, images: list[dict] | None, confirm_command,
                           confirm_workspace_write, confirm_schedule, source: str | None, steerable: bool):
    """The turn through the tool loop, on the tools its kind allows. A picture the model refused is read here and the
    turn sent again without it. Returns the loop's result, or `_NO_REPLY` once an error frame went out."""
    ctx, system, context, llm_user = turn.ctx, turn.system, turn.context, turn.llm_user
    kb_block, card, traced, rule_files = turn.kb_block, turn.card, turn.traced, turn.rule_files
    emit({"type": "stream_start", "source": "arslan"})

    async def _dispatch(user_content):
        # Arslan's answer path uses the native tool-calling loop (structured tool_calls,
        # no text-protocol narration-as-answer bug). Experts use the same native loop.
        # K3: a person is chatting, so Claude keeps the system and history cache entries an hour.
        # S64-0b: what the user attached (a file's text, a picture, what OCR reads off it) is outside content.
        # K10-1 (D3): so is a folder's rules file.
        # INB2 (#475 F2, H1, H2): so is the project knowledge found for it, for the "about you" allowlist, and
        # so are the project card and a note in view that came from a run off the list.
        with request_policy.prompt_cache(long=True), untrusted.carried(bool(attached_context or images) or rule_files > 0), \
                untrusted.off_list_in(bool(kb_block) or bool(card) or traced):
            return await _run_answer(user_content)

    try:
        # Q1b (#486 review, G1): one the phone made with no kind stored is read as quick (phone_ids.kind_of).
        quick = phone_ids.kind_of(conversation_id, await _stored_kind(conversation_id)) == "quick"
        narrow = quick
    except Exception:  # noqa: BLE001 — an unreadable kind gets the four tools, never every tool (Q1 card, rule 4)
        quick, narrow = False, True

    async def _run_answer(user_content):
        return await tool_loop.run_native(
            system=system,
            user_content=user_content,
            history=ctx["history"][:-1],
            emit=emit,
            on_chunk=lambda c: emit({"type": "stream_chunk", "content": c}),
            resolve_tools=_quick_tools if narrow else _arslan_tools,
            resolve_callable=_quick_tools if narrow else _callable_tools,
            allow_escalation=False,
            confirm_command=confirm_command, confirm_workspace_write=confirm_workspace_write,
                             confirm_schedule=confirm_schedule,
            conversation_id=conversation_id,
            caller=ToolCaller(actor="host", spawn_id=None, conversation_id=conversation_id),
            # Whether THIS turn carries an image is known only here — build_user_blocks
            # has already folded the images into the content by the time run_native sees
            # it. The vision slot applies on image turns and nowhere else, so the fact
            # has to be passed rather than inferred.
            has_images=bool(images),
            # A narrowed turn that isn't quick (its kind was unreadable) gets no phone note: attach_file isn't one of the four.
            turn_notes=[*([QUICK_NOTE] if quick else [PHONE_NOTE] if source == "phone" and not narrow else []),
                        *([SCHEDULED_NOTE] if tool_loop._nobody_to_ask(confirm_command) else [])] or None,
            # K9b: only a turn that holds the turn lock with the box open (handle_user_message, a resumed
            # task) reads what the user sends meanwhile; never a scheduled run, a job, a worker or a
            # delegated loop on the same conversation (review of #393).
            steerable=steerable,
        )

    try:
        result = await _dispatch(llm_user)
    except TaskError:
        raise
    except Exception as exc:  # noqa: BLE001
        # THE MODEL WOULD NOT LOOK AT THE PICTURE. Two things used to go wrong
        # here and both were invisible from this file: the raw provider JSON
        # reached the user because explain() was never called on this path (it
        # was wired only into spawn dispatch), and the OCR fallback shipped in
        # v0.1.11 had no caller in this package at all — a chat image was the
        # one route it could not serve.
        recovered = None
        if images and ocr_fallback.model_refused_the_image(str(exc)):
            recovered = await _read_images_locally(images)
        if recovered:
            # Retry WITHOUT the picture. Sending it again to a model that just
            # rejected it fails identically; what changed is that the words are
            # now in the text, so the turn can finish.
            result = None
            try:
                result = await _dispatch(_with_turn_context(context, build_user_blocks(
                    f"{user_message}\n\n{recovered}", attached_context, None)))
            except TaskError:
                raise
            except Exception as retry_exc:  # noqa: BLE001 — report the retry honestly
                emit(await llm_errors.error_frame(retry_exc))
                return _NO_REPLY
        else:
            # Order is the point: vision_errors is the NARROWEST reading (it only
            # fires on image-specific refusals), llm_errors covers the
            # billing/auth/rate family, and the raw text is what survives when
            # neither recognises the fault — never an invented diagnosis.
            emit(await llm_errors.error_frame(exc, had_images=bool(images)))
            return _NO_REPLY
    return result


async def _answer_clarify(conversation_id: str, emit: EventSink, result: dict) -> str | None:
    """The choice card the turn ended with, stored and shown; None when it ended without one."""
    # PA-3: the model asked for a structured user choice — ask_user_choice is a
    # TERMINAL tool, so the loop ended the turn with validated/clamped {question,
    # options}. Persist a compact text twin (question + bulleted labels) so
    # history/recap keep the context, close the stream WITHOUT a ghost bubble
    # (message_id=None — the card is the visible element), and emit the card frame.
    # No promise guard (nothing was promised) and no further LLM call.
    clarify = result.get("clarify")
    if clarify:
        compact = clarify["question"] + "\n" + "\n".join(
            f"- {o['label']}" for o in clarify["options"])
        shown = result.get("final")     # K8a: text that went out before the choice card: kept, in its bubble
        msg_id = await memory.add_message(conversation_id, "arslan", f"{shown}\n\n{compact}" if shown else compact,
                                          **({"display_content": shown} if shown else {}))
        emit({"type": "stream_end", "message_id": msg_id if shown else None,
              "usage": _usage_frame(usage_sink.detail())})
        emit(protocol.clarify_options(clarify["question"], clarify["options"]))
        return compact
    return None


async def _answer_reply(conversation_id: str, user_message: str, emit: EventSink, result: dict,
                        attached_context: str | None) -> str:
    """The reply, with the promise check's correction and the sources' footer when they apply, stored with the turn's
    tool summary, and the stream closed with the turn's usage. `attached_context` is read for the footer only: it
    never goes to the model from here, so no images go with it."""
    full = result.get("final") or ""
    # HX-1 A2 空头支票拦截: PROMISE_RE on a turn that called no tool (a turn that really searched may
    # honestly narrate in-progress work, HX acceptance #1). 0.1.63 K5: the spawn tier is gone (nothing set
    # its spawn name; C7 deletes spawns).
    # A matched promise gets a bounded honest correction appended to the SAME message
    # (streamed live + persisted, so history stays honest) plus the audit event.
    # Fail-open: guard errors never break the answer turn.
    try:
        # 0.1.42: while a background job of this conversation is really running,
        # "it's being worked on in the background" is true, and the generic
        # correction ("nothing is running in the background") would be the lie.
        from server.services import background_jobs
        job_running = any(job.phase != "finished" for job in background_jobs.jobs_for(conversation_id))
        check_generic = not result.get("tool_trace") and not job_running
        if full and check_generic:
            outcome = await promise_guard.correct(full, conversation_id=conversation_id)
            if outcome is not None:
                correction = outcome["correction"]
                emit({"type": "stream_chunk", "content": "\n\n" + correction})
                full = f"{full}\n\n{correction}"
                from server.services import recap_service
                await recap_service.log_event(
                    conversation_id, "promise_intercept",
                    {"tier": "answer", "pattern": outcome["pattern"],
                     "corrected": outcome["corrected"]},
                    f"空头支票拦截:命中「{outcome['pattern']}」→ "
                    f"{'重合成更正' if outcome['corrected'] else '模板更正'}")
    except Exception as exc:  # noqa: BLE001 — interception is never fatal
        logger.warning("promise interception failed (fail-open, answer kept): %s", exc)
    from arslan.companion.source_links import source_link_footer
    from server.services.task_context import precise_text_request
    footer = ""
    if not precise_text_request(user_message):
        footer = source_link_footer(user_message + "\n" + (attached_context or ""), result.get("tool_trace") or [],
                                    language=await ocr_fallback.current_ui_language())
    if full and footer:
        full += footer
        emit({"type": "stream_chunk", "content": footer})
    # K2: the turn's tool summary rides after the reply in `content` (the model's history);
    # display_content keeps the reply alone. No block for an empty reply: readers fall back to
    # `content` when display_content is empty, and would show it.
    tools_block = turn_tools.block(result.get("tool_trace"), outside=result.get("external_seen") is True) if full else ""
    if tools_block:
        msg_id = await memory.add_message(conversation_id, "arslan", f"{full}\n\n{tools_block}",
                                          display_content=full)
    else:
        msg_id = await memory.add_message(conversation_id, "arslan", full)
    # S3-M3 Task 5 seam choice: the answer turn's usage rides the stream_end the body
    # ALREADY emits (one frame shape for dispatch + answer, no extra answer_usage frame).
    # _handle_answer_body runs inside the host Run's usage_sink.collecting()
    # wrapper, so the collecting contextvars are still open here and detail()/total()
    # read exactly what the Run will persist on exit (no duplicate ledger entry).
    emit({"type": "stream_end", "message_id": msg_id,
          "usage": _usage_frame(usage_sink.detail())})
    return full










































async def _skill_index(limit: int = 80) -> str:
    """One line per registered skill: key — name: what it is for.

    0.1.55: only skills with a body are counted, and in SQL BEFORE the limit. The
    limit used to apply first, so bodyless rows (registered but never usable) took
    the slots: on a fresh install 44 skills had a body and the model saw 31."""
    from sqlalchemy import func

    from server.db.models import SkillPack
    try:
        async with db_session.AsyncSessionLocal() as db:
            rows = (await db.execute(select(SkillPack).where(
                SkillPack.status == "registered", SkillPack.body.is_not(None), SkillPack.enabled.is_not(False),
                func.trim(SkillPack.body) != "").order_by(SkillPack.key).limit(limit))).scalars().all()
    except Exception:  # noqa: BLE001 — a missing index must never break a turn
        return ""
    # Every skill is listed with its name and description (the user's D2(1), 2026-10-30, as Claude Code and
    # Codex do). Only one skill_trust does not read as its own would be listed by its key alone ([a-z0-9-], at
    # most 60, #472 R2); skill_trust is the one place that decides, and states the limit.
    from server.registry import skill_trust
    return "\n".join(f"- {r.key}" if not skill_trust.reads_as_own(r)
                     else f"- {r.key} — {r.name}: {' '.join((r.description or '').split())[:100]}" for r in rows)


# K7 (v0.1.63): the tools every request carries. Everything else `_callable_tools` reaches is found
# with find_tools and called with use_tool, and from the next turn of that conversation it is appended
# to this table (server/orchestrator/on_demand.py). Chosen by 30 days of one user's calls (⓪Plan, Q2):
# run_command 320, web 156, desktop_* 90, memory 47, jobs 29, list_my_capabilities 25, MCP 18,
# ask_user_choice ~12, read_skill 9, browser_open/look 8; update_plan stays for K5's working method.
# To keep a request under 12k characters (the master plan's K7 row; ⓪Plan chose A): attach_file, the
# browser and a job's status and stop are found on demand too. find_tools names them.
# With Hands on, the whole desktop family is resident: a Hands task is one long turn (Q1).
# C3b's demotions (browser back/click/type/select/press, propose_capability) are here.
RESIDENT = frozenset({
    "web_search", "web_extract", "read_file", "list_dir", "search_files", "write_file", "edit_file",
    "run_command", "update_plan", "ask_user_choice", "start_background_work", "recall", "remember",
    "read_skill", "list_my_capabilities"})


def _resident(key: str) -> bool:
    return key in RESIDENT or key.startswith("desktop_")


async def _arslan_tools() -> list[dict]:
    """The tools a request is shown: the resident ones, find_tools and use_tool, then the tools this
    conversation used on demand, in first-use order (marked `appended`: they follow the sorted table)."""
    from server.orchestrator import on_demand
    from server.services import personal_context
    every = await _every_tool()
    shown = [tool for tool in every if _resident(tool["key"])] + [on_demand.FIND_TOOLS, on_demand.USE_TOOL]
    keys = {tool["key"] for tool in shown}
    by_key = {tool["key"]: tool for tool in every}
    context = personal_context.current()
    return shown + [{**by_key[key], "appended": True}
                    for key in on_demand.used(context.conversation_id if context else None)
                    if key in by_key and key not in keys]


async def _callable_tools() -> list[dict]:
    """Every tool this turn may run, shown or not, under the same gates (job, Hands, SSH, MCP)."""
    return await _every_tool()


async def _every_tool() -> list[dict]:
    """Arslan's host-level safe toolset: web + chart + second-brain recall/remember
    (no spawn wiring)."""
    from server.registry import tool, tool_defs
    tools = tool.listed(tool_defs.TOOLS, await tool.read_offer(_skill_index))
    return tools + await _host_mcp_tools()


async def _host_mcp_tools() -> list[dict]:
    """Host MCP tools: SERVER-level consent (user ruling 2026-08-18), and only of servers that are
    ready in THIS process (0.1.61 §B1) — the state is read, never awaited. Ready here means the
    row says `ready` AND the session manager holds a live session for it (`ready_now`), so the
    last run's `ready`, or one whose session died while its restart waits, offers nothing.
    connect is the human act — every discovered tool of a host_allowed server
    rides along; per-tool wire/host_enabled stay the SPAWN dimension's
    vocabulary and no longer gate the host."""
    from server.db.models import MCPServer, Tool
    from server.mcp.supervisor import ready_now
    async with db_session.AsyncSessionLocal() as db:
        allowed = (await db.execute(
            select(MCPServer.id, MCPServer.state).where(MCPServer.host_allowed.is_(True))
        )).all()
        keys = [f"mcp_{sid}" for sid, state in allowed if ready_now(sid, state)]
        if not keys:
            return []
        rows = (await db.execute(
            select(Tool).where(Tool.toolset_key.in_(keys))
            # G1 §3. ORDER BY is load-bearing, not tidiness: these rows become
            # the `tools` array, Anthropic renders tools BEFORE the system prefix
            # that carries the cache breakpoint, so any reordering invalidates
            # the entire cached prefix. An unordered SELECT is not random, it is
            # unspecified — which is worse, because it will look stable in
            # testing and drift on a real database.
            .order_by(Tool.key)
        )).scalars().all()
    # Carry input_schema through so `_native_tool_schemas` (in run_native) hands the model the
    # real JSON Schema captured at MCP discovery — instead of a permissive {} it must guess against.
    return [{"key": t.key, "description": t.description, "input_schema": t.input_schema or {}}
            for t in rows]
