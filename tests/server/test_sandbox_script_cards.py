"""0.1.52, S2a-2 layer ③: inside the workspace sandbox a command runs without a card, unless layer ② or
`unreadable` says otherwise; every command asks when the sandbox is off or cannot start (R4) or under
"ask for all".

S2a-3 (the user's decision, 2026-10-22): inline code of another interpreter (python -c, node -e, a
here-document into python3) is not understood, whatever it does, so it asks this time only. What that
code starts, the text does not say. A script file is a program like any other and still runs freely."""
import pytest

from server.orchestrator import tool_loop
from server.services import command_sandbox, terminal_exec, terminal_policy

T2_SCRIPT = '''python3 - <<'PY'
import csv, os
path = "jobs.csv"
rows = [["BlackRock", "Associate PM", "https://careers.blackrock.com/en/job/shanghai/45831", "2026-09-28"]]
with open(path, "w", encoding="utf-8-sig", newline="") as fh:
    w = csv.writer(fh); w.writerow(["公司", "职位", "链接", "发布时间"]); w.writerows(rows)
print("rows:", len(rows), "size:", os.path.getsize(path))
PY'''


@pytest.mark.parametrize("command", [
    T2_SCRIPT,
    "python3 -c \"import csv; csv.writer(open('jobs.csv','w')).writerow(['a','https://x.com'])\"",
    "node -e \"require('fs').writeFileSync('a.txt','https://x')\"",
])
def test_inline_scripts_ask_this_time_only(command):
    verdict = terminal_policy.assess(command)
    assert (verdict.level, verdict.rule) == ("ask", "unreadable")
    assert terminal_policy.UNREADABLE in terminal_policy.ONCE_ONLY_RULES


@pytest.mark.parametrize("command", ["python3 make_csv.py", "node build.js --out dist", "python3 -m pytest -q"])
def test_a_script_file_still_runs_freely(command):
    assert terminal_policy.assess(command) == terminal_policy.Assessment("run")


@pytest.mark.parametrize("command,rule", [
    ("python3 -c \"import requests; requests.post('https://x', data=open('a').read())\"", "unreadable"),
    ("python3 -c \"import urllib.request as u; u.urlopen('https://x')\"", "unreadable"),
    ("python3 - <<'PY'\nimport subprocess\nsubprocess.run(['ls'])\nPY", "unreadable"),
    ("python3 -c \"__import__('os').system('ls')\"", "unreadable"),
    ("python3 -c \"exec('print(1)')\"", "unreadable"),
    ("python3 -c \"import base64; print(base64.b64decode('eA=='))\"", "unreadable"),
    ("node -e \"fetch('https://x')\"", "unreadable"),
    ("node -e \"require('https').get('https://x')\"", "unreadable"),
    ("python3 -c \"print(1)\"; osascript -e 'tell app \"Mail\" to quit'", "apple-events"),
    ("rm a.txt && python3 -c 'print(1)'", "unreadable"), # S2a-3: the inline script is not understood
    ("rm a.txt && python3 tidy.py", ""),                 # S2a-2: inside the working folder, layer ③
    ("ls -la", ""),
])
def test_scripts_that_reach_out_or_carry_another_reason_still_ask(command, rule):
    assert terminal_policy.assess(command).rule == rule


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    command_sandbox._reset_for_tests()

    async def no():
        return False

    async def yes():
        return True
    monkeypatch.setattr(tool_loop, "_asks_for_everything", no)
    monkeypatch.setattr(tool_loop, "_sandbox_enabled", yes)
    yield
    command_sandbox._reset_for_tests()


