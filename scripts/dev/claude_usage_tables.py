#!/usr/bin/env python3
"""Per-session, per-day token tables from Claude Code's local transcripts.

Purpose
-------
Claude Code stores each local session as a JSONL transcript under
``~/.claude/projects/<project>/<session>.jsonl`` (subagent runs live in
``<project>/<session-id>/subagents/*.jsonl``). This script sums the token
usage in those files per UTC date, session and model, optionally grouped
into "lanes" by session title, and prints a Markdown or CSV table.

Privacy rule: usage fields only
-------------------------------
Transcripts contain prompts, replies and tool output. This script never
reads any of that. Every parsed record goes through ``project()``, the only
place that touches the parsed dict, and it returns an allow-listed
projection: ``message.usage.{input_tokens, cache_read_input_tokens,
cache_creation_input_tokens, output_tokens}``, ``message.id``,
``message.model``, ``sessionId``, ``timestamp``, ``requestId``,
``isSidechain`` and, for ``custom-title`` records, ``customTitle``. The rest
of the code only sees that projection, so it cannot reach content.

Dedupe
------
The same assistant message is written several times (streaming partials,
copies in subagent files, resumed sessions). We keep one record per
``message.id`` (falling back to ``requestId``; a record with neither is
always kept). Among duplicates we keep the one with the largest
``output_tokens`` (a streamed partial reports fewer output tokens than the
final record), and on a tie the first one seen. Files are read in sorted
path order, so the result is deterministic.

Limits
------
Cloud sessions have no local transcript; they report their own usage and do
not appear here.

Usage
-----
    python3 scripts/dev/claude_usage_tables.py [--root DIR] [--since YYYY-MM-DD]
        [--until YYYY-MM-DD] [--lanes FILE] [--lane "prefix=lane"] [--format md|csv]

``--lanes FILE`` is a local JSON object ``{"title or title-prefix": "lane"}``;
the longest matching prefix wins; unmapped sessions go to lane "other".
No default map is shipped.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from collections.abc import Callable, Iterator, Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

USAGE_KEYS = (
    "input_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
    "output_tokens",
)
FIELDS = ("input", "cache_read", "cache_write", "output")
UNKNOWN_DATE = "unknown"


def _num(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0
    return max(int(value), 0)


def _str(value: object) -> str:
    return value if isinstance(value, str) else ""


def project(rec: object) -> dict[str, Any] | None:
    """Return the allow-listed projection of one parsed record, or None.

    This is the ONLY function that reads the parsed dict. Nothing else in
    this module may index into a raw record.
    """
    if not isinstance(rec, Mapping):
        return None
    rtype = _str(rec.get("type"))
    if rtype == "custom-title":
        return {
            "kind": "title",
            "title": _str(rec.get("customTitle")),
            "session_id": _str(rec.get("sessionId")),
            "timestamp": _str(rec.get("timestamp")),
        }
    if rtype != "assistant":
        return None
    message = rec.get("message")
    if not isinstance(message, Mapping):
        return None
    usage = message.get("usage")
    tokens = [0, 0, 0, 0]
    if isinstance(usage, Mapping):
        tokens = [_num(usage.get(k)) for k in USAGE_KEYS]
    return {
        "kind": "usage",
        "message_id": _str(message.get("id")),
        "model": _str(message.get("model")) or "unknown",
        "request_id": _str(rec.get("requestId")),
        "session_id": _str(rec.get("sessionId")),
        "timestamp": _str(rec.get("timestamp")),
        "sidechain": rec.get("isSidechain") is True,
        "tokens": tokens,
    }


def find_files(root: Path) -> list[tuple[Path, str | None]]:
    """Return (path, parent_session_id or None) in sorted order."""
    out: list[tuple[Path, str | None]] = []
    if not root.is_dir():
        return out
    for project_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for f in sorted(project_dir.glob("*.jsonl")):
            out.append((f, None))
        for session_dir in sorted(p for p in project_dir.iterdir() if p.is_dir()):
            for f in sorted((session_dir / "subagents").glob("*.jsonl")):
                out.append((f, session_dir.name))
    return out


def iter_projected(
    path: Path,
    wrap: Callable[[Any], Any] | None,
    skipped: list[int],
) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
            except ValueError:
                skipped[0] += 1
                continue
            if wrap is not None:
                parsed = wrap(parsed)
            if not isinstance(parsed, Mapping):
                skipped[0] += 1
                continue
            proj = project(parsed)
            if proj is not None:
                yield proj


def utc_date(timestamp: str) -> str:
    if not timestamp:
        return UNKNOWN_DATE
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return UNKNOWN_DATE
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).date().isoformat()


def collect(
    root: Path, wrap: Callable[[Any], Any] | None = None
) -> tuple[dict[tuple[str, str, str], list[int]], dict[str, str], int]:
    """Return ({(date, session, model): [4 sums]}, {session: title}, skipped)."""
    skipped = [0]
    best: dict[str, dict[str, Any]] = {}  # dedupe key -> chosen record
    unkeyed: list[dict[str, Any]] = []
    titles: dict[str, tuple[tuple[str, int], str]] = {}
    seq = 0
    for path, parent in find_files(root):
        for proj in iter_projected(path, wrap, skipped):
            seq += 1
            sid = parent or proj["session_id"] or path.stem
            if proj["kind"] == "title":
                if parent is None and proj["title"]:
                    order = (proj["timestamp"], seq)
                    if sid not in titles or order >= titles[sid][0]:
                        titles[sid] = (order, proj["title"])
                continue
            proj["session_id"] = sid
            key = proj["message_id"] or proj["request_id"]
            if not key:
                unkeyed.append(proj)
            elif key not in best or proj["tokens"][3] > best[key]["tokens"][3]:
                best[key] = proj
    rows: dict[tuple[str, str, str], list[int]] = {}
    for proj in [*best.values(), *unkeyed]:
        k = (utc_date(proj["timestamp"]), proj["session_id"], proj["model"])
        acc = rows.setdefault(k, [0, 0, 0, 0])
        for i, v in enumerate(proj["tokens"]):
            acc[i] += v
    return rows, {s: t for s, (_, t) in titles.items()}, skipped[0]


def lane_for(title: str, lanes: Mapping[str, str]) -> str:
    best = ""
    for prefix in lanes:
        if title.startswith(prefix) and len(prefix) > len(best):
            best = prefix
    return lanes[best] if best else "other"


def build_tables(
    rows: Mapping[tuple[str, str, str], list[int]],
    titles: Mapping[str, str],
    lanes: Mapping[str, str],
    since: date | None,
    until: date | None,
) -> tuple[list[list[Any]], list[list[Any]]]:
    detail: list[list[Any]] = []
    totals: dict[tuple[str, str], list[int]] = {}
    for (day, sid, model), sums in rows.items():
        if since or until:
            if day == UNKNOWN_DATE:
                continue
            d = date.fromisoformat(day)
            if (since and d < since) or (until and d > until):
                continue
        title = titles.get(sid, sid)
        lane = lane_for(title, lanes)
        detail.append([day, lane, title, model, *sums])
        acc = totals.setdefault((day, lane), [0, 0, 0, 0])
        for i, v in enumerate(sums):
            acc[i] += v
    detail.sort(key=lambda r: (r[0], r[1], r[2], r[3]))
    summary = [[d, ln, *s] for (d, ln), s in sorted(totals.items())]
    return detail, summary


DETAIL_HEAD = ["date", "lane", "session", "model", *FIELDS]
SUMMARY_HEAD = ["date", "lane", *FIELDS]


def render_md(detail: list[list[Any]], summary: list[list[Any]]) -> str:
    def table(head: list[str], body: list[list[Any]]) -> list[str]:
        lines = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
        for r in body:
            cells = [str(c).replace("|", "\\|").replace("\n", " ") for c in r]
            lines.append("| " + " | ".join(cells) + " |")
        return lines

    out = table(DETAIL_HEAD, detail) + ["", "Per-lane daily totals", ""]
    out += table(SUMMARY_HEAD, summary)
    return "\n".join(out) + "\n"


def render_csv(detail: list[list[Any]], summary: list[list[Any]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(DETAIL_HEAD)
    w.writerows(detail)
    buf.write("\n")
    w.writerow(SUMMARY_HEAD)
    w.writerows(summary)
    return buf.getvalue()


def _parse_date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {text!r}") from exc


def main(argv: list[str] | None = None, *, wrap: Callable[[Any], Any] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Per-session daily token tables from local transcripts."
    )
    ap.add_argument("--root", type=Path, default=Path.home() / ".claude" / "projects")
    ap.add_argument("--since", type=_parse_date)
    ap.add_argument("--until", type=_parse_date)
    ap.add_argument("--lanes", type=Path, help="JSON object {title-prefix: lane}")
    ap.add_argument("--lane", action="append", default=[], metavar="PREFIX=LANE")
    ap.add_argument("--format", choices=("md", "csv"), default="md")
    args = ap.parse_args(argv)

    lanes: dict[str, str] = {}
    if args.lanes:
        data = json.loads(args.lanes.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            ap.error("--lanes file must be a JSON object")
        lanes.update({str(k): str(v) for k, v in data.items()})
    for item in args.lane:
        prefix, sep, lane = item.rpartition("=")
        if not sep or not prefix:
            ap.error(f"--lane expects PREFIX=LANE, got {item!r}")
        lanes[prefix] = lane

    rows, titles, skipped = collect(args.root, wrap)
    detail, summary = build_tables(rows, titles, lanes, args.since, args.until)
    text = render_csv(detail, summary) if args.format == "csv" else render_md(detail, summary)
    sys.stdout.write(text)
    print(f"skipped {skipped} malformed line(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
