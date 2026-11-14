"""Tests for scripts/dev/claude_usage_tables.py (synthetic fixtures only)."""

from __future__ import annotations

import csv
import importlib.util
import io
import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "dev" / "claude_usage_tables.py"
_spec = importlib.util.spec_from_file_location("claude_usage_tables", _SCRIPT)
assert _spec and _spec.loader
cut = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cut)

SENTINEL = "SENTINEL-CONTENT-DO-NOT-READ"


def assistant(
    mid: str | None,
    ts: str,
    *,
    sid: str = "sess-a",
    model: str = "model-x",
    inp: int = 0,
    cr: int = 0,
    cw: int = 0,
    out: int = 0,
    request_id: str | None = None,
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "model": model,
        "usage": {
            "input_tokens": inp,
            "cache_read_input_tokens": cr,
            "cache_creation_input_tokens": cw,
            "output_tokens": out,
            "server_tool_use": {"note": SENTINEL},
        },
        "content": [{"type": "text", "text": SENTINEL}],
    }
    if mid is not None:
        message["id"] = mid
    rec: dict[str, Any] = {
        "type": "assistant",
        "sessionId": sid,
        "timestamp": ts,
        "isSidechain": False,
        "message": message,
        "content": SENTINEL,
        "text": SENTINEL,
        "toolUseResult": {"stdout": SENTINEL},
        "tool_input": {"command": SENTINEL},
    }
    if request_id:
        rec["requestId"] = request_id
    return rec


def title(sid: str, text: str, ts: str | None = None) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "type": "custom-title",
        "customTitle": text,
        "sessionId": sid,
        "content": SENTINEL,
    }
    if ts:
        rec["timestamp"] = ts
    return rec


def write(path: Path, records: list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(r if isinstance(r, str) else json.dumps(r) for r in records) + "\n",
        encoding="utf-8",
    )


def run(root: Path, capsys: pytest.CaptureFixture[str], *args: str, wrap: Any = None) -> str:
    assert cut.main(["--root", str(root), *args], wrap=wrap) == 0
    return capsys.readouterr().out


def csv_rows(text: str) -> list[list[str]]:
    return [r for r in csv.reader(io.StringIO(text)) if r]


def detail_rows(text: str) -> list[list[str]]:
    rows = csv_rows(text)
    end = rows.index(cut.SUMMARY_HEAD)
    return rows[1:end]


def summary_rows(text: str) -> list[list[str]]:
    rows = csv_rows(text)
    return rows[rows.index(cut.SUMMARY_HEAD) + 1 :]


T1 = "2026-03-01T10:00:00.000Z"


def test_dedupe_across_records_and_subagent_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    proj = tmp_path / "proj"
    msg = assistant("msg-1", T1, inp=10, cr=20, cw=30, out=5)
    partial = assistant("msg-1", T1, inp=10, cr=20, cw=30, out=2)
    other = assistant("msg-2", T1, inp=1, cr=2, cw=3, out=4)
    write(proj / "sess-a.jsonl", [partial, msg, other])
    write(proj / "sess-a" / "subagents" / "agent-1.jsonl", [msg])
    out = run(tmp_path, capsys, "--format", "csv")
    rows = detail_rows(out)
    assert len(rows) == 1
    # hand sum: msg-1 (largest output, 10/20/30/5) + msg-2 (1/2/3/4)
    assert rows[0][5:9] == ["11", "22", "33", "9"]


