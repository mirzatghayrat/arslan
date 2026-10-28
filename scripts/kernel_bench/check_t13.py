"""T13 code review, Python (v0.1.64 M64): a PR on a tiny shop package with four planted bugs.

How a review is read and scored: review_kit (the matching rule is written down there). Two of
the four need context outside the changed lines: P1 (money.apply_discount takes a whole
percent, in a file the PR does not touch) and P4 (every user's cart lives in one shared dict).
"""

from __future__ import annotations

from scripts.kernel_bench import fixture_t13, review_kit
from scripts.kernel_bench.review_kit import Bug

BUGS = (
    Bug(
        "P1",
        "shop/cart.py",
        (26, 29),
        "wrong unit: a fraction passed where a whole percent is expected",
        (
            "percent",
            "百分",
            "whole number",
            "整数",
            "integer",
            "fraction",
            "小数",
            "unit",
            "单位",
            "比例",
            "ratio",
            "0-100",
            "0 到 100",
            "too small",
            "太小",
            "几乎",
            "almost no",
            "rounds",
        ),
        "apply_discount(subtotal, 0.15)",
        context=True,
    ),
    Bug(
        "P2",
        "shop/cart.py",
        (34, 35),
        "off by one: a page holds size - 1 lines",
        (
            "off-by-one",
            "off by one",
            "差一",
            "少一",
            "少了一",
            "漏掉",
            "one fewer",
            "one less",
            "size - 1",
            "size-1",
            "last line",
            "last item",
            "最后一",
            "边界",
            "boundary",
            "9 lines",
            "9 行",
            "exclusive",
            "不包含",
        ),
        "start + size - 1",
    ),
    Bug(
        "P3",
        "shop/inventory.py",
        (24, 27),
        "failure reported as success: True after OutOfStock",
        (
            "return true",
            "returns true",
            "return false",
            "returns false",
            "返回 true",
            "返回true",
            "返回 false",
            "返回false",
            "返回值",
            "return value",
            "success",
            "成功",
            "always true",
            "总是",
            "even when",
            "即使",
            "failure",
            "失败",
        ),
        "except OutOfStock:",
    ),
    Bug(
        "P4",
        "shop/api.py",
        (21, 23),
        "wrong scope: clearing one user's cart empties every user's",
        (
            "all users",
            "every user",
            "all carts",
            "every cart",
            "other users",
            "other user's",
            "everyone",
            "every customer",
            "all customers",
            "entire",
            "whole",
            "所有用户",
            "所有人",
            "其他用户",
            "别的用户",
            "所有购物车",
            "全部",
            "整个",
            "pop(",
            "del ",
        ),
        "_CARTS.clear()",
        context=True,
    ),
)


def check(run: str, reply: str) -> dict:
    return review_kit.check(run, reply, BUGS, fixture_t13.head())
