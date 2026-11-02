"""v0.1.64 CAP2a: `create_skill` is a card, on the install card's channel.

The user sees the whole SKILL.md in the window that asked; only their yes writes it (on at once, marked
as the user's). A no or no answer writes only its ledger row; nobody to ask saves nothing and keeps no
draft; a skill that would come with files, or under a key that is taken, is refused before any card."""
import json

import pytest
from sqlalchemy import select

from server.db import session as db_session
from server.db.models import SkillPack
from server.registry import executors, seed_catalog
from server.services import approvals, background_jobs, permission_store, permissions, skill_forge

BODY = ("## Trigger\nThe user asks for this week's report, or says \"wrap up the week\" on a Friday.\n\n"
        "## Method\n1. Read this week's meeting notes.\n2. Keep each meeting's decisions and who does what.\n")
ARGS = {"key": "weekly-report", "name": "Weekly report", "description": "A one-page report of the week",
        "body": BODY, "why": "save what we just did as a skill"}


@pytest.fixture(autouse=True)
def _fresh(execution_db, tmp_path, monkeypatch):
    permission_store._reset_for_tests()
    from server import config
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path)


def _window(approved=True, outcome=None, seen=None):
    """The asking window's card (`confirm_command.ask_capability`)."""
    async def ask(card):
        if seen is not None:
            seen.append(card)
        approvals.LAST_OUTCOME.set(outcome or ("approved" if approved else "declined"))
        return {"approved": approved, "call_id": "cap-1", "keys": {}, "folders": []}
    return ask


async def _never(card):
    raise AssertionError("no card for this")


async def _propose(args=None, ask=None):
    return await skill_forge.propose({**ARGS, **(args or {})}, conversation_id="c1", ask=ask)


async def _skills() -> dict:
    async with db_session.AsyncSessionLocal() as db:
        return {p.key: p for p in (await db.execute(select(SkillPack))).scalars().all()}


async def _rows():
    async with db_session.AsyncSessionLocal() as db:
        return list(reversed(await permission_store.recent(db)))


def _row_text(row) -> str:
    return json.dumps({c: getattr(row, c) for c in ("kind", "target", "detail", "extra")}, default=str)


async def test_a_yes_saves_exactly_the_text_shown_as_the_users_skill_on_at_once():
    from server.orchestrator import arslan, untrusted
    seen = []
    token = untrusted.track_turn()                                   # a turn that read nothing from outside
    try:
        out = await _propose(ask=_window(seen=seen))
    finally:
        untrusted.end_turn(token)
    assert out["ok"] is True and out["saved"] == "weekly-report" and out["refresh"] is True
    [card] = seen
    assert (card["kind"], card["key"], card["name"], card["body"]) == (skill_forge.AUTHORED, "weekly-report",
                                                                       "Weekly report", BODY)
    assert card["why"] == "save what we just did as a skill" and card["outside"] is False
    pack = (await _skills())["weekly-report"]
    assert (pack.body, pack.name, pack.category, pack.enabled, pack.status) == (card["body"], card["name"],
                                                                                "authored", True, "registered")
    assert "weekly-report" in await arslan._skill_index()             # read_skill lists it from now on
    [row] = await _rows()
    assert (row.kind, row.target, row.conversation_id) == ("capability", "skill:weekly-report", "c1")
    assert (row.decided_by, row.decision, row.scope) == ("user", "allow", "once")
    assert "meeting notes" not in _row_text(row)                      # the ledger never keeps the body


@pytest.mark.parametrize("outcome,decided", [("declined", ("user", "deny")), ("expired", ("expired", "expired"))])
async def test_a_no_or_no_answer_saves_nothing_but_its_ledger_row(outcome, decided):
    out = await _propose(ask=_window(approved=False, outcome=outcome))
    assert out["ok"] is False and out["declined"] is True and outcome in out["note"]
    assert "weekly-report" not in await _skills()
    [row] = await _rows()
    assert (row.decided_by, row.decision) == decided and row.target == "skill:weekly-report"


async def test_a_scheduled_run_saves_nothing_keeps_no_draft_and_the_inbox_lists_it():
    out = await _propose(ask=None)                                   # no card surface at all (S1)
    assert out["ok"] is False and out["not_saved"] is True
    assert "weekly-report" not in await _skills()
    [row] = await _rows()
    assert (row.kind, row.target, row.decided_by, row.decision) == ("capability", "skill:weekly-report",
                                                                    "policy", "deny")


async def test_a_background_job_saves_nothing_and_writes_no_row():
    async def surface(frame):
        raise AssertionError("a job shows no save-a-skill card")
    token = background_jobs._inside_job.set("job-1")
    try:
        with permissions.asking_with(surface):
            out = await _propose(ask=None)
    finally:
        background_jobs._inside_job.reset(token)
    assert out["not_saved"] is True and "weekly-report" not in await _skills() and await _rows() == []


