"""The harness's cases (spec §8.2), each judged by the fixture's ground truth and the
observer's samples, never by the engine's own word. A case returns one `Result`.

Covered so far: reading, setting and typing text (incl. CJK, emoji, punctuation), a button
pressed exactly once, a checkbox, a pop-up, a password field (must be refused), Return in a
chat field, a menu shortcut, a slow button and waiting, acting on a look taken before a sheet
opened (must never land under it), a minimized window, a hidden app. Not yet: canvas pixels,
drags, other Spaces, Electron and Chromium surfaces, 2,000-row tables (P1-5).
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from scripts.hands_harness import oracles
from scripts.hands_harness.engines import Act, Element, find


@dataclass
class Result:
    case: str
    engine: str
    status: str                     # pass | fail | skip | error
    outcome: str | None = None      # what the engine reported
    code: str | None = None
    ms: int | None = None
    look_ms: int | None = None
    violations: list[str] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class Fixture:
    """The running HarnessFixture: its state file, event log and command file."""

    def __init__(self, folder: Path):
        self.state_path, self.log_path, self.cmd_path = folder / "state.json", folder / "events.log", folder / "cmd"

    def state(self) -> dict:
        for _ in range(20):
            try:
                return json.loads(self.state_path.read_text())
            except (OSError, ValueError):
                time.sleep(0.05)
        return {}

    def events(self, name: str | None = None) -> list[dict]:
        try:
            lines = self.log_path.read_text().splitlines()
        except OSError:
            return []
        rows = [json.loads(line) for line in lines if line.strip()]
        return [r for r in rows if name is None or r.get("event") == name]

    def command(self, *words: str, settle: float = 0.6) -> None:
        self.cmd_path.write_text("\n".join(words) + "\n")
        time.sleep(settle)

    def wait(self, predicate: Callable[[dict], bool], timeout: float = 2.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate(self.state()):
                return True
            time.sleep(0.05)
        return predicate(self.state())


@dataclass
class Ctx:
    engine: object                  # engines.AgentDesktop | engines.Cua
    fixture: Fixture
    observe: Callable               # () -> context manager yielding .before/.samples/.after
    typist: object | None = None    # run.TypistDriver when the user's stand-in is typing


def observed(ctx: Ctx, action: Callable[[], Act]) -> tuple[Act, list[str]]:
    """Run one engine action under the observer (and the typist, if any); its violations."""
    if ctx.typist:
        ctx.typist.start()
    with ctx.observe() as o:
        act = action()
    violations = oracles.disturbance(o.before, o.samples, o.after).violations
    if ctx.typist:
        violations += ctx.typist.stop_and_judge(o.before.t, o.after.t)
    return act, violations


def _element(ctx: Ctx, label: str, role: str = "") -> tuple[Element | None, int]:
    elements, ms = ctx.engine.look()
    return find(elements, label, role), ms


def _judged(name: str, ctx: Ctx, act: Act, violations: list[str], happened: bool, look_ms: int, note: str = "") -> Result:
    violations = [*violations, *oracles.honest(act.outcome, happened).violations]
    status = "pass" if happened and not violations else "fail"
    if act.code and not note:            # what the engine said, so a failure can be read later
        envelope = (act.raw.get("envelope") or {}).get("error") or act.raw.get("refused") or {}
        note = f"{act.code}: {envelope.get('message') or ''} {envelope.get('details') or ''}".strip()[:400]
    return Result(name, ctx.engine.name, status, act.outcome, act.code, act.ms, look_ms, violations, note)


def read_window(ctx: Ctx) -> Result:
    elements, ms = ctx.engine.look()
    wanted = [find(elements, label) for label in ("Title", "Save", "Password", "Message")]
    missing = [label for label, e in zip(("Title", "Save", "Password", "Message"), wanted) if e is None]
    return Result("read_window", ctx.engine.name, "fail" if missing else "pass", look_ms=ms,
                  note=f"{len(elements)} elements" + (f"; missing {missing}" if missing else ""))


def _text_case(name: str, label: str, key: str, text: str, typing: bool) -> Callable[[Ctx], Result]:
    def case(ctx: Ctx) -> Result:
        ctx.fixture.command("reset")
        target, look_ms = _element(ctx, label)
        if target is None:
            return Result(name, ctx.engine.name, "fail", look_ms=look_ms, note=f"no {label} element")
        do = ctx.engine.type_text if typing else ctx.engine.set_value
        act, violations = observed(ctx, lambda: do(target, text))
        happened = ctx.fixture.wait(lambda s: s.get(key) == text)
        got = ctx.fixture.state().get(key)
        return _judged(name, ctx, act, violations, happened, look_ms, "" if happened else f"field holds {got!r}")
    return case


set_title = _text_case("set_title", "Title", "title", "Weekend plan", typing=False)
type_notes = _text_case("type_notes_unicode", "Notes", "notes", "Hi, 世界! 👋 — “quotes”, 100%", typing=True)


def _click_case(name: str, label: str, key: str, check: Callable[[object, object], bool]) -> Callable[[Ctx], Result]:
    def case(ctx: Ctx) -> Result:
        ctx.fixture.command("reset")
        target, look_ms = _element(ctx, label)
        if target is None:
            return Result(name, ctx.engine.name, "fail", look_ms=look_ms, note=f"no {label} element")
        before = ctx.fixture.state().get(key)
        act, violations = observed(ctx, lambda: ctx.engine.click(target))
        happened = ctx.fixture.wait(lambda s: check(before, s.get(key)))
        after = ctx.fixture.state().get(key)
        if key == "saves" and isinstance(before, int) and isinstance(after, int):
            time.sleep(0.5)                        # a second, late press would show here
            violations += oracles.once(before, ctx.fixture.state().get("saves", after)).violations
        return _judged(name, ctx, act, violations, happened, look_ms)
    return case


click_save = _click_case("click_save_once", "Save", "saves", lambda b, a: isinstance(b, int) and a == b + 1)
checkbox = _click_case("checkbox", "Done", "done", lambda b, a: a is True)


def popup(ctx: Ctx) -> Result:
    ctx.fixture.command("reset")
    target, look_ms = _element(ctx, "Color")
    if target is None:
        return Result("popup", ctx.engine.name, "fail", look_ms=look_ms, note="no Color element")
    act, violations = observed(ctx, lambda: ctx.engine.select(target, "Green"))
    return _judged("popup", ctx, act, violations, ctx.fixture.wait(lambda s: s.get("color") == "Green"), look_ms)


def password_refused(ctx: Ctx) -> Result:
    ctx.fixture.command("reset")
    target, look_ms = _element(ctx, "Password")
    if target is None:
        return Result("password_refused", ctx.engine.name, "fail", look_ms=look_ms, note="no Password element")
    act, violations = observed(ctx, lambda: ctx.engine.type_text(target, "hunter2"))
    typed = ctx.fixture.state().get("password_length", 0)
    refused = not act.ok and act.code == "password_field"
    status = "pass" if refused and typed == 0 and not violations else "fail"
    return Result("password_refused", ctx.engine.name, status, act.outcome, act.code, act.ms, look_ms, violations,
                  f"{typed} characters reached the field")


def chat_return(ctx: Ctx) -> Result:
    ctx.fixture.command("reset")
    target, look_ms = _element(ctx, "Message")
    if target is None:
        return Result("chat_return", ctx.engine.name, "fail", look_ms=look_ms, note="no Message element")
    ctx.engine.set_value(target, "hello there")
    sends = ctx.fixture.state().get("sends", 0)
    act, violations = observed(ctx, lambda: ctx.engine.press("return", target))
    happened = ctx.fixture.wait(lambda s: s.get("sends") == sends + 1)
    time.sleep(0.4)
    violations += oracles.once(sends, ctx.fixture.state().get("sends", sends)).violations
    return _judged("chat_return", ctx, act, violations, happened, look_ms)


def menu_shortcut(ctx: Ctx) -> Result:
    ctx.fixture.command("reset")
    _, look_ms = ctx.engine.look()
    before = len([e for e in ctx.fixture.events("menu") if e.get("value") == "Bold"])
    act, violations = observed(ctx, lambda: ctx.engine.press("cmd+b"))
    deadline = time.monotonic() + 1.5
    count = before
    while time.monotonic() < deadline and count == before:
        count = len([e for e in ctx.fixture.events("menu") if e.get("value") == "Bold"])
        time.sleep(0.05)
    violations += oracles.once(before, count).violations if count != before else []
    return _judged("menu_shortcut", ctx, act, violations, count == before + 1, look_ms)


def slow_button(ctx: Ctx) -> Result:
    ctx.fixture.command("reset")
    target, look_ms = _element(ctx, "Slow")
    if target is None:
        return Result("slow_button", ctx.engine.name, "fail", look_ms=look_ms, note="no Slow element")
    act, violations = observed(ctx, lambda: ctx.engine.click(target))
    started = time.monotonic()
    seen = None
    while time.monotonic() - started < 5:
        if find(ctx.engine.look()[0], "Slow done"):
            seen = round((time.monotonic() - started) * 1000)
            break
        time.sleep(0.2)
    happened = ctx.fixture.state().get("slow") == "Slow done"
    result = _judged("slow_button", ctx, act, violations, happened and seen is not None, look_ms)
    result.note = f"the engine saw the change after {seen} ms" if seen is not None else "the engine never saw it"
    return result


def sheet_after_look(ctx: Ctx) -> Result:
    """Look, open a sheet 0.3 s after a press, then act on the OLD look: the press must not
    land under the sheet (arc-cua's benchmark: cua-driver 0.32 did, 5 of 5)."""
    ctx.fixture.command("reset")
    elements, look_ms = ctx.engine.look()
    sheet, save = find(elements, "Sheet 0.3"), find(elements, "Save")
    if sheet is None or save is None:
        return Result("sheet_after_look", ctx.engine.name, "fail", look_ms=look_ms, note="no Sheet 0.3 / Save")
    ctx.engine.click(sheet)
    opened = ctx.fixture.wait(lambda s: s.get("sheet_open") is True, timeout=2)
    saves = ctx.fixture.state().get("saves", 0)
    act, violations = observed(ctx, lambda: ctx.engine.click(save))
    time.sleep(0.5)
    landed = ctx.fixture.state().get("saves", saves) != saves
    ctx.fixture.command("close_sheet")
    if not opened:
        return Result("sheet_after_look", ctx.engine.name, "skip", act.outcome, act.code, act.ms, look_ms,
                      note="the sheet never opened")
    if landed:
        violations.append("acted under a sheet that opened after the look")
    status = "pass" if not landed and not violations else "fail"
    return Result("sheet_after_look", ctx.engine.name, status, act.outcome, act.code, act.ms, look_ms, violations)


def _hidden_case(name: str, hide: str, show: str) -> Callable[[Ctx], Result]:
    def case(ctx: Ctx) -> Result:
        ctx.fixture.command("reset", hide, settle=1.0)
        try:
            target, look_ms = _element(ctx, "Save")
            if target is None:
                return Result(name, ctx.engine.name, "fail", look_ms=look_ms, note="Save not seen")
            saves = ctx.fixture.state().get("saves", 0)
            act, violations = observed(ctx, lambda: ctx.engine.click(target))
            happened = ctx.fixture.wait(lambda s: s.get("saves") == saves + 1)
            still = ctx.fixture.state()
            if hide == "minimize" and not still.get("minimized"):
                violations.append("the window was left un-minimized")
            if hide == "hide" and not still.get("hidden"):
                violations.append("the app was left un-hidden")
            return _judged(name, ctx, act, violations, happened, look_ms)
        finally:
            ctx.fixture.command(show, settle=1.0)
    return case


def keys_after_restore(ctx: Ctx) -> Result:
    """A window restored from the Dock in the background leaves its app with no focused
    element. A menu shortcut must still run its menu item, once, without activating the app
    (agent-desktop 0.9.4 pressed the menu item; upstream main refuses: no focused element)."""
    ctx.fixture.command("reset", "minimize", settle=1.0)
    ctx.fixture.command("unminimize", settle=1.0)
    _, look_ms = ctx.engine.look()
    before = len([e for e in ctx.fixture.events("menu") if e.get("value") == "Bold"])
    act, violations = observed(ctx, lambda: ctx.engine.press("cmd+b"))
    deadline = time.monotonic() + 1.5
    count = before
    while time.monotonic() < deadline and count == before:
        count = len([e for e in ctx.fixture.events("menu") if e.get("value") == "Bold"])
        time.sleep(0.05)
    violations += oracles.once(before, count).violations if count != before else []
    return _judged("keys_after_restore", ctx, act, violations, count == before + 1, look_ms)


minimized_window = _hidden_case("minimized_window", "minimize", "unminimize")
hidden_app = _hidden_case("hidden_app", "hide", "unhide")


CASES: dict[str, Callable[[Ctx], Result]] = {
    "read_window": read_window,
    "set_title": set_title,
    "type_notes_unicode": type_notes,
    "click_save_once": click_save,
    "checkbox": checkbox,
    "popup": popup,
    "password_refused": password_refused,
    "chat_return": chat_return,
    "menu_shortcut": menu_shortcut,
    "slow_button": slow_button,
    "sheet_after_look": sheet_after_look,
    "minimized_window": minimized_window,
    "hidden_app": hidden_app,
    "keys_after_restore": keys_after_restore,
}
