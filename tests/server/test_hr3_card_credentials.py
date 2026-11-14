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
3. Review round 1: the two texts a card shows as they are given, Arslan's reason (`why`) and the label of the machine
   a command runs on, pass it too (`card_purpose.shown_name`), before any cut: the title in every language, the
   frame's `why` and `remote_host` (the Mac card's heading, and the first item of its touches row), and the reason as
   the run_command gate hands it on.

Not covered here: what `shown`'s docstring lists (a url the reader cuts before it, the command as typed, in a reason
or a label what isn't a url's userinfo). Stand-in values only (`zz-user:FAKE`, `FAKE-token`, example.invalid,
192.0.2.1); no network, and only the remote card sent end to end has a database (the test one, `execution_db`).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from server.orchestrator import command_gate, tool_loop
from server.orchestrator.turn_state import ToolTurn
from server.services import card_purpose, command_confirm, command_sandbox, permissions, terminal_policy
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


# ── 3. Arslan's reason and the machine's label (review round 1) ──────────────

#: The line the reason is given for: one that reads the same each time, so only the reason, the label and where each is
#: cut change.
LINE = "git push origin main"
#: The ssh login a machine's label ends with (tool_gates: an enrolled machine's free-form name, then its login).
LOGIN = "zz-user@192.0.2.1"
#: Each title form a reason is cut in: an ordinary card's, the outside card's, and a remote card's, with a plain label
#: and with one that names a url with userinfo.
FORMS = ({}, {"outside": True}, {"host": LOGIN}, {"host": f"zz-node {U}/zz ({LOGIN})"})


def _no_userinfo(text: str) -> bool:
    """No stand-in userinfo in `text`, nor the start of one a cut left after a `://`: the stand-ins' userinfo starts
    with `z` or `f` (`zz-user:FAKE@`, `FAKE-token@`), their host with `e`."""
    low = text.lower()
    return "fake" not in low and not re.search(r"://[zf]", low)


def test_the_reason_loses_a_urls_userinfo_before_any_cut():
    """Arslan's reason with a url's userinfo (a user and password, a token alone), at each place a cut can fall: the
    title's, in every language and form (the reason is cut to fit the phone's heading), and the frame's at 300 (its
    `why`, the Mac card's heading). Neither names the userinfo nor the start of it; the url keeps its host and nothing
    else changes. A zero-width character inside `://`, which the cleaning drops, doesn't hide one either."""
    read = {False: card_purpose.summarize(LINE), True: card_purpose.summarize(LINE, outside=True)}
    for n in range(331):
        why = "w" * n + f" {U}/zz {T}/zz"
        said = protocol.propose_run_command("c", "git", ["push", "origin", "main"], why=why)["why"]
        assert _no_userinfo(said), (n, said)
        for lang in LANGS:
            for where in FORMS:
                title = card_purpose.phrase(LINE, why, lang=lang, reading=read["outside" in where], **where)
                assert _no_userinfo(title), (n, lang, where, title)
    assert protocol.propose_run_command("c", "git", ["push"], why=f"push to {U}/zz.git, then {T}/zz")["why"] == (
        f"push to {PLAIN}/zz.git, then {PLAIN}/zz")
    # Word by word: a url with no path keeps the words after it, up to an `@` there (an ssh login, an e-mail address).
    plain = f"push to {PLAIN} for {LOGIN}, then zz-ops@example.invalid"
    assert protocol.propose_run_command("c", "git", ["push"], why=plain)["why"] == plain
    assert protocol.propose_run_command("c", "git", ["push"], why=f"push to {T} for {LOGIN}")["why"] == (
        f"push to {PLAIN} for {LOGIN}")
    hidden = f"push to https:/{chr(0x200B)}/zz-user:FAKE@example.invalid/zz"
    assert protocol.propose_run_command("c", "git", ["push"], why=hidden)["why"] == f"push to {PLAIN}/zz"
    assert all(_no_userinfo(card_purpose.phrase(LINE, hidden, lang=lang)) for lang in LANGS)


@pytest.mark.parametrize("label, plain", [
    (U, PLAIN),
    (f"zz-node {U}/zz ({LOGIN})", f"zz-node {PLAIN}/zz ({LOGIN})"),
    (f"{T} ({LOGIN})", f"{PLAIN} ({LOGIN})"),
    (LOGIN, LOGIN),
    (f"zz-node ({LOGIN})", f"zz-node ({LOGIN})"),
    ("zz-user@example.invalid:zz.git", "zz-user@example.invalid:zz.git"),
], ids=["url", "named-url", "named-token", "login", "named-login", "scp-like"])
def test_the_machines_label_loses_a_urls_userinfo_and_nothing_else(label, plain):
    """The label of the machine a command runs on (an enrolled machine's free-form name, then its ssh login): the frame's
    `remote_host`, which the Mac card puts first on its touches row, is the label without a url's userinfo and as given
    otherwise (an ssh login, an scp-like `user@host:path`); the title, in every language, is the one with that label."""
    frame = protocol.propose_run_command("c", "uptime", [], remote_host=label, fingerprints=["SHA256:zz"])
    assert frame["remote_host"] == plain and frame["fingerprints"] == ["SHA256:zz"]
    assert [item for item in [frame["remote_host"], *frame["summary"]["touches"]] if not _no_userinfo(item)] == []
    titles = [card_purpose.phrase("uptime", lang=lang, host=label) for lang in LANGS]
    assert titles == [card_purpose.phrase("uptime", lang=lang, host=plain) for lang in LANGS]
    assert all(_no_userinfo(title) for title in titles)


