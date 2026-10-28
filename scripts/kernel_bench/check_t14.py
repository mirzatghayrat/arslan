"""T14 code review, TypeScript (v0.1.64 M64): a PR adding a rate limiter and per-user settings,
four planted bugs.

How a review is read and scored: review_kit (the matching rule is written down there). Two of
the four need context outside the changed lines: T1 (clock.nowSeconds is in seconds, the window
in milliseconds) and T4 (DEFAULTS is one object every user shares).
"""

from __future__ import annotations

from scripts.kernel_bench import fixture_t14, review_kit
from scripts.kernel_bench.review_kit import Bug

BUGS = (
    Bug(
        "T1",
        "src/limiter.ts",
        (23, 26),
        "wrong unit: milliseconds added to a time in seconds",
        ("millisecond", "毫秒", "second", "秒", "unit", "单位", "1000", "1,000"),
        "now + this.options.windowMs",
        context=True,
    ),
    Bug(
        "T2",
        "src/limiter.ts",
        (29, 29),
        "off by one: limit + 1 requests are allowed",
        (
            "off-by-one",
            "off by one",
            ">=",
            "≥",
            "limit + 1",
            "limit+1",
            "one extra",
            "one more",
            "多一",
            "多放",
            "多允许",
            "差一",
            "边界",
            "boundary",
        ),
        "bucket.count > this.options.limit",
    ),
    Bug(
        "T3",
        "src/settings.ts",
        (15, 19),
        "async: forEach does not wait, saveAll resolves before the writes",
        (
            "not awaited",
            "isn't awaited",
            "never awaited",
            "doesn't await",
            "does not await",
            "doesn't wait",
            "does not wait",
            "won't wait",
            "promise.all",
            "for...of",
            "for (const",
            "returns 0",
            "returns before",
            "fire-and-forget",
            "fire and forget",
            "unhandled",
            "race",
            "没有等",
            "未等待",
            "不会等",
            "没等",
            "不等待",
            "返回 0",
            "立即返回",
            "提前返回",
        ),
        "all.forEach(async",
    ),
    Bug(
        "T4",
        "src/settings.ts",
        (8, 9),
        "shared state: Object.assign writes the user's values into DEFAULTS",
        (
            "mutat",
            "修改了",
            "改了",
            "改掉",
            "共享",
            "shared",
            "污染",
            "pollut",
            "in place",
            "原地",
            "leak",
            "泄漏",
            "every user",
            "所有用户",
            "other users",
            "其他用户",
            "copy",
            "拷贝",
            "副本",
            "spread",
            "{ ...defaults",
            "{...defaults",
            "first argument",
            "第一个参数",
            "target",
        ),
        "Object.assign(DEFAULTS, user)",
        context=True,
    ),
)


def check(run: str, reply: str) -> dict:
    return review_kit.check(run, reply, BUGS, fixture_t14.head())
