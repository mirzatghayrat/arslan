"""S7: the install-a-capability card writes a ledger row too (§5.4: every card is in the ledger).

The card stays as it is — the asking window's alone, carrying back the key the user typed and the folders
they picked (0.1.57 §3.1), so it does not ask through `permissions.decide`. Its answer is recorded after
it (`permissions.record_card_outcome`): allowed or refused by the user, or expired; never the key. A
scheduled run (nobody to ask) writes a `policy` refusal, which the Inbox lists (S1); a background job, which
never shows the window's card, writes nothing (⓪Plan, S7; CAP1a removed the finds)."""
from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta

import pytest

from server.db import session as db_session
from server.services import approvals, capability_flow, capability_search, permission_store, permissions

KEY = "s3cr3t-value-7f"
CAND = {"id": "registry:io.github.haris-musa/excel-mcp-server@1.1.2", "kind": "mcp", "name": "excel-mcp-server",
        "summary": "Reads and writes .xlsx", "source": "registry",
        "source_url": "https://github.com/haris-musa/excel-mcp-server",
        "repo": "haris-musa/excel-mcp-server", "version": "1.1.2", "runtime": "uv",
        "package": {"registry_type": "pypi", "identifier": "excel-mcp-server", "version": "1.1.2", "arguments": []},
        "remote": None, "not_here": None, "path": None, "stars": 4216, "pushed_days": 10,
        "needs": {"keys": [{"name": "EXCEL_TOKEN", "secret": True, "required": True, "description": "a key"}],
                  "network": None},
        "license": {"spdx": "MIT", "read_from": "github:LICENSE", "verdict": "usable"}}


@pytest.fixture(autouse=True)
def _fresh(execution_db, monkeypatch):
    permission_store._reset_for_tests()

    async def installed(c, *, folders, keys):
        return {"state": "failed", "stage": "install", "code": "x", "detail": ""}
    monkeypatch.setattr(capability_flow, "install_mcp", installed)
    capability_search.remember("c1", {"candidates": [copy.deepcopy(CAND)]})


def _window(approved: bool, outcome: str):
    """The asking window's card: answered (or not), with the key the user typed."""
    async def ask(card):
        approvals.LAST_OUTCOME.set(outcome)
        return {"approved": approved, "call_id": "cap-1", "keys": {"EXCEL_TOKEN": KEY} if approved else {},
                "folders": ["/Users/x/Downloads"] if approved else []}
    return ask


async def _propose(ask):
    return await capability_flow.propose({"candidate_id": CAND["id"], "why": "read the formulas"},
                                         conversation_id="c1", ask=ask, emit=lambda e: None)


async def _rows():
    async with db_session.AsyncSessionLocal() as db:
        return list(reversed(await permission_store.recent(db)))


def _no_key(row) -> bool:
    return KEY not in json.dumps([row.target, row.detail, row.extra], default=str)


@pytest.mark.parametrize("approved,outcome,expected", [
    (True, "approved", ("user", "allow", "once")),
    (False, "declined", ("user", "deny", None)),
    (False, "expired", ("expired", "expired", None)),
])
async def test_each_answer_is_one_row_and_never_the_key(approved, outcome, expected):
    async def surface(frame):
        raise AssertionError("the install card is the window's own; no decide card here")
    with permissions.asking_with(surface):
        await _propose(_window(approved, outcome))
    [row] = await _rows()
    assert (row.kind, row.target, row.conversation_id) == ("capability", "capability:excel-mcp-server", "c1")
    assert (row.decided_by, row.decision, row.scope) == expected
    assert row.detail == "read the formulas" and _no_key(row)
    assert (row.extra or {}).get("source_url") == CAND["source_url"]


async def test_an_expired_card_is_not_a_refusal_in_the_inbox():
    with permissions.asking_with(_window(False, "expired")):
        await _propose(_window(False, "expired"))
    async with db_session.AsyncSessionLocal() as db:
        listed = await permission_store.refused_groups(db, datetime.utcnow() - timedelta(hours=1))
    assert listed == []                       # an expiry the person saw is not "could not be asked"


async def test_every_answer_writes_exactly_one_row_and_a_job_that_skips_the_card_writes_none():
    """⓪Plan's S7 check: yes, no and expired each add exactly one row; a background job, which never shows
    the window's install card, adds none (S1's ruling; CAP1a removed the finds)."""
    from server.services import background_jobs

    async def surface(frame):
        raise AssertionError("no decide card here")
    with permissions.asking_with(surface):
        for approved, outcome in ((True, "approved"), (False, "declined"), (False, "expired")):
            before = len(await _rows())
            await _propose(_window(approved, outcome))
            assert len(await _rows()) == before + 1, outcome
        token = background_jobs._inside_job.set("job-1")
        try:
            out = await _propose(None)
        finally:
            background_jobs._inside_job.reset(token)
    assert out["not_added"] is True
    assert [r.decided_by for r in await _rows()] == ["user", "user", "expired"]


