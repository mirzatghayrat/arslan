"""Layer 2: dispatch a clean task_brief to a spawn; persist display + memory separately."""
from __future__ import annotations

import logging
import re
from collections.abc import Callable

from sqlalchemy import select

from server.db import session as db_session
from server.db.models import ChatMessage, MCPServer, Spawn
from server.orchestrator import memory, spawn_loop
from server.registry import service as registry_service
from server.services.llm_factory import build_adapter

logger = logging.getLogger(__name__)

_SPAWN_HISTORY_LIMIT = 10  # recent spawn turns included for continuity

_SPAWN_TOOL_GUIDANCE = (
    "\n\nUSE YOUR TOOLS — do not narrate or fabricate:\n"
    "- You have the tools listed under 'Your equipment' (and you can chart with render_chart). "
    "When you need fresh/factual data you are not certain of (prices, news, a repo's stars, recent "
    "events), you MUST actually CALL web_search by emitting the tool-call JSON — NEVER write 'STEP 1: "
    "call web_search' or '调用 web_search' as plain text; that does nothing.\n"
    "- When the user asks for a chart/graph/图, CALL render_chart with the structured data so a real "
    "chart is drawn. Pick the type that fits: line|bar|area|pie|scatter|radar|funnel|gauge|heatmap "
    "(args: {type, x:[labels], series:[{name, values:[numbers]}]}; optional stacked/horizontal/smooth; "
    "heatmap also needs y:[row labels]). NEVER return matplotlib/Python code or a data table instead "
    "of the chart, and NEVER draw a chart as a Markdown code block (```mermaid xychart-beta / "
    "```mermaid pie / ```chart) — those show to the user as raw code, NOT a chart; only render_chart "
    "draws a real chart. And NEVER invent 'simulated'/'模拟' data to fill it — get the real numbers via "
    "web_search first, then render_chart.\n"
    "- ACT in THIS reply: emit the tool call now, or give your final answer. A promise to use a tool, "
    "or code for the user to run, is not acceptable. Writing '我来搜索…' / '我获取到了数据' / "
    "'上图已为您生成' WITHOUT actually emitting the tool JSON is a HALLUCINATION — the tool did NOT run "
    "and there is NO chart. Never describe a tool result you did not actually receive.\n"
    "- If you genuinely lack a tool needed for the task, escalate a need (see protocol) — do not "
    "fabricate a result.\n"
    "- When the user asks to turn a repeatable method into a reusable skill, CALL create_skill with a "
    "proper SKILL.md body (frontmatter name/description + '## Trigger' + decision rules) — it creates a "
    "CANDIDATE (observation → eval → human confirm), never a live skill directly.\n"
    "WORKED EXAMPLE — user: '查特斯拉近一周股价,用折线图画出来'. Your replies, one tool per turn, "
    "each reply being ONLY the JSON (no prose):\n"
    "  turn 1 → {\"tool\": \"web_search\", \"args\": {\"query\": \"Tesla TSLA stock price past week\"}}\n"
    "  turn 2 (after the TOOL RESULT) → {\"tool\": \"render_chart\", \"args\": {\"type\": \"line\", "
    "\"title\": \"TSLA 近一周\", \"x\": [\"6/20\",\"6/23\",\"6/24\"], \"series\": [{\"name\": \"close\", "
    "\"values\": [305.1, 312.4, 309.8]}]}}\n"
    "  turn 3 → your short final text answer. Follow this shape exactly for any 'search + chart' task."
)

_PROPOSE_PREFIX = (
    "PROPOSE MODE: Do NOT produce the final deliverable yet. First propose a concrete "
    "direction for this task and ask 1-3 short clarifying questions, then ask the user to "
    "confirm before you execute. Keep it brief. Respond in the user's language.\n\nTask:\n"
)

_EXECUTE_CONFIRMED_PREFIX = (
    "EXECUTE MODE: The user has CONFIRMED the direction you proposed. Deliver the complete, "
    "final result now. Do NOT ask further questions and do NOT re-propose — produce the "
    "deliverable. Your tool budget is FRESH this turn — earlier exhaustion (yours or in the "
    "history) does NOT apply now; use your tools. Respond in the user's language.\n\nTask:\n"
)


