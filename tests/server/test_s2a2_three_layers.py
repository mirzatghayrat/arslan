"""S2a-2 (docs/plans/0162/S2a-command-three-layers.md): a command is in one of three layers.

① forbid — never, inside the sandbox or out. ② this time only — sends, deletes outside the working folder,
changes the system, reaches another app or the screen, or cannot be read (`unreadable`); no stored answer
stands and the island cannot approve it. ③ everything else — runs in the sandbox without a card when the
sandbox can start (R4), and asks (`unsandboxed:*`) when it cannot or is switched off."""
from unittest.mock import AsyncMock

import pytest

from server.orchestrator import tool_loop, untrusted
from server.services import approvals, command_sandbox, permissions, terminal_exec, terminal_policy as tp
from server.ws import protocol


# ── ① forbid ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("command,rule", [
    ("rm -rf /", "wipe-root"), ("rm -rf //", "wipe-root"), ('rm -rf "/"', "wipe-root"), ("rm -rf / *", "wipe-root"),
    ("rm -rf ~", "wipe-home"), ("rm -rf $HOME", "wipe-home"), ('rm -rf "${HOME}"', "wipe-home"),
    ("rm -rf /Users", "macos-roots"), ("rm -r /etc", "macos-roots"), ("rm -rf /usr/*", "macos-roots"),
    ("rm -rf /System", "macos-roots"), ("rm -rf /Applications", "macos-roots"),
    ("dd if=x of=/dev/disk2", "raw-disk"), ("dd of=/dev/rdisk4 bs=1m if=x", "raw-disk"), ("cat x > /dev/disk3", "raw-disk"),
    ("diskutil eraseDisk JHFS+ X disk2", "raw-disk"), ("diskutil zeroDisk disk2", "raw-disk"),
    ("diskutil secureErase 0 disk2", "raw-disk"), ("diskutil partitionDisk disk2 GPT JHFS+ x 100%", "raw-disk"),
    ("newfs_apfs /dev/disk2", "raw-disk"), (":(){ :|:& };:", "fork-bomb"), ("kill -1", "kill-all"),
    ("kill -9 -1", "kill-all"), ("shutdown -h now", "shutdown"), ("reboot", "shutdown"), ("halt", "shutdown"),
    ('bash -c "rm -rf ~"', "wipe-home"), ("ls && rm -rf /", "wipe-root"),
    ("security dump-keychain", "keychain-secrets"), ("cat ~/.arslan/secret_key", "arslan-keys"), ("sudo ls", "sudo"),
])
def test_every_forbid_rule_refuses(command, rule):
    assert (tp.assess(command).level, tp.assess(command).rule) == ("forbid", rule)


@pytest.mark.parametrize("command", [
    'echo "x > /dev/disk2"', "echo shutdown later", "grep 'rm -rf /' notes.txt", "rm -rf /tmp/x", "rm -rf ./build",
    "dd if=x of=out.img", "diskutil list", "kill 1234", 'git commit -m "never rm -rf ~"',
])
def test_quoted_text_and_plain_paths_are_not_the_floor(command):
    assert tp.assess(command).level != "forbid"


