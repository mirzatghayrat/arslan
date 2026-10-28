"""T13 code review, Python (v0.1.64 M64): a PR on a tiny shop package with four planted bugs.

How a review is read and scored: review_kit (the matching rule is written down there). Two of
the four need code the PR does not change: P1 (money.apply_discount takes a whole percent) and
P4 (the PR changes Inventory.take's contract from raising OutOfStock to returning False, and
orders.place_order, which the PR does not touch, still waits for the exception).
Keywords name the type in prose; code tokens and generic words are left out (②Main's review).
"""

from __future__ import annotations

from scripts.kernel_bench import fixture_t13, review_kit
from scripts.kernel_bench.review_kit import Bug, Extra

BUGS = (
    Bug(
        "P1",
        "shop/cart.py",
        (26, 29),
        "wrong unit: a fraction passed where a whole percent is expected",
        (
            "percent",
            "百分",
            "integer",
            "整数",
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
            "almost no discount",
            "几乎没有折扣",
            "几乎不打折",
            # Hand check of r64-m64-base (2026-10-28): correct P1 findings said "passes 0.15
            # instead of 15" and were scored "located".
            "而非 15",
            "应传 15",
            "传 15",
            "instead of 15",
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
            "one fewer",
            "one less",
            "one short",
            "drops the last",
            "last line",
            "last item",
            "最后一行",
            "最后一个",
            "9 lines",
            "9 行",
            "exclusive",
            # Hand check of r64-m64-base (2026-10-28): correct P2 findings said "每页少返回一行/一条".
            "少返回",
            "每页少",
            "one line short",
            "one row short",
        ),
        "start + size - 1",
    ),
    Bug(
        "P3",
        "shop/inventory.py",
        (23, 26),
        "failure reported as success: True after a short line",
        (
            "returns true",
            "return true",
            "should return false",
            "should be false",
            "返回 true",
            "返回true",
            "应返回 false",
            "应该返回 false",
            "返回值",
            "return value",
            "reports success",
            "as success",
            "报告成功",
            "当成成功",
            "以为成功",
            "以为预留成功",
            "always true",
        ),
        "if not self.take(line.sku, line.qty):",
    ),
    Bug(
        "P4",
        "shop/inventory.py",
        (12, 15),
        "contract change: take() no longer raises; an untouched caller breaks",
        (
            "no longer raise",
            "doesn't raise",
            "does not raise",
            "stopped raising",
            "instead of raising",
            "never raised",
            "not raised",
            "不再抛",
            "不抛",
            "不会抛",
            "没有抛",
            "caller",
            "调用方",
            "调用者",
            "breaking change",
            "contract",
            "契约",
            "backorder",
            "缺货单",
            # Generous on purpose (②Main's recheck): P4's places are far from every other bug's.
            "抛",
            "异常",
            "exception",
            "throw",
            "except",
            "raise",
            "placed",
            "走不到",
            "进不去",
            "never fires",
            "never runs",
            "unreachable",
            "dead code",
        ),
        "return False",
        context=True,
        also=(("shop/orders.py", (7, 10)), ("shop/inventory.py", (4, 5))),
    ),
)
# True flaws the fixture has that were not planted: neither caught nor a false positive.
EXTRAS = (
    Extra(
        "x-float-total",
        (("shop/api.py", (16, 18)),),
        ("whole number", "float", "整数", "小数", "fraction", "not an int"),
        "P1's effect where checkout uses the total: total_cents is no longer whole cents",
    ),
    Extra(
        "x-thread",
        (("shop/api.py", (4, 9)), ("shop/api.py", (12, 23))),
        ("thread", "线程", "concurren", "并发", "lock", "锁", "atomic", "原子"),
        "_CARTS is shared by every request with no lock",
    ),
)


def check(run: str, reply: str) -> dict:
    return review_kit.check(run, reply, BUGS, fixture_t13.head(), EXTRAS)
