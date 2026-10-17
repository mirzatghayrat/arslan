"""T8 three turns on one report: write it, shorten section 2, add a table.

The runner copies the run folder after turns 1 and 2 (`<run>.turn1`, `<run>.turn2`).
Turn 1 must leave a report with the three `## ` sections the prompt names (进展, 问题,
下一步; an extra section is fine) that uses the notes (at least three of their key numbers).
Then one point each:
- turn 2 shortened section 2 to at most 60% of its turn-1 length, but kept something there
  (at least 10 characters);
- turn 2 left sections 1 and 3 as they were;
- turn 3 added a Markdown table (more tables than after turn 2) and kept all three sections
  of turn 2.
3 = all three; a first report without three sections or without the notes' numbers = 0.
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
KEY_NUMBERS = ("42", "31", "12%", "1.8", "0.9", "3.1", "3.9")
TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$", re.M)


def fixture(run: str) -> None:
    (Path(run) / "notes.md").write_text(NOTES)


NAMES = ("进展", "问题", "下一步")


def sections(text: str) -> list[str] | None:
    """Bodies of the three named `## ` sections (进展, 问题, 下一步), whitespace-normalised, in
    that order; None when one is missing. Other sections are ignored (the 0.1.61 reference
    round added a fourth, 关键数字, which a count of sections would have failed)."""
    found: dict[str, str] = {}
    for m in re.finditer(r"(?ms)^##[ \t]+(.*?)$\n?(.*?)(?=^##[ \t]|\Z)", text):
        name = next((n for n in NAMES if n in m.group(1)), None)
        if name and name not in found:
            found[name] = " ".join(m.group(2).split())
    return [found[n] for n in NAMES] if len(found) == 3 else None


def _report(folder: str) -> str:
    path = Path(folder) / "report.md"
    return path.read_text(errors="ignore") if path.exists() else ""


def check(run: str) -> dict:
    t1, t2, t3 = _report(f"{run}.turn1"), _report(f"{run}.turn2"), _report(run)
    s1, s2 = sections(t1), sections(t2)
    facts = sum(1 for k in KEY_NUMBERS if k in t1)
    if s1 is None or facts < 3:
        return {"score": 0, "turn1_sections": s1 is not None, "turn1_key_numbers": facts}
    s2 = s2 or []
    shorter = len(s2) == 3 and 10 <= len(s2[1]) <= 0.6 * len(s1[1])
    others_kept = len(s2) == 3 and s2[0] == s1[0] and s2[2] == s1[2]
    flat3 = " ".join(t3.split())
    table = len(TABLE_RULE.findall(t3)) > len(TABLE_RULE.findall(t2))
    kept_in_3 = len(s2) == 3 and all(part in flat3 for part in s2)
    points = int(shorter) + int(others_kept) + int(table and kept_in_3)
    return {"score": points, "turn1_sections": True, "turn1_key_numbers": facts, "section2_shortened": shorter,
            "sections_1_3_kept": others_kept, "table_added": table, "turn3_kept_text": kept_in_3}
