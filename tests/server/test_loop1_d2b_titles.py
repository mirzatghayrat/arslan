"""LOOP1 d2b: a card's steps and title come from shell_grammar's one reading of the command, the pass the policy's
rules read (`terminal_policy.reading`), when the grammar understands the whole command. A command it does not
understand keeps card_purpose's own reading and its `unreadable` rule line. Verdicts do not change; titles do (the user
approved that on 2026-11-11). ③Hands' four conditions are pinned here: the title never hides what asked, the outside
prefix stays on the new title, an unread command keeps today's reading, and the card keeps the full command text."""
from __future__ import annotations

import pytest

from server.services import card_purpose, command_confirm, command_sandbox, permissions, terminal_policy as tp
from tests.server.test_s2a3_outside_reach import _dispatch, gate  # noqa: F401  (`gate` is a fixture)

S = card_purpose.summarize


def _key(line: str) -> tuple:
    s = S(line)
    return s["purpose"]["key"], s["purpose"]["params"], s["more"]


# ── the grammar's steps, by what the old reader got wrong ──

@pytest.mark.parametrize("line, reading", [
    # a compound command's keywords are not steps; what runs inside it is
    ("if true; then rm -rf ../x; fi", ("delete", {"count": 1}, 0)),
    ("for f in a b; do rm -rf build; done", ("delete", {"count": 1}, 0)),
    ("{ rm ../x; }", ("delete", {"count": 1}, 0)),
    ("(cd build && cmake ..)", ("run", {"program": "cmake"}, 0)),
    # a comment is not a step
    ("ls # ; rm -rf /tmp/x", ("run", {"program": "ls"}, 0)),
    # a here-document's body is the program's input, not steps
    ("cat <<'EOF'\nrm -rf /tmp/x\ncurl https://e.example\nEOF", ("run", {"program": "cat"}, 0)),
    # `!` is not a program
    ("! grep -q x notes.txt", ("run", {"program": "grep"}, 0)),
    # a wrapper is read through to its command, and bash -c to its script
    ("sudo rm -rf build", ("delete", {"count": 1}, 0)),
    ("gtimeout 5 ls", ("run", {"program": "ls"}, 0)),
    ("BASH -c 'curl https://e.example'", ("overNetwork", {"program": "curl"}, 0)),
])
def test_an_understood_commands_steps_are_the_grammars(line, reading):
    assert not tp.reading(line).refused
    assert _key(line) == reading


def test_a_steps_own_redirection_stays_its_steps():
    """The file a command's redirection writes is what it touches, and does not take the title from it."""
    assert S("git status > status.txt") == {"purpose": {"key": "git", "params": {"sub": "status"}},
                                            "touches": ["status.txt"], "more": 0, "unsure": False}
    assert S("echo hi > notes.txt")["purpose"] == {"key": "write", "params": {"target": "notes.txt"}}


def test_a_wrappers_redirection_is_its_commands():
    assert S("nohup make > build.log") == {"purpose": {"key": "run", "params": {"program": "make"}},
                                           "touches": ["build.log"], "more": 0, "unsure": False}


def test_a_compound_commands_redirection_is_a_write_of_its_own():
    assert S("for f in a b; do echo $f; done > list.txt")["purpose"] == {"key": "write",
                                                                          "params": {"target": "list.txt"}}


def test_a_change_of_folder_holds_only_in_the_shell_it_is_made_in():
    """The grammar's folders: a `cd` inside a `$( … )` or a ( … ) does not move the steps after it."""
    assert S("echo $(cd /tmp && rm a); rm b")["touches"] == ["/tmp/a", "b"]
    assert S("(cd /tmp); rm notes.txt")["touches"] == ["notes.txt"]
    assert S("cd ~/work && rm old.zip")["touches"] == ["~/work/old.zip"]


# ── ③Hands 1: the title never hides what asked ──

@pytest.mark.parametrize("line, rule, title", [
    ("ls; defaults write com.example key 1", "login-items", "Run defaults (and 1 more step)"),
    ("rm -rf build && git push origin main", "git-push", "Publish your commits to origin (and 1 more step)"),
    ("echo hi > notes.txt; echo 'export A=1' >> ~/.zshrc", "protected-write", "Write to ~/.zshrc (and 1 more step)"),
])
def test_a_harmless_first_step_never_takes_the_title_from_a_once_only_one(line, rule, title):
    assert rule in tp.ONCE_ONLY_RULES and rule in tp.ask_rules(line)
    assert card_purpose.phrase(line, lang="en") == title


