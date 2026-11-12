"""HR-0: the hard-rules registry (server/services/hard_rules.py) covers every rule key and permission kind once, each
row's test is a real collected test, and `never_auto` fails closed. The island reads never_auto's command part with
no change in what it answers."""
from __future__ import annotations

import importlib
from collections import Counter

import pytest

from server.services import approvals, hard_rules, permissions, terminal_policy as tp
from server.services.permissions import Request
from tests.server import hard_rules_cases as hr

STAND_IN = "zz-stand-in-word"
_THREE = "tests/server/test_s2a2_three_layers.py::"
FORBID_CASES = _THREE + "test_every_forbid_rule_refuses"
ASK_CASES = _THREE + "test_layer_two_asks_this_time_only"
UNREADABLE_CASES = _THREE + "test_what_cannot_be_read_asks_this_time_only"
PROTECTED_CASES = _THREE + "test_a_write_into_startup_ssh_credential_or_agent_files_asks_this_time_only"
HARMLESS_CASES = _THREE + "test_layer_three_runs"


def _parser_keys() -> set[str]:
    """Read from the live tables (not hard_rules' copy), so a key added to them is seen here."""
    return {key for key, *_ in tp._FORBID} | set(tp.ONCE_ONLY_RULES)


def _rule_gaps(keys: set[str], rows) -> tuple[set[str], set[str]]:
    """(keys with no DIRECT row, keys in more than one)."""
    counts = Counter(key for row in rows for key in row.rules)
    return keys - set(counts), {key for key, n in counts.items() if n > 1}


def _kind_gaps(kinds: set[str], rows, may_auto: frozenset[str]) -> tuple[set[str], set[str]]:
    """(kinds placed nowhere, kinds placed twice): each kind is in one NEVER_AUTO row or in MAY_AUTO_KINDS."""
    counts = Counter([*(kind for row in rows for kind in row.kinds), *may_auto])
    return kinds - set(counts), {kind for kind, n in counts.items() if n > 1}


# ── the registry covers every key and kind ───────────────────────────────────

def test_every_parser_key_has_exactly_one_direct_row():
    assert _rule_gaps(_parser_keys(), hard_rules.DIRECT) == (set(), set())


def test_every_permission_kind_is_placed_once_and_never_autos_kinds_are_its_rows():
    assert _kind_gaps(set(permissions.KINDS), hard_rules.NEVER_AUTO, hard_rules.MAY_AUTO_KINDS) == (set(), set())
    assert {kind for row in hard_rules.NEVER_AUTO for kind in row.kinds} == hard_rules.NEVER_AUTO_KINDS
    assert set(tp.ONCE_ONLY_RULES) <= {rule for row in hard_rules.NEVER_AUTO for rule in row.rules}


def test_ids_are_unique_and_every_row_names_a_layer():
    ids = [row.id for row in hard_rules.ALL]
    assert len(ids) == len(set(ids)) and {row.layer for row in hard_rules.ALL} <= set(hard_rules.LAYERS)
    # HR-1: one kernel row per run-later family, and the rows are kernel rows.
    from server.services import run_later
    later = {row.id for row in hard_rules.RUN_LATER}
    assert {"run-later/" + name for name, _ in run_later.FAMILIES} <= later
    assert {row.layer for row in hard_rules.RUN_LATER if not row.id.startswith(("run-later/direct-forms",
            "run-later/click-lift", "run-later/never-auto", "run-later/file-tools"))
            and row.id != "run-later/write-token"} == {"kernel"}         # HR-2a's file-tool rows hold in-process
    # HR-3 part 1: the direct forms (the parser), the click-lift rule (the gate) and never_auto's command part.
    assert {"run-later/direct-forms", "run-later/click-lift", "run-later/never-auto"} <= later


#: HR-1c: the check after each command, one row per thing it undoes or names (written out, not derived).
POST_RUN_IDS = {"post-run/hooks-quarantine", "post-run/config-revert", "post-run/include-check"}


@pytest.mark.timeout(600)
def test_the_post_run_rows_resolve_like_the_others():
    rows = [row for row in hard_rules.ALL if row.layer == "post-run"]
    assert "post-run" in hard_rules.LAYERS and {row.id for row in rows} == POST_RUN_IDS
    assert rows == list(hard_rules.POST_RUN)
    for row in rows:
        module, name = row.holder.split(":")
        assert module == "server.services.git_config_guard"
        assert callable(getattr(importlib.import_module(module), name)), row.id
    assert hr.unresolved(rows, hr.collected(tuple(sorted({row.test.split("::")[0] for row in rows})))) == []