def _frame_brief(task_brief: str, *, mode: str = "execute", proposed_direction: str | None = None) -> str:
    if mode == "propose":
        return f"{_PROPOSE_PREFIX}{task_brief}"
    if mode == "execute_confirmed":
        carried = f"\n\nThe direction you proposed (now confirmed):\n{proposed_direction}" if proposed_direction else ""
        return f"{_EXECUTE_CONFIRMED_PREFIX}{task_brief}{carried}"
    return task_brief


def _get_adapter():
    """Indirection so tests can stub adapter construction."""
    return build_adapter(role="execute")


async def _load_spawn(spawn_id: int) -> Spawn | None:
    async with db_session.AsyncSessionLocal() as db:
        return await db.get(Spawn, spawn_id)


async def get_spawn_name(spawn_id: int) -> str | None:
    """Resolve a spawn's name (used to caption the routing frame before streaming)."""
    spawn = await _load_spawn(spawn_id)
    return spawn.name if spawn else None


async def last_spawn_output(spawn_id: int) -> str | None:
    """The spawn's most recent assistant output (e.g. the direction it proposed)."""
    async with db_session.AsyncSessionLocal() as db:
        row = await db.execute(
            select(ChatMessage.content)
            .where(ChatMessage.spawn_id == spawn_id, ChatMessage.role == "assistant")
            .order_by(ChatMessage.id.desc())
            .limit(1)
        )
        return row.scalar_one_or_none()


async def _spawn_history(spawn_id: int) -> list[dict]:
    async with db_session.AsyncSessionLocal() as db:
        rows = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.spawn_id == spawn_id)
            .order_by(ChatMessage.id.desc())
            .limit(_SPAWN_HISTORY_LIMIT)
        )
        msgs = list(reversed(rows.scalars().all()))
    return [{"role": m.role, "content": m.content} for m in msgs]


_SKILL_BLOCK_LIMIT = 2000   # 约束①: cap of one skill's injected block (header+summary+TOC)

# PC-4: single anti-fabrication line prepended ONCE above the per-skill technique blocks.
_TECHNIQUE_HONESTY_PREAMBLE = (
    "技法说明:以下技能正文可能是摘要。引用的脚本/文件若不在你的工具清单内,不得假装执行或编造其输出;"
    "若已装备 read_skill/run_python(Code Sandbox 工具集)可读全文或跑脚本,没有就如实说明,不要虚构结果。"
)


def _skill_toc(body: str) -> list[str]:
    """Markdown ##/### heading lines, in order."""
    return [ln.strip() for ln in body.splitlines() if re.match(r"#{2,3}\s+\S", ln.strip())]