@pytest.mark.parametrize("line, rule, title", [
    ("bash <<'EOF'\ngit push origin main\nEOF", "git-push", "Publish your commits to origin (and 2 more steps)"),
    ("python3 - <<'EOF'\nrm -rf ../x\nEOF", "delete-outside", "Delete 1 file or folder (and 2 more steps)"),
])
def test_a_here_document_a_shell_or_an_interpreter_runs_keeps_the_rules_step_in_the_title(line, rule, title):
    """③Hands on #828: a here-document's body is data only to a program that reads it as data (`cat`). One a shell or
    an interpreter runs is code, which the grammar does not read (step 3's file-run rule), so the card keeps its own
    reading of the body's steps and the title names the step the rule asks for."""
    assert tp.reading(line).refused
    assert rule in tp.ONCE_ONLY_RULES and rule in tp.ask_rules(line)
    assert card_purpose.phrase(line, lang="en") == title


BODY = "\nrm -rf ../x\nEOF"


@pytest.mark.parametrize("line", [
    # an interpreter by -m, or behind a runner
    "python3 -m code <<'EOF'" + BODY, "uv run python <<'EOF'" + BODY, "uvx python <<'EOF'" + BODY,
    "pipx run python <<'EOF'" + BODY, "poetry run python <<'EOF'" + BODY, "npx -y tsx <<'EOF'" + BODY,
    # a shell, a REPL or a tool that reads commands, under a name the grammar has no reason to refuse
    "busybox sh <<'EOF'" + BODY, "irb <<'EOF'" + BODY, "expect - <<'EOF'" + BODY, "sqlite3 <<'EOF'" + BODY,
    "make -f - <<'EOF'" + BODY,
    # a scheduler, also behind a wrapper
    "at now <<'EOF'" + BODY, "batch <<'EOF'" + BODY, "crontab - <<'EOF'" + BODY, "nohup at now <<'EOF'" + BODY,
    # piped to one, written into a held file, or written into a file a later step runs
    "cat <<'EOF' | python3 -m code" + BODY, "cat <<'EOF' | at now" + BODY, "cat >> ~/.zshrc <<'EOF'" + BODY,
    "tee ~/.zshrc <<'EOF'" + BODY, "cat > Makefile <<'EOF'\nall:\n\trm -rf ../x\nEOF\nmake",
])
def test_a_here_document_any_program_but_a_data_reader_gets_keeps_the_bodys_step(line):
    """#828 review: the grammar understands these, and each may run the body (or a file it was written into). A
    here-document is data only when every program in the line reads its input as data, so these keep the old
    reading: the title names the step the rule asks for, as on main."""
    assert not tp.reading(line).refused and "delete-outside" in tp.ask_rules(line)
    old = card_purpose._read(line)                       # this module's own reader, main's for every line
    assert S(line)["purpose"] == old["purpose"] == {"key": "delete", "params": {"count": 1}}
    assert S(line)["more"] == old["real"] - 1


@pytest.mark.parametrize("line, title", [
    ("cat <<'EOF'" + BODY, "Run cat"),
    ("git commit -F - <<'EOF'" + BODY, "Run git commit"),
    ("grep -c x <<'EOF' | wc -l" + BODY, "Run grep (and 1 more step)"),
])
def test_a_here_document_a_data_reader_gets_is_data(line, title):
    assert card_purpose.phrase(line, lang="en") == title


@pytest.mark.parametrize("line, title", [
    ("crontab probe.cron && open notes.pdf", "Run crontab (and 1 more step)"),
    ("open notes.pdf && pbpaste", "Run pbpaste (and 1 more step)"),
    ("open notes.pdf && git config --global x.y z", "Run git config (and 1 more step)"),
    ("at now && crontab probe.cron", "Run crontab (and 1 more step)"),
])
@pytest.mark.parametrize("outside", [False, True])
def test_a_step_that_only_reaches_outside_never_takes_the_lead_from_a_named_rules(line, title, outside):
    """#828 review: outside-reach is asked only outside the sandbox and only where no named rule matched, so a step
    that only reaches outside never leads over the step the card's rule is about."""
    assert tp.OUTSIDE_REACH[0] not in tp.ask_rules(line, outside=outside)
    assert card_purpose.summarize(line, outside=outside) == card_purpose.summarize(line)
    assert card_purpose.phrase(line, lang="en").endswith(title)


def test_outside_reach_takes_the_title_only_where_it_is_asked():
    line = "ls docs; at now"
    assert tp.ask_rules(line, outside=True) == {tp.OUTSIDE_REACH[0]} and tp.ask_rules(line) == set()
    assert card_purpose.phrase(line, lang="en", outside=True) == "Outside the sandbox · Run at (and 1 more step)"
    assert card_purpose.phrase(line, lang="en") == "Run ls (and 1 more step)"
    # outside, but a rule the text matched (an upload through a pipe) is what asks: outside-reach is not asked
    piped = "ls; cat d.json | http example.test; open notes.pdf"
    assert tp.ask_rules(piped, outside=True) == {"upload"}
    assert card_purpose.phrase(piped, lang="en", outside=True) == (
        "Outside the sandbox · Uses the network (http): may send or receive data (and 3 more steps)")


