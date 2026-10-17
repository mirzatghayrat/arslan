"""T8 three turns on one report: write it, shorten section 2, add a table.

The runner copies the run folder after turns 1 and 2 (`<run>.turn1`, `<run>.turn2`).
Turn 1 must leave a report with exactly three `## ` sections. Then one point each:
- turn 2 shortened section 2 to at most 60% of its turn-1 length;
- turn 2 left sections 1 and 3 as they were;
- turn 3 added a Markdown table and kept the turn-2 text of sections 1 and 3.
3 = all three; a report without three sections after turn 1 = 0.
"""
from __future__ import annotations

import re
from pathlib import Path

NOTES = """# 笔记：团队周会（虚构）

- 本周上线了导出功能，用户反馈导出 CSV 时中文乱码，已定位到编码设置，下周修。
- 支持工单从上周的 42 张降到 31 张，主要是登录问题减少了。
- 新招的两位工程师下周一入职，需要准备电脑和账号。
- 服务器费用比预算高 12%，原因是日志保留时间太长，建议从 90 天改成 30 天。
- 下个月要做一次用户访谈，目标是 8 位老用户，重点问导出和搜索。
- 搜索的平均响应时间从 1.8 秒降到 0.9 秒，用户满意度调查里搜索一项从 3.1 分升到 3.9 分。
"""
TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$", re.M)


def fixture(run: str) -> None:
    (Path(run) / "notes.md").write_text(NOTES)


def sections(text: str) -> list[str]:
    """Bodies of the `## ` sections, whitespace-normalised, in order."""
    parts = re.split(r"(?m)^##\s+.*$", text)[1:]
    return [" ".join(p.split()) for p in parts]


def _report(folder: str) -> str:
    path = Path(folder) / "report.md"
    return path.read_text(errors="ignore") if path.exists() else ""


def check(run: str) -> dict:
    t1, t2, t3 = _report(f"{run}.turn1"), _report(f"{run}.turn2"), _report(run)
    s1, s2 = sections(t1), sections(t2)
    if len(s1) != 3:
        return {"score": 0, "turn1_sections": len(s1)}
    shorter = len(s2) == 3 and len(s2[1]) <= 0.6 * len(s1[1])
    others_kept = len(s2) == 3 and s2[0] == s1[0] and s2[2] == s1[2]
    flat3 = " ".join(t3.split())
    table = bool(TABLE_RULE.search(t3)) and not TABLE_RULE.search(t2)
    kept_in_3 = len(s2) == 3 and s2[0] in flat3 and s2[2] in flat3
    points = int(shorter) + int(others_kept) + int(table and kept_in_3)
    return {"score": points, "turn1_sections": 3, "section2_shortened": shorter,
            "sections_1_3_kept": others_kept, "table_added": table, "turn3_kept_text": kept_in_3}
