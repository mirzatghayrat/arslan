"""Host link check on a saved table (0.1.50, S6 bench T2).

With a working browser, finding ten postings stopped being the problem; links
did: one run reused search pages for several rows, another wrote six links that
open other jobs (built, not opened). After a research turn saves a text file of
links, two deterministic facts come back to the model as a host hint:

- links shared by several lines (a row's link must open that row's item);
- links that never appeared in this turn's search results, opened pages or
  command output (a link the turn never saw is a guess).

Facts only — no model judges anything here. The model decides: open and replace,
or mark the rows unverified.
"""
from __future__ import annotations

import json
import re
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

_URL = re.compile(r"https?://[^\s\"'<>()\[\]{}，。、；“”‘’|\\]+", re.I)   # \\: JSON-escaped quotes
_TRAIL = ".,;:!?)]}>'\""
TEXT_SUFFIXES = {".csv", ".tsv", ".md", ".markdown", ".txt", ".json", ".html"}
_NOT_EVIDENCE = {"write_file", "edit_file", "update_plan"}
MIN_LINKS = 3                     # fewer link occurrences than this is not a table of links
MAX_HINTS_PER_FILE = 2
_EXAMPLES = 3


def normalize(url: str) -> str:
    """Comparable form: decoded, no fragment, scheme- and www-insensitive, no trailing slash."""
    url = unquote(url.strip().rstrip(_TRAIL))
    parts = urlsplit(url)
    host = parts.netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    path = parts.path.rstrip("/")
    return f"{host}{path}" + (f"?{parts.query}" if parts.query else "")


def urls_in(text: str) -> list[str]:
    return [m.group(0).rstrip(_TRAIL) for m in _URL.finditer(text or "")]


def evidence(tool_trace: list[dict]) -> set[str]:
    """Every link this turn saw: in any tool result (search results, page text,
    snapshots, command output) or as the address it opened."""
    seen: set[str] = set()
    for item in tool_trace:
        if item.get("tool") in _NOT_EVIDENCE:
            continue
        result = item.get("result") or {}
        if not result.get("ok"):
            continue
        text = json.dumps(result, ensure_ascii=False, default=str)
        opened = (item.get("args") or {}).get("url")
        for url in urls_in(text) + ([opened] if isinstance(opened, str) else []):
            seen.add(normalize(url))
    return seen


def review(content: str, seen: set[str]) -> dict | None:
    """{"shared": {url: [line numbers]}, "unseen": [urls]} or None when the file
    is not a table of links or nothing is wrong."""
    per_line: dict[str, list[int]] = {}
    for number, line in enumerate((content or "").splitlines(), start=1):
        for url in dict.fromkeys(urls_in(line)):
            per_line.setdefault(url, []).append(number)
    if sum(len(lines) for lines in per_line.values()) < MIN_LINKS:
        return None
    shared = {url: lines for url, lines in per_line.items() if len(lines) > 1}
    unseen = [url for url in per_line if normalize(url) not in seen]
    return {"shared": shared, "unseen": unseen} if shared or unseen else None


def hint(path: str, found: dict) -> str:
    parts = []
    for url, lines in list(found["shared"].items())[:_EXAMPLES]:
        parts.append(f"lines {', '.join(map(str, lines))} use the same link ({url})")
    if found["unseen"]:
        sample = ", ".join(found["unseen"][:_EXAMPLES])
        parts.append(f"{len(found['unseen'])} links never appeared in this turn's search results, opened "
                     f"pages or command output (e.g. {sample})")
    return (f"\n[Host check on {PurePosixPath(path).name}: " + "; ".join(parts) + ". A link must open the page "
            "for its own row: open the doubtful ones (web_extract or browser_open) and replace any that show "
            "something else, then save again. If you cannot check them, mark them unverified in the file and "
            "say so.]")


def applies(path: str) -> bool:
    return PurePosixPath(path or "").suffix.lower() in TEXT_SUFFIXES