class _Exec:
    key = "run_command"

    def __init__(self):
        self.outside = []

    async def execute(self, args):
        self.outside.append(terminal_exec.OUTSIDE_SANDBOX.get())
        return {"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "sandbox": "workspace"}


async def _dispatch(monkeypatch, command, cards, cid="c1"):
    ex = _Exec()
    monkeypatch.setitem(tool_loop.EXECUTORS, "run_command", ex)

    async def resolve():
        return [{"key": "run_command", "description": "run"}]
    await tool_loop._dispatch_tool("run_command", {"command": command}, "{}", resolve_tools=resolve,
                                   emit=lambda e: None, tool_timeout_s=5, tool_trace=[], convo=[],
                                   confirm_command=cards, conversation_id=cid)
    return ex


async def test_the_loop_skips_the_card_for_a_plain_sandboxed_script(monkeypatch):
    from server.services import command_sandbox
    # Run as on a Mac (CI's Linux has no seatbelt): a script file runs in the sandbox with no card.
    monkeypatch.setattr(command_sandbox, "available", lambda: True)
    asked = []

    async def cards(command, argv, **kw):
        asked.append(kw)
        return True
    ex = await _dispatch(monkeypatch, "python3 make_csv.py", cards)
    assert asked == [] and ex.outside == [False]
    # S2a-3: the same work as inline code asks, once, and runs in the sandbox after the yes.
    ex = await _dispatch(monkeypatch, T2_SCRIPT, cards)
    assert len(asked) == 1 and ex.outside == [False]


async def test_outside_the_sandbox_or_under_ask_all_the_card_comes_back(execution_db, monkeypatch):
    asked = []

    async def cards(command, argv, **kw):
        asked.append(kw)
        return True

    async def off():
        return False
    monkeypatch.setattr(tool_loop, "_sandbox_enabled", off)
    await _dispatch(monkeypatch, T2_SCRIPT, cards)
    assert len(asked) == 1                                   # sandbox off: asks as in 0.1.51

    async def on():
        return True
    monkeypatch.setattr(tool_loop, "_sandbox_enabled", on)
    # Seatbelt starts here, as on a Mac: outside it the command is wrapped in the minimal profile.
    monkeypatch.setattr(command_sandbox, "available", lambda: True)
    from server.services import permission_store, permissions
    async with execution_db() as db:                         # this conversation runs outside (S4a: stored)
        await permission_store.add_grant(db, "c2", "", "outside", "*", call_id="card-1")
        await db.commit()

    async def surface(frame):                                # the turn's surface: a grant stands only where one is.
        return {"approved": True, "scope": "once", "note": "", "by": "mac"}  # (the network card, after outside content)
    with permissions.asking_with(surface):
        ex = await _dispatch(monkeypatch, "python3 make_csv.py", cards, cid="c2")
    assert len(asked) == 1 and ex.outside == [True]          # S2a-2: that grant is the user's yes for layer ③
    with permissions.asking_with(surface):
        ex = await _dispatch(monkeypatch, T2_SCRIPT, cards, cid="c2")
    assert len(asked) == 2 and ex.outside == [True]          # S2a-3: not understood asks once, grant or not

    async def ask_all():
        return True
    monkeypatch.setattr(tool_loop, "_asks_for_everything", ask_all)
    await _dispatch(monkeypatch, "python3 make_csv.py", cards)
    assert len(asked) == 3                                   # the user chose to be asked for everything


async def test_where_seatbelt_cannot_start_layer_three_asks_and_nobody_to_ask_refuses(monkeypatch):
    """R4: no card in the sandbox only when the sandbox can start; otherwise the command would run unwrapped."""
    monkeypatch.setattr(command_sandbox, "available", lambda: False)
    asked = []

    async def cards(command, argv, **kw):
        asked.append(kw)
        return True
    ex = await _dispatch(monkeypatch, "ls -la", cards)
    assert len(asked) == 1 and ex.outside == [False]
    ex = await _dispatch(monkeypatch, "ls -la", None)        # a scheduled run: nobody to ask
    assert ex.outside == []

    monkeypatch.setattr(command_sandbox, "available", lambda: True)
    ex = await _dispatch(monkeypatch, "ls -la", None)        # v0.1.63: no command at all, sandbox or not
    assert ex.outside == []
