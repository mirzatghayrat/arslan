"""0.1.47 proactivity policy: what may be raised, and when it may interrupt."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from arslan import proactive_policy as policy
from arslan.proactive_policy import Candidate, Evidence, ProactiveConfig


def candidate(**over):
    base = dict(kind="web_change", fingerprint="web:1:abc", source_key="watch:1", title_key="title.web_change",
                evidence=(Evidence("web.changed", {"label": "Pricing"}, quote="Pro plan now $12"),),
                goal="Read the page and tell me what changed.")
    base.update(over)
    return Candidate(**base)


def gated(c, existing=(), muted=()):
    return policy.gate(c, existing=set(existing), muted=set(muted))


def test_a_complete_candidate_passes():
    assert gated(candidate()).ok


@pytest.mark.parametrize("change,reason", [
    ({"evidence": ()}, "no_evidence"),                                          # no evidence, no proposal
    ({"evidence": (Evidence(" "),)}, "no_evidence"),                            # a line that says nothing
    ({"title_key": " "}, "no_title"),
    ({"kind": "gossip"}, "unknown_kind"),
    ({"priority": "urgent!!"}, "bad_priority"),
    ({"goal": "  "}, "no_goal"),
    ({"goal": "x" * 1501}, "goal_too_long"),
])
def test_the_gate_refuses_and_names_the_rule(change, reason):
    verdict = gated(candidate(**change))
    assert (verdict.ok, verdict.reason) == (False, reason)


def test_a_brief_needs_no_goal_but_still_needs_evidence():
    assert gated(candidate(kind="brief", goal="", fingerprint="brief:2026-09-30", source_key="brief")).ok
    assert gated(candidate(kind="brief", goal="", evidence=())).reason == "no_evidence"


def test_duplicates_and_mutes_are_dropped():
    assert gated(candidate(), existing={"web:1:abc"}).reason == "duplicate"
    assert gated(candidate(), muted={"watch:1"}).reason == "muted_source"
    assert gated(candidate(), muted={"kind:web_change"}).reason == "muted_kind"
    assert gated(candidate(), muted={"watch:2", "kind:folder_change"}).ok       # other sources stay audible


def test_secrets_never_reach_the_inbox():
    key = "sk-" + "a1B2c3D4" * 6
    assert gated(candidate(evidence=(Evidence("web.changed", quote=f"token {key}"),))).reason == "credential"
    assert gated(candidate(goal=f"use {key}")).reason == "credential"


@pytest.mark.parametrize("hour,minute,quiet", [
    (23, 0, True), (22, 0, True), (3, 30, True), (7, 59, True),      # 22:00–08:00 wraps midnight
    (8, 0, False), (12, 0, False), (21, 59, False),
])
def test_quiet_hours_wrap_midnight(hour, minute, quiet):
    assert policy.in_quiet_hours(datetime(2026, 9, 30, hour, minute), "22:00", "08:00") is quiet


def test_quiet_hours_same_day_and_disabled():
    assert policy.in_quiet_hours(datetime(2026, 9, 30, 13, 0), "12:00", "14:00")
    assert not policy.in_quiet_hours(datetime(2026, 9, 30, 15, 0), "12:00", "14:00")
    assert not policy.in_quiet_hours(datetime(2026, 9, 30, 3, 0), "09:00", "09:00")   # equal = none


NOON = datetime(2026, 9, 30, 12, 0)


def may(c=None, *, now=NOON, notified_today=0, **config):
    return policy.may_notify(c or candidate(), now=now, config=ProactiveConfig(**config), notified_today=notified_today)


def test_a_notification_needs_every_condition():
    assert may()
    assert not may(notify=False)                                             # the user said no
    assert not may(candidate(notify=False))                                  # this watch is silent
    assert not may(now=datetime(2026, 9, 30, 23, 30))                        # quiet hours
    assert not may(notified_today=5)                                         # cap spent
    assert may(notified_today=4)
    assert not may(notify_daily_cap=0)


def test_job_and_schedule_problems_never_notify_twice():
    # the job and the scheduler already notified when they ended
    for kind in ("job_followup", "scheduled_problem"):
        assert not may(candidate(kind=kind))
    for kind in ("web_change", "folder_change", "brief"):
        assert may(candidate(kind=kind))


def test_a_watch_raises_once_a_day():
    assert policy.cooldown_over(None, NOON)
    assert not policy.cooldown_over(NOON - timedelta(hours=23), NOON)
    assert policy.cooldown_over(NOON - timedelta(hours=24), NOON)


def test_items_go_stale_by_kind():
    assert not policy.is_stale("job_followup", NOON - timedelta(days=6), NOON)
    assert policy.is_stale("job_followup", NOON - timedelta(days=8), NOON)
    assert policy.is_stale("brief", NOON - timedelta(days=3), NOON)            # yesterday's brief is history
    assert not policy.is_stale("web_change", NOON - timedelta(days=13), NOON)


def test_the_brief_comes_once_a_day_after_its_time_and_only_if_on():
    on = ProactiveConfig(brief_enabled=True, brief_time="08:30")
    assert not policy.brief_due(datetime(2026, 9, 30, 8, 29), on, None)
    assert policy.brief_due(datetime(2026, 9, 30, 8, 30), on, None)
    assert policy.brief_due(datetime(2026, 9, 30, 14, 0), on, "2026-09-29")     # woke late: still today's
    assert not policy.brief_due(datetime(2026, 9, 30, 14, 0), on, "2026-09-30")
    assert not policy.brief_due(datetime(2026, 9, 30, 14, 0), ProactiveConfig(), None)   # default off


def test_diagnosis_spend_is_off_at_zero_and_bounded_otherwise():
    assert not policy.diagnosis_allowed(cap_usd=0, spent_micro=0, worst_case_micro=1)
    assert policy.diagnosis_allowed(cap_usd=0.10, spent_micro=50_000, worst_case_micro=50_000)   # exactly fits
    assert not policy.diagnosis_allowed(cap_usd=0.10, spent_micro=50_000, worst_case_micro=50_001)
    assert not policy.diagnosis_allowed(cap_usd=0.10, spent_micro=100_000, worst_case_micro=1)


def test_most_important_first_then_newest():
    rows = [SimpleNamespace(priority=p, created_at=NOON + timedelta(minutes=m), n=n)
            for n, (p, m) in enumerate([("normal", 0), ("high", -5), ("normal", 9), ("low", 30)])]
    assert [r.n for r in policy.order(rows)] == [1, 2, 0, 3]


def test_config_defaults_spend_nothing_and_reject_bad_input():
    config = ProactiveConfig()
    assert config.enabled and config.diagnosis_daily_usd == 0 and not config.brief_enabled
    assert ProactiveConfig(quiet_start="6:5").quiet_start == "06:05"
    for bad in ({"quiet_start": "25:00"}, {"brief_time": "noon"}, {"diagnosis_daily_usd": 9},
                {"notify_daily_cap": -1}, {"surprise": 1}):
        with pytest.raises(ValueError):
            ProactiveConfig(**bad)
