"""Score T3: a table file in the folder with Apple's revenue and net income (SEC 10-K) for the
three fiscal years the task asks for.

The prompt asks for "the last three completed fiscal years", so which years are right depends on
the run's date, not on when this file was written (it used to fix FY2023-FY2025 and failed every
right answer once FY2026 was reported). A fiscal year counts once its 10-K is filed, the date
recorded in TRUTH. A year that has ended but has no row in TRUTH also counts: the check then
reports it under "no_truth" with score 0 instead of quietly scoring an older set of years. Add a
row from the 10-K when that happens; never from a secondary site.

    python -m scripts.kernel_bench.check_t3 RUN_FOLDER [YYYY-MM-DD]   (default: today)
"""

import datetime
import os
import sys
import re
import json

# Fiscal year -> (10-K filed, revenue, net income), $ billions. From each year's Form 10-K on SEC
# EDGAR (CIK 0000320193; us-gaap RevenueFromContractWithCustomerExcludingAssessedTax and
# NetIncomeLoss), accession number in the comment.
TRUTH = {
    2023: (datetime.date(2023, 11, 3), 383.285, 96.995),  # 0000320193-23-000106
    2024: (datetime.date(2024, 11, 1), 391.035, 93.736),  # 0000320193-24-000123
    2025: (datetime.date(2025, 10, 31), 416.161, 112.010),  # 0000320193-25-000079
    2026: (datetime.date(2026, 11, 3), 478.834, 132.175),  # 0000320193-26-000026
}


def fiscal_year_end(year: int) -> datetime.date:
    """Apple's fiscal year ends on the last Saturday of September."""
    end = datetime.date(year, 9, 30)
    return end - datetime.timedelta(days=(end.weekday() - 5) % 7)


def asked_years(when: datetime.date) -> list[int]:
    """The three fiscal years that were Apple's last completed ones on `when`."""
    year = when.year
    while True:
        done = when >= TRUTH[year][0] if year in TRUTH else when > fiscal_year_end(year)
        if done:
            return [year - 2, year - 1, year]
        year -= 1


def check(root: str, when: datetime.date | None = None) -> dict:
    years = asked_years(when or datetime.date.today())
    missing = [y for y in years if y not in TRUTH]
    if missing:
        return {"file": None, "correct_of_6": 0, "source": False, "score": 0, "years": years,
                "no_truth": missing}
    truth = [TRUTH[y][1] for y in years] + [TRUTH[y][2] for y in years]
    cands = []
    for d, _, fs in os.walk(root):
        for f in fs:
            if f.lower().endswith(
                (".csv", ".md", ".xlsx", ".txt", ".tsv", ".html", ".json")
            ) and not f.startswith("."):
                cands.append(os.path.join(d, f))

    def text_of(p):
        if p.endswith(".xlsx"):
            # An .xlsx is a zip of XML; read every cell's text and value without a library.
            import zipfile

            try:
                z = zipfile.ZipFile(p)
                return " ".join(
                    re.sub(r"<[^>]+>", " ", z.read(n).decode("utf-8", "ignore"))
                    for n in z.namelist()
                    if n.startswith("xl/") and n.endswith(".xml")
                )
            except Exception:
                return ""
        return open(p, encoding="utf-8", errors="ignore").read()

    best = None
    for p in cands:
        t = text_of(p)
        nums = []
        # Two readings, union: plain numbers (commas as separators between fields) and
        # thousands-grouped numbers. One reading alone glued "2023-09-30,383.29" into 30,383.
        for pat in (r"\d+(?:\.\d+)?", r"\d{1,3}(?:,\d{3})+(?:\.\d+)?"):
            for raw in re.findall(pat, t):
                try:
                    nums.append(float(raw.replace(",", "")))
                except ValueError:
                    pass

        def found(
            x,
        ):  # accept billions, millions, or raw dollars, within 0.3% (every honest whole-billion rounding of the true values is <= 0.28% off)
            return any(abs(n - x * k) <= x * k * 0.003 for n in nums for k in (1, 1e3, 1e9))

        hits = sum(found(x) for x in truth)
        src = bool(re.search(r"sec\.gov|10-K|investor\.apple\.com", t, re.I))
        if best is None or hits > best[1]:
            best = (os.path.relpath(p, root), hits, src)
    if not best:
        res = {"file": None, "correct_of_6": 0, "source": False, "score": 0}
    else:
        f, hits, src = best
        score = 3 if hits == 6 and src else 2 if hits >= 4 else 1 if hits >= 1 else 0
        res = {"file": f, "correct_of_6": hits, "source": src, "score": score}
    return {**res, "years": years}


if __name__ == "__main__":
    day = datetime.date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else None
    print(json.dumps(check(sys.argv[1], when=day), ensure_ascii=False))
