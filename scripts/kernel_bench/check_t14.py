"""T14 code review, TypeScript (v0.1.64 M64): a PR adding a rate limiter and per-user settings,
four planted bugs.

How a review is read and scored: review_kit (the matching rule is written down there). Two of
the four need code the PR does not change: T1 (clock.nowSeconds is in seconds, the window in
milliseconds) and T4 (DEFAULTS is one object every user shares).
Keywords name the type in prose; code tokens and generic words are left out (②Main's review).
"""

from __future__ import annotations

from scripts.kernel_bench import fixture_t14, review_kit
from scripts.kernel_bench.review_kit import Bug, Extra

BUGS = (
    Bug(
        "T1",
        "src/limiter.ts",
        (23, 26),
        "wrong unit: milliseconds added to a time in seconds",
        (
            "millisecond",
            "毫秒",
            "seconds",
            "秒",
            "unit",
            "单位",
            "1000x",
            "1000 times",
            "1,000 times",
            "1000 倍",
            "千倍",
        ),
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
            "one extra",
            "one more request",
            "one request too many",
            "too many requests",
            "limit + 1 requests",
            "多一个",
            "多一次",
            "多放",
            "多允许",
            "差一",
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
            "returns 0",
            "returns before",
            "resolves before",
            "fire-and-forget",
            "fire and forget",
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
            "共享",
            "shared",
            "污染",
            "pollut",
            "in place",
            "原地",
            "every user",
            "所有用户",
            "other users",
            "其他用户",
            "first argument",
            "第一个参数",
            "修改默认",
            "改写默认",
            "改动默认",
            "副本",
            "拷贝",
        ),
        "Object.assign(DEFAULTS, user)",
        context=True,
    ),
)
# True flaws the fixture has that were not planted: neither caught nor a false positive.
EXTRAS = (
    Extra(
        "x-esm-imports",
        (("src/limiter.ts", (1, 1)), ("src/settings.ts", (1, 1)), ("src/index.ts", (1, 7))),
        ("extension", "扩展名", "后缀", "esm", "resolve", "解析", "nodenext", "module resolution"),
        'relative imports without ".js" under "type": "module"',
    ),
    Extra(
        "x-buckets-grow",
        (("src/limiter.ts", (16, 35)),),
        (
            "prune",
            "never removed",
            "never deleted",
            "never cleaned",
            "evict",
            "grows",
            "unbounded",
            "memory",
            "清理",
            "无限增长",
            "内存",
            "不会删除",
        ),
        "buckets are never pruned",
    ),
)


def check(run: str, reply: str) -> dict:
    return review_kit.check(run, reply, BUGS, fixture_t14.head(), EXTRAS)
