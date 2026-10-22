"""S7: the install-a-capability card writes a ledger row too (§5.4: every card is in the ledger).

The card stays as it is — the asking window's alone, carrying back the key the user typed and the folders
they picked (0.1.57 §3.1), so it does not ask through `permissions.decide`. Its answer is recorded after
it (`permissions.record_card_outcome`): allowed or refused by the user, or expired; never the key. A
scheduled run (nobody to ask) writes a `policy` refusal, which the Inbox lists (S1); a background job, which
never shows the window's card, records the find only (⓪Plan, S7)."""
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
    the window's install card, adds none (it records the find only: S1's ruling)."""
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
    assert out["recorded"] is True
    assert [r.decided_by for r in await _rows()] == ["user", "user", "expired"]


async def test_a_scheduled_runs_refusal_is_still_one_row():
    out = await _propose(None)                # no surface at all: a scheduled run (S1)
    assert out["recorded"] is True
    assert [(r.kind, r.decided_by) for r in await _rows()] == [("capability", "policy")]


async def test_the_outcome_recorder_takes_only_known_kinds():
    with pytest.raises(ValueError):
        await permissions.record_card_outcome(
            permissions.Request(kind="install", target="x", title="t"), permissions.Context("c1"), approved=True)
    assert await _rows() == []
