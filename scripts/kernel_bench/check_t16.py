"""T16 split, delegate, summarise (v0.1.64 M64, for the SUB card): three independent regions'
order tables; the entrant, as the one in charge, hands each region to a sub-session, each writes
`out/<region>.md`, then it writes `summary.md` covering all three.

What is recorded: how many sub-sessions it opened (the run's tool-call record, tool_record.py),
whether each region's file holds that region's answer, whether the summary covers every region.
The run's cost and the provider's 429 answers are in the run's record (`usage`, `rate_limited_429`).

- The top product is read from the lines that claim it (最高 / 最多 / 第一 / 畅销 / top / best /
  most): at least one such line names the right product and no other, and no such line names
  only a wrong one. A product named anywhere else (a per-product table) does not count
  (②Main's review of #436: a file listing every product passed with a wrong top).
- A region's part is right when `out/<region>.md` has its total (to the cent; thousands
  separators allowed), claims the right top product, and holds no other region's total. Another
  region's total in it is how two sub-sessions writing the same file shows up (the card's "no
  two wrote one file").
- The summary covers a region when that region's section of `summary.md` (its lines from the
  one naming the region until a line naming another) has its total and claims its top product.

3 = every part right, the summary covers every region, and 2 to 4 sub-sessions were opened;
2 = the same without that (no sub-session, too many, or no tool record to count them);
1 = at least one part right or one region covered; 0 = nothing.
"""

from __future__ import annotations

import random
import re
from collections import Counter
from pathlib import Path

from scripts.kernel_bench import tool_record

REGIONS = ("north", "south", "west")
PRODUCTS = ("kettle", "lamp", "fan", "heater", "blender", "toaster")
ROWS = 300


def fixture(run: str, seed: int = 64) -> dict:
    """The tables, and each region's answer for the runner (never written to the agent's folder)."""
    rng = random.Random(seed)
    answers: dict[str, dict] = {}
    for region in REGIONS:
        while True:
            rows = [
                (
                    f"{region[0].upper()}{i:04d}",
                    rng.choice(PRODUCTS),
                    rng.randint(1, 9),
                    rng.randint(500, 9999),
                )
                for i in range(1, ROWS + 1)
            ]
            qty: Counter = Counter()
            for _, product, n, _ in rows:
                qty[product] += n
            (top, first), (_, second) = qty.most_common(2)
            cents = sum(n * price for _, _, n, price in rows)
            if first != second and all(
                a["total"] != f"{cents / 100:.2f}" for a in answers.values()
            ):
                break
        folder = Path(run) / "regions" / region
        folder.mkdir(parents=True, exist_ok=True)
        lines = ["order_id,product,qty,unit_price"] + [
            f"{o},{p},{n},{c / 100:.2f}" for o, p, n, c in rows
        ]
        (folder / "orders.csv").write_text("\n".join(lines) + "\n")
        answers[region] = {"total": f"{cents / 100:.2f}", "top": top}
    return {"answers": answers}


def _plain(text: str) -> str:
    """Thousands separators out: 12,345.67 -> 12345.67."""
    return re.sub(r"(?<=\d)[,，'](?=\d{3}\b)", "", text)


def _read(path: Path) -> str:
    return _plain(path.read_text(encoding="utf-8", errors="ignore")) if path.is_file() else ""


CLAIM = re.compile(r"最高|最多|第一|畅销|\btop\b|\bbest\b|\bmost\b", re.I)


def _named(line: str, words) -> set[str]:
    return {w for w in words if re.search(rf"(?<![a-z]){w}(?![a-z])", line)}


def claims_top(text: str, top: str) -> bool:
    """A line claiming the top product names `top` and no other, and none names only a wrong one."""
    said = [_named(line, PRODUCTS) for line in text.splitlines() if CLAIM.search(line)]
    said = [s for s in said if s]
    return any(s == {top} for s in said) and not any(len(s) == 1 and s != {top} for s in said)


def _sections(text: str) -> dict[str, str]:
    """Each region's lines: from a line naming that region (and no other) until one naming another."""
    out: dict[str, list[str]] = {r: [] for r in REGIONS}
    current = None
    for line in text.splitlines():
        here = _named(line, REGIONS)
        if len(here) == 1:
            current = next(iter(here))
        elif len(here) > 1:
            current = None
        if current:
            out[current].append(line)
    return {r: "\n".join(lines) for r, lines in out.items()}


def check(run: str, params: dict, names: list[str] | None, who: str) -> dict:
    answers = params["answers"]
    parts, covered = {}, {}
    sections = _sections(_read(Path(run) / "summary.md").lower())
    for region, want in answers.items():
        text = _read(Path(run) / "out" / f"{region}.md").lower()
        others = [a["total"] for r, a in answers.items() if r != region]
        parts[region] = (
            want["total"] in text
            and claims_top(text, want["top"])
            and not any(t in text for t in others)
        )
        section = sections.get(region, "")
        covered[region] = want["total"] in section and claims_top(section, want["top"])
    subs = tool_record.sub_sessions(who, names) if names is not None else None
    whole = all(parts.values()) and all(covered.values())
    if whole:
        score = 3 if subs is not None and 2 <= subs <= 4 else 2
    else:
        score = 1 if any(parts.values()) or any(covered.values()) else 0
    return {
        "score": score,
        "sub_sessions": subs,
        "tool_record": names is not None,
        "parts_right": sorted(r for r, ok in parts.items() if ok),
        "summary_covers": sorted(r for r, ok in covered.items() if ok),
    }