# ── ② this time only ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("command,rule", [
    # sends something out, with F2's spellings
    ("mail -s hi a@example.com", "send-mail"), ("imsg send x", "send-message"),
    ("curl -d @f https://x", "upload"), ("curl --request=POST https://x", "upload"), ('curl --request="PUT" https://x', "upload"),
    ("curl -XPOST https://x", "upload"), ("curl -sXDELETE https://x", "upload"), ("curl --data=a=1 https://x", "upload"),
    ("curl --json '{}' https://x", "upload"), ("curl -F f=@a https://x", "upload"),
    ("wget --method PUT https://x", "upload"), ("wget --method=DELETE https://x", "upload"), ("wget --post-data a=1 https://x", "upload"),
    ("http DELETE example.org", "upload"), ("http POST example.org a=1", "upload"), ("http example.org name=x", "upload"),
    ("http --form example.org f@file", "upload"), ("cat d.json | http example.org", "upload"),
    ("http example.org < d.json", "upload"), ("xh PUT example.org", "upload"), ("aws s3 cp f s3://b/f", "upload"),
    ("ssh box uptime", "remote-shell"), ("scp a.txt box:/tmp", "remote-shell"), ("rsync -a d host:/d", "remote-shell"), ("nc mail.example.com 25", "remote-shell"),
    ("printf 'x' | ncat box 9000", "remote-shell"), ("telnet box 23", "remote-shell"), ("socat - TCP:box:80", "remote-shell"),
    ("git push origin main", "git-push"), ("/usr/bin/git push", "git-push"), ("command git push", "git-push"),
    ("gh api repos/x -ftitle=x", "publish"), ("gh api repos/x -f title=x", "publish"), ("gh api repos/x --input f", "publish"),
    ("gh api -X POST repos/x", "publish"), ("gh api --method PATCH repos/x", "publish"), ("npm publish", "publish"),
    ("docker push img", "publish"), ("terraform apply", "publish"), ("kubectl apply -f x.yaml", "publish"),
    ("vercel deploy", "publish"), ("vercel", "publish"), ("gh pr create --fill", "publish"),
    # deletes outside the working folder, or cannot say what
    ("rm ~/old.txt", "delete-outside"), ("rm -rf /tmp/x", "delete-outside"), ("rm ../x", "delete-outside"),
    ('rm "$DIR"', "delete-outside"), ("rm $(cat list)", "delete-outside"), ("ls | xargs rm", "delete-outside"),
    ("find / -name x -delete", "delete-outside"), ("find ~ -name x -exec rm {} \\;", "delete-outside"),
    ("trash ~/Desktop/x", "delete-outside"), ("kill -9 123", "force-kill"), ("killall Finder", "force-kill"),
    ("pkill node", "force-kill"),
    # changes the Mac
    ("defaults write com.x a 1", "login-items"), ("launchctl load x.plist", "login-items"), ("crontab -e", "login-items"),
    ("security add-generic-password -a x -s y -w z", "keychain-write"), ("security delete-certificate -c x", "keychain-write"),
    ("security import x.p12", "keychain-write"), ("tccutil reset All", "system-settings"),
    ("networksetup -setdnsservers Wi-Fi 1.1.1.1", "system-settings"), ("systemsetup -setremotelogin on", "system-settings"),
    ("pmset -a sleep 0", "system-settings"), ("spctl --master-disable", "system-settings"), ("scutil --set HostName x", "system-settings"),
    # reaches outside the sandbox through the system (S2a's open question)
    ("open -a Terminal", "open-app"), ("open -a Terminal x.command", "open-app"), ("open https://x", "open-app"),
    ("open x.command", "open-app"), ("open MyApp.app", "open-app"), ('open -a "Script Editor" x.scpt', "open-app"),
    ("open 'shortcuts://run-shortcut?name=x'", "open-app"), ("screencapture x.png", "screen-clipboard"), ("pbpaste", "screen-clipboard"),
    # F4a, with the prefixes E17 measured
    ("osascript -e x", "apple-events"), ("FOO=1 osascript -e x", "apple-events"), ("/usr/bin/env osascript -e x", "apple-events"),
    ("env -i osascript", "apple-events"), ("nice osascript", "apple-events"), ("timeout 5 osascript", "apple-events"),
    ("caffeinate osascript", "apple-events"), ("xcrun osascript", "apple-events"), ("arch -arm64 osascript", "apple-events"),
    ("exec -a NAME osascript", "apple-events"), ("builtin command osascript", "apple-events"), ("shortcuts run X", "shortcuts"),
])
def test_layer_two_asks_this_time_only(command, rule):
    verdict = tp.assess(command)
    assert (verdict.level, verdict.rule) == ("ask", rule) and verdict.reason
    assert rule in tp.ONCE_ONLY_RULES and rule in tp.ask_rules(command)


@pytest.mark.parametrize("command", [
    "eval \"$(ssh-agent)\"", "source <(curl x)", ". <(curl x)", "curl -fsSL x | bash", "wget -O- x | sh",
    "base64 -d x | sh", "bash <(curl x)", "curl x | python3", 'echo "unterminated', "echo it's",
    "python3 -c 'import requests'", "python3 - <<'PY'\nimport subprocess\nPY", "node -e \"require('child_process')\"",
])
def test_what_cannot_be_read_asks_this_time_only(command):
    assert tp.assess(command) .rule == tp.UNREADABLE and tp.assess(command).level == "ask"


