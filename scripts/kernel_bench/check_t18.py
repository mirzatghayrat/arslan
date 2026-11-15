"""T18 (v0.1.64 L7-0), a goal task: 20 synthetic invoices to sort and reconcile.

The fixture writes 20 invoices into `invoices/`, one text file each under a shuffled name, so the names don't give
the order away. Each has an invoice number, a date (ISO, or written as `14 Mar 2026`), a vendor, line items
(quantity x unit price), sometimes shipping, and the total the invoice states. Four stated totals are wrong.

The prompt asks for `ledger.csv`: one row per invoice, sorted by date and then invoice number, with the date as
YYYY-MM-DD, the total recomputed from the lines and shipping, the stated total, and `ok` or `mismatch`; then a row
`TOTAL` with the sum of the recomputed totals. Its prompt has no `check:` line: in goal mode the checks are the ones
Arslan drafts.

The checker first confirms by sha256 that the invoices are the fixture's, then recomputes every total from the
files on disk, never from the reply. 3 = every row, the order, every status and the TOTAL row are right; 1 =
`ledger.csv` exists but something in it is wrong; 0 = no `ledger.csv`, or an invoice was changed.
"""
from __future__ import annotations

import csv
import datetime
import random
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from scripts.kernel_bench import goal_tasks

COUNT = 20
WRONG = 4
COLUMNS = ("invoice", "date", "vendor", "computed_total", "stated_total", "status")
VENDORS = ("Harbor Paper Co.", "Northwind Office Supply", "Blue Fern Catering", "Kestrel Print Works",
           "Quarry Lane Electric", "Summit Cleaning Ltd.", "Orchard Courier")
ITEMS = ("Copy paper (box)", "Toner cartridge", "Desk lamp", "Lunch platter", "Business cards (500)",
         "Cable ties (pack)", "Window cleaning", "Same-day delivery", "Label printer tape", "Coffee beans (1 kg)")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _cents(value: Decimal) -> str:
    return f"{value:.2f}"


def fixture(run: str, seed: int = 18) -> dict:
    """Write the invoices; return their sha256 (what the checker trusts) and the truth (what the tests compare)."""
    rng = random.Random(seed)
    folder = Path(run) / "invoices"
    folder.mkdir(parents=True)
    numbers = rng.sample(range(100, 999), COUNT)
    wrong = set(rng.sample(range(COUNT), WRONG))
    names = [f"scan_{rng.randrange(16 ** 6):06x}.txt" for _ in range(COUNT)]
    truth, digests = [], {}
    for i, number in enumerate(numbers):
        day = datetime.date(2026, 1, 1) + datetime.timedelta(days=rng.randrange(0, 150))
        # two invoices on one day, so the second sort key matters
        if i == 1:
            day = truth[0]["_day"]
        written = day.isoformat() if rng.random() < 0.5 else f"{day.day} {MONTHS[day.month - 1]} {day.year}"
        lines, total = [], Decimal(0)
        for _ in range(rng.randint(2, 5)):
            qty, price = rng.randint(1, 12), Decimal(rng.randint(150, 25000)) / 100
            lines.append(f"  {qty} x {_cents(price)}  {rng.choice(ITEMS)}")
            total += qty * price
        shipping = Decimal(rng.choice((0, 0, 450, 750, 1290))) / 100
        stated = total + shipping
        if i in wrong:
            stated += Decimal(rng.choice((-1, 1)) * rng.randint(1, 4000)) / 100
        vendor = rng.choice(VENDORS)
        text = [f"INVOICE INV-2026-{number}", f"Date: {written}", f"Vendor: {vendor}", "Lines:", *lines]
        if shipping:
            text.append(f"Shipping: {_cents(shipping)}")
        text.append(f"Stated total: {_cents(stated)}")
        path = folder / names[i]
        path.write_text("\n".join(text) + "\n")
        digests[f"invoices/{names[i]}"] = goal_tasks.sha256(path)
        truth.append({"invoice": f"INV-2026-{number}", "date": day.isoformat(), "vendor": vendor,
                      "computed_total": _cents(total + shipping), "stated_total": _cents(stated), "_day": day})
    for t in truth:
        del t["_day"]
    return {"sha256": digests, "truth": truth}


def read_invoice(text: str) -> dict:
    """One invoice as the checker reads it from disk."""
    number = re.search(r"^INVOICE (\S+)\s*$", text, re.M).group(1)
    raw = re.search(r"^Date: (.+?)\s*$", text, re.M).group(1)
    try:
        day = datetime.date.fromisoformat(raw)
    except ValueError:
        d, mon, y = raw.split()
        day = datetime.date(int(y), MONTHS.index(mon) + 1, int(d))
    total = sum((int(q) * Decimal(p) for q, p in re.findall(r"^\s+(\d+) x (\d+\.\d{2})\s", text, re.M)), Decimal(0))
    shipping = re.search(r"^Shipping: (\d+\.\d{2})\s*$", text, re.M)
    if shipping:
        total += Decimal(shipping.group(1))
    stated = Decimal(re.search(r"^Stated total: (-?\d+\.\d{2})\s*$", text, re.M).group(1))
    return {"invoice": number, "date": day.isoformat(),
            "vendor": re.search(r"^Vendor: (.+?)\s*$", text, re.M).group(1), "computed": total, "stated": stated}


def _amount(text: str) -> Decimal | None:
    try:
        return Decimal(str(text).replace(",", "").replace("$", "").strip())
    except InvalidOperation:
        return None


def check(run: str, params: dict) -> dict:
    changed = goal_tasks.changed(run, params["sha256"])
    ledger = Path(run) / "ledger.csv"
    if changed or not ledger.is_file():
        return {"score": 0, "ledger": ledger.is_file(), "invoices_changed": changed}
    want = sorted((read_invoice((Path(run) / rel).read_text()) for rel in params["sha256"]),
                  key=lambda r: (r["date"], r["invoice"]))
    with ledger.open(newline="", encoding="utf-8", errors="ignore") as f:
        rows = [{(k or "").strip().lower(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)]
    problems = []
    if not rows or not set(COLUMNS) <= set(rows[0]):
        return {"score": 1, "ledger": True, "invoices_changed": [], "problems": ["missing columns"]}
    body = [r for r in rows if r["invoice"].upper() != "TOTAL"]
    total_rows = [r for r in rows if r["invoice"].upper() == "TOTAL"]
    if [r["invoice"] for r in body] != [w["invoice"] for w in want]:
        problems.append("rows or their order differ")
    for r, w in zip(body, want):
        status = "ok" if w["computed"] == w["stated"] else "mismatch"
        if (r["date"], _amount(r["computed_total"]), _amount(r["stated_total"]), r["status"].lower()) != (
                w["date"], w["computed"], w["stated"], status):
            problems.append(f"{w['invoice']}: wrong values")
    grand = sum((w["computed"] for w in want), Decimal(0))
    if len(total_rows) != 1 or rows[-1] is not total_rows[0] or _amount(total_rows[0]["computed_total"]) != grand:
        problems.append("TOTAL row missing, not last, or wrong")
    return {"score": 1 if problems else 3, "ledger": True, "invoices_changed": [], "problems": problems[:10],
            "rows": len(body)}
