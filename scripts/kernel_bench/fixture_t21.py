"""T21 (v0.1.64 L7-0), rules revealed by the validator: 300 synthetic orders with planted faults.

`data/orders.csv` (order_id, order_date, customer, currency, amount) has non-ISO dates, lower-case currency codes,
duplicate order ids, amounts without two decimals and customer names with stray spaces, and it isn't in date order.
`validate.py --rules rules.dat clean/orders.csv` first checks that the clean file has the source's header and every
order id, then the rules in order, and prints only the first rule that fails, with its text and the first errors. So
rule k is shown only once rules 1 to k-1 pass; after the last it exits 0. The rules, text and code, are only in the
encoded `rules.dat`, and most hold a choice that can't be guessed from the data: every slash date reads both ways
(day first is right), `rmb` is CNY, the first row of a repeated id is the one kept, `12,50` has a decimal comma, and
rows of one date keep the source's order. The card's first draft had 4 rules; the L7-0 pilot's `off` arm completed
that in every run, so it has 6 (the card: more stages).

Chained: rule 1 is readable in `rules.dat`; rules 2 to 6 are sealed, each under a key derived from the cleaned values
that the rule before asks for on a few probe order ids (goal_tasks.SEAL). The validator derives the key from the
clean file once the rule passes. The pilot's worker decoded `rules.dat` and read all four rules at once; now the data
file shows only rule 1, and rule k+1 opens only with rule k's own answer.

The fixture returns the expected clean rows, which only the checker (check_t21.py) sees.
"""
from __future__ import annotations

import csv
import datetime
import io
import json
import random
import secrets
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from scripts.kernel_bench import goal_tasks

HEADER = ["order_id", "order_date", "customer", "currency", "amount"]
ROWS = 300
DUPLICATES = 12
CUSTOMERS = ("Alder & Finch", "Brightwater Ltd", "Copperline", "Dunmore Foods", "Elm Street Bikes", "Fairhaven Inn",
             "Granite Labs", "Hollow Oak Studio", "Iris Pharmacy", "Juniper Rail", "Kingsley Tools", "Lumen Optics")
CODES = ("USD", "EUR", "GBP", "CNY")

# Each rule: its text, and the code of `check(src, clean)` -> errors, where both are lists of row dicts and
# `first(rows)` (validate.py) maps an id to its first row.
RULES = [
    ("Rule 1 of 6: order_date must be written YYYY-MM-DD. In the source, a date written with slashes is day first "
     "(DD/MM/YYYY), so 03/04/2026 is 3 April 2026.", '''
def iso(text):
    if "/" in text:
        d, m, y = text.split("/")
        return "%04d-%02d-%02d" % (int(y), int(m), int(d))
    return text

def check(src, clean):
    want = first(src)
    return ["order %s: order_date should be %s, not %s" % (r["order_id"], iso(want[r["order_id"]]["order_date"]),
            r["order_date"]) for r in clean if r["order_date"] != iso(want[r["order_id"]]["order_date"])]
'''),
    ("Rule 2 of 6: currency must be an upper-case ISO 4217 code. The source's `rmb` is the renminbi, CNY.", '''
def code(text):
    return "CNY" if text.strip().lower() == "rmb" else text.strip().upper()

def check(src, clean):
    want = first(src)
    return ["order %s: currency should be %s, not %s" % (r["order_id"], code(want[r["order_id"]]["currency"]),
            r["currency"]) for r in clean if r["currency"] != code(want[r["order_id"]]["currency"])]
'''),
    ("Rule 3 of 6: each order_id appears once. When the source repeats an id, keep the first row in file order and "
     "drop the later ones.", '''
def check(src, clean):
    want, seen, errors = first(src), set(), []
    for r in clean:
        if r["order_id"] in seen:
            errors.append("order %s appears more than once" % r["order_id"])
        seen.add(r["order_id"])
        if r["customer"].split() != want[r["order_id"]]["customer"].split():
            errors.append("order %s: kept the wrong row (customer %s)" % (r["order_id"], r["customer"]))
    return errors
'''),
    ("Rule 4 of 6: amount must have exactly two decimals, with a point and nothing else (no sign of a currency, no "
     "thousands separator). In the source, an amount like 12,50 uses a decimal comma: it is 12.50.", '''
import re
from decimal import Decimal, ROUND_HALF_UP

def amount(text):
    return str(Decimal(text.strip().replace(",", ".")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

def check(src, clean):
    want = first(src)
    return ["order %s: amount should be %s, not %s" % (r["order_id"], amount(want[r["order_id"]]["amount"]),
            r["amount"]) for r in clean
            if not re.fullmatch(r"-?[0-9]+[.][0-9]{2}", r["amount"]) or r["amount"] != amount(want[r["order_id"]]["amount"])]
'''),
    ("Rule 5 of 6: customer has no space before or after it, and never two spaces in a row.", '''
def check(src, clean):
    want = first(src)
    return ["order %s: customer should be %r, not %r" % (r["order_id"], " ".join(r["customer"].split()),
            r["customer"]) for r in clean if r["customer"] != " ".join(want[r["order_id"]]["customer"].split())]
'''),
    ("Rule 6 of 6: rows are in order of order_date, oldest first; rows with the same date keep the order they have in "
     "the source.", '''
def iso(text):
    if "/" in text:
        d, m, y = text.split("/")
        return "%04d-%02d-%02d" % (int(y), int(m), int(d))
    return text

def check(src, clean):
    where = {}
    for i, r in enumerate(src):
        where.setdefault(r["order_id"], (iso(r["order_date"]), i))
    want = sorted(where, key=lambda oid: where[oid])
    got = [r["order_id"] for r in clean]
    if got == want:
        return []
    n = next(i for i, (a, b) in enumerate(zip(got, want)) if a != b) if len(got) == len(want) else 0
    return ["row %d is order %s; it should be order %s" % (n + 2, got[n] if n < len(got) else "-", want[n])]
'''),
]

