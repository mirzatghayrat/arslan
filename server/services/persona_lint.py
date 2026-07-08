"""Persona-vs-equipment delivery lint (HX-6 / spec P2).

Deterministic, ADVISORY-ONLY check run at spawn create / suggest_update time: when the
persona text promises a delivery FORMAT, verify the spawn's equipped tools + system
artifact channels can actually deliver it. Mismatches come back as human-readable
`capability_warnings` attached to the response frame — never a hard reject.

Prevents the Deck-Master class of bug: a persona promising "single-file HTML
presentation by default" while the product had no HTML artifact channel (until HX-2)
— i.e. "人设写了产品没有的能力".

Channel map (case-insensitive, CJK + EN detectors):
- HTML          → system channel exists (HX-2 sniff_html_doc artifact) → never warn.
- PPT/pptx/幻灯片 → needs the render_deck tool ("HTML slides/幻灯片" excluded: HTML channel).
- chart/图表     → needs the render_chart tool (图表配图 counts as image, not chart).
- PDF           → no delivery channel exists → always warn ("print-to-PDF" excluded:
                  that's the USER printing the HTML deliverable, not a spawn promise).
- 图片/image/海报/poster/图表配图 → no image-generation channel → always warn.
- Excel/xlsx/表格文件 → no delivery channel → always warn.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Iterable

logger = logging.getLogger(__name__)

# "HTML slides / HTML 幻灯片 / HTML presentation / HTML deck" are deliverable via the
# system HTML channel — strip them before the PPT detector runs.
_HTML_QUALIFIED_DECK_RE = re.compile(
    r"(?i)(?:单文件\s*)?html\s*(?:幻灯片|slides?|presentations?|decks?|报告|文档)")
# "print-to-PDF" (from the HTML deliverable) is not a spawn delivery promise.
_PRINT_TO_PDF_RE = re.compile(r"(?i)print[- ]?to[- ]?pdf|打印[成为]\s*pdf")
# 图表配图 = illustration imagery; counted by the image detector, must not also fire chart.
_CHART_ILLUSTRATION = "图表配图"

_PPT_RE = re.compile(r"(?i)\bppts?\b|\bpowerpoints?\b|\bpptx\b|\bslides?\b|幻灯片")
_PDF_RE = re.compile(r"(?i)\bpdfs?\b")
_IMAGE_RE = re.compile(r"(?i)\bimages?\b|\bposters?\b|图片|海报|图表配图")
_CHART_RE = re.compile(r"(?i)\bcharts?\b|图表")
_EXCEL_RE = re.compile(r"(?i)\bexcel\b|\bxlsx\b|表格文件")

WARN_PPT = "人设承诺交付 PowerPoint/PPT,但未装备 render_deck 工具"
WARN_PDF = "人设承诺交付 PDF,但系统没有 PDF 交付通道"
WARN_IMAGE = "人设承诺交付图片/海报,但系统没有图片生成通道"
WARN_CHART = "人设承诺交付图表,但未装备 render_chart 工具"
WARN_EXCEL = "人设承诺交付 Excel/表格文件,但系统没有该交付通道"


def lint_delivery_claims(system_prompt: str, tool_keys: set[str]) -> list[str]:
    """Pure, deterministic lint: persona delivery claims vs actually-available channels.

    Returns [] when clean. Warnings are human-readable Chinese, advisory only.
    """
    text = system_prompt or ""
    warnings: list[str] = []

    ppt_text = _HTML_QUALIFIED_DECK_RE.sub(" ", text)
    if _PPT_RE.search(ppt_text) and "render_deck" not in tool_keys:
        warnings.append(WARN_PPT)

    if _PDF_RE.search(_PRINT_TO_PDF_RE.sub(" ", text)):
        warnings.append(WARN_PDF)

    if _IMAGE_RE.search(text):
        warnings.append(WARN_IMAGE)

    chart_text = text.replace(_CHART_ILLUSTRATION, " ")
    if _CHART_RE.search(chart_text) and "render_chart" not in tool_keys:
        warnings.append(WARN_CHART)

    if _EXCEL_RE.search(text):
        warnings.append(WARN_EXCEL)

    return warnings


async def tool_keys_for_toolsets(toolset_keys: Iterable[str]) -> set[str]:
    """Tool keys a spawn equipped with `toolset_keys` could call: safe+wired tools in
    those toolsets, plus the universal safe baseline (mirrors wired_tools_for_spawn)."""
    from sqlalchemy import or_, select

    from server.db import session as db_session
    from server.db.models import Tool
    from server.registry.service import _UNIVERSAL_SAFE_TOOLS

    keys = [str(k) for k in toolset_keys]
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Tool.key).where(
                or_(Tool.toolset_key.in_(keys), Tool.key.in_(_UNIVERSAL_SAFE_TOOLS)),
                Tool.tier == "safe",
                Tool.status == "wired",
            )
        )).scalars().all()
    return set(rows)


async def lint_spawn(spawn_id: int) -> list[str]:
    """Advisory lint for an EXISTING spawn (used right after confirm_create).

    Fail-open: any error returns [] — the lint must never break spawn creation."""
    try:
        from server.db import session as db_session
        from server.db.models import Spawn
        from server.registry import service as registry_service

        async with db_session.AsyncSessionLocal() as db:
            spawn = await db.get(Spawn, spawn_id)
        if spawn is None:
            return []
        wired = await registry_service.wired_tools_for_spawn(spawn_id, current_turn=0)
        return lint_delivery_claims(spawn.system_prompt or "", {t["key"] for t in wired})
    except Exception as exc:  # noqa: BLE001 — advisory, fail-open by design
        logger.warning("persona lint failed for spawn %s: %s", spawn_id, exc)
        return []