@pytest.mark.parametrize("args,says", [
    ({"body": "no trigger section here " * 10}, "'## Trigger'"),
    ({"body": "## Trigger\n" + "x" * (skill_forge.MAX_SKILL_BYTES + 10)}, "KB limit"),
    ({"key": "Weekly Report"}, "key must be"),
    ({"key": "w" * 61}, "at most 60"),
    ({"name": " \u200b "}, "name is required"),
    ({"name": "\u3164\u3164"}, "name is required"),                     # Hangul fillers only (review F4)
    ({"body": BODY + '\nRun it with run_python {"skill_script": "weekly-report/build.py"}.\n'}, "attached files"),
    ({"body": BODY + '\nRead read_skill {"key": "weekly-report", "section": "references/layout.md"}.\n'},
     "attached files"),
    ({"body": BODY + "\n## Bundled scripts\n- build.py\n"}, "attached files"),
], ids=["no-trigger", "too-big", "bad-key", "long-key", "blank-name", "filler-name", "script", "reference", "bundled"])
async def test_refused_before_any_card(args, says):
    out = await _propose(args, ask=_never)
    assert out["ok"] is False and says in out["error"]
    assert "weekly-report" not in await _skills() and await _rows() == []


async def test_files_left_on_disk_under_the_key_are_refused_before_any_card(tmp_path):
    """A removed import's scripts and references stay in skill_scripts/<key>/: read_skill and run_python would
    serve them with a skill of that key."""
    (tmp_path / "skill_scripts" / "weekly-report" / "references").mkdir(parents=True)
    out = await _propose(ask=_never)
    assert out["ok"] is False and "files are already stored" in out["error"] and await _rows() == []


async def test_a_key_that_is_taken_is_refused_before_any_card_and_never_overwritten():
    async with db_session.AsyncSessionLocal() as db:
        db.add(SkillPack(key="weekly-report", name="Theirs", category="imported", description="d", tier="safe",
                         status="registered", body=BODY))
        await db.commit()
    out = await _propose(ask=_never)
    assert out["ok"] is False and "pick another key" in out["error"]
    assert (await _skills())["weekly-report"].name == "Theirs" and await _rows() == []


async def test_a_skill_of_that_key_written_while_the_card_waits_is_not_overwritten():
    async def ask(card):
        async with db_session.AsyncSessionLocal() as db:
            db.add(SkillPack(key="weekly-report", name="Other", category="imported", description="d", tier="safe",
                             status="registered", body=BODY))
            await db.commit()
        return {"approved": True, "call_id": "cap-1", "keys": {}, "folders": []}
    out = await _propose(ask=ask)
    assert out["ok"] is False and "meanwhile" in out["error"]
    assert (await _skills())["weekly-report"].name == "Other"


#: Invisible characters outside the "C" categories (review F4): a variation selector, the combining grapheme
#: joiner, Hangul fillers, the blank braille pattern, a supplementary variation selector.
HIDDEN = "\ufe0f\u034f\u115f\u1160\u3164\uffa0\u2800\U000e0100"


async def test_the_card_shows_what_is_stored_names_clean_and_the_body_as_written():
    """#472 F4 under UNI1 (CAPX-followups.md): a name loses every hidden character, so a bidi override or a
    zero-width character cannot make the card's title read differently. The body keeps ordinary text, format
    characters included (the card shows a bidi control escaped; UNI1b counts the rest), and loses only Tag and
    control characters. What the card shows is what is stored."""
    seen, tag = [], "\U000e0041"
    await _propose({"name": "Weekly\u202e report\n" + HIDDEN, "description": "A one-page\u200b report" + HIDDEN,
                    "body": BODY + "Always cite the notes.\u202e\u200b\x07" + HIDDEN + tag + "\n"},
                   ask=_window(seen=seen))
    [card] = seen
    assert card["name"] == "Weekly report" and card["description"] == "A one-page report"
    assert "Always cite the notes.\u202e\u200b" + HIDDEN + "\n" in card["body"] and not {"\x07", tag} & set(card["body"])
    pack = (await _skills())["weekly-report"]
    assert (pack.name, pack.description, pack.body) == (card["name"], card["description"], card["body"])


