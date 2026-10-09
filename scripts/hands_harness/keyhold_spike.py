"""Q2 spike (spec 2026-10-08-0157 §12 Q2, P2-3 day 1): can Hands hold the user's keys during a
borrow and give them back exactly?

    .venv/bin/python -m scripts.hands_harness.keyhold_spike --hands-app ".../Arslan Hands DEV.app" auto
    .venv/bin/python -m scripts.hands_harness.keyhold_spike --hands-app ... user     # the user types

`auto` (the Mac left alone): the Typist in front stands in for the user (HID-level key events from
this process, as the harness types); the fixture behind it is what Hands acts on.
  E2  whose events the tap sees: the "user's" (this process), agent-desktop's key to the fixture
  E3  hold while the user types, then replay: nothing reaches the Typist while held, then exactly
      what was typed, in order
  E4  does an action of Hands (agent-desktop, posted to a pid) reset the system's idle time?
  E6  the same keys through the active input method (the user's Pinyin), with and without a hold
  E7  a modifier held across the hold: shift down, a, b | replay | shift up, c - same as without
`user` (the user at the keyboard): which source pid real keystrokes carry, while nothing is held.
Writes a JSON report; prints a summary. Uses the development Hands' `probe_keyhold` op.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import time
from pathlib import Path

from scripts.hands_harness import cases as C
from scripts.hands_harness.run import build, launch, start_hands

TYPED = "the quick brown fox"


def post_text(text: str, gap: float = 0.06) -> None:
    import Quartz
    for ch in text:
        for down in (True, False):
            event = Quartz.CGEventCreateKeyboardEvent(None, 0, down)
            Quartz.CGEventKeyboardSetUnicodeString(event, 1, ch)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
        time.sleep(gap)


def post_key(code: int, down: bool, shift: bool) -> None:
    import Quartz
    event = Quartz.CGEventCreateKeyboardEvent(None, code, down)
    Quartz.CGEventSetFlags(event, Quartz.kCGEventFlagMaskShift if shift else 0)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
    time.sleep(0.05)


def post_shift(down: bool) -> None:
    import Quartz
    event = Quartz.CGEventCreateKeyboardEvent(None, 56, down)      # left shift
    Quartz.CGEventSetType(event, Quartz.kCGEventFlagsChanged)
    Quartz.CGEventSetFlags(event, Quartz.kCGEventFlagMaskShift if down else 0)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
    time.sleep(0.05)


def typist_text(log: Path) -> str:
    texts = [json.loads(line)["value"] for line in log.read_text().splitlines()
             if line.strip() and json.loads(line).get("event") == "text"]
    return texts[-1] if texts else ""


def front_is(pid: int) -> bool:
    from scripts.hands_harness.observer import _front_pid
    return _front_pid() == pid


def bring_front(pid: int) -> bool:
    import AppKit
    app = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
    if app is not None:
        app.activateWithOptions_(0)
    time.sleep(0.6)
    return front_is(pid)


def auto(hands, work: Path) -> dict:
    report: dict = {}
    fixture_bin, typist_bin = build(work)
    subprocess.run(["pkill", "-x", "HarnessFixture"], capture_output=True)
    subprocess.run(["pkill", "-x", "Typist"], capture_output=True)
    fixture = launch(fixture_bin, {"HARNESS_LOG": str(work / "events.log"), "HARNESS_STATE": str(work / "state.json"),
                                   "HARNESS_CMD": str(work / "cmd")})
    log = work / "typist.log"
    typist = launch(typist_bin, {"TYPIST_LOG": str(log)})
    try:
        fix = C.Fixture(work)
        fix.wait(lambda s: "title" in s, timeout=10)
        time.sleep(1.0)
        if not bring_front(typist.pid):
            return {"error": "the Typist could not be brought to the front; nothing typed"}
        start = hands.call("probe_keyhold", {"do": "start"})
        report["start"] = {k: start["probe"].get(k) for k in ("tap", "listen_access", "post_access", "own_pid")}
        report["start"]["error"] = start.get("error")
        me = __import__("os").getpid()

        # E2: the "user's" keys (this process) and agent-desktop's key to the fixture.
        before = hands.call("probe_keyhold", {"do": "status"})["probe"]["seen_total"]
        post_text("ab")
        hands.call("press", {"app": "HarnessFixture", "keys": "tab"})
        time.sleep(0.3)
        seen = hands.call("probe_keyhold", {"do": "status"})["probe"]
        new = seen["seen"][-(seen["seen_total"] - before):] if seen["seen_total"] > before else []
        keys = [e for e in new if e["type"] in (10, 11, 12)]
        report["E2"] = {"this_pid": me, "key_events": [{k: e[k] for k in ("type", "pid", "parent", "ours")} for e in keys]}

        # E3: hold while typing, replay, compare.
        if not bring_front(typist.pid):
            return {**report, "error": "the Typist left the front"}
        base = typist_text(log)
        hands.call("probe_keyhold", {"do": "arm"})
        t0 = time.monotonic()
        post_text(TYPED)
        typed_ms = round((time.monotonic() - t0) * 1000)
        time.sleep(0.3)
        during = typist_text(log)
        held = hands.call("probe_keyhold", {"do": "status"})["probe"]["held"]
        t1 = time.monotonic()
        released = hands.call("probe_keyhold", {"do": "release"})
        release_ms = round((time.monotonic() - t1) * 1000)
        time.sleep(0.8)
        after = typist_text(log)
        report["E3"] = {"typed": TYPED, "typing_ms": typed_ms, "held_events": held,
                        "replayed": released.get("replayed"), "release_ms": release_ms,
                        "arrived_while_held": during[len(base):], "arrived_after": after[len(base):],
                        "exact": after[len(base):] == TYPED and during == base}

        # E6 / E7: the same keys with and without a hold in between must give the same text, through
        # whatever input method is active (here: the user's Pinyin). E6 "nihao" + space; E7 shift
        # held across the hold: shift down, a, b | replay | shift up, c, space.
        def tap_key(code: int, shift: bool = False) -> None:
            post_key(code, True, shift)
            post_key(code, False, shift)

        def nihao(hold: bool) -> None:
            for code in (45, 34, 4, 0, 31):                          # n i h a o
                tap_key(code)
                if hold and code == 4:
                    hands.call("probe_keyhold", {"do": "release"})
            tap_key(49)                                              # space: commit

        def shifted(hold: bool) -> None:
            post_shift(True)
            tap_key(0, True)
            tap_key(11, True)
            if hold:
                hands.call("probe_keyhold", {"do": "release"})
            time.sleep(0.2)
            post_shift(False)
            tap_key(8)
            tap_key(49)

        for name, sequence in (("E6", nihao), ("E7", shifted)):
            results = {}
            for hold in (False, True):
                if not bring_front(typist.pid):
                    return {**report, "error": "the Typist left the front"}
                tap_key(53)                                          # escape: no composition left over
                time.sleep(0.3)
                base = typist_text(log)
                if hold:
                    hands.call("probe_keyhold", {"do": "arm"})
                sequence(hold)
                time.sleep(0.8)
                text = typist_text(log)
                results["held" if hold else "plain"] = text[len(base):] if text.startswith(base) else text
            report[name] = {**results, "same": results["plain"] == results["held"]}

        # E4: does Hands' own action reset the system's idle time?
        time.sleep(3.0)
        idle_before = hands.call("probe_keyhold", {"do": "status"})["probe"]["idle_hid_s"]
        hands.call("press", {"app": "HarnessFixture", "keys": "tab"})
        idle_after = hands.call("probe_keyhold", {"do": "status"})["probe"]["idle_hid_s"]
        post_text("x")
        idle_after_user = hands.call("probe_keyhold", {"do": "status"})["probe"]["idle_hid_s"]
        report["E4"] = {"idle_before_s": idle_before, "idle_after_hands_press_s": idle_after,
                        "idle_after_a_user_key_s": idle_after_user,
                        "hands_press_resets_idle": idle_after is not None and idle_after < 0.5}
        report["final"] = {k: v for k, v in hands.call("probe_keyhold", {"do": "status"})["probe"].items()
                           if k in ("disabled", "overflow", "held", "armed", "secure_input")}
        return report
    finally:
        typist.terminate()
        fixture.terminate()


def user(hands, seconds: float) -> dict:
    start = hands.call("probe_keyhold", {"do": "start"})
    before = start["probe"]["seen_total"]
    time.sleep(seconds)
    seen = hands.call("probe_keyhold", {"do": "status"})["probe"]
    new = seen["seen"][-min(64, seen["seen_total"] - before):] if seen["seen_total"] > before else []
    pids: dict[str, int] = {}
    for e in new:
        kind = "key" if e["type"] in (10, 11, 12) else "mouse"
        pids[f"{kind} pid={e['pid']} parent={e['parent']} ours={e['ours']}"] = pids.get(
            f"{kind} pid={e['pid']} parent={e['parent']} ours={e['ours']}", 0) + 1
    return {"seconds": seconds, "events": seen["seen_total"] - before, "by_source": pids,
            "user_key_age_ms": seen.get("user_key_age_ms"), "user_mouse_age_ms": seen.get("user_mouse_age_ms")}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hands-app", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("mode", choices=["auto", "user"])
    parser.add_argument("--seconds", type=float, default=12.0)
    args = parser.parse_args()
    hands = start_hands(args.hands_app)
    work = Path(tempfile.mkdtemp(prefix="keyhold-spike-"))
    report = auto(hands, work) if args.mode == "auto" else user(hands, args.seconds)
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.out:
        args.out.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
