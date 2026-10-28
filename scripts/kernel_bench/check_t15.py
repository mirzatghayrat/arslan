"""T15 code review, Swift (v0.1.64 M64): a PR adding the model behind a notes list, four
planted bugs.

How a review is read and scored: review_kit (the matching rule is written down there). Two of
the four need code the PR does not change: S1 (Paging.swift: the server numbers pages from 1)
and S4 (the PR changes Note's equality to compare ids only, and EditTracker, which the PR does
not touch, compares notes to tell whether the user changed one).
Keywords name the type in prose; code tokens and generic words are left out (②Main's review).
"""

from __future__ import annotations

from scripts.kernel_bench import fixture_t15, review_kit
from scripts.kernel_bench.review_kit import Bug, Extra

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
            "从 1",
            "第 1 页",
            "第一页",
            "第 0 页",
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
        (39, 39),
        "crash: force-unwrapping what the user typed",
        (
            "force unwrap",
            "force-unwrap",
            "强制解包",
            "强解",
            "crash",
            "崩溃",
            "闪退",
            "trap",
            "invalid input",
            "non-numeric",
            "非数字",
            "fatal",
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
        ),
        "Timer.scheduledTimer",
    ),
    Bug(
        "S4",
        "Sources/Notes/Note.swift",
        (12, 14),
        "contract change: == compares ids only; an untouched caller breaks",
        (
            "equality",
            "相等",
            "判等",
            "only compar",
            "只比较",
            "unsaved",
            "未保存",
            "没保存",
            "caller",
            "调用方",
            "调用者",
            "contract",
            "契约",
            "edits are lost",
            "lose edits",
            "lost edits",
            "改动丢失",
            "丢失修改",
            "never detects",
            "检测不到",
        ),
        "lhs.id == rhs.id",
        context=True,
        also=(("Sources/Notes/EditTracker.swift", (4, 5)),),
    ),
)
# True flaws the fixture has that were not planted: neither caught nor a false positive.
EXTRAS = (
    Extra(
        "x-fetch-error",
        ((FILE, (43, 48)),),
        ("error", "failure", "失败", "错误", "ignored", "silently", "静默", "忽略", "吞"),
        "load drops a fetch failure without telling anyone",
    ),
)


def check(run: str, reply: str) -> dict:
    return review_kit.check(run, reply, BUGS, fixture_t15.head(), EXTRAS)
