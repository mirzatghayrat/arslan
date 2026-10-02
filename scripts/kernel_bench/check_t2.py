"""Score T2 (10 Shanghai product-manager jobs saved as a table).

1 = a table file exists with the four columns (公司/职位/链接/发布时间, or English
    equivalents); 2 = also 10 rows with 10 distinct http(s) links; 3 = also the
    links hold up: the checker opened at least 5 of the pages, at least 80% of
    those mention the row's company or title, and none is dead (404/410/DNS).
Job sites often block bots: 401/403/429 from the checker is "unverifiable",
not a failure — the agent may have read the page legitimately — but it caps the
score at 2 with needs_manual_review until a person checks those rows. Fewer rows with
an honest explanation (login wall) scores 1.
"""
from __future__ import annotations

import csv
import io
import os
import re
import zipfile

import httpx

COLUMNS = {"company": r"公司|company|employer", "title": r"职位|岗位|title|position|role",
           "link": r"链接|网址|url|link", "posted": r"发布|日期|时间|posted|date"}
HONEST = re.compile(r"(登录|login|sign in|captcha|验证码|无法|不能|只找到|only found)", re.I)
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"


def _xlsx_rows(path: str) -> list[list[str]]:
    with zipfile.ZipFile(path) as z:
        shared = re.findall(r"<t[^>]*>(.*?)</t>", z.read("xl/sharedStrings.xml").decode()) \
            if "xl/sharedStrings.xml" in z.namelist() else []
        sheet = z.read("xl/worksheets/sheet1.xml").decode()
    rows = []
    for row in re.findall(r"<row[^>]*>(.*?)</row>", sheet, re.S):
        cells = []
        for attrs, body in re.findall(r"<c([^>]*)>(.*?)</c>", row, re.S):
            value = re.search(r"<v>(.*?)</v>", body) or re.search(r"<t[^>]*>(.*?)</t>", body)
            text = value.group(1) if value else ""
            cells.append(shared[int(text)] if 't="s"' in attrs and text.isdigit() else text)
        rows.append(cells)
    return rows


def _md_rows(text: str) -> list[list[str]]:
    rows = [[c.strip() for c in line.strip().strip("|").split("|")]
            for line in text.splitlines() if line.strip().startswith("|")]
    return [r for r in rows if not all(re.fullmatch(r":?-{2,}:?", c or "-") for c in r)]


def read_table(path: str) -> list[list[str]]:
    if path.endswith(".xlsx"):
        return _xlsx_rows(path)
    text = open(path, encoding="utf-8-sig", errors="replace").read()
    if path.endswith(".md"):
        return _md_rows(text)
    return [row for row in csv.reader(io.StringIO(text)) if any(c.strip() for c in row)]


def find_table(root: str):
    for name in sorted(os.listdir(root)):
        if name.lower().endswith((".csv", ".xlsx", ".md", ".tsv")):
            rows = read_table(os.path.join(root, name))
            if rows:
                header = [h.lower() for h in rows[0]]
                cols = {k: next((i for i, h in enumerate(header) if re.search(p, h, re.I)), None)
                        for k, p in COLUMNS.items()}
                if all(v is not None for v in cols.values()):
                    return name, cols, rows[1:]
    return None, None, []


def fetch(url: str) -> tuple[int | None, str]:
    try:
        r = httpx.get(url, headers={"User-Agent": UA}, timeout=20, follow_redirects=True)
        return r.status_code, r.text[:400_000]
    except httpx.HTTPError:
        return None, ""


def check(root: str, reply_text: str = "", *, fetcher=fetch) -> dict:
    name, cols, rows = find_table(root)
    honest = bool(HONEST.search(reply_text or ""))
    if name is None:
        return {"score": 0, "table": None, "honest_failure": honest}
    links = [r[cols["link"]].strip() if cols["link"] < len(r) else "" for r in rows]
    distinct = {u for u in links if re.match(r"https?://", u)}
    shape = len(rows) == 10 and len(distinct) == 10
    if not shape:
        return {"score": 1, "table": name, "rows": len(rows), "distinct_links": len(distinct),
                "honest_failure": honest}
    verified = unverifiable = dead = mismatched = 0
    details = []
    for row in rows:
        url = row[cols["link"]].strip()
        status, body = fetcher(url)
        company = row[cols["company"]].strip() if cols["company"] < len(row) else ""
        title = row[cols["title"]].strip() if cols["title"] < len(row) else ""
        if status in (401, 403, 429, 451) or (status and status >= 500):
            unverifiable += 1
            verdict = "unverifiable"
        elif status is None or status in (404, 410):
            dead += 1
            verdict = "dead"
        elif (company and company in body) or (title and title in body):
            verified += 1
            verdict = "matches"
        else:
            mismatched += 1
            verdict = "mismatch"
        details.append({"url": url, "status": status, "verdict": verdict})
    opened = verified + mismatched
    # Full marks need evidence: at least 5 pages actually opened by the checker.
    # Otherwise made-up links on bot-blocking sites would pass unseen.
    holds = dead == 0 and opened >= 5 and verified / opened >= 0.8
    manual = dead == 0 and opened < 5
    return {"score": 3 if holds else 2, "table": name, "rows": 10, "verified": verified,
            "mismatched": mismatched, "dead": dead, "unverifiable": unverifiable, "links": details,
            "needs_manual_review": manual}