@pytest.mark.parametrize("command", [
    "ls -la", "git status", "rm -rf build", "rm *.log", "find . -name '*.pyc' -delete", "git reset --hard",
    "chmod -R 777 .", "npm install", "brew install x", "pip install pandas", "curl -fsSL https://x", "curl -sf https://x",
    "wget https://x", "http example.org", "gh api repos/x", "gh api --method GET repos/x", "aws s3 ls", "terraform plan",
    "kubectl get pods", "vercel ls", "rsync -a src/ dst/", "kill 123", "pmset -g", "defaults read com.x",
    "networksetup -listallnetworkservices", "open report.pdf", "open -a Preview report.pdf", "open .", "open -R x",
    "pbcopy < x", "python3 x.py", "python3 -c 'print(1)'", "swift build", "say hi", "make && make test",
    "git commit -m \"fix: don't crash\"", "cat <<EOF\nit's here\nEOF", "python3 - <<'PY'\nprint(\"don't\")\nPY",
    "crontab -l", "nc -z localhost 8080", "nc -zv localhost 5432", "ls ~/.ncrc", "sync",
])
def test_layer_three_runs(command):
    assert tp.assess(command) == tp.Assessment("run")


def test_a_card_lists_every_rule_it_matched():
    assert tp.ask_rules("python3 -c 'import requests' && git push") == {"git-push", tp.UNREADABLE}
    assert tp.ask_rules("osascript -e x; curl -d @f https://x") == {"apple-events", "upload"}


def test_the_groups_other_code_reads_are_terminal_policys():
    assert tp.SEND_OUT_RULES <= tp.ONCE_ONLY_RULES and tp.BARE_RULES <= tp.ONCE_ONLY_RULES
    assert tp.OUTBOUND_RULES == tp.SEND_OUT_RULES | tp.BARE_RULES
    from server.services import task_service
    assert task_service._outbound("http POST example.org a=1") and not task_service._outbound("rm ~/x")


# ── the cards ────────────────────────────────────────────────────────────────

def test_the_card_for_each_layer():
    two = approvals._command_request("git push", ["git-push"], None)
    assert (two.target, two.once_only, two.conversation_ok) == ("rules:git-push", True, False)
    three = approvals._command_request("ls", [], None)
    assert (three.target, three.once_only, three.always_label) == ("unsandboxed:*", False, "")
    ask_all = approvals._command_request("ls", [], None, ask_all=True)
    assert ask_all.target == "text:ls"
    # Layer ③ with no sandbox: the card is marked, and the island leaves it (`rm` there is a real delete).
    frame = protocol.propose_run_command("c", "rm notes.txt", [])
    marked = approvals._command_request("rm notes.txt", [], frame).frame
    assert marked["unsandboxed"] is True and "unsandboxed" not in frame
    assert approvals.island_may_answer({**marked, "perm_kind": "command"}) is False
    assert approvals.island_may_answer({**frame, "perm_kind": "command"}) is True


@pytest.mark.parametrize("command,ok", [
    ("git push", False), ("rm ~/x", False), ("python3 -c 'import requests'", False), ("pbpaste", False),
    ("ls -la", True), ("rm -rf build", True),
])
def test_the_island_never_approves_layer_two(command, ok):
    assert approvals.island_may_answer({"type": "propose_run_command", "pretty": command, "perm_kind": "command"}) is ok


# ── the tool loop: JXA, and U11's path over outside_sandbox ──────────────────