def _skill_technique_block(name: str, body: str, *, has_scripts: bool, key: str,
                           read_skill_available: bool = False,
                           run_python_available: bool = False) -> str:
    """One skill's injected block. Short skills inline whole; long skills = intro summary +
    a section table-of-contents (## headings only) + (when read_skill is wired) a read_skill
    hint, total length bounded by _SKILL_BLOCK_LIMIT.

    PC compat fix: read_skill / run_python live ONLY in the code_sandbox toolset, so a spawn
    can be equipped with a skill WITHOUT them. We emit those hints ONLY when the spawn actually
    has the tool wired; otherwise we fall back to honest wording that never points the spawn at
    a tool it cannot call. The intro summary is the prose *before the first heading* so the
    injected block never re-dumps section bodies or ### subheadings."""
    body = (body or "").strip()
    header = f"### {name}\n"
    if has_scripts and run_python_available:
        run_hint = f"\n\n运行本技能脚本: 用 run_python 的 skill_script 参数, 路径 `{key}/<file>.py`。"
    elif has_scripts:
        run_hint = "\n\n(本技能附带脚本, 跑脚本需装备 Code Sandbox 工具集)"
    else:
        run_hint = ""
    whole = header + body + run_hint
    if len(whole) <= _SKILL_BLOCK_LIMIT:
        return whole
    if read_skill_available:
        hint = (f"\n\n[本技能正文 {len(body)} 字, 已省略。用 read_skill(key='{key}') 读全文, "
                f"或 read_skill(key='{key}', section='## 标题') 读某章。]" + run_hint)
        more = "read_skill"
    else:
        # No read_skill wired → never point at it; be honest the full text isn't reachable.
        hint = (f"\n\n[本技能正文 {len(body)} 字, 此处为摘要+目录;读全文需装备 Code Sandbox 工具集]"
                + run_hint)
        more = None
    toc_all = _skill_toc(body)
    h2 = [t for t in toc_all if t.startswith("## ")]
    toc_lines = list(h2)
    if len(h2) < len(toc_all):  # deeper (###) sections omitted
        toc_lines.append(f"(更细章节见 {more})" if more else "(更细章节略)")
    m = re.search(r"(?m)^#{2,3}\s+\S", body)
    intro = (body[:m.start()] if m else body).strip()

    def _assemble(lines: list[str]) -> str:
        toc = ("\n目录:\n" + "\n".join(f"- {t}" for t in lines)) if lines else ""
        budget = _SKILL_BLOCK_LIMIT - len(header) - len(toc) - len(hint)
        summary = intro[:max(0, budget)].rsplit("\n", 1)[0] if budget > 0 else ""
        return header + summary + toc + hint

    block = _assemble(toc_lines)
    if len(block) > _SKILL_BLOCK_LIMIT:  # too many ## headings → truncate the TOC too
        overflow = f"(更多章节见 {more})" if more else "(更多章节略)"
        block = _assemble(h2[:10] + [overflow])
    return block[:_SKILL_BLOCK_LIMIT]


def _equipment_block_from(equipment: dict, wired: list[dict], skill_bodies: dict[str, str | None] | None = None) -> str:
    """Build the equipment section given precomputed equipment + wired tool dicts.

    Design note: called from dispatch() which already holds both values (computed
    once) so we avoid a duplicate wired_tools_for_spawn query. Unequipped spawns
    never reach here — dispatch() skips the call when equipment is empty.
    """
    skill_bodies = skill_bodies or {}
    lines: list[str] = []
    wired_keys = {t["key"] for t in wired}
    # read_skill / run_python are the two tools in the code_sandbox toolset; a spawn only has
    # them if that toolset is wired. Gate the read_skill/run_python skill hints on their real
    # presence so we never point a spawn at a tool it cannot call (PC compat fix).
    read_skill_available = "read_skill" in wired_keys
    run_python_available = "run_python" in wired_keys
    for t in wired:
        lines.append(f"- TOOL {t['key']} (live): {t['description']}")
    for ts in equipment["toolsets"]:
        # A toolset is live iff its own status is "wired" — that is the same liveness signal
        # the TOOL lines above use (Tool.status == "wired"). Do NOT cross-check ts["key"]
        # against wired_keys: wired_keys holds individual TOOL keys (e.g. "render_chart"),
        # while ts["key"] is a TOOLSET key (e.g. "charting") — never a member — so that clause
        # was always true and wrongly stamped every live toolset "(not yet live)".
        if ts["status"] != "wired":
            lines.append(f"- {ts['name']} (not yet live)")
    technique_blocks: list[str] = []
    for sk in equipment["skills"]:
        body = (skill_bodies.get(sk["key"]) or "").strip()
        if body:
            technique_blocks.append(
                _skill_technique_block(sk["name"], body,
                                       has_scripts=bool(sk.get("has_scripts")), key=sk["key"],
                                       read_skill_available=read_skill_available,
                                       run_python_available=run_python_available))
        else:
            lines.append(f"- TECHNIQUE {sk['name']}: {sk['description']}")
    lines.append(
        "You have NO other tools. If you lack a capability or data, escalate a need "
        "(see protocol); never ask the user to run things and never pretend to have "
        "other tools."
    )
    block = "\n\nYour equipment:\n" + "\n".join(lines)
    if technique_blocks:
        # PC-4 (承接 HX 轮 fabrication 护栏): ONE honesty preamble at the top of the
        # techniques section — injected skill bodies may be summaries, and any referenced
        # script/file not in the live tool list must never be faked or its output invented.
        block += "\n\nYour techniques:\n" + _TECHNIQUE_HONESTY_PREAMBLE + "\n\n" + \
            "\n\n".join(technique_blocks)
    return block