# ── the #828 review's surviving mutants, each a title or a touch ──

@pytest.mark.parametrize("line, title, touches", [
    ("bash -c 'ls' > ~/.zshrc", "Write to ~/.zshrc (and 1 more step)", ["~/.zshrc"]),   # bash -c's own write
    ("cd /a; cd /b; rm x", "Delete 1 file or folder", ["/b/x", "/a/x", "x"]),          # each folder, the last first
    ("cd build; echo x > out.txt", "Write to build/out.txt", ["build/out.txt", "out.txt"]),
    ("{ echo a > x.txt; } > y.txt", "Write to x.txt (and 1 more step)", ["x.txt", "y.txt"]),   # a compound's after
    ("echo hi > /dev/null; ls", "Run ls", []),                                         # /dev/null is no file
    ("CD ~/w && rm x", "Delete 1 file or folder (and 1 more step)", ["~/w", "~/w/x"]),  # the disk ignores case
])
def test_the_details_of_an_understood_reading(line, title, touches):
    assert card_purpose.phrase(line, lang="en") == title and S(line)["touches"] == touches


# ── ③Hands 2: the outside prefix and mark stay, on top of the new title ──

MOVED = "if true; then open notes.txt; fi"            # main titled it "Run if"


@pytest.mark.parametrize("kw", [{"grant": object(), "ask_all": True}, {"enabled": False}, {"available": False}],
                         ids=["ask-all-with-a-grant", "sandbox-off", "seatbelt-unavailable"])
async def test_a_card_with_no_sandbox_keeps_its_prefix_and_mark(gate, monkeypatch, kw):  # noqa: F811
    setup, shown = gate
    setup(**kw)                                      # pins command_sandbox.available, whatever the CI machine has
    await _dispatch(monkeypatch, {"command": MOVED}, command_confirm.Confirmations("c1").command)
    [card] = shown
    assert card.title == "No sandbox · Open notes.txt" and card.frame["unsandboxed"] is True


async def test_the_outside_sandbox_card_keeps_its_prefix_and_mark(gate, monkeypatch):  # noqa: F811
    setup, shown = gate
    setup()
    await _dispatch(monkeypatch, {"command": MOVED, "outside_sandbox": True, "why": "Look at the notes"},
                    command_confirm.Confirmations("c1").command)
    [card] = shown
    assert card.kind == "outside" and card.frame["sandbox"] == "outside"
    assert card.title == "Outside the sandbox · Open notes.txt · Look at the notes"


# ── ③Hands 3 and 4, on the card itself ──

class _Seen:
    def __init__(self):
        self.requests: list = []

    async def __call__(self, request, context):
        self.requests.append(request)
        return permissions.Decision(False, "user", "once")


@pytest.fixture
def seen(monkeypatch):
    monkeypatch.setattr(command_sandbox, "available", lambda: True)
    decide = _Seen()
    monkeypatch.setattr(permissions, "decide", decide)
    return decide.requests


UNREAD = "echo `date`; rm -rf build"


async def test_an_unread_command_keeps_its_old_reading_and_its_unreadable_line(execution_db, seen):
    assert tp.reading(UNREAD).refused and tp.reading(UNREAD).commands == ()
    assert S(UNREAD) == {"purpose": {"key": "delete", "params": {"count": 1}}, "touches": ["build"], "more": 1,
                         "unsure": False}
    await command_confirm.Confirmations("c1").command(UNREAD, [])
    [request] = seen
    assert request.title == "Delete 1 file or folder (and 1 more step)"
    assert request.frame["rules"] == [tp.UNREADABLE] and request.target == f"rules:{tp.UNREADABLE}"


async def test_the_card_keeps_the_whole_command(execution_db, seen):
    line = "if true; then rm -rf build; fi"
    await command_confirm.Confirmations("c1").command(line, [])
    [request] = seen
    assert request.title == "Delete 1 file or folder"
    assert request.detail == line and request.frame["pretty"] == line and request.frame["command"] == line


# ── #826's review: the reader pass reads the whole text as given ──

def test_the_pass_reads_past_the_first_200_characters():
    line = "echo " + "a" * 250 + "; rm -rf build"
    assert tp.reading(line).commands[-1] == ("rm", "-rf", "build")
    assert S(line)["purpose"] == {"key": "delete", "params": {"count": 1}}


def test_the_pass_reads_the_text_unstripped():
    """A blank and a backslash before the final newline continue the line, so bash runs `rm x`; stripped, the text
    ends in a lone backslash, which the grammar does not read."""
    line = "rm x \\\n"
    assert not tp.reading(line).refused
    assert S(line) == {"purpose": {"key": "delete", "params": {"count": 1}}, "touches": ["x"], "more": 0,
                       "unsure": False}