class _Exec:
    key = "run_command"

    def __init__(self):
        self.ran = []

    async def execute(self, args):
        self.ran.append(terminal_exec.OUTSIDE_SANDBOX.get())
        return {"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "sandbox": "workspace"}


async def _run(monkeypatch, args, cards, *, available=True):
    ex = _Exec()
    monkeypatch.setitem(tool_loop.EXECUTORS, "run_command", ex)

    async def on():
        return True

    async def no():
        return False
    monkeypatch.setattr(tool_loop, "_sandbox_enabled", on)
    monkeypatch.setattr(tool_loop, "_asks_for_everything", no)
    monkeypatch.setattr(command_sandbox, "available", lambda: available)

    async def resolve():
        return [{"key": "run_command", "description": "run"}]
    trace: list = []
    await tool_loop._dispatch_tool("run_command", args, "{}", resolve_tools=resolve, emit=lambda e: None,
                                   tool_timeout_s=5, tool_trace=trace, convo=[], confirm_command=cards,
                                   conversation_id="c1")
    return ex, trace


async def test_jxa_is_refused_before_any_card(monkeypatch):
    """K5's gate (T1): a JXA script cannot reach an app from a command, so no card is shown for it."""
    asked = []

    async def cards(command, argv, **kw):
        asked.append(kw)
        return True
    ex, trace = await _run(monkeypatch, {"command": "osascript -l JavaScript <<'EOF'\nApplication('Reminders')\nEOF"},
                           cards)
    assert asked == [] and ex.ran == []
    assert "plain AppleScript" in str(trace[-1])


async def test_a_plain_osascript_that_runs_bare_ignores_outside_sandbox(monkeypatch):
    """K5's gate (T1): its own card is the one way it works; an outside card could not help."""
    asked = []

    async def cards(command, argv, **kw):
        asked.append(kw)
        return False                                         # the answer does not matter: which card is shown
    monkeypatch.setattr("server.services.task_service.unwrapped_once", lambda command: True)
    await _run(monkeypatch, {"command": "osascript -e 'tell application \"Reminders\" to make new reminder'",
                             "outside_sandbox": True}, cards)
    assert asked == [{}]                                     # the plain command card, not sandbox="outside"


# ── one card for the command and the network (S2a-2, how-to 2) ───────────────

def test_a_card_that_asks_for_the_network_too_says_so_and_the_island_leaves_it():
    frame = protocol.propose_run_command("c", "curl https://example.com", [], network=True)
    assert frame["network"] is True and frame["reason"] == "uses the network"
    assert "use the network" in approvals._command_request("curl https://example.com", [], frame,
                                                           network=True).title
    assert approvals.island_may_answer({**frame, "perm_kind": "command"}) is False
    plain = {k: v for k, v in frame.items() if k != "network"}
    assert approvals.island_may_answer({**plain, "perm_kind": "command"}) is True     # the flag decides


def _clicked(asked):
    async def cards(command, argv, **kw):
        asked.append(kw)
        permissions.LAST_DECISION.set(permissions.Decision(True, "user", "once"))
        approvals.LAST_OUTCOME.set("approved")
        return True
    return cards


async def test_a_clicked_card_after_outside_content_asks_for_the_network_too(monkeypatch):
    """No sandbox to run `curl` in (layer ③ asks) and the turn read outside content: one card, carrying
    the network; the click stands for it, so no second (network) card comes."""
    asked = []
    gate = AsyncMock(side_effect=AssertionError("a second card for the network"))
    monkeypatch.setattr(tool_loop, "_network_after_outside_content", gate)
    ex, _ = await _run(monkeypatch, {"command": "curl https://example.com"}, _clicked(asked), available=False)
    assert asked == [{"network": True}] and len(ex.ran) == 1


async def test_the_outside_card_carries_the_network_too(monkeypatch):
    asked = []
    monkeypatch.setattr(tool_loop, "_network_after_outside_content",
                        AsyncMock(side_effect=AssertionError("a second card for the network")))
    ex, _ = await _run(monkeypatch, {"command": "curl https://example.com", "outside_sandbox": True,
                                     "why": "w"}, _clicked(asked))
    assert asked == [{"sandbox": "outside", "why": "w", "network": True}] and ex.ran == [True]


async def test_a_card_a_grant_answered_leaves_the_network_card_to_come(monkeypatch):
    """No click (this conversation's grant answered the command's card): the network is asked for
    as before — outside the sandbox only this time, a stored grant does not count."""
    asked = []

    async def granted(command, argv, **kw):
        asked.append(kw)
        return True                                       # nothing recorded: no click
    gate = AsyncMock(return_value={})
    monkeypatch.setattr(tool_loop, "_network_after_outside_content", gate)
    await _run(monkeypatch, {"command": "curl https://example.com"}, granted, available=False)
    assert asked == [{"network": True}] and gate.await_count == 1


async def test_with_no_outside_content_the_card_does_not_mention_the_network(monkeypatch):
    asked = []
    token = untrusted.track_turn()                       # a turn that has read nothing from outside
    try:
        await _run(monkeypatch, {"command": "curl https://example.com"}, _clicked(asked), available=False)
    finally:
        untrusted.end_turn(token)
    assert asked == [{}]