async def _mcp_health_advisory(wired: list[dict]) -> str:
    """PB-4: one advisory line when any wired mcp_* tool belongs to a server whose last
    health probe failed — steers the spawn toward builtin equivalents up front instead of
    letting it burn a turn on a known-bad server. Fail-open: any lookup error → no line."""
    try:
        by_server: dict[int, list[str]] = {}
        for t in wired:
            key = t.get("key") or ""
            if not key.startswith("mcp_"):
                continue
            try:
                sid = int(key.split("__", 1)[0].split("_", 1)[1])   # mcp_{sid}__{name}
            except (ValueError, IndexError):
                continue
            by_server.setdefault(sid, []).append(key)
        if not by_server:
            return ""
        async with db_session.AsyncSessionLocal() as db:
            failing_ids = {r[0] for r in (await db.execute(
                select(MCPServer.id).where(MCPServer.id.in_(by_server),
                                           MCPServer.health_status == "failing")
            )).all()}
        failing_keys = sorted(k for sid in failing_ids for k in by_server[sid])
        if not failing_keys:
            return ""
        return (f"\n\n注意:MCP 工具 {', '.join(failing_keys)} 所属服务最近体检失败,"
                "优先使用等价内置工具。")
    except Exception as exc:  # noqa: BLE001 — advisory is best-effort, never blocks dispatch
        logger.warning("mcp health advisory lookup failed (non-fatal): %s", exc)
        return ""