def test_a_long_label_loses_the_userinfo_before_the_titles_cut():
    """The title cuts the label to 80: a url's userinfo at each place that cut can fall is off before it."""
    for n in range(100):
        label = "n" * n + f" {U}/zz ({LOGIN})"
        for lang in LANGS:
            title = card_purpose.phrase("uptime", lang=lang, host=label)
            assert _no_userinfo(title), (n, lang, title)


class _Asker:
    """A card surface that records each frame and answers no."""

    def __init__(self):
        self.frames: list[dict] = []

    async def __call__(self, frame):
        self.frames.append(frame)
        return {"approved": False, "scope": "once", "note": "", "by": "mac", "call_id": frame["call_id"]}


async def test_the_remote_card_as_sent_names_neither(execution_db):
    """The remote card as command_confirm builds it and the permission layer sends it, with a reason the frame cuts
    inside a token's url: its title, `why`, `remote_host` and touches, and nothing else in it, name no userinfo; the
    label's ssh login is as given."""
    asker = _Asker()
    with permissions.asking_with(asker):
        await command_confirm.Confirmations("c1").command(
            "uptime", [], remote_host=f"zz-node {U}/zz ({LOGIN})", fingerprints=["SHA256:zz"],
            why="w" * 285 + f" {T}/zz", host="192.0.2.1")
    [frame] = asker.frames
    assert frame["remote_host"] == f"zz-node {PLAIN}/zz ({LOGIN})"
    assert _no_userinfo(frame["title"]) and _no_userinfo(frame["why"]) and len(frame["why"]) == 300
    assert "fake" not in json.dumps(frame, ensure_ascii=False).lower()


#: Reasons whose url's userinfo the gate's cut at 300 falls inside, at each place it can: a long one, and a short one
#: padded with white space the cleaning folds into one space (so a title would show what that cut left).
GATE_CUT = [prefix + f" {U}/zz" for k in range(270, 300) for prefix in ("w" * k, "w" + " " * k)]


@pytest.fixture
def gate(monkeypatch):
    """The run_command gate with the sandbox on and able to start, no "ask for every command", and a stand-in that runs
    nothing (as tests/server/test_smart8_card_purpose.py sets it up)."""
    command_sandbox._reset_for_tests()

    async def no():
        return False

    async def yes():
        return True

    class _Exec:
        key = "run_command"

        async def execute(self, args):
            return {"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "sandbox": "workspace"}
    monkeypatch.setattr(command_gate, "_asks_for_everything", no)
    monkeypatch.setattr(command_gate, "_sandbox_enabled", yes)
    monkeypatch.setattr(command_sandbox, "available", lambda: True)
    monkeypatch.setitem(tool_loop.EXECUTORS, "run_command", _Exec())
    yield
    command_sandbox._reset_for_tests()


async def _resolve():
    return [{"key": "run_command", "description": "run"}]


async def _run_command(args: dict, confirm_command) -> dict:
    return await tool_loop._run_tool("run_command", args, "{}", ToolTurn(
        resolve_tools=_resolve, emit=lambda e: None, tool_timeout_s=5, tool_trace=[], convo=[],
        confirm_command=confirm_command, conversation_id="c1"))


@pytest.mark.parametrize("extra", [{}, {"outside_sandbox": True}], ids=["ordinary", "outside"])
async def test_the_gate_takes_the_userinfo_off_before_it_cuts_the_reason(gate, extra):
    """run_command's reason as the gate hands it to its card, the ordinary one and the outside one (the card's title
    and frame `why` are made from it), cut at 300: a cut inside a url's userinfo leaves none of it."""
    calls: list[dict] = []

    async def cards(command, argv, **kw):
        calls.append(kw)
        return False
    for why in GATE_CUT:
        await _run_command({"command": LINE, "why": why, **extra}, cards)
    assert len(calls) == len(GATE_CUT)
    assert [kw["why"] for kw in calls if not _no_userinfo(kw["why"])] == []


@pytest.mark.parametrize("extra, kind", [({}, "command"), ({"outside_sandbox": True}, "outside")],
                         ids=["ordinary", "outside"])
async def test_a_scheduled_fires_refusal_title_names_none_of_it_either(gate, monkeypatch, extra, kind):
    """In a scheduled task's own fire, with nobody to ask, the refusal the Inbox lists (the ordinary card's, the outside
    card's) is titled from the same reason, as the gate cut it."""
    seen = []

    async def refuse(req, ctx):
        seen.append(req)
        return "refused"
    monkeypatch.setattr(permissions, "refuse_unattended", refuse)
    with command_gate.scheduled_fire("c1"):
        for why in GATE_CUT:
            await _run_command({"command": LINE, "why": why, **extra}, None)
    assert [req.kind for req in seen] == [kind] * len(GATE_CUT)
    assert [req.title for req in seen if not _no_userinfo(req.title)] == []
