"""Hands engine harness, L1 (spec docs/specs/2026-10-08-0157-hands-v2.md §8): drives a
development Arslan Hands directly over its socket, with either engine, against the
HarnessFixture app, judging every case by ground truth and the observer.

    .venv/bin/python -m scripts.hands_harness.run --hands-app ".../Arslan Hands DEV.app" \\
        [--engines agent-desktop,cua] [--cases a,b] [--runs 3] [--typist] [--out DIR]

Needs macOS, a development Hands with Cua Driver beside it (HANDS_CUA_DRIVER=1), allowed
Accessibility and Screen Recording, and Xcode's swiftc. Acts only on the fixture app.

--typist starts the user's stand-in: a front window the harness types into at 8 characters a
second during every action, by posting key events as a user would. It takes the keyboard:
run it only when the Mac is left alone (the bake-off, §8.4).
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from scripts.hands_harness import cases as C
from scripts.hands_harness import oracles
from scripts.hands_harness.engines import AgentDesktop, Arc, Cua, Hands
from scripts.hands_harness.observer import Observer

HERE = Path(__file__).resolve().parent
FIXTURE_NAME = "HarnessFixture"


def build(work: Path) -> tuple[Path, Path]:
    """Each fixture as a real app bundle (bundle id, regular app), as the engines see apps;
    run from inside its bundle so it has that identity, with the environment the harness sets."""
    binaries = []
    for name, bundle_id in (("HarnessFixture", "com.arslan.harness.fixture"), ("Typist", "com.arslan.harness.typist")):
        contents = work / f"{name}.app" / "Contents"
        (contents / "MacOS").mkdir(parents=True, exist_ok=True)
        subprocess.run(["swiftc", "-O", "-o", str(contents / "MacOS" / name), str(HERE / f"{name}.swift")], check=True)
        (contents / "Info.plist").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0"><dict>'
            f"<key>CFBundleIdentifier</key><string>{bundle_id}</string><key>CFBundleName</key><string>{name}</string>"
            f"<key>CFBundleExecutable</key><string>{name}</string><key>CFBundlePackageType</key><string>APPL</string>"
            "</dict></plist>\n")
        subprocess.run(["codesign", "--force", "--sign", "-", str(contents.parent)], check=True, capture_output=True)
        binaries.append(contents / "MacOS" / name)
    return binaries[0], binaries[1]


def launch(binary: Path, env: dict[str, str]) -> subprocess.Popen:
    return subprocess.Popen([str(binary)], env={**os.environ, **env}, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)


def start_hands(app: Path) -> Hands:
    ready = Path.home() / "Library" / "Application Support" / "Arslan Hands" / "ready.json"

    def alive() -> bool:
        try:
            os.kill(int(json.loads(ready.read_text())["pid"]), 0)
            return True
        except (OSError, ValueError, KeyError):
            return False
    if not alive():                      # none, or one that ended without cleaning up
        subprocess.run(["/usr/bin/open", "-g", "-j", str(app)], check=True)
        deadline = time.monotonic() + 15
        while not alive() and time.monotonic() < deadline:
            time.sleep(0.1)
    hands = Hands()
    status = hands.call("status")
    if not (status.get("accessibility") and status.get("cua_driver")):
        sys.exit(f"Hands is not ready for the harness: {status}")
    return hands


def engine_pids() -> set[int]:
    """Hands and its engines draw their own windows (the agent cursor): not the user's."""
    out = subprocess.run(["pgrep", "-f", "arslan-hands|cua-driver|agent-desktop"], capture_output=True, text=True)
    return {int(p) for p in out.stdout.split()} | {os.getpid()}


class TypistDriver:
    """Types into the Typist window as a user would (HID-level key events) while an action
    runs, and judges that one action: O2 from the Typist's own key-window log within the
    action's time, O5 from the text it gained during the action (exactly what was typed then,
    and none of it in the fixture's fields)."""

    TEXT = "the quick brown fox jumps over the lazy dog "
    BURST, PAUSE = 1.5, 1.3          # typing in bursts, for borrow-class actions

    def __init__(self, log: Path, fixture: C.Fixture, pid: int):
        self.log, self.fixture, self.pid = log, fixture, pid
        self._skipped = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._i = 0
        self._typed = ""
        self._t0 = 0.0
        self._text0 = ""
        self._bursts = False

    def _type(self) -> None:
        import Quartz
        burst_started = time.monotonic()
        while not self._stop.is_set():
            if self._bursts and time.monotonic() - burst_started > self.BURST:
                # A person pauses: a borrow waits for 1 s without keys, and the next burst
                # starts while it runs, so those keys must be held and given back.
                self._stop.wait(self.PAUSE)
                burst_started = time.monotonic()
                continue
            ch = self.TEXT[self._i % len(self.TEXT)]
            self._i += 1
            for down in (True, False):
                event = Quartz.CGEventCreateKeyboardEvent(None, 0, down)
                Quartz.CGEventKeyboardSetUnicodeString(event, 1, ch)
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
            self._typed += ch
            self._stop.wait(0.125)

    def _rows(self) -> list[dict]:
        try:
            return [json.loads(line) for line in self.log.read_text().splitlines() if line.strip()]
        except OSError:
            return []

    def _text(self) -> str:
        texts = [r["value"] for r in self._rows() if r.get("event") == "text"]
        return texts[-1] if texts else ""

    def _in_front(self) -> bool:
        from scripts.hands_harness.observer import _front_pid
        return _front_pid() == self.pid

    def start(self, bursts: bool = False) -> None:
        """Type only into the Typist: if it is not in front, bring it back first; if it still
        is not, type nothing at all (never into whatever app is in front instead). `bursts`:
        type and pause like a person, so a borrow (which waits for a pause) can start."""
        self._bursts = bursts
        time.sleep(0.3)                                   # let the last action's keys land
        if not self._in_front():
            import AppKit
            app = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(self.pid)
            if app is not None:
                app.activateWithOptions_(0)
            time.sleep(0.5)
        self._skipped = not self._in_front()
        if self._skipped:
            return
        self._text0 = self._text()
        self._typed = ""
        self._t0 = time.time()
        self._stop.clear()
        self._thread = threading.Thread(target=self._type, daemon=True)
        self._thread.start()

    def stop_and_judge(self, _start: float, _end: float, borrowed: bool = False) -> list[str]:
        if self._skipped:
            return ["typist not in front before the action: nothing typed"]
        time.sleep(0.4)                                   # keep typing a little after the action
        self._stop.set()
        if self._thread:
            self._thread.join()
        t1 = time.time()
        time.sleep(0.5)
        text = self._text()
        gained = text[len(self._text0):] if text.startswith(self._text0) else text
        state = self.fixture.state()
        verdict = oracles.typed_exactly(self._typed, gained,
                                        [str(state.get(k, "")) for k in ("title", "notes", "chat")])
        if borrowed:
            # A borrow takes the key window by design (G4); what must hold is every key
            # arriving exactly once, in order, in the user's window - O5 above.
            return verdict.violations
        keys = [(float(r["t"]), bool(r["value"])) for r in self._rows() if r.get("event") == "key"]
        key_verdict = oracles.key_window(keys, self._t0, t1, borrow_ms=150)
        return verdict.violations + key_verdict.violations