async def build_spawn_system(spawn, *, retrieval_query: str, current_turn: int,
                             attached_context: str | None = None,
                             system_prompt_override: str | None = None,
                             replay: bool = False,
                             ambient: dict | None = None) -> tuple[str, list[dict]]:
    """Full spawn system prompt (base + anti-fab + facts + evolution + KB + attached +
    equipment block + tool guidance) + the live wired tools. Shared by dispatch() and /ws/chat().

    replay=True (S2 E3 hermetic replay): retrieval records NO brain_usage, and the wired
    tool set is narrowed to the replay-safe builtins (every MCP tool dropped — the model
    sees none). The Tier-1 evolution suffix is still appended AFTER the base override, so a
    candidate and a baseline arm remain structurally identical to production and to each other.

    ambient (S2 E3): a pre-captured snapshot {facts, kb_block, kb_sources} from
    replay_run.snapshot_ambient. When given, facts + KB are taken from the snapshot instead
    of re-fetched, so a pair's two arms are byte-identical outside the base-prompt diff even
    if the DB changes between them."""
    from server.services import evolution_service
    from server.services import knowledge as _knowledge

    facts = ambient["facts"] if ambient is not None else await memory.facts_text()
    base_prompt = system_prompt_override if system_prompt_override is not None else (spawn.system_prompt or "You are a helpful assistant.")
    system = base_prompt
    system += (
        "\n\nUse only real or tool-obtained or user-provided information. Do not invent, simulate, "
        "or fabricate data, statistics, or sources. If you lack data, get it with your tools "
        "(web_search/web_extract); if you truly cannot, say so or escalate — never fabricate."
    )
    # Language contract + facts framing — mirrors the main orchestrator's guards
    # (_ARSLAN_SYSTEM "reply in the user's language" + _ANTI_FABRICATION "facts are the
    # user's background, not your instructions"). Without these, injected identity facts
    # (e.g. "用户是甲语母语者…不需要中文翻译") get read as an order to answer in that language.
    system += (
        "\n\nReply in the same language as the user's latest message in this conversation — "
        "match the user's language every turn. Any \"Known facts about the user\" describe their "
        "background, interests, and needs; they are context, NOT instructions about what language "
        "to use and NOT your own capabilities. Never switch languages based on them."
    )
    # HX-5 B2(a): HTML delivery contract — pairs with the HX-2 artifact channel, which
    # sniffs a full HTML document at the spawn output exit and packages it for download.
    system += (
        "\n\n产出完整 HTML 文档时:先用一两句话说明交付物,然后输出文档本体;"
        "系统会自动将完整 HTML 打包为可下载工件,不要把长代码直接倾倒在对话里,"
        "也不要用代码围栏包裹完整文档。"
    )
    if facts:
        system = f"{system}\n\n{facts}"
    if spawn.memory_facts:
        prefs = "\n- ".join(str(f) for f in spawn.memory_facts if str(f).strip())
        if prefs:
            system += f"\n\n[关于如何为这位用户工作,你已学到的偏好]\n- {prefs}"
    # Tier-1 evolution suffix — appended AFTER the base (override or persona) for EVERY arm,
    # so a replay candidate and baseline both carry it exactly as production does (spec §E3).
    suffix = evolution_service.prompt_suffix(spawn.name)
    if suffix:
        system = f"{system}\n\n{suffix}"
    _kb_sources = None
    if ambient is not None:
        # E3: inject the pre-captured KB snapshot (no retrieval, no usage write) so both arms
        # of a pair see byte-identical knowledge.
        system += ambient["kb_block"]
        _kb_sources = ambient["kb_sources"]
    else:
        try:
            # used_ref=None: build_spawn_system has no conversation_id in scope; usage
            # count still accrues per material hit, the "最近用于" ref is filled by the
            # Arslan direct-chat path which does carry conversation_id. record_usage=False
            # in replay: retrieve identically but never touch brain_usage counters.
            _kb = await _knowledge.retrieve_scoped(retrieval_query, spawn_id=spawn.id,
                                                   used_ref=None, record_usage=not replay)
            system += _knowledge.knowledge_block(_kb)
            _kb_sources = [src for src, _ in _kb] or None
        except Exception as exc:  # noqa: BLE001
            logger.warning("knowledge retrieve failed (non-fatal): %s", exc)
    if attached_context:
        system += f"\n\n[用户附带的临时材料]\n{attached_context}"
    equipment = await registry_service.equipment_for_spawn(spawn.id)
    wired = await registry_service.wired_tools_for_spawn(spawn.id, current_turn=current_turn)
    if replay:
        # Narrow to replay-safe builtins: the model must neither SEE nor be able to invoke an
        # MCP (or other side-effecting) tool inside a hermetic replay.
        from server.services.replay_safety import filter_replay_tools
        wired = filter_replay_tools(wired)
    skill_body_map = await registry_service.skill_bodies([s["key"] for s in equipment["skills"]])
    system += _equipment_block_from(equipment, wired, skill_body_map)
    system += await _mcp_health_advisory(wired)
    system += _SPAWN_TOOL_GUIDANCE

    from server.orchestrator import run_trace
    run_trace.record_prompt(system_prompt=system, injected_kb=None, injected_kb_sources=_kb_sources)

    return system, wired


async def _apply_zero_tool_honesty(
    full: str, spawn_name: str | None, conversation_id: str,
    on_chunk: Callable[[str], None] | None, *, log_events: bool = True,
) -> str:
    """S0: run the zero-tool spawn's final answer through the shared honesty pass. On a
    fabrication hit, append the bounded honest correction (streamed live via on_chunk +
    returned so it persists) and log a promise_intercept(tier=zero_tool) audit event.
    Fail-open: any error keeps the original answer and the turn survives.

    log_events=False (S2 E3 hermetic replay): the guard STILL runs and the correction is
    STILL applied to the output — only the ConversationEvent audit write is skipped."""
    if not full:
        return full
    try:
        from server.orchestrator import promise_guard
        outcome = await promise_guard.correct_zero_tool(full, spawn_name=spawn_name)
        if outcome is not None:
            correction = outcome["correction"]
            if on_chunk is not None:
                on_chunk("\n\n" + correction)
            full = f"{full}\n\n{correction}"
            if not log_events:
                return full  # replay: correction applied, audit event suppressed
            try:
                from server.services import recap_service
                await recap_service.log_event(
                    conversation_id, "promise_intercept",
                    {"tier": "zero_tool", "pattern": outcome["pattern"],
                     "corrected": outcome["corrected"]},
                    f"零工具分身空头支票拦截:命中「{outcome['pattern']}」→ "
                    f"{'重合成更正' if outcome['corrected'] else '模板更正'}")
            except Exception:  # noqa: BLE001 — audit is best-effort
                pass
    except Exception as exc:  # noqa: BLE001 — honesty pass never breaks the turn
        logger.warning("zero-tool honesty pass failed (fail-open, answer kept): %s", exc)
    return full


