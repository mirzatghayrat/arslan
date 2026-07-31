"""The three allowlisted modules ship KEYS now, not sentences.

Gate item ①. The completion criterion the user set is exact: the three modules
come OUT of test_no_display_text_from_the_backend.ALLOWED and that guard stays
green — not the guard relaxed to accommodate them.

Each module had a different reason for being hard, and each is asserted here on
the shape that made it hard:

  runs.py             six sentences ASSEMBLED FROM NUMBERS. Keying them means
                      shipping the numbers separately, so the interface can
                      compose the sentence in the reader's language.
  conversations.py    one composed sentence that is PERSISTED into
                      ConversationEvent.summary. Rows already written keep their
                      Chinese forever — the fix can only change what is written
                      from now on, and the UI must render both shapes.
  scheduled_tasks.py  API errors that reach the user through HTTPException
                      detail, which nothing translates. FastAPI allows a dict
                      there, and the client already parses structured details
                      with a `code` (the evolve spend gate precedent).
"""
from __future__ import annotations

import re

import pytest

CJK = re.compile(r"[一-鿿぀-ヿ가-힯]")


# ---------------------------------------------------------------------------
# runs.py — anomalies carry keys + params
# ---------------------------------------------------------------------------

def _anomaly(**kw):
    from server.schemas import AnomalyOut

    base = dict(severity="red", kind="error_rate", spawn_id=1, spawn_name="小美",
                title_key="anomaly.error_rate.high", detail_key="anomaly.error_rate.detail",
                params={"pct": 60, "errs": 3, "n": 5})
    base.update(kw)
    return AnomalyOut(**base)


def test_anomaly_carries_a_key_and_the_numbers_separately():
    a = _anomaly()
    assert a.title_key and a.detail_key
    assert a.params["pct"] == 60
    # The spawn name is a separate field already — it is USER DATA and must not
    # be baked into a translatable string.
    assert a.spawn_name == "小美"


def test_no_anomaly_field_carries_an_assembled_sentence():
    """Discriminating: a key plus a leftover Chinese `title` would satisfy any
    test that only checked for the key's presence."""
    a = _anomaly()
    dumped = a.model_dump()
    for field in ("title_key", "detail_key"):
        assert not CJK.search(str(dumped[field])), f"{field} still holds display text"
    # spawn_name is the only field allowed to hold user text
    for field, value in dumped.items():
        if field in ("spawn_name", "params"):
            continue
        assert not CJK.search(str(value)), f"{field} = {value!r} is display text"


@pytest.mark.asyncio
async def test_every_anomaly_rule_emits_a_key(monkeypatch):
    """Drives the real endpoint over synthetic runs so each rule is exercised.

    A rule that kept its f-string would show up here as a missing key rather
    than as a passing test about a different rule."""
    from server.api import runs as runs_api

    rows = _fake_runs()
    out = await _anomalies_with(runs_api, monkeypatch, rows)
    assert out, "no anomalies produced — the fixture no longer triggers any rule"
    for a in out:
        assert a.title_key, f"{a.kind} has no title_key"
        assert not CJK.search(a.title_key)


# ---------------------------------------------------------------------------
# conversations.py — structure in ref, and the persistence boundary
# ---------------------------------------------------------------------------

def test_the_distill_summary_is_a_key_with_counts_beside_it():
    from server.api.conversations import _distill_event

    key, ref = _distill_event(distilled=3, failed=0)
    assert not CJK.search(key)
    assert ref["distilled"] == 3 and ref["failed"] == 0


def test_the_failed_case_is_distinguishable_from_the_clean_one():
    """Two different sentences before; two different keys now. Collapsing them
    into one key would lose the distinction the original wording carried."""
    from server.api.conversations import _distill_event

    clean_key, _ = _distill_event(distilled=3, failed=0)
    failed_key, ref = _distill_event(distilled=3, failed=2)
    assert clean_key != failed_key
    assert ref["failed"] == 2


# ---------------------------------------------------------------------------
# scheduled_tasks.py — structured error details
# ---------------------------------------------------------------------------

def test_scheduled_errors_are_structured_codes():
    from server.api.scheduled_tasks import _err

    exc = _err(404, "scheduled.task_not_found", task_id=7)
    assert exc.status_code == 404
    assert exc.detail["code"] == "scheduled.task_not_found"
    assert exc.detail["params"]["task_id"] == 7
    assert not CJK.search(str(exc.detail))


def test_the_client_can_read_the_code_the_way_it_already_does():
    """The frontend's request() already prefers detail.code for structured
    details (the evolve spend-gate precedent) — the shape must match that, or
    the user sees 'HTTP 404' instead of a sentence."""
    from server.api.scheduled_tasks import _err

    detail = _err(422, "scheduled.cron_required").detail
    assert isinstance(detail, dict) and "code" in detail


# ---------------------------------------------------------------------------
# The gate criterion itself
# ---------------------------------------------------------------------------

def test_the_three_modules_are_out_of_the_allowlist():
    """The user's completion criterion, asserted directly rather than implied."""
    from tests.server.test_no_display_text_from_the_backend import ALLOWED

    for name in ("conversations.py", "runs.py", "scheduled_tasks.py"):
        assert name not in ALLOWED, f"{name} is still allowlisted"
    # registry.py stays: it is operator-facing, and the user placed it OUTSIDE
    # the gate deliberately.
    assert "registry.py" in ALLOWED


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _fake_runs():
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)

    class R:
        def __init__(self, rid, status, score):
            self.id = rid
            self.spawn_id = 1
            self.spawn_name = "小美"
            self.status = status
            self.overall_score = score
            self.created_at = now
            # The rule reads error_kind, not status — a fixture missing it
            # produced an AttributeError rather than a wrong answer, which is
            # the better failure but still a fixture that did not resemble a Run.
            self.error_kind = "LLMError" if status == "error" else None

    # 5 runs, 4 errored -> error_rate red; scores below threshold -> pass_rate
    return [R(1, "error", None), R(2, "error", None), R(3, "error", None),
            R(4, "error", None), R(5, "scored", 0.1)]


async def _anomalies_with(runs_api, monkeypatch, rows):
    """Call the anomaly endpoint against a stubbed session returning `rows`."""
    class _Res:
        def __init__(self, items): self._items = items
        def scalars(self):
            class _S:
                def __init__(self, it): self._it = it
                def all(self_inner): return self_inner._it
            return _S(self._items)
        def all(self): return []

    class _Session:
        async def execute(self, *a, **k):
            return _Res(rows)

    return await runs_api.runs_anomalies(range="7d", db=_Session())