VALIDATE = '''"""Validate a cleaned orders file against the rules revealed so far. Each run shows the first rule that fails."""
import argparse
import base64
import csv
import hashlib
import json
import sys
import zlib

sys.dont_write_bytecode = True
SOURCE = "data/orders.csv"

{decoder}
{seal}

def probe_values(clean, probe):
    """The cleaned values a rule's probe reads: the first row of each probe id, its field as the rule judges it."""
    got = first(clean)
    values = []
    for oid in probe["ids"]:
        value = got[oid][probe["field"]] if oid in got else ""
        values.append(" ".join(value.split()) if probe["form"] == "spaces" else value)
    return values


def rows(path):
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def first(rows):
    out = {}
    for r in rows:
        out.setdefault(r["order_id"], r)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rules", required=True)
    ap.add_argument("clean")
    args = ap.parse_args()
    data = _decode(args.rules)
    total = 1 + len(data["sealed"])
    head, src = rows(SOURCE)
    try:
        got_head, clean = rows(args.clean)
    except OSError:
        print("No cleaned file at %s yet." % args.clean)
        return 1
    ids, got = set(r["order_id"] for r in src), [r.get("order_id") for r in clean]
    if got_head != head or set(got) != ids:
        print("The cleaned file must have the source's header (%s) and every order_id in it, and no other id."
              % ",".join(head))
        return 1
    rule = data["first"]
    for n in range(1, total + 1):
        space = {"first": first}
        exec(compile(rule["code"], "rule_%d" % n, "exec"), space)
        errors = space["check"](src, clean)
        if errors:
            print(rule["text"])
            for e in errors[:5]:
                print("  " + e)
            print("%d row(s) break this rule." % len(errors))
            return 1
        print("Rule %d of %d: passed." % (n, total))
        if n < total:
            # The next rule is sealed under this rule's correct values (it passed, so they are).
            probe = data["probes"][n - 1]
            text = _unseal(data["sealed"][n - 1], _key(data["salt"], n, probe_values(clean, probe)))
            if text is None:
                print("Rule %d passes, but the cleaned %s of orders %s isn't what it asks." % (
                    n, probe["field"], ", ".join(probe["ids"])))
                return 1
            rule = json.loads(text)
    print("Every rule passes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''.replace("{decoder}", goal_tasks.DECODER).replace("{seal}", goal_tasks.SEAL)


def _spaced(rng: random.Random, name: str) -> str:
    """About one name in eight as a careless export writes it: a space before or after, or a doubled space inside."""
    roll = rng.random()
    if roll < 0.04:
        return " " + name
    if roll < 0.08:
        return name + "  "
    if roll < 0.12 and " " in name:
        return name.replace(" ", "  ", 1)
    return name


PROBE_IDS = 6


def _probes(originals: list[list], body: list[list]) -> list[dict]:
    """Rule k's probe for rules 1-5 (rule 6 is the last; nothing is sealed under it): order ids whose cleaned value a
    naive reading of rule k gets wrong, so only the rule's own answer opens rule k+1. Row layout: id, the source's
    date, customer, currency, amount, then the ISO date, currency, amount and customer the rules ask for."""
    counts: dict = {}
    for r in body:
        counts[r[0]] = counts.get(r[0], 0) + 1

    def ids(pick) -> list[str]:
        return [r[0] for r in originals if pick(r)][:PROBE_IDS]

    return [
        {"field": "order_date", "form": "exact", "ids": ids(lambda r: "/" in r[1])},     # day first, not month
        {"field": "currency", "form": "exact", "ids": ids(lambda r: r[3] == "rmb")},     # CNY, not RMB
        {"field": "customer", "form": "spaces", "ids": ids(lambda r: counts[r[0]] > 1)},  # the first row's
        {"field": "amount", "form": "exact", "ids": ids(lambda r: r[4] != r[7])},         # 12,50 is 12.50
        {"field": "customer", "form": "exact", "ids": ids(lambda r: r[2] != r[8])},       # no stray spaces
    ]


def fixture(run: str, seed: int = 21) -> dict:
    rng = random.Random(seed)
    unique = ROWS - DUPLICATES
    ids = [f"A{n}" for n in rng.sample(range(10000, 99999), unique)]
    body = []
    for oid in ids:
        day = datetime.date(2026, 1, 1) + datetime.timedelta(days=rng.randrange(0, 330))
        written = day.isoformat()
        if rng.random() < 0.15:
            while day.day > 12 or day.day == day.month:
                day = datetime.date(2026, rng.randint(1, 12), rng.randint(1, 12))
            written = f"{day.day:02d}/{day.month:02d}/{day.year}"
        currency = rng.choice(CODES)
        roll = rng.random()
        written_cur = "rmb" if currency == "CNY" and roll < 0.4 else currency.lower() if roll < 0.2 else currency
        cents, style = rng.randint(100, 900000), rng.random()
        if style < 0.08:                                         # whole: no decimals
            value = Decimal(cents // 100)
            written_amount = str(cents // 100)
        elif style < 0.16:                                       # one decimal
            value = Decimal(cents - cents % 10) / 100
            written_amount = f"{value:.1f}"
        elif style < 0.24:                                       # a decimal comma
            value = Decimal(cents) / 100
            written_amount = f"{value:.2f}".replace(".", ",")
        else:
            value = Decimal(cents) / 100
            written_amount = f"{value:.2f}"
        customer = rng.choice(CUSTOMERS)
        body.append([oid, written, _spaced(rng, customer), written_cur, written_amount, day.isoformat(), currency,
                     f"{value.quantize(Decimal('0.01'), ROUND_HALF_UP)}", customer])
    originals = list(body)
    for _ in range(DUPLICATES):                                  # a later row repeats an earlier id: same date and
        orig = rng.choice(originals)                             # currency, another customer and amount
        other = rng.choice([c for c in CUSTOMERS if c != orig[8]])
        dup = [orig[0], orig[1], other, orig[3], f"{Decimal(rng.randint(100, 90000)) / 100:.2f}"] + orig[5:8] + [other]
        body.insert(rng.randrange(body.index(orig) + 1, len(body) + 1), dup)
    expected, seen = {}, set()
    for r in body:
        if r[0] not in seen:
            seen.add(r[0])
            expected[r[0]] = {"order_date": r[5], "customer": r[8], "currency": r[6], "amount": r[7]}
    position = {oid: i for i, oid in enumerate(expected)}
    order = sorted(expected, key=lambda oid: (expected[oid]["order_date"], position[oid]))
    root = Path(run)
    (root / "data").mkdir(parents=True)
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows([HEADER] + [r[:5] for r in body])
    (root / "data" / "orders.csv").write_text(buf.getvalue())
    salt = secrets.token_hex(8)
    probes = _probes(originals, body)
    sealed = []
    for k, probe in enumerate(probes, 1):
        values = [expected[oid][probe["field"]] for oid in probe["ids"]]
        text = json.dumps({"text": RULES[k][0], "code": RULES[k][1]})
        sealed.append(goal_tasks.seal(text, goal_tasks.derive_key(salt, k, values)))
    data = {"salt": salt, "first": {"text": RULES[0][0], "code": RULES[0][1]}, "probes": probes, "sealed": sealed}
    (root / "rules.dat").write_text(goal_tasks.encode(data) + "\n")
    (root / "validate.py").write_text(VALIDATE)
    return {"sha256": {rel: goal_tasks.sha256(root / rel) for rel in ("validate.py", "rules.dat", "data/orders.csv")},
            "expected": expected, "order": order, "header": HEADER}