async def test_a_scheduled_runs_refusal_is_still_one_row():
    out = await _propose(None)                # no surface at all: a scheduled run (S1)
    assert out["not_added"] is True
    assert [(r.kind, r.decided_by) for r in await _rows()] == [("capability", "policy")]


async def test_the_outcome_recorder_takes_only_known_kinds():
    with pytest.raises(ValueError):
        await permissions.record_card_outcome(
            permissions.Request(kind="install", target="x", title="t"), permissions.Context("c1"), approved=True)
    assert await _rows() == []


# ── ⓪Plan's review of #367 ───────────────────────────────────────────────────

def _row_text(row) -> str:
    return json.dumps({c: getattr(row, c) for c in ("target", "detail", "extra", "kind", "conversation_id")},
                      default=str)


@pytest.mark.parametrize("url,kept", [
    ("https://someone:tok3n-in-userinfo@github.com/haris-musa/excel-mcp-server", "https://github.com/haris-musa/excel-mcp-server"),
    ("https://github.com/haris-musa/excel-mcp-server?access_token=tok3n-in-query", "https://github.com/haris-musa/excel-mcp-server"),
    ("https://github.com/haris-musa/excel-mcp-server#tok3n-in-fragment", "https://github.com/haris-musa/excel-mcp-server"),
    ("HTTP://Example.COM:8080/a/b?x=tok3n", "http://example.com:8080/a/b"),
    ("git+ssh://git@github.com/haris-musa/excel-mcp-server.git", None),
    ("javascript:alert(1)", None),
    ("https://example.com/" + "a" * 500, "https://example.com/" + "a" * 280),
], ids=["userinfo", "query", "fragment", "port-and-case", "ssh", "script", "long"])
async def test_review_f1_the_source_url_keeps_scheme_host_and_path_only(url, kept):
    capability_search.remember("c1", {"candidates": [{**copy.deepcopy(CAND), "source_url": url}]})
    with permissions.asking_with(_window(False, "declined")):
        await _propose(_window(False, "declined"))
    [row] = await _rows()
    assert row.extra["source_url"] == kept
    assert "tok3n" not in _row_text(row)


async def test_review_f2_a_stale_expiry_never_records_this_card_as_expired():
    """An outcome left by an earlier card, and an asker that does not set its own: the answer is what counts."""
    async def yes_without_an_outcome(card):
        return {"approved": True, "call_id": "cap-1", "keys": {}, "folders": []}

    async def no_without_an_outcome(card):
        return {"approved": False, "call_id": "cap-2", "keys": {}, "folders": []}
    for ask in (yes_without_an_outcome, no_without_an_outcome):
        approvals.LAST_OUTCOME.set("expired")
        await _propose(ask)
    assert [(r.decided_by, r.decision) for r in await _rows()] == [("user", "allow"), ("user", "deny")]
    # And the recorder itself: a yes is a yes, whatever `expired` says.
    await permissions.record_card_outcome(capability_flow._ledger_request(CAND, "x"), permissions.Context("c1"),
                                          approved=True, expired=True)
    assert (await _rows())[-1].decision == "allow"


async def test_review_f3a_no_folder_the_user_picked_goes_in():
    await _propose(_window(True, "approved"))
    [row] = await _rows()
    assert "/Users/x/Downloads" not in _row_text(row) and "Downloads" not in _row_text(row)


async def test_review_f3b_a_successful_install_is_still_one_row(monkeypatch):
    installs = []

    async def installed(c, *, folders, keys):
        installs.append(c["name"])
        return {"state": "on", "source_id": "s1", "tools": ["read_range"], "scan": {"level": "clean"}}
    monkeypatch.setattr(capability_flow, "install_mcp", installed)
    out = await _propose(_window(True, "approved"))
    assert out["ok"] is True and installs == ["excel-mcp-server"]
    assert [(r.decided_by, r.decision) for r in await _rows()] == [("user", "allow")]


@pytest.mark.parametrize("approved,outcome,installs", [(True, "approved", 1), (False, "declined", 0),
                                                        (False, "expired", 0)])
async def test_review_f3c_a_ledger_that_cannot_be_written_changes_nothing(monkeypatch, approved, outcome, installs):
    done = []

    async def installed(c, *, folders, keys):
        done.append(c["name"])
        return {"state": "on", "source_id": "s1", "tools": ["read_range"], "scan": {"level": "clean"}}

    async def broken(db, **fields):
        raise RuntimeError("database is locked")
    monkeypatch.setattr(capability_flow, "install_mcp", installed)
    monkeypatch.setattr(permission_store, "record", broken)
    out = await _propose(_window(approved, outcome))
    assert len(done) == installs and out["ok"] is approved


async def test_review_nits_the_name_is_plain_and_the_version_is_the_pinned_packages():
    cand = {**copy.deepcopy(CAND), "name": "excel‮mcp​\x07", "version": "9.9.9"}
    capability_search.remember("c1", {"candidates": [cand]})
    await _propose(_window(False, "declined"))
    [row] = await _rows()
    assert row.target == "capability:excelmcp" and row.extra["version"] == "1.1.2"
