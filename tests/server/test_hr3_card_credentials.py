"""HR-3: a card's title and touches row name no typed url's credentials. A `scheme://` url's userinfo (`user:pass@`, a
token alone, a plain ssh user) comes off at one point on its way to a card, `card_purpose.shown`
(`git_config_guard.without_credentials`): the reading `summarize` returns, whichever step read it (the frame's
`summary`: the Mac card's words and touches row; and the reading the title is made of, the phone's heading); the file
or git setting a run-later fact names on the title; and what command_confirm puts on a touches row (the push card's
lines, a delete card's targets). An scp-like `user@host:path` stays as written (an ssh login: that form has no
password), and nothing else changes.

1. Every vector in tests/fixtures/card_purpose_vectors.json whose line types a url with userinfo: no title, in any of
   the six languages, and nothing in its summary names it.
2. The point's other callers, and what it reads in a reading.

Not covered here: what `shown`'s docstring lists (a url the reader cuts before it, the command as typed).
Stand-in values only (`zz-user:FAKE`, `FAKE-token`, example.invalid); no network, no database.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from server.services import card_purpose, command_confirm, terminal_policy
from server.ws import protocol

ROOT = Path(__file__).resolve().parents[2]
VECTORS = json.loads((ROOT / "tests/fixtures/card_purpose_vectors.json").read_text(encoding="utf-8"))["vectors"]
LANGS = tuple(card_purpose.TEXT)
#: A `scheme://` url's userinfo, word by word, as the stripper reads it (up to its last `@` before a `/`, `?` or `#`);
#: an scp-like `user@host:path` has none.
USERINFO = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://([^/?#\s]*)@")
TYPED = [(v["line"], info) for v in VECTORS for info in USERINFO.findall(v["line"]) if info]
U, T, PLAIN = "https://zz-user:FAKE@example.invalid", "https://FAKE-token@example.invalid", "https://example.invalid"


def _titles(line: str) -> list[str]:
    """The line's title in every language: an ordinary card's, and the outside card's the gate asks when a write that
    runs later lifts (`run_later`, read from the line)."""
    later = terminal_policy.run_later_targets(line)
    return [card_purpose.phrase(line, lang=lang, **where) for lang in LANGS
            for where in ({}, {"outside": True, "run_later": later})]


# ── 1. every vector with a typed url's userinfo ─────────────────────────────

def test_the_walk_is_not_empty():
    """The vectors it walks: the push, clone, fetch, pull and open cards at least, in the six languages."""
    assert len(LANGS) == 6
    assert {card_purpose.summarize(line)["purpose"]["key"] for line, _ in TYPED} >= {
        "gitPush", "gitClone", "gitFetch", "open"}


@pytest.mark.parametrize("line, userinfo", TYPED, ids=[line for line, _ in TYPED])
def test_no_title_or_touches_row_names_a_typed_urls_userinfo(line, userinfo):
    """No title in any language, no touches row and nothing else in the summary names it, case aside (a program's
    name is read lower-case), read inside the sandbox or outside it."""
    secret = userinfo.lower()
    for title in _titles(line):
        assert secret not in title.lower(), title
    for outside in (False, True):
        summary = card_purpose.summarize(line, outside=outside)
        assert not [item for item in summary["touches"] if secret in item.lower()]
        assert secret not in json.dumps(summary, ensure_ascii=False).lower()


# ── 2. the point's other callers, and a reading as it reads one ─────────────

@pytest.mark.parametrize("typed, plain", [
    (f"git -c url.{U}/.insteadOf={PLAIN}/ fetch", f"git -c url.{PLAIN}/.insteadOf={PLAIN}/ fetch"),
    (f"git -c credential.{T}.helper=zz fetch", f"git -c credential.{PLAIN}.helper=zz fetch"),
    (f"echo zz > {U}/.envrc", f"echo zz > {PLAIN}/.envrc"),
], ids=["git-setting", "git-setting-token", "file"])
def test_a_run_later_fact_names_no_typed_userinfo(typed, plain):
    """The fact that names what runs later (a git setting, else a file, as read from the line) passes the same point:
    the title is the one of the line typed without the userinfo, in every language; the targets themselves keep it."""
    later = terminal_policy.run_later_targets(typed)
    assert later and later != terminal_policy.run_later_targets(plain)
    assert _titles(typed) == _titles(plain)
    assert not [title for title in _titles(typed) if "fake" in title.lower()]


def test_the_push_cards_lines_on_the_touches_row_pass_it_too():
    """command_confirm's lines on the touches row (`_with_ci`: where a push goes, the CI files it sends), which end the
    `reason` too, pass the same point, whatever a reader gave them."""
    frame = protocol.propose_run_command("c1", "git push", [])
    command_confirm._with_ci(frame, [f"Push destination: {U}/zz.git", "CI file: .github/workflows/zz.yml"])
    assert frame["summary"]["touches"] == [f"Push destination: {PLAIN}/zz.git", "CI file: .github/workflows/zz.yml"]
    assert frame["reason"].endswith(f"Push destination: {PLAIN}/zz.git; CI file: .github/workflows/zz.yml")
    assert "fake" not in json.dumps(frame).lower()


def test_a_delete_cards_targets_pass_it_too():
    """A delete card's targets as written (`_delete_keys`), which the Mac card shows as its touches row."""
    assert command_confirm._delete_keys("trash", f"rm -rf ~/{U}/zz ~/zz-plain") == {
        "delete_mode": "trash", "delete_targets": [f"~/{PLAIN}/zz", "~/zz-plain"]}


def test_a_reading_loses_the_userinfo_of_every_text_param_and_touches_item_and_nothing_else():
    """Every text param of the purpose, an inner purpose's too, and every touches item, each then listed once; a count,
    the flags and an scp-like `user@host:path` as they are."""
    reading = {"purpose": {"key": "open", "params": {"target": f"{U}/zz", "count": 2},
                           "inner": {"key": "gitClone", "params": {"repo": f"{T}/zz.git"}}},
               "touches": [f"{U}/zz", f"{PLAIN}/zz", "zz-user@example.invalid:zz.git"], "more": 1, "unsure": True}
    assert card_purpose.shown(reading) == {
        "purpose": {"key": "open", "params": {"target": f"{PLAIN}/zz", "count": 2},
                    "inner": {"key": "gitClone", "params": {"repo": f"{PLAIN}/zz.git"}}},
        "touches": [f"{PLAIN}/zz", "zz-user@example.invalid:zz.git"], "more": 1, "unsure": True}