def _row_files() -> tuple[str, ...]:
    return tuple(sorted({row.test.split("::")[0] for row in hard_rules.ALL}))


@pytest.mark.timeout(600)                                  # one pytest collection of a dozen files, under load
def test_every_rows_test_is_a_collected_test():
    assert hr.unresolved(hard_rules.ALL, hr.collected(_row_files())) == []


def test_every_rows_holder_exists():
    for row in hard_rules.ALL:
        module, name = row.holder.split(":")
        assert callable(getattr(importlib.import_module(module), name)), row.id


def test_a_parametrized_rows_test_has_a_case_for_each_key_it_stands_for():
    """A row pointing at a test parametrized by `rule` or `kind` is proven only by that test's own case for it."""
    for row in hard_rules.ALL:
        given = hr.cases(row.test)
        for argname, keys in (("rule", row.rules), ("kind", row.kinds)):
            if keys and given and argname in given[0]:
                assert keys <= {case[argname] for case in given}, (row.id, keys - {c[argname] for c in given})


# ── the checks above go red (mutation checks) ────────────────────────────────

def test_a_stand_in_rule_key_with_no_row_is_found(monkeypatch):
    monkeypatch.setattr(tp, "_FORBID", [*tp._FORBID, (STAND_IN, STAND_IN, STAND_IN, False)])
    assert _rule_gaps(_parser_keys(), hard_rules.DIRECT) == ({STAND_IN}, set())


def test_a_removed_row_is_found():
    row = next(r for r in hard_rules.DIRECT if r.id == "git-push")
    assert _rule_gaps(_parser_keys(), [r for r in hard_rules.DIRECT if r is not row]) == ({"git-push"}, set())
    assert _rule_gaps(_parser_keys(), [*hard_rules.DIRECT, row])[1] == {"git-push"}


def test_a_stand_in_kind_or_a_removed_kind_row_is_found():
    assert _kind_gaps({*permissions.KINDS, STAND_IN}, hard_rules.NEVER_AUTO, hard_rules.MAY_AUTO_KINDS)[0] == {STAND_IN}
    rows = [r for r in hard_rules.NEVER_AUTO if r.id != "outside"]
    assert _kind_gaps(set(permissions.KINDS), rows, hard_rules.MAY_AUTO_KINDS)[0] == {"outside"}


@pytest.mark.timeout(600)
def test_a_row_whose_test_is_not_collected_is_found():
    from dataclasses import replace
    row = replace(hard_rules.DIRECT[0], test="tests/server/test_hard_rules.py::test_" + STAND_IN.replace("-", "_"))
    assert hr.unresolved([row], hr.collected(_row_files())) == [row.id]


# ── never_auto ───────────────────────────────────────────────────────────────

def _command(text: str, target: str | None = None) -> Request:
    return Request(kind="command", target=target or "text:" + text, title="t", detail=text)


@pytest.mark.parametrize("kind", sorted(permissions.KINDS))
def test_never_auto_by_kind(kind):
    harmless = hr.first_command(HARMLESS_CASES)
    assert hard_rules.never_auto(Request(kind=kind, target="x", title="t", detail=harmless)) is (
        kind in hard_rules.NEVER_AUTO_KINDS)


FULL_ACCESS_STILL_ASKS = ("send", "site", "shortcut")       # written out: S5's table and CLS, not derived


@pytest.mark.parametrize("kind", FULL_ACCESS_STILL_ASKS)
def test_what_full_access_still_asks_is_never_auto(kind):
    assert kind in permissions.KINDS
    assert hard_rules.never_auto(Request(kind=kind, target="x", title="t", once_only=False)) is True


@pytest.mark.parametrize("kind", FULL_ACCESS_STILL_ASKS)
def test_taking_a_full_access_kind_back_out_is_found(kind, monkeypatch):
    """Mutant: the kind moved back to MAY_AUTO_KINDS. never_auto then lets it through, which the test above refuses,
    and it is placed twice, which the coverage check refuses."""
    monkeypatch.setattr(hard_rules, "MAY_AUTO_KINDS", hard_rules.MAY_AUTO_KINDS | {kind})
    assert hard_rules.never_auto(Request(kind=kind, target="x", title="t", once_only=False)) is False
    assert _kind_gaps(set(permissions.KINDS), hard_rules.NEVER_AUTO, hard_rules.MAY_AUTO_KINDS)[1] == {kind}


