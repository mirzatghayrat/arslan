"""T13 fixture: a tiny synthetic Python shop package; the PR adds a member discount, paging and
checkout. Written for the bench, no real project's code. The planted bugs are in check_t13.BUGS."""

from __future__ import annotations

from pathlib import Path

from scripts.kernel_bench import review_kit

BASE = {
    "shop/__init__.py": '"""A tiny shop."""\n',
    "shop/money.py": '''"""Money helpers. Every amount is a whole number of cents."""
from decimal import ROUND_HALF_UP, Decimal


def to_cents(amount: str) -> int:
    """'12.34' -> 1234."""
    return int((Decimal(amount) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def apply_discount(cents: int, percent: int) -> int:
    """Take `percent` off `cents`. `percent` is a whole number from 0 to 100: 15 means 15%."""
    if not 0 <= percent <= 100:
        raise ValueError(f"percent out of range: {percent}")
    return cents - cents * percent // 100
''',
    "shop/cart.py": '''"""A shopping cart."""
from dataclasses import dataclass, field


@dataclass
class Line:
    sku: str
    price_cents: int
    qty: int


@dataclass
class Cart:
    owner: str
    lines: list[Line] = field(default_factory=list)

    def add(self, sku: str, price_cents: int, qty: int = 1) -> None:
        self.lines.append(Line(sku, price_cents, qty))

    def subtotal(self) -> int:
        return sum(line.price_cents * line.qty for line in self.lines)
''',
    "shop/inventory.py": '''"""Stock levels."""


class OutOfStock(Exception):
    pass


class Inventory:
    def __init__(self, stock: dict[str, int]):
        self.stock = dict(stock)

    def take(self, sku: str, qty: int) -> None:
        if self.stock.get(sku, 0) < qty:
            raise OutOfStock(sku)
        self.stock[sku] -= qty
''',
    "shop/api.py": '''"""Request handlers: the web layer calls these, one call per request."""
from shop.cart import Cart

_CARTS: dict[str, Cart] = {}


def get_cart(user_id: str) -> Cart:
    """This user's cart (each user has their own)."""
    return _CARTS.setdefault(user_id, Cart(owner=user_id))
''',
    "shop/orders.py": '''"""Single-item orders taken over the phone (the call centre's screen calls this)."""
from shop.inventory import Inventory, OutOfStock


def place_order(inventory: Inventory, sku: str, qty: int) -> str:
    """'placed' when the stock was taken, 'backordered' when there was not enough."""
    try:
        inventory.take(sku, qty)
    except OutOfStock:
        return "backordered"
    return "placed"
''',
    "tests/test_cart.py": """from shop.cart import Cart


def test_subtotal():
    cart = Cart(owner="u1")
    cart.add("A", 250, 2)
    assert cart.subtotal() == 500
""",
}

PR = {
    "shop/cart.py": '''"""A shopping cart."""
from dataclasses import dataclass, field

from shop.money import apply_discount


@dataclass
class Line:
    sku: str
    price_cents: int
    qty: int


@dataclass
class Cart:
    owner: str
    lines: list[Line] = field(default_factory=list)

    def add(self, sku: str, price_cents: int, qty: int = 1) -> None:
        self.lines.append(Line(sku, price_cents, qty))

    def subtotal(self) -> int:
        return sum(line.price_cents * line.qty for line in self.lines)

    def total(self, member: bool) -> int:
        """What the customer pays: members get 15% off."""
        subtotal = self.subtotal()
        if member:
            return apply_discount(subtotal, 0.15)
        return subtotal

    def page(self, number: int, size: int = 10) -> list[Line]:
        """The lines on page `number` (pages start at 0), `size` lines a page."""
        start = number * size
        return self.lines[start:start + size - 1]
''',
    "shop/inventory.py": '''"""Stock levels."""


class OutOfStock(Exception):
    pass


class Inventory:
    def __init__(self, stock: dict[str, int]):
        self.stock = dict(stock)

    def take(self, sku: str, qty: int) -> bool:
        """Take `qty` of `sku`; False, and nothing taken, when there is not enough."""
        if self.stock.get(sku, 0) < qty:
            return False
        self.stock[sku] -= qty
        return True

    def reserve_all(self, lines) -> bool:
        """Take every line's quantity, or none of them. True when all were taken."""
        taken = []
        for line in lines:
            if not self.take(line.sku, line.qty):
                for done in taken:
                    self.stock[done.sku] += done.qty
                return True
            taken.append(line)
        return True
''',
    "shop/api.py": '''"""Request handlers: the web layer calls these, one call per request."""
from shop.cart import Cart

_CARTS: dict[str, Cart] = {}


def get_cart(user_id: str) -> Cart:
    """This user's cart (each user has their own)."""
    return _CARTS.setdefault(user_id, Cart(owner=user_id))


def checkout(user_id: str, inventory, member: bool) -> dict:
    cart = get_cart(user_id)
    if not inventory.reserve_all(cart.lines):
        return {"ok": False, "error": "out of stock"}
    total = cart.total(member)
    clear_cart(user_id)
    return {"ok": True, "total_cents": total}


def clear_cart(user_id: str) -> None:
    """Empty this user's cart once they have checked out."""
    _CARTS.pop(user_id, None)
''',
    "tests/test_cart.py": """from shop.cart import Cart


def test_subtotal():
    cart = Cart(owner="u1")
    cart.add("A", 250, 2)
    assert cart.subtotal() == 500


def test_member_total():
    cart = Cart(owner="u1")
    cart.add("A", 1000)
    assert cart.total(member=False) == 1000
""",
}

MESSAGE = """Add member discount, cart paging and checkout

- Cart.total(member): members get 15% off.
- Cart.page(number, size) for the cart page.
- Inventory.take returns False when stock is short instead of raising
  (checkout tries many lines; no exception per line).
- Inventory.reserve_all: all-or-nothing stock reservation.
- api.checkout and api.clear_cart.
"""


def head() -> dict[str, str]:
    """Every file as it stands on `feature`."""
    return {**BASE, **PR}


def fixture(run: str) -> None:
    review_kit.build_repo(Path(run) / "repo", BASE, PR, MESSAGE)
