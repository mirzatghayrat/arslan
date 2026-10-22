"""0.1.62 F4a (R2): osascript and `shortcuts run` through the terminal are recognised however
they are written (a path, `command`, `exec`, `xargs`), and their card is for this time only:
no "In this conversation", no "Always", and no answer stored before it lets one through."""
from unittest.mock import AsyncMock

import pytest

from server.services import approvals, permissions, run_registry
from server.services import terminal_policy as tp
from tests.server.test_background_jobs import CID, _declining
from tests.server.test_run_command_confirm_flow import (_collect_until, _enable_shell,
                                                        _stub_run_command_executor, _stub_tool_loop_adapter,
                                                        app_client)  # noqa: F401 — a fixture

OSA = "-e 'tell application \"Finder\" to activate'"
SPELLINGS = [
    (f"osascript {OSA}", "apple-events"),
    (f"/usr/bin/osascript {OSA}", "apple-events"),
    (f"command osascript {OSA}", "apple-events"),
    ("echo x | xargs osascript", "apple-events"),
    ("printf 'a\\0' | xargs -0 osascript", "apple-events"),
    ("ls *.scpt | xargs -I {} osascript {}", "apple-events"),
    ("ls *.scpt | xargs -n 1 osascript", "apple-events"),
    (f"exec /usr/bin/osascript {OSA}", "apple-events"),
    (f"command /usr/bin/osascript {OSA}", "apple-events"),
    ('shortcuts run "Send note"', "shortcuts"),
    ('/usr/bin/shortcuts run "Send note"', "shortcuts"),
    ('command shortcuts run "Send note"', "shortcuts"),
]


@pytest.mark.parametrize("command,rule", SPELLINGS)
def test_every_spelling_is_recognised(command, rule):
    verdict = tp.assess(command)
    assert verdict.level == "ask" and verdict.rule == rule, verdict


def test_inside_a_shell_string_too():
    assert "apple-events" in tp.ask_rules(f'zsh -c "/usr/bin/osascript {OSA}"')


@pytest.mark.parametrize("command", ['echo "use osascript"', "grep -r osascript .", "cat shortcuts.txt",
                                     "command -v osascript"])
def test_a_mention_is_not_a_run(command):
    assert tp.assess(command).level == "run"


@pytest.mark.parametrize("command,rule", SPELLINGS)
def test_the_card_is_for_this_time_only(command, rule):
    req = approvals._command_request(command, sorted(tp.ask_rules(command)), None)
    assert req.once_only is True
    assert permissions.options_for(req) == ["once"]
    assert req.remember_as == () and req.always_label == ""      # the Inbox's "Always allow" stores nothing


def test_a_remembered_rule_no_longer_lets_it_through():
    # S2a-2: no stored "Always" is read for any rule now; these two were the first (F4a).
    assert {"apple-events", "shortcuts"} <= tp.ONCE_ONLY_RULES
    assert tp.assess("brew install x").level == "run"                  # `install` is gone: the sandbox holds it


def test_a_once_only_ask_never_shares_a_card_with_one_that_is_not():
    import dataclasses
    once = approvals._command_request("osascript x", ["apple-events"], None)
    assert permissions._dedupe(once) != permissions._dedupe(dataclasses.replace(once, once_only=False))


async def test_a_jobs_card_offers_only_this_time(execution_db, monkeypatch):
    from server.services import settings_service
    monkeypatch.setattr(settings_service, "shell_confirm_policy", AsyncMock(return_value="ask_risky"))
    monkeypatch.setattr(tp, "always_allowed", AsyncMock(return_value={"apple-events"}))
    asked = []
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: _declining(asked, "options"))
    confirm = approvals.JobConfirmations(CID)
    assert await confirm.command(f"/usr/bin/osascript {OSA}", []) is False   # remembered, still asked
    assert asked == [["once"]]


def test_the_windows_card_offers_only_this_time_despite_a_rule_and_a_grant(app_client, monkeypatch):  # noqa: F811
    from server.services import permission_store
    _enable_shell(app_client, policy="ask_risky")

    async def remember():
        async with app_client.db_maker() as db:
            await permission_store.add_rule(db, "legacy_rule", "apple-events", created_from="card")
            await permission_store.add_grant(db, "osa", "", "command", "rules:apple-events")
            await db.commit()
    app_client.portal.call(remember)
    for command in (f"osascript {OSA}", f"/usr/bin/osascript {OSA}"):
        _stub_tool_loop_adapter(monkeypatch, command, [])
        executor = _stub_run_command_executor(monkeypatch)
        with app_client.websocket_connect("/ws/arslan/osa") as ws:
            ws.receive_json()
            ws.send_json({"type": "user_message", "content": "tell Finder"})
            frames = _collect_until(ws, "propose_run_command")
            assert frames[-1]["type"] == "propose_run_command", [f["type"] for f in frames]
            assert frames[-1]["options"] == ["once"]
            ws.send_json({"type": "cancel_run_command", "call_id": frames[-1]["call_id"]})
            _collect_until(ws, "stream_end")
        assert executor.calls == []


# ── review fixes (⓪Plan on #199) ───────────────────────────────────────────────────────

@pytest.mark.parametrize("make,n", [
    (lambda n: "xargs " + " ".join(["-n 1"] * n) + " not-osascript", 40),
    (lambda n: "xargs " + " ".join(["-0"] * n) + " cat", 60),
    (lambda n: "xargs " + " ".join(["-n1"] * n) + " -I", 40),
    (lambda n: "ls | xargs " + "-P 4 " * n + "osascript.sh", 40),
], ids=["n-1", "zero", "n1", "P-4"])
def test_recognising_a_long_xargs_line_is_fast(make, n):
    _assert_grows_linearly(make, n)