def test_dedupe_falls_back_to_request_id_and_keeps_keyless(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    recs = [
        assistant(None, T1, inp=1, out=1, request_id="req-1"),
        assistant(None, T1, inp=1, out=1, request_id="req-1"),
        assistant(None, T1, inp=5, out=5),
        assistant(None, T1, inp=5, out=5),
    ]
    write(tmp_path / "p" / "sess-a.jsonl", recs)
    rows = detail_rows(run(tmp_path, capsys, "--format", "csv"))
    assert rows[0][5:9] == ["11", "0", "0", "11"]


def test_subagent_counts_toward_parent_session(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    proj = tmp_path / "proj"
    write(proj / "sess-a.jsonl", [title("sess-a", "Lane A — test"), assistant("m1", T1, out=7)])
    # The record's own sessionId differs; the parent folder wins.
    write(
        proj / "sess-a" / "subagents" / "agent-9.jsonl",
        [assistant("m2", T1, sid="other-id", out=3)],
    )
    rows = detail_rows(run(tmp_path, capsys, "--format", "csv"))
    # One row per source; both belong to the parent session.
    assert [(r[2], r[4], r[8]) for r in rows] == [
        ("Lane A — test", "main", "7"),
        ("Lane A — test", "sub", "3"),
    ]


def test_split_by_utc_date_and_model(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    recs = [
        assistant("m1", "2026-03-01T23:59:59.000Z", out=1),
        assistant("m2", "2026-03-02T00:00:00.000Z", out=2),
        # 23:30 at -02:00 is 01:30 UTC the next day
        assistant("m3", "2026-03-02T23:30:00-02:00", out=4),
        assistant("m4", "2026-03-02T00:00:01.000Z", model="model-y", out=8),
    ]
    write(tmp_path / "p" / "sess-a.jsonl", recs)
    rows = detail_rows(run(tmp_path, capsys, "--format", "csv"))
    got = {(r[0], r[3]): r[8] for r in rows}
    assert got == {
        ("2026-03-01", "model-x"): "1",
        ("2026-03-02", "model-x"): "2",
        ("2026-03-03", "model-x"): "4",
        ("2026-03-02", "model-y"): "8",
    }


def test_latest_title_and_lane_prefix(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    proj = tmp_path / "p"
    write(
        proj / "s1.jsonl",
        [
            title("s1", "Old name", "2026-03-01T00:00:00Z"),
            title("s1", "Lane A — test one", "2026-03-01T05:00:00Z"),
            title("s1", "Stale name", "2026-03-01T01:00:00Z"),
            assistant("a", T1, sid="s1", out=1),
        ],
    )
    write(
        proj / "s2.jsonl", [title("s2", "Lane A2 — test two"), assistant("b", T1, sid="s2", out=2)]
    )
    write(proj / "s3.jsonl", [title("s3", "Unrelated"), assistant("c", T1, sid="s3", out=4)])
    write(proj / "s4.jsonl", [assistant("d", T1, sid="s4", out=8)])
    lanes = tmp_path / "lanes.json"
    lanes.write_text(json.dumps({"Lane A": "lane-a"}), encoding="utf-8")
    out = run(
        tmp_path, capsys, "--format", "csv", "--lanes", str(lanes), "--lane", "Lane A2=lane-a2"
    )
    rows = {r[2]: r[1] for r in detail_rows(out)}
    assert rows == {
        "Lane A — test one": "lane-a",
        "Lane A2 — test two": "lane-a2",  # longest prefix wins
        "Unrelated": "other",
        "s4": "other",  # no title: session id shown
    }
    summary = {(r[0], r[1]): r[6] for r in summary_rows(out)}
    assert summary[("2026-03-01", "other")] == "12"


def test_content_never_in_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(
        tmp_path / "p" / "s1.jsonl",
        [title("s1", "Lane A — test"), assistant("m1", T1, sid="s1", out=3)],
    )
    write(tmp_path / "p" / "s1" / "subagents" / "a.jsonl", [assistant("m2", T1, sid="s1", out=3)])
    for fmt in ("md", "csv"):
        assert SENTINEL not in run(tmp_path, capsys, "--format", fmt)
    assert SENTINEL not in capsys.readouterr().err


class Guard(Mapping[str, Any]):
    """Mapping that raises on any key outside the allow-list, and on iteration."""

    def __init__(self, data: Mapping[str, Any], schema: Mapping[str, Any], seen: set[str]) -> None:
        self._data = data
        self._schema = schema
        self._seen = seen

    def __getitem__(self, key: str) -> Any:
        if key not in self._schema:
            raise AssertionError(f"non-allow-listed key accessed: {key}")
        self._seen.add(key)
        value = self._data[key]
        sub = self._schema[key]
        if isinstance(value, dict) and sub:
            return Guard(value, sub, self._seen)
        return value

    def __iter__(self) -> Iterator[str]:
        raise AssertionError("iteration over a raw record")

    def __len__(self) -> int:
        raise AssertionError("len() of a raw record")


USAGE_SCHEMA = {k: None for k in cut.USAGE_KEYS}
SCHEMA = {
    "type": None,
    "sessionId": None,
    "timestamp": None,
    "requestId": None,
    "isSidechain": None,
    "customTitle": None,
    "message": {"id": None, "model": None, "usage": USAGE_SCHEMA},
}


def test_projection_only_touches_allow_listed_keys(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(
        tmp_path / "p" / "s1.jsonl",
        [
            title("s1", "Lane A — test"),
            assistant("m1", T1, sid="s1", inp=1, cr=2, cw=3, out=4, request_id="r"),
        ],
    )
    write(tmp_path / "p" / "s1" / "subagents" / "a.jsonl", [assistant("m2", T1, sid="s1", out=5)])
    seen: set[str] = set()
    out = run(
        tmp_path,
        capsys,
        "--format",
        "csv",
        wrap=lambda d: Guard(d, SCHEMA, seen),
    )
    rows = detail_rows(out)
    assert [r[4:9] for r in rows] == [
        ["main", "1", "2", "3", "4"],
        ["sub", "0", "0", "0", "5"],
    ]
    assert {"message", "usage", "output_tokens", "customTitle", "id"} <= seen
    assert not seen & {"content", "text", "toolUseResult", "tool_input", "server_tool_use"}


def test_project_output_keys_are_allow_listed() -> None:
    proj = cut.project(assistant("m", T1, out=1))
    assert set(proj) == {
        "kind",
        "message_id",
        "model",
        "request_id",
        "session_id",
        "timestamp",
        "sidechain",
        "tokens",
    }
    assert SENTINEL not in json.dumps(proj)
    tproj = cut.project(title("s", "T"))
    assert set(tproj) == {"kind", "title", "session_id", "timestamp"}
    assert cut.project({"type": "user", "message": {"content": SENTINEL}}) is None


def test_malformed_lines_skipped(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(
        tmp_path / "p" / "s1.jsonl",
        [
            "{not json",
            assistant("m1", T1, sid="s1", out=5),
            "[1, 2]",
            '{"type": "assistant", "message": 5}',
        ],
    )
    assert cut.main(["--root", str(tmp_path), "--format", "csv"]) == 0
    cap = capsys.readouterr()
    assert detail_rows(cap.out)[0][8] == "5"
    assert "skipped 2 malformed" in cap.err


def test_since_until_inclusive(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    recs = [assistant(f"m{d}", f"2026-03-0{d}T12:00:00Z", out=d) for d in (1, 2, 3, 4)]
    write(tmp_path / "p" / "s1.jsonl", recs)
    out = run(tmp_path, capsys, "--format", "csv", "--since", "2026-03-02", "--until", "2026-03-03")
    assert [r[0] for r in detail_rows(out)] == ["2026-03-02", "2026-03-03"]
    assert [r[0] for r in summary_rows(out)] == ["2026-03-02", "2026-03-03"]


def test_markdown_layout(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(
        tmp_path / "p" / "s1.jsonl",
        [title("s1", "Lane A — test"), assistant("m1", T1, sid="s1", inp=1, out=2)],
    )
    out = run(tmp_path, capsys, "--lane", "Lane A=lane-a")
    assert (
        out.splitlines()[0]
        == "| date | lane | session | model | source | input | cache_read | cache_write | output"
        " | requests | avg_context | cache_rewrites |"
    )
    assert (
        "| 2026-03-01 | lane-a | Lane A — test | model-x | main | 1 | 0 | 0 | 2 | 1 | 0 | 0 |"
        in out
    )
    assert "Per-lane daily totals" in out
    assert "| 2026-03-01 | lane-a | main | 1 | 0 | 0 | 2 | 1 | 0 | 0 |" in out


def _col(rows: list[list[str]], name: str) -> list[str]:
    idx = (
        cut.DETAIL_HEAD.index(name)
        if len(rows[0]) == len(cut.DETAIL_HEAD)
        else cut.SUMMARY_HEAD.index(name)
    )
    return [r[idx] for r in rows]


def test_requests_counted_after_dedupe(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    recs = [
        assistant("m1", T1, out=1),
        assistant("m1", T1, out=9),  # duplicate, kept as one request
        assistant("m2", T1, out=1),
        assistant(None, T1, out=1, request_id="r1"),
        assistant(None, T1, out=1, request_id="r1"),
        assistant(None, T1, out=1),  # keyless: always counted
    ]
    write(tmp_path / "p" / "sess-a.jsonl", recs)
    rows = detail_rows(run(tmp_path, capsys, "--format", "csv"))
    assert _col(rows, "requests") == ["4"]


def test_avg_context_floor_and_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    recs = [
        assistant("m1", T1, cr=10),
        assistant("m2", T1, cr=5),
        assistant("m3", T1, cr=0),
        # a record with no usage at all still counts as a request with zero cache_read
        {"type": "assistant", "sessionId": "sess-b", "timestamp": T1, "message": {"id": "m4"}},
    ]
    write(tmp_path / "p" / "sess-a.jsonl", recs[:3])
    write(tmp_path / "p" / "sess-b.jsonl", recs[3:])
    rows = detail_rows(run(tmp_path, capsys, "--format", "csv"))
    by_session = {r[2]: (r[9], r[10]) for r in rows}
    assert by_session["sess-a"] == ("3", "5")  # 15 // 3
    assert by_session["sess-b"] == ("1", "0")
    assert cut._columns([0, 7, 0, 0, 2, 0])[5] == 3  # floor of 3.5
    assert cut._columns([0, 0, 0, 0, 0, 0])[5] == 0  # no requests


@pytest.mark.parametrize(
    ("cr", "cw", "inp", "expected"),
    [
        (21_000, 79_000, 0, False),  # 79% write
        (20_000, 80_000, 0, True),  # exactly 80%
        (0, 100_000, 0, True),  # all write
        (25_000, 25_000, 0, False),  # context exactly 50,000 is not counted
        (10_000, 40_001, 0, True),  # 50,001, write share ~80.0%
        (10_000, 40_000, 1, True),  # input counts toward the context: 50,001
        (10_000, 40_000, 0, False),  # 50,000 exactly
        (0, 0, 60_000, False),  # no cache at all
    ],
)
def test_cache_rewrite_thresholds(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], cr: int, cw: int, inp: int, expected: bool
) -> None:
    assert cut.REWRITE_WRITE_SHARE == 0.8
    assert cut.REWRITE_MIN_CONTEXT == 50_000
    write(tmp_path / "p" / "sess-a.jsonl", [assistant("m1", T1, inp=inp, cr=cr, cw=cw)])
    rows = detail_rows(run(tmp_path, capsys, "--format", "csv"))
    assert _col(rows, "cache_rewrites") == [("1" if expected else "0")]


def test_main_sub_split_and_totals(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    proj = tmp_path / "p"
    write(
        proj / "s1.jsonl",
        [
            title("s1", "Lane A — test"),
            assistant("a1", T1, sid="s1", cr=100, cw=0, out=1),
            assistant("a2", T1, sid="s1", cr=0, cw=60_000, out=1),  # rewrite
        ],
    )
    write(
        proj / "s2.jsonl",
        [
            title("s2", "Lane A — other"),
            assistant("b1", T1, sid="s2", model="model-y", cr=50, out=1),
        ],
    )
    write(
        proj / "s1" / "subagents" / "x.jsonl",
        [
            assistant("c1", T1, sid="s1", cr=40, out=1),
            assistant("c2", T1, sid="s1", cr=0, cw=70_000, out=1),  # rewrite
            assistant("c3", T1, sid="s1", cr=1, out=1),
        ],
    )
    out = run(tmp_path, capsys, "--format", "csv", "--lane", "Lane A=lane-a")
    detail = detail_rows(out)
    assert [(r[2], r[3], r[4], r[9], r[10], r[11]) for r in detail] == [
        ("Lane A — other", "model-y", "main", "1", "50", "0"),
        ("Lane A — test", "model-x", "main", "2", "50", "1"),
        ("Lane A — test", "model-x", "sub", "3", "13", "1"),
    ]
    # Totals: date, lane, source, in, cr, cw, out, requests, avg_context, rewrites
    assert summary_rows(out) == [
        ["2026-03-01", "lane-a", "main", "0", "150", "60000", "3", "3", "50", "1"],
        ["2026-03-01", "lane-a", "sub", "0", "41", "70000", "3", "3", "13", "1"],
    ]