async def _run_model(
    spawn, system: str, wired: list[dict], user_content: str, history: list[dict],
    current_turn: int, conversation_id: str,
    on_chunk: Callable[[str], None] | None, emit: Callable[[dict], None] | None,
    allow_escalation: bool, *, replay: bool = False,
) -> tuple[str, dict | None]:
    """Run the spawn's model turn and return (full_output, escalation). Shared by the live
    and replay dispatch paths so replay reuses the EXACT equipped/zero-tool branching (only
    the replay flags differ). Returns escalation=None for the zero-tool path."""
    if wired:
        # Equipped path: bounded native tool loop (gate-per-call).
        out_loop = await spawn_loop.run(
            spawn_id=spawn.id,
            system=system,
            user_content=user_content,
            history=history,
            current_turn=current_turn,
            emit=(emit or (lambda e: None)),
            on_chunk=(on_chunk or (lambda c: None)),
            allow_escalation=allow_escalation,
            conversation_id=conversation_id,
            replay=replay,
        )
        return out_loop["final"] or "", out_loop["escalation"]
    # Zero-tool path: plain chat_stream (a persona-only spawn has no wired tools, so it
    # cannot run the native tool-loop). It still streams live, but its FINAL answer is run
    # through the SAME honesty detectors the equipped/answer paths use — closing the S0 gap
    # where a tool-less spawn could fabricate "已生成PPT并交付" / "正在生成中,稍等" unchecked.
    adapter = _get_adapter()
    a = await adapter if hasattr(adapter, "__await__") else adapter
    full = ""
    async for piece in a.chat_stream(system, user_content, history=history):
        full += piece
        if on_chunk is not None:
            on_chunk(piece)
    full = await _apply_zero_tool_honesty(full, spawn.name, conversation_id, on_chunk,
                                          log_events=not replay)
    return full, None