class _TooSlow(Exception):
    pass


class _hard_limit:
    """Fail instead of hanging if a pattern ever backtracks without end again (SIGALRM, Unix)."""

    def __init__(self, seconds):
        self.seconds = seconds

    def __enter__(self):
        import signal

        def stop(signum, frame):
            raise _TooSlow(f"pattern matching took longer than {self.seconds} s")
        self.old = signal.signal(signal.SIGALRM, stop)
        signal.setitimer(signal.ITIMER_REAL, self.seconds)

    def __exit__(self, *exc):
        import signal
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, self.old)
        return False


def _our_patterns_take(texts) -> float:
    """CPU time this thread spends on the once-only rules over these detection texts, under the hard
    limit. Building the texts (Hermes' normalisation) is not counted: it is not what these rules are
    tested for, and it is quadratic in lines itself (0.9 s for 600 lines of exec here). Nor is time
    the thread waits for a core: wall time caught a longer run descheduled more often on a loaded
    runner."""
    import time
    ours = [p for k, p, _w in tp._ASK_C if k in tp.ONCE_ONLY_RULES]
    with _hard_limit(5.0):
        started = time.thread_time()
        for text in texts:
            for pattern in ours:
                pattern.search(text)
        return time.thread_time() - started


def _growth(make, n):
    """Double n until one run takes at least 5 ms of CPU, so the clean time is far above the clock's
    resolution on a fast runner too; then the best of five at n and 4n, taken in turn. Each size's
    detection texts are built once."""
    texts = tp._detection_texts(make(n))
    while n < 512 and _our_patterns_take(texts) < 0.005:
        n *= 2
        texts = tp._detection_texts(make(n))
    larger = tp._detection_texts(make(4 * n))
    small = large = float("inf")
    for _ in range(5):
        small = min(small, _our_patterns_take(texts))
        large = min(large, _our_patterns_take(larger))
        if large > 1.0:                   # past the backstop already: no need for five
            break
    return n, small, large


def _assert_grows_linearly(make, n):
    """4x the input may take about 4x the time (measured 3.8-4.1x, 3.4-4.1x with every core busy).
    Relative to itself in the same run, so a loaded runner does not fail it (an absolute 0.1 s bound
    did, under xdist); a pattern that tries every line again from every line (quadratic: ~16x) or
    worse fails. The absolute bound is only a backstop, and the hard limit stops one that never ends."""
    n, small, large = _growth(make, n)
    assert large / max(small, 1e-9) < 10, f"{n}: {small * 1000:.2f} ms, {4 * n}: {large * 1000:.2f} ms"
    assert large < 1.0, f"{4 * n}: {large:.2f} s"


@pytest.mark.parametrize("make,n", [
    (lambda n: "\nexec " * n + "x", 75),
    (lambda n: "\n exec  exec \t" * n, 50),
    (lambda n: "\ncommand " * n + "x", 75),
    (lambda n: "exec -a " * n + "x", 50),
], ids=["exec-lines", "exec-pairs", "command-lines", "exec-a"])
def test_recognising_many_lines_of_launchers_is_fast(make, n):
    _assert_grows_linearly(make, n)


@pytest.mark.parametrize("command", ["osascript<<EOF\ntell app \"Finder\" to activate\nEOF", "osascript</dev/null",
                                     "osascript>/dev/null -e x", 'shortcuts run<input.txt'])
def test_a_redirection_right_after_the_name_is_still_the_program(command):
    assert tp.assess(command).level == "ask" and tp.assess(command).rule in tp.ONCE_ONLY_RULES


@pytest.mark.parametrize("command", ["ls | xargs -r osascript", "ls | xargs -p osascript", "ls | xargs -0 -r osascript"])
def test_lowercase_xargs_flags_are_flags(command):
    assert tp.assess(command).rule == "apple-events"


def test_a_path_in_a_variable_is_not_the_program():
    assert "apple-events" not in tp.ask_rules("FOO=/opt/osascript make")


def test_exec_with_a_name_is_recognised():
    assert tp.assess(f"exec -a quiet osascript {OSA}").rule == "apple-events"
    assert tp.assess(f"exec -a quiet /usr/bin/osascript {OSA}").rule == "apple-events"


@pytest.mark.parametrize("command", ["osascript.sh run", "./osascript-helper x", "/opt/bin/osascriptx"])
def test_only_osascript_itself_is_the_program(command):
    assert "apple-events" not in tp.ask_rules(command) and tp.assess(command).rule != "apple-events"


def test_a_once_only_request_offers_once_whatever_its_kind():
    req = permissions.Request(kind="command", target="rules:install", title="t", always_label="installs software",
                              once_only=True)
    assert permissions.options_for(req) == ["once"]
    assert permissions.options_for(permissions.Request(kind="command", target="rules:install", title="t",
                                                       always_label="installs software")) == [
        "once", "conversation", "always"]


async def test_no_rule_or_grant_answers_a_once_only_request(execution_db):
    from server.db import session as db_session
    from server.services import permission_store
    async with db_session.AsyncSessionLocal() as db:
        await permission_store.add_rule(db, "command", "rules:install", label="installs software", created_from="t")
        await permission_store.add_grant(db, "c-once", "", "command", "rules:install")
        await db.commit()
    ctx = permissions.Context(conversation_id="c-once")
    base = dict(kind="command", target="rules:install", title="t", always_label="installs software")
    assert await permissions._standing(permissions.Request(**base, once_only=True), ctx, "") is None
    assert await permissions._standing(permissions.Request(**base), ctx, "") is not None