def test_every_once_only_rule_is_never_auto_by_its_text_or_its_card():
    by_rule = {c["rule"]: c["command"] for c in reversed(hr.cases(ASK_CASES))}
    by_rule["protected-write"] = hr.first_command(PROTECTED_CASES)
    by_rule[tp.UNREADABLE] = hr.first_command(UNREADABLE_CASES)
    from tests.server.test_s2a3_outside_reach import GAPS        # asks only outside: never_auto reads it that way
    by_rule[tp.OUTSIDE_REACH[0]] = GAPS[0]
    assert set(by_rule) == set(tp.ONCE_ONLY_RULES)
    harmless = hr.first_command(HARMLESS_CASES)
    for rule, text in by_rule.items():
        assert hard_rules.never_auto(_command(text)), rule                       # no once_only flag: the text decides
        assert hard_rules.never_auto(_command(harmless, target="rules:" + rule)), rule
    assert not hard_rules.never_auto(_command(harmless))


def test_an_ask_rule_not_yet_placed_is_never_auto(monkeypatch):
    """A rule added to the parser later, before it is placed in NEVER_AUTO_RULES, fails closed."""
    harmless = hr.first_command(HARMLESS_CASES)
    monkeypatch.setattr(tp, "assess", lambda command, **kw: tp.Assessment("ask", STAND_IN, STAND_IN))
    monkeypatch.setattr(tp, "ask_rules", lambda command, **kw: {STAND_IN})
    assert STAND_IN not in hard_rules.NEVER_AUTO_RULES
    assert hard_rules.never_auto(_command(harmless)) is True
    assert hard_rules.never_auto(_command(harmless, target="rules:" + STAND_IN)) is True


def test_a_forbidden_command_is_never_auto():
    for case in hr.cases(FORBID_CASES):
        assert hard_rules.never_auto(_command(case["command"])), case["rule"]


@pytest.mark.parametrize("request_", [
    None, object(), Request(kind=STAND_IN, target="x", title="t"), Request(kind="folder", target="x", title="t", once_only=True),
    Request(kind="command", target="x", title="t", detail=None), Request(kind="command", target=None, title="t", detail="x"),
    Request(kind="folder", target="x", title="t", once_only="no"),
], ids=["none", "not-a-request", "unknown-kind", "once-only", "no-detail", "no-target", "malformed-once-only"])
def test_unknown_or_malformed_fails_closed(request_):
    assert hard_rules.never_auto(request_) is True


def test_the_run_later_hook_is_read(monkeypatch):
    write = Request(kind="workspace_write", target="x", title="t")
    assert hard_rules.never_auto(write) is False
    monkeypatch.setattr(hard_rules, "_writes_run_later", lambda request: True)   # HR-1 / HR-2
    assert hard_rules.never_auto(write) is True


# ── the island reads never_auto's command part, unchanged ────────────────────

def test_the_islands_risky_set_is_the_old_one():
    assert approvals._island_risky_rules() == tp.ONCE_ONLY_RULES | {"network"}       # the set before HR-0


def test_the_island_answers_every_existing_case_as_before():
    old = tp.ONCE_ONLY_RULES | {"network"}
    texts = [c["command"] for node in (FORBID_CASES, ASK_CASES, UNREADABLE_CASES, PROTECTED_CASES, HARMLESS_CASES)
             for c in hr.cases(node)]
    for text in texts:
        verdict = tp.assess(text)
        before = verdict.level != "forbid" and verdict.rule not in old
        frame = {"type": "propose_run_command", "pretty": text, "perm_kind": "command"}
        assert approvals.island_may_answer(frame) is before


# ── refused before any card, with no table row ───────────────────────────────

@pytest.mark.parametrize("rule", ["empty", "too-long"])
def test_an_empty_or_too_long_command_is_refused(rule):
    text = "" if rule == "empty" else (STAND_IN + " ") * (tp.MAX_COMMAND_CHARS // len(STAND_IN))
    assert (tp.assess(text).level, tp.assess(text).rule) == ("forbid", rule)