async def _dispatch_replay(
    conversation_id: str, *, spawn, task_brief: str,
    on_chunk: Callable[[str], None] | None, on_event: Callable[[dict], None] | None,
    prior_output: str | None, instruction: str | None, allow_escalation: bool,
    mode: str, system_prompt_override: str | None, attached_context: str | None,
    ambient: dict | None,
) -> dict:
    """Hermetic replay dispatch (S2 E3). Owns the replay Run end-to-end: create the
    kind='replay' recorder, scope usage/trace collection, run the model with the replay
    flags (no brain_usage, no MCP tools, no ConversationEvent, no persisted artifact),
    finalize to status='replayed' with the output persisted, and return result['run_id'].
    Never persists ChatMessage/ArslanMessage. Reused by evaluator/replay_run/skill_forge."""
    from arslan.llm import usage_sink
    from server.orchestrator import run_trace
    from server.services.run_recorder import RunRecorder

    recorder = await RunRecorder.start(
        conversation_id=conversation_id, spawn_id=spawn.id, spawn_name=spawn.name,
        user_message=task_brief, kind="replay")
    emit = recorder.tee(on_event or (lambda e: None))

    full = ""
    escalation: dict | None = None
    # usage_sink + run_trace scoped HERE (replay callers dispatch directly, not via the
    # orchestrator), so the replay Run captures its own model/provider/tokens + full tool
    # trace + assembled system prompt (drained inside finalize before this context exits).
    with usage_sink.collecting(), run_trace.collecting():
        try:
            current_turn = await memory.user_turn_count(conversation_id)
            system, wired = await build_spawn_system(
                spawn, retrieval_query=task_brief, current_turn=current_turn,
                attached_context=attached_context,
                system_prompt_override=system_prompt_override,
                replay=True, ambient=ambient)
            history = await _spawn_history(spawn.id)
            if instruction:
                user_content = (
                    f"{task_brief}\n\nYour previous result:\n{prior_output or ''}\n\n"
                    f"Apply this refinement and return the full revised result:\n{instruction}")
            else:
                user_content = _frame_brief(task_brief, mode=mode, proposed_direction=prior_output)
            # stream_start opens the dispatch step; finalize's fallback closes it (no spawn_meta).
            emit({"type": "stream_start", "source": "spawn", "spawn_id": spawn.id})
            full, escalation = await _run_model(
                spawn, system, wired, user_content, history, current_turn, conversation_id,
                on_chunk, emit, allow_escalation, replay=True)
        except Exception as exc:  # noqa: BLE001 — record the failed replay Run, then re-raise
            _usage = usage_sink.detail()
            _prompt = run_trace.prompt()
            await recorder.finalize(
                replay=True, summary_message_id=None, full_output="",
                model=_usage["model"], provider=_usage["provider"],
                tokens_in=_usage["tokens_in"], tokens_out=_usage["tokens_out"],
                tokens_estimated=(_usage["tokens_in"] is None),
                error_kind=type(exc).__name__, error_text=str(exc),
                system_prompt=_prompt["system_prompt"], injected_kb=_prompt["injected_kb"],
                injected_kb_sources=_prompt.get("injected_kb_sources"))
            raise
        # Deliberately DO NOT call html_artifact.package_spawn_output with a real run_id: a
        # replay writes no HTML file / no downloadable Run-linked artifact (deck returns base64
        # in-memory; nothing lands on disk).
        _usage = usage_sink.detail()
        _prompt = run_trace.prompt()
        await recorder.finalize(
            replay=True, summary_message_id=None, full_output=full,
            model=_usage["model"], provider=_usage["provider"],
            tokens_in=_usage["tokens_in"], tokens_out=_usage["tokens_out"],
            tokens_estimated=(_usage["tokens_in"] is None),
            system_prompt=_prompt["system_prompt"], injected_kb=_prompt["injected_kb"],
            injected_kb_sources=_prompt.get("injected_kb_sources"))
    return {
        "full_output": full,
        "spawn_name": spawn.name,
        "summary_message_id": None,
        "assistant_message_id": None,
        "escalation": escalation,
        "artifact": None,
        "run_id": recorder.run_id,
    }


