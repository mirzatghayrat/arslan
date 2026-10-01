"""Score T3: a table file in the folder with Apple FY2023-FY2025 revenue and net income (SEC 10-K)."""

import os
import sys
import re
import json


def check(root: str) -> dict:
    TRUTH = {"rev": [383.285, 391.035, 416.161], "ni": [96.995, 93.736, 112.010]}  # $ billions
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

        hits = sum(found(x) for x in TRUTH["rev"] + TRUTH["ni"])
        src = bool(re.search(r"sec\.gov|10-K|investor\.apple\.com", t, re.I))
        if best is None or hits > best[1]:
            best = (os.path.relpath(p, root), hits, src)
    if not best:
        res = {"file": None, "correct_of_6": 0, "source": False, "score": 0}
    else:
        f, hits, src = best
        score = 3 if hits == 6 and src else 2 if hits >= 4 else 1 if hits >= 1 else 0
        res = {"file": f, "correct_of_6": hits, "source": src, "score": score}
    return res


if __name__ == "__main__":
    print(json.dumps(check(sys.argv[1]), ensure_ascii=False))
