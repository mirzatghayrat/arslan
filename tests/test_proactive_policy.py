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
    ({"title_key": "title.made_up"}, "unknown_key"),                            # the UI could not say it
    ({"evidence": (Evidence("web.changed"), Evidence("web.secretly"))}, "unknown_key"),
])
def test_the_gate_refuses_and_names_the_rule(change, reason):
    verdict = gated(candidate(**change))
    assert (verdict.ok, verdict.reason) == (False, reason)


@pytest.mark.parametrize("kind", policy.KINDS)
def test_every_kind_needs_a_goal(kind):
    """INB7-e: the morning brief was the one kind with nothing to do; with it gone, every item carries a goal."""
    assert gated(candidate(kind=kind, title_key=f"title.{kind}", goal="")).reason == "no_goal"


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


def test_a_watch_raises_once_a_day():
    assert policy.cooldown_over(None, NOON)
    assert not policy.cooldown_over(NOON - timedelta(hours=23), NOON)
    assert policy.cooldown_over(NOON - timedelta(hours=24), NOON)


def test_items_go_stale_by_kind():
    assert not policy.is_stale("job_followup", NOON - timedelta(days=6), NOON)
    assert policy.is_stale("job_followup", NOON - timedelta(days=8), NOON)
    assert not policy.is_stale("web_change", NOON - timedelta(days=13), NOON)
    # A kind no longer raised (a stored brief row, INB7-e) still has days: the default 7.
    assert not policy.is_stale("brief", NOON - timedelta(days=6), NOON)
    assert policy.is_stale("brief", NOON - timedelta(days=8), NOON)


def test_the_morning_brief_is_gone_from_the_policy():
    """INB7-e (the user's Q9, #605 review F2): the brief kind, its keys and days, brief_due and its config fields went."""
    assert "brief" not in policy.KINDS and "brief" not in policy.FRESH_DAYS
    assert "title.brief" not in policy.TITLE_KEYS and not any(k.startswith("brief.") for k in policy.EVIDENCE_KEYS)
    assert not hasattr(policy, "brief_due")
    assert not {"brief_enabled", "brief_time"} & set(ProactiveConfig.model_fields)
    assert gated(candidate(kind="brief", title_key="title.brief", goal="")).reason == "unknown_kind"


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
    assert config.enabled and config.diagnosis_daily_usd == 0
    assert ProactiveConfig(quiet_start="6:5").quiet_start == "06:05"
    for bad in ({"quiet_start": "25:00"}, {"quiet_end": "noon"}, {"diagnosis_daily_usd": 9},
                {"surprise": 1}):
        with pytest.raises(ValueError):
            ProactiveConfig(**bad)


def test_the_key_catalog_covers_every_kind_and_every_job_reason():
    assert policy.TITLE_KEYS == {f"title.{kind}" for kind in policy.KINDS}
    assert {f"job.reason.{r}" for r in policy.JOB_REASONS} <= policy.EVIDENCE_KEYS
    assert "other" in policy.JOB_REASONS          # the detector falls back to it for a reason it does not know


def test_the_frontend_key_copy_is_not_stale():
    """web/src/locales/proactive-keys.json is what the frontend test checks the six
    languages against; if the catalog changed and it did not, that test guards nothing."""
    import json

    from scripts import proactive_keys

    assert json.loads(proactive_keys.PATH.read_text(encoding="utf-8")) == proactive_keys.catalog(), (
        "catalog changed: run `.venv/bin/python -m scripts.proactive_keys` and add the words in web/src/locales/proactive.ts")