async def test_blank_padding_cannot_hide_the_end_of_the_text():
    """Review F5 and recheck R1: the box shows 190 px. Blank lines, trailing white space, long runs inside a
    line (any white space, not only spaces) and the line separators are tidied before the card, so the last
    line stays in reach; the card's line count is read_skill's; the skill keeps exactly the tidied text."""
    seen = []
    padded = (BODY + "\n" * 60 + "Then send it." + " " * 400 + "to the team.   \n" + " " * 100 + "Done.\n"
              + "Ideographic" + "\u3000" * 2000 + "no-break" + "\u00a0" * 2000 + "em" + "\u2003" * 2000 + "end.\n"
              + "Separators" + "\u2028" * 2000 + "\u2029" * 50 + "last line.\n\n\n")
    out = await _propose({"body": padded}, ask=_window(seen=seen))
    [card] = seen
    body = card["body"]
    assert "\n\n\n" not in body and "\u2028" not in body and "\u2029" not in body
    assert not any(line != line.rstrip() for line in body.split("\n"))
    assert "Then send it." + " " * 16 + "to the team.\n" + " " * 64 + "Done.\n" in body
    assert "Ideographic" + " " * 16 + "no-break" + " " * 16 + "em" + " " * 16 + "end.\n" in body
    assert body.endswith("Separators\n\nlast line.\n")
    assert len(body.rstrip("\n").split("\n")) == len(body.splitlines())   # the web's count, read_skill's split
    assert (await _skills())["weekly-report"].body == body
    assert out["tidied"] is True and "taken out" in out["note"]


#: Indentation is meaning in code and YAML: kept as written (recheck R1), up to 64 characters.
CODE = ("```python\ndef f(xs):\n    for a in xs:\n        for b in a:\n            for c in b:\n"
        "                if c:\n                    print(c)\n                print('x')\n```\n"
        "```yaml\nspec:\n  template:\n    spec:\n      containers:\n        - name: app\n          env:\n"
        "            - name: X\n              valueFrom:\n                secretKeyRef:\n                  name: s\n```\n"
        "```make\nall:\n\tcc -o app main.c\n\t                 -O2\n```\n")


async def test_indentation_in_code_is_kept_as_written():
    seen = []
    out = await _propose({"body": BODY + CODE}, ask=_window(seen=seen))
    assert seen[0]["body"] == BODY + CODE and (await _skills())["weekly-report"].body == BODY + CODE
    assert "tidied" not in out and "taken out" not in out["note"]


@pytest.mark.parametrize("read_outside", [False, True])
async def test_the_card_says_when_this_turn_read_outside_content(read_outside):
    from server.orchestrator import untrusted
    seen = []
    token = untrusted.track_turn()
    try:
        if read_outside:
            untrusted.mark_external()
        await _propose(ask=_window(seen=seen))
    finally:
        untrusted.end_turn(token)
    assert seen[0]["outside"] is read_outside


async def test_outside_any_turn_the_card_takes_the_safe_side():
    seen = []
    await _propose(ask=_window(seen=seen))
    assert seen[0]["outside"] is True


async def test_the_tool_loop_asks_on_the_install_cards_channel_directly_and_through_use_tool(monkeypatch):
    """The same card and the same ledger row either way; inside a background job there is no card."""
    from server.orchestrator import on_demand
    from tests.server import test_k7_on_demand as k7
    golden = k7.golden
    cards = []

    async def confirm_command(*a, **k):
        return False
    confirm_command.ask_capability = _window(approved=False, seen=cards)
    maker = {"key": "create_skill", "description": "c"}

    async def direct():
        return [maker]

    async def without():
        return [on_demand.USE_TOOL]
    await k7._turn(monkeypatch, [golden._Resp(tool_calls=[golden._tc("create_skill", ARGS)]), golden._Resp(content="ok")],
                   conversation="c-direct", resolve_tools=direct, resolve_callable=direct, confirm_command=confirm_command)
    await k7._turn(monkeypatch, [golden._Resp(tool_calls=[golden._tc("use_tool", {"name": "create_skill", "arguments": ARGS})]),
                                 golden._Resp(content="ok")],
                   conversation="c-proxy", resolve_tools=without, resolve_callable=direct, confirm_command=confirm_command)
    assert len(cards) == 2 and cards[0] == cards[1] and cards[0]["kind"] == skill_forge.AUTHORED
    assert [(r.target, r.decided_by, r.decision) for r in await _rows()] == [("skill:weekly-report", "user", "deny")] * 2
    token = background_jobs._inside_job.set("job-1")
    try:
        await k7._turn(monkeypatch, [golden._Resp(tool_calls=[golden._tc("create_skill", ARGS)]), golden._Resp(content="ok")],
                       conversation="c-job", resolve_tools=direct, resolve_callable=direct, confirm_command=confirm_command)
    finally:
        background_jobs._inside_job.reset(token)
    assert len(cards) == 2 and "weekly-report" not in await _skills()


def test_nothing_writes_a_skill_behind_the_card():
    """No executor: every create_skill call goes through the tool loop's card branch."""
    assert "create_skill" not in executors.EXECUTORS


def test_tool_in_catalog_as_safe_wired():
    ts = next(t for t in seed_catalog.TOOLSETS if t["key"] == "skill_authoring")
    assert ts["tier"] == "safe"
    assert ts["status"] == "wired"
    tools = {t[0]: t for t in ts["tools"]}
    assert "create_skill" in tools
    _, _, tier, status = tools["create_skill"]
    assert (tier, status) == ("safe", "wired")