def summarize(results: list[C.Result]) -> str:
    lines = ["| case | engine | pass | median ms | look ms | outcomes | violations |", "|---|---|---|---|---|---|---|"]
    keys = sorted({(r.case, r.engine) for r in results}, key=lambda k: (list(C.CASES).index(k[0]), k[1]))
    for case, engine in keys:
        rows = [r for r in results if r.case == case and r.engine == engine]
        passed = sum(r.status == "pass" for r in rows)
        ms = [r.ms for r in rows if r.ms is not None]
        look = [r.look_ms for r in rows if r.look_ms is not None]
        outcomes = ",".join(sorted({str(r.outcome or r.code or r.status) for r in rows}))
        violations = "; ".join(sorted({v for r in rows for v in r.violations}))[:160]
        lines.append(f"| {case} | {engine} | {passed}/{len(rows)} | {statistics.median(ms) if ms else '–'} | "
                     f"{statistics.median(look) if look else '–'} | {outcomes} | {violations or '–'} |")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hands-app", required=True, type=Path)
    parser.add_argument("--engines", default="agent-desktop,cua")
    parser.add_argument("--cases", default=",".join(C.CASES))
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--typist", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    work = Path(tempfile.mkdtemp(prefix="hands-harness-"))
    out = args.out or work
    out.mkdir(parents=True, exist_ok=True)
    fixture_bin, typist_bin = build(work)
    subprocess.run(["pkill", "-x", FIXTURE_NAME], capture_output=True)
    fixture_proc = launch(fixture_bin, {"HARNESS_LOG": str(work / "events.log"), "HARNESS_STATE": str(work / "state.json"),
                                        "HARNESS_CMD": str(work / "cmd")})
    typist_proc = None
    fixture = C.Fixture(work)
    try:
        if not fixture.wait(lambda s: "title" in s, timeout=10):
            sys.exit("the fixture did not start")
        time.sleep(3)          # its window's accessibility tree is not ready at once (arc: measured)
        hands = start_hands(args.hands_app)
        typist = None
        if args.typist:
            typist_proc = launch(typist_bin, {"TYPIST_LOG": str(work / "typist.log")})
            time.sleep(1.5)
            typist = TypistDriver(work / "typist.log", fixture, typist_proc.pid)
        ignore = engine_pids()
        results: list[C.Result] = []
        for engine_name in [e.strip() for e in args.engines.split(",") if e.strip()]:
            if engine_name == "arc":
                engine = Arc(os.environ["ARC_CUA"], FIXTURE_NAME)
            elif engine_name == "agent-desktop":
                engine = AgentDesktop(hands, FIXTURE_NAME)
            else:
                engine = Cua(hands, FIXTURE_NAME)
            for run in range(args.runs):
                for name in [c.strip() for c in args.cases.split(",") if c.strip()]:
                    ctx = C.Ctx(engine=engine, fixture=fixture, observe=lambda: Observer(ignore | engine_pids()),
                                typist=typist)
                    try:
                        result = C.CASES[name](ctx)
                    except Exception as exc:  # noqa: BLE001 — one broken case must not end the run
                        result = C.Result(name, engine.name, "error", note=f"{type(exc).__name__}: {exc}")
                    results.append(result)
                    print(json.dumps({"run": run, **result.to_dict()}, ensure_ascii=False), flush=True)
        (out / "results.json").write_text(json.dumps([r.to_dict() for r in results], ensure_ascii=False, indent=1))
        summary = summarize(results)
        (out / "summary.md").write_text(summary + "\n")
        print(summary)
        print(f"results: {out}")
    finally:
        fixture_proc.terminate()
        if typist_proc:
            typist_proc.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
