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
_SKILL_BODY_LIMIT = 1500  # max chars of a skill body injected per technique (bounded)

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


_SKILL_BLOCK_LIMIT = 1500   # 约束①: cap of one skill's injected block (header+summary+TOC)


def _skill_toc(body: str) -> list[str]:
    """Markdown ##/### heading lines, in order."""
    return [ln.strip() for ln in body.splitlines() if re.match(r"#{2,3}\s+\S", ln.strip())]


def _skill_technique_block(name: str, body: str, *, has_scripts: bool, key: str) -> str:
    """One skill's injected block. Short skills inline whole; long skills = intro summary +
    a section table-of-contents (## headings only) + a read_skill hint, total length bounded
    by _SKILL_BLOCK_LIMIT. The intro summary is the prose *before the first heading* so the
    injected block never re-dumps section bodies or ### subheadings."""
    body = (body or "").strip()
    header = f"### {name}\n"
    run_hint = (f"\n\n运行本技能脚本: 用 run_python 的 skill_script 参数, 路径 `{key}/<file>.py`。"
                if has_scripts else "")
    whole = header + body + run_hint
    if len(whole) <= _SKILL_BLOCK_LIMIT:
        return whole
    hint = (f"\n\n[本技能正文 {len(body)} 字, 已省略。用 read_skill(key='{key}') 读全文, "
            f"或 read_skill(key='{key}', section='## 标题') 读某章。]" + run_hint)
    toc_all = _skill_toc(body)
    h2 = [t for t in toc_all if t.startswith("## ")]
    toc_lines = list(h2)
    if len(h2) < len(toc_all):  # deeper (###) sections omitted → point at read_skill
        toc_lines.append("(更细章节见 read_skill)")
    m = re.search(r"(?m)^#{2,3}\s+\S", body)
    intro = (body[:m.start()] if m else body).strip()

    def _assemble(lines: list[str]) -> str:
        toc = ("\n目录:\n" + "\n".join(f"- {t}" for t in lines)) if lines else ""
        budget = _SKILL_BLOCK_LIMIT - len(header) - len(toc) - len(hint)
        summary = intro[:max(0, budget)].rsplit("\n", 1)[0] if budget > 0 else ""
        return header + summary + toc + hint

    block = _assemble(toc_lines)
    if len(block) > _SKILL_BLOCK_LIMIT:  # too many ## headings → truncate the TOC too
        block = _assemble(h2[:10] + ["(更多章节见 read_skill)"])
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
    for t in wired:
        lines.append(f"- TOOL {t['key']} (live): {t['description']}")
    for ts in equipment["toolsets"]:
        if ts["status"] != "wired" or ts["key"] not in wired_keys:
            lines.append(f"- {ts['name']} (not yet live)")
    technique_blocks: list[str] = []
    for sk in equipment["skills"]:
        body = (skill_bodies.get(sk["key"]) or "").strip()
        if body:
            technique_blocks.append(
                _skill_technique_block(sk["name"], body,
                                       has_scripts=bool(sk.get("has_scripts")), key=sk["key"]))
        else:
            lines.append(f"- TECHNIQUE {sk['name']}: {sk['description']}")
    lines.append(
        "You have NO other tools. If you lack a capability or data, escalate a need "
        "(see protocol); never ask the user to run things and never pretend to have "
        "other tools."
    )
    block = "\n\nYour equipment:\n" + "\n".join(lines)
    if technique_blocks:
        block += "\n\nYour techniques:\n" + "\n\n".join(technique_blocks)
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
                             system_prompt_override: str | None = None) -> tuple[str, list[dict]]:
    """Full spawn system prompt (base + anti-fab + facts + evolution + KB + attached +
    equipment block + tool guidance) + the live wired tools. Shared by dispatch() and /ws/chat."""
    from server.services import evolution_service
    from server.services import knowledge as _knowledge

    facts = await memory.facts_text()
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
    suffix = evolution_service.prompt_suffix(spawn.name)
    if suffix:
        system = f"{system}\n\n{suffix}"
    _kb_sources = None
    try:
        # used_ref=None: build_spawn_system has no conversation_id in scope; usage
        # count still accrues per material hit, the "最近用于" ref is filled by the
        # Arslan direct-chat path which does carry conversation_id.
        _kb = await _knowledge.retrieve_scoped(retrieval_query, spawn_id=spawn.id, used_ref=None)
        system += _knowledge.knowledge_block(_kb)
        _kb_sources = [src for src, _ in _kb] or None
    except Exception as exc:  # noqa: BLE001
        logger.warning("knowledge retrieve failed (non-fatal): %s", exc)
    if attached_context:
        system += f"\n\n[用户附带的临时材料]\n{attached_context}"
    equipment = await registry_service.equipment_for_spawn(spawn.id)
    wired = await registry_service.wired_tools_for_spawn(spawn.id, current_turn=current_turn)
    skill_body_map = await registry_service.skill_bodies([s["key"] for s in equipment["skills"]])
    system += _equipment_block_from(equipment, wired, skill_body_map)
    system += await _mcp_health_advisory(wired)
    system += _SPAWN_TOOL_GUIDANCE

    from server.orchestrator import run_trace
    run_trace.record_prompt(system_prompt=system, injected_kb=None, injected_kb_sources=_kb_sources)

    return system, wired


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
) -> dict:
    """Run the spawn on a clean task. Streams via on_chunk; returns
    {full_output, spawn_name, summary_message_id, assistant_message_id, escalation,
    artifact}.

    run_id (when the caller records the turn as a Run) enables the HTML deliverable
    channel (HX-2, B1/B3): a full/truncated `<!DOCTYPE html>` final output is stored
    on disk and the persisted display_content becomes a one-line summary + download
    link; `artifact` carries {kind:"html", ...} for the WS frame, else None.

    When prior_output+instruction are given, runs a refinement of a previous result.
    on_event receives tool_call/tool_result dicts from the loop (equipped spawns only).
    escalation is None for normal completions; a dict for escalating spawns.

    Design: current_turn and wired are computed once here and shared between the
    equipment block builder and the spawn_loop call, avoiding duplicate DB queries.
    Equipment is fetched first (cheap); wired is skipped entirely for unequipped
    spawns (zero-tool path uses legacy chat_stream, byte-identical to pre-loop).
    """
    spawn = await _load_spawn(spawn_id)
    if spawn is None:
        raise ValueError(f"spawn {spawn_id} not found")

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

    full = ""
    escalation = None

    if wired:
        # Equipped path: bounded tool loop (JSON protocol, gate-per-call).
        out_loop = await spawn_loop.run(
            spawn_id=spawn_id,
            system=system,
            user_content=user_content,
            history=history,
            current_turn=current_turn,
            emit=(on_event or (lambda e: None)),
            on_chunk=(on_chunk or (lambda c: None)),
            allow_escalation=allow_escalation,
            conversation_id=conversation_id,
        )
        full = out_loop["final"] or ""
        escalation = out_loop["escalation"]
    else:
        # Legacy path: plain chat_stream (byte-identical to pre-loop behavior for
        # zero-wired-tool spawns, including spawns with only unwired/non-wired equipment).
        adapter = _get_adapter()
        a = await adapter if hasattr(adapter, "__await__") else adapter
        async for piece in a.chat_stream(system, user_content, history=history):
            full += piece
            if on_chunk is not None:
                on_chunk(piece)

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