async def dispatch(
    conversation_id: str,
    *,
    spawn_id: int,
    task_brief: str,
    on_chunk: Callable[[str], None] | None = None,
    on_event: Callable[[dict], None] | None = None,
    prior_output: str | None = None,
    instruction: str | None = None,
    allow_escalation: bool = True,
    mode: str = "execute",
    system_prompt_override: str | None = None,
    persist: bool = True,
    attached_context: str | None = None,
    run_id: int | None = None,
    replay: bool = False,
    ambient: dict | None = None,
) -> dict:
    """Run the spawn on a clean task. Streams via on_chunk; returns
    {full_output, spawn_name, summary_message_id, assistant_message_id, escalation,
    artifact} (replay adds run_id).

    run_id (when the caller records the turn as a Run) enables the HTML deliverable
    channel (HX-2, B1/B3): a full/truncated `<!DOCTYPE html>` final output is stored
    on disk and the persisted display_content becomes a one-line summary + download
    link; `artifact` carries {kind:"html", ...} for the WS frame, else None.

    When prior_output+instruction are given, runs a refinement of a previous result.
    on_event receives tool_call/tool_result dicts from the loop (equipped spawns only).
    escalation is None for normal completions; a dict for escalating spawns.

    replay=True (S2 E3 hermetic replay): the axis is SEPARATE from `mode` (which is the
    execute/propose framing). A replay runs the spawn WITHOUT touching real state — no
    brain_usage, no ConversationEvent (honesty guards still execute), no MCP tools, no
    persistent artifact, persist forced off — but DOES record a `kind='replay'` Run
    (status='replayed', final_output set, full trace) that this call owns end-to-end and
    whose id it returns as result["run_id"]. `ambient` is the per-pair snapshot shared by
    both arms (see build_spawn_system / replay_run.snapshot_ambient).

    No-override hermetic rule (eval sealing): a dispatch is hermetic iff `replay=True` OR
    `is_hermetic_context(conversation_id)`. An eval-sentinel conversation_id is ALWAYS
    sealed — `replay=False` cannot override it (a safety control is no-override, and the
    throat keys off conversation_id anyway); `replay=True` remains an explicit-hardening
    path for any other conversation_id.

    Design: current_turn and wired are computed once here and shared between the
    equipment block builder and the spawn_loop call, avoiding duplicate DB queries.
    Equipment is fetched first (cheap); wired is skipped entirely for unequipped
    spawns (zero-tool path uses legacy chat_stream, byte-identical to pre-loop).
    """
    spawn = await _load_spawn(spawn_id)
    if spawn is None:
        raise ValueError(f"spawn {spawn_id} not found")

    # No-override hermetic rule (eval sealing): an evolution eval/replay conversation_id is
    # ALWAYS sealed — replay=False cannot opt out (a safety control is no-override, and the
    # throat keys off conversation_id anyway). replay=True stays an explicit-hardening path.
    from server.services.replay_safety import is_hermetic_context
    if replay or is_hermetic_context(conversation_id):
        return await _dispatch_replay(
            conversation_id, spawn=spawn, task_brief=task_brief, on_chunk=on_chunk,
            on_event=on_event, prior_output=prior_output, instruction=instruction,
            allow_escalation=allow_escalation, mode=mode,
            system_prompt_override=system_prompt_override,
            attached_context=attached_context, ambient=ambient,
        )

    current_turn = await memory.user_turn_count(conversation_id)
    system, wired = await build_spawn_system(
        spawn, retrieval_query=task_brief, current_turn=current_turn,
        attached_context=attached_context, system_prompt_override=system_prompt_override,
    )

    history = await _spawn_history(spawn_id)

    if instruction:
        user_content = (
            f"{task_brief}\n\nYour previous result:\n{prior_output or ''}\n\n"
            f"Apply this refinement and return the full revised result:\n{instruction}"
        )
    else:
        # In execute_confirmed mode, prior_output carries the spawn's proposed direction.
        user_content = _frame_brief(task_brief, mode=mode, proposed_direction=prior_output)

    full, escalation = await _run_model(
        spawn, system, wired, user_content, history, current_turn, conversation_id,
        on_chunk, on_event, allow_escalation,
    )

    # HX-2 (B1/B3): sniff the final output for a full/truncated HTML document at THIS
    # exit — every dispatched spawn passes through here, so the channel is universal.
    # Fail-open inside package_spawn_output: any error → raw text, the turn survives.
    display = full
    artifact = None
    if not escalation:
        from server.services import html_artifact
        display, artifact = html_artifact.package_spawn_output(run_id, full)

    assistant_message_id = None
    summary_id = None
    if persist:
        # Scope 2: spawn's own memory — capture the assistant row id for feedback wiring.
        spawn_content = f"[escalation] {escalation['need']}" if escalation else full
        async with db_session.AsyncSessionLocal() as db:
            db.add(ChatMessage(spawn_id=spawn_id, role="user", content=user_content))
            assistant_row = ChatMessage(spawn_id=spawn_id, role="assistant", content=spawn_content)
            db.add(assistant_row)
            await db.commit()
            await db.refresh(assistant_row)
            assistant_message_id = assistant_row.id

        # Scope 1: Arslan memory — DISPLAY (full) vs MEMORY (1-line, deterministic — no extra LLM call)
        if escalation:
            summary = f"[{spawn.name}] escalated: {escalation['need']}"
        else:
            summary = f"[{spawn.name}] {task_brief} -> delivered"
        summary_id = await memory.add_message(
            conversation_id,
            "spawn_summary",
            summary,
            display_content=display,
            spawn_id=spawn_id,
        )
    return {
        "full_output": full,
        "spawn_name": spawn.name,
        "summary_message_id": summary_id,
        "assistant_message_id": assistant_message_id,
        "escalation": escalation,
        "artifact": artifact,
    }
