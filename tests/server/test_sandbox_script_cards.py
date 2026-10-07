"""0.1.52: inside the workspace sandbox a plain data script runs without a card; a script
that reaches out, starts programs, drives other apps or hides its code still asks, and
so does anything with another reason to ask, outside the sandbox, or under "ask for all"."""
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
def test_plain_scripts_run_freely(command):
    assert terminal_policy.assess(command).rule.startswith("hermes:script execution")
    assert terminal_policy.runs_freely_in_sandbox(command) is True


@pytest.mark.parametrize("command", [
    "python3 -c \"import requests; requests.post('https://x', data=open('a').read())\"",
    "python3 -c \"import urllib.request as u; u.urlopen('https://x')\"",
    "python3 - <<'PY'\nimport subprocess\nsubprocess.run(['ls'])\nPY",
    "python3 -c \"__import__('os').system('ls')\"",
    "python3 -c \"exec('print(1)')\"",
    "python3 -c \"import base64; print(base64.b64decode('eA=='))\"",
    "node -e \"fetch('https://x')\"",
    "node -e \"require('https').get('https://x')\"",
    "python3 -c \"print(1)\"; osascript -e 'tell app \"Mail\" to quit'",
    "rm a.txt && python3 -c 'print(1)'",
    "ls -la",
])
def test_scripts_that_reach_out_or_carry_another_reason_still_ask(command):
    assert terminal_policy.runs_freely_in_sandbox(command) is False


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
    asked = []

    async def cards(command, argv, **kw):
        asked.append(kw)
        return True
    ex = await _dispatch(monkeypatch, T2_SCRIPT, cards)
    assert asked == [] and ex.outside == [False]


async def test_outside_the_sandbox_or_under_ask_all_the_card_comes_back(monkeypatch):
    asked = []

    async def cards(command, argv, **kw):
        asked.append(kw)
        return True
    cards.honours_session_grants = True                      # the chat window's callback

    async def off():
        return False
    monkeypatch.setattr(tool_loop, "_sandbox_enabled", off)
    await _dispatch(monkeypatch, T2_SCRIPT, cards)
    assert len(asked) == 1                                   # sandbox off: asks as in 0.1.51

    async def on():
        return True
    monkeypatch.setattr(tool_loop, "_sandbox_enabled", on)
    command_sandbox.grant("c2")                              # this conversation runs outside
    await _dispatch(monkeypatch, T2_SCRIPT, cards, cid="c2")
    assert len(asked) == 2

    async def ask_all():
        return True
    monkeypatch.setattr(tool_loop, "_asks_for_everything", ask_all)
    await _dispatch(monkeypatch, T2_SCRIPT, cards)
    assert len(asked) == 3                                   # the user chose to be asked for everything
