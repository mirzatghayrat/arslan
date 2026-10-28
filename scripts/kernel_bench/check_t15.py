"""T15 code review, Swift (v0.1.64 M64): a PR adding the model behind a notes list, four
planted bugs.

How a review is read and scored: review_kit (the matching rule is written down there). Two of
the four need context outside the changed lines: S1 (Paging.swift: the server numbers pages
from 1) and S4 (the index the list passes is into `visible`, not `notes`).
"""

from __future__ import annotations

from scripts.kernel_bench import fixture_t15, review_kit
from scripts.kernel_bench.review_kit import Bug

FILE = "Sources/Notes/NotesModel.swift"
BUGS = (
    Bug(
        "S1",
        FILE,
        (9, 9),
        "off by one: the first page is 1, not 0",
        (
            "from 1",
            "1-based",
            "one-based",
            "starts at 1",
            "start at 1",
            "page 1",
            "page: 1",
            "从 1",
            "第 1 页",
            "第一页",
            "0 页",
            "page 0",
            "页码",
            "off-by-one",
            "off by one",
            "zero-based",
            "0-based",
        ),
        "PageRequest(page: 0)",
        context=True,
    ),
    Bug(
        "S2",
        FILE,
        (38, 38),
        "crash: force-unwrapping what the user typed",
        (
            "force unwrap",
            "force-unwrap",
            "强制解包",
            "强解",
            "crash",
            "崩溃",
            "闪退",
            "nil",
            "trap",
            "invalid input",
            "non-numeric",
            "非数字",
            "fatal",
            "guard let",
            "if let",
        ),
        "Int(text)!",
    ),
    Bug(
        "S3",
        FILE,
        (20, 27),
        "retain cycle: the repeating timer holds self strongly and is never invalidated",
        (
            "retain cycle",
            "reference cycle",
            "strong reference",
            "strongly",
            "weak self",
            "[weak",
            "unowned",
            "leak",
            "循环引用",
            "强引用",
            "泄漏",
            "泄露",
            "invalidate",
            "never released",
            "never deallocated",
            "不会释放",
            "无法释放",
            "deinit",
        ),
        "Timer.scheduledTimer",
    ),
    Bug(
        "S4",
        FILE,
        (31, 32),
        "wrong index: removes from notes by an index into visible",
        (
            "visible",
            "filter",
            "过滤",
            "筛选",
            "search",
            "搜索",
            "wrong note",
            "另一条",
            "别的笔记",
            "错的",
            "index into",
            "different array",
            "out of range",
            "越界",
        ),
        "notes.remove(at: index)",
        context=True,
    ),
)


def check(run: str, reply: str) -> dict:
    return review_kit.check(run, reply, BUGS, fixture_t15.head())
