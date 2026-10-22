"""0.1.45 hands: Arslan's browser and Mac automation.

Looking (open a page, read it, go back, list Shortcuts) is free. Acting in the
browser and running a Shortcut or an AppleScript happen only inside a background
job; acting in a Mac app through Hands happens in a chat reply too, under the
run's own limits (H3, v0.1.63). Everything asks first. Every card goes through `permissions.decide`
(0.1.61 §A11): an AppleScript is asked every time, with the whole script shown,
and never remembered (a script runs outside the sandbox and what it does past
its app is read from its words only, so no app's yes stands for one: release
gate B1); a website and a Shortcut are asked for this task or this conversation
(no "Always" yet); an app is asked for this task, this conversation or always.
macOS adds its own Automation consent the first time a script controls an app.

Arslan never types into a password field: the user logs in themselves in the
visible browser window, and that profile keeps the session.

0.1.53 adds Mac apps through Arslan Hands (agent-desktop behind a separate
helper app that alone holds Accessibility; spec
docs/specs/2026-10-03-0153-hands-agent-desktop.md). Acting runs in a chat reply
or a background job alike (H3); an action whose real label deletes, sends, pays,
buys, transfers or submits asks every time. Stop (`POST /hands/stop`) refuses
every Hands call of the work it stopped, checked again after each card. Since 0.1.61 one `app` card covers both
looking and acting, for this task first (or this conversation, or always); the
answer is remembered by the permission store (§A5).
"""
from __future__ import annotations

import asyncio
import contextvars
import re
import time
import uuid
from urllib.parse import urlsplit

from arslan.aio import within
from server.services import approvals

_PASSWORD = re.compile(r"pass(word|code|phrase)|密码|口令|パスワード|contraseña|mot de passe|passwort|\bpin\b", re.I)
_OUTPUT_LIMIT = 8_000


def _conversation_and_job() -> tuple[str | None, str | None]:
    from server.services import background_jobs, personal_context
    ctx = personal_context.current()
    return (ctx.conversation_id if ctx is not None else None), background_jobs._inside_job.get()


# H2 (0.1.62): a result that stopped before anything reached an app says `executed: False`, so a task
# counts it as a known failure, not as something the user must check (docs/plans/0162/H2). The code
# decides it: NOT_EXECUTED codes are only ever said before the action (Hands' own checks in
# desktop/hands/src/server.rs `guarded` run before `run_envelope`; a card, a front that was not
# borrowed, a locked screen; `hands_unavailable` is raised only when the request never reached Hands,
# hands_client._NotSent). MAYBE_EXECUTED codes may come after part or all of it ran: a lost reply,
# a time-out, Stop or a takeover pause killing agent-desktop mid-action, typed text without Return,
# and every agent-desktop error. A code in neither set gets no `executed` (taken as "maybe"); a test
# fails when a code anywhere in Hands or here is in neither. A few paths here also say it whatever
# the code, because no action request had been sent yet in that call (`_failed(nothing_sent=True)`).
NOT_EXECUTED = frozenset({
    # cards (`_no`) and checks in this file
    "declined", "no_answer", "no_one_to_ask", "reviewer_denied", "not_allowed", "act_in_background",
    "bad_request", "no_such_file", "app_not_found", "no_apps", "hands_unavailable", "no_passwords", "no_page",
    "too_long", "append_unreadable", "window_not_found", "app_refused",
    # Hands' refusals before the action (server.rs, borrow.rs, visit.rs, takeover.rs, argv.rs)
    "app_denied", "app_look_only", "app_click_only", "ref_wrong_app", "ref_unknown", "bad_ref", "password_field",
    "borrow_off", "waiting_for_pause", "secure_input", "window_elsewhere", "window_unreachable", "borrow_declined",
    "screen_locked", "takeover_unsafe", "target_unreadable", "app_not_running", "apps_unreadable", "app_ambiguous",
    "op_not_allowed", "changed", "menu_unreadable", "menu_disabled", "menu_ambiguous", "menu_not_found",
    "bad_token", "peer_not_allowed", "no_takeover", "not_paused",
    # a screenshot that was not taken (capture.m via server.rs capture_code)
    "screen_recording_off", "window_not_capturable", "needs_macos_14", "not_supported", "capture_failed",
    # the Cua Driver path's own checks (not in a release build; F5b deletes them)
    "arg_not_allowed", "borrow_not_allowed", "element_required", "engine_missing",
})
MAYBE_EXECUTED = frozenset({
    "unknown", "TIMEOUT", "submit_unsure", "takeover_paused", "takeover_resumed", "takeover_ended",
    "stopped_by_user", "busy", "helper_failed", "bad_output", "bad_reply", "refused", "batch_stopped",
    "menu_press_failed", "append_needs_set_value", "browser_unavailable",
    "engine_error", "engine_refused", "engine_unknown",
    # agent-desktop's error codes (hands_contract.HINTS), and its fallback
    "STALE_REF", "SNAPSHOT_NOT_FOUND", "AMBIGUOUS_TARGET", "ELEMENT_NOT_FOUND", "APP_NOT_FOUND",
    "WINDOW_NOT_FOUND", "PERM_DENIED", "POLICY_DENIED", "ACTION_NOT_SUPPORTED", "ACTION_FAILED",
    "APP_UNRESPONSIVE", "INTERNAL",
})


def _not_run(result: dict) -> dict:
    """A result for a call that stopped before anything was sent to an app (H2)."""
    return {**result, "executed": False}


# S1a (U14 a, #317): a scheduled run has nobody to ask, so permissions.decide refuses every action there, and R7
# takes start_background_work out of it. Its refusals say what to do instead: tell the user.
_SCHEDULED_INSTEAD = ("A scheduled run cannot act on this Mac: nobody is there to approve it. Tell the user what "
                      "you would have done, so they can do it or ask you in a conversation.")


async def _not_in_job(kind: str, target: str, title: str) -> dict:
    if _scheduled_run() is not None:
        return await _refused_unattended(kind, target, title)
    return _not_run({"ok": False, "external": False, "code": "act_in_background",
                     "error": "Acting in the browser and running Shortcuts or scripts happen in background work. "
                              "Call start_background_work with this goal; looking at pages is fine here."})


async def _refused_unattended(kind: str, target: str, title: str) -> dict:
    """S1b follow-up (cloud audit): a scheduled run's refusal leaves the row decide() leaves for want of someone
    to ask (policy, deny, no "Always"), so the Inbox lists what the run could not do (S1b)."""
    from server.services import permissions
    await permissions.refuse_unattended(permissions.Request(kind=kind, target=target, title=title), _context())
    return _not_run({"ok": False, "external": False, "code": "act_in_background", "error": _SCHEDULED_INSTEAD})


def _unavailable() -> dict:
    return _not_run({"ok": False, "external": False, "code": "hands_unavailable",
                     "error": "Arslan Hands is not available on this Mac."})


def _bad_request(error: str) -> dict:
    return _not_run({"ok": False, "external": False, "code": "bad_request", "error": error})


# The tool loop stops a tool after TOOL_TIMEOUT_S (20 s) unless the tool declares `timeout_s`.
# These tools wait for the user's card (approvals.TIMEOUT_S each) and for slow apps, so 20 s cut
# them off mid-card. Measured on the user's Mac, 2026-10-05: a Notes look died twice while its
# card was open; an unanswered AppleScript card expired after 20 s and the model asked again.
CARD_S = approvals.TIMEOUT_S       # the card window (30 min, 0.1.61); a test pins the two equal
RUN_S = 120                        # _run's default; a Hands call is 60 s, a read is tried twice


# ── asking (0.1.61 §A11): every card here goes through permissions.decide ────────

def _context():
    from server.services import permissions
    conversation_id, job_id = _conversation_and_job()
    return permissions.Context(conversation_id, job_id=job_id)


def _request(kind: str, target: str, title: str, detail: str, frame_kind: str, frame_target: str, *,
             always_label: str = "", extra: dict | None = None):
    """A `permissions.Request` whose card keeps Hands' own frame kinds (desktop_app, desktop_risky,
    desktop_takeover, mac_shortcut, mac_script, browser_site), which the island and the phone
    already know; `perm_kind` on the card is the request's kind."""
    from server.services import permissions
    from server.ws import protocol
    return permissions.Request(
        kind=kind, target=target, title=title[:300], detail=detail, always_label=always_label,
        frame=protocol.propose_action(uuid.uuid4().hex, frame_kind, frame_target[:300], detail),
        extra=extra or {})


async def _decide(kind: str, target: str, title: str, detail: str, frame_kind: str, frame_target: str, *,
                  always_label: str = "", extra: dict | None = None):
    """One card through `permissions.decide`: the money rung, an "Always" rule, a grant for this task
    or conversation, else the card on the surface bound to this turn or job."""
    from server.services import permissions
    return await permissions.decide(
        _request(kind, target, title, detail, frame_kind, frame_target, always_label=always_label, extra=extra),
        _context())


def _app_request(app: dict, detail: str, *, step: str = "", frame_kind: str = "desktop_app",
                 frame_target: str = ""):
    """Looking at and acting in one app is one `app` request (0.1.61 §A11): kept by bundle id, "for
    this task" first, "Always" unless the app reaches every other app."""
    from server.services import hands_service, permissions
    from server.ws import protocol
    bundle = str(app.get("bundle_id") or app.get("name") or "")
    name = str(app.get("name") or bundle)
    return permissions.Request(
        kind="app", target=bundle, title=f"Use {name}?", detail=detail,
        always_label=hands_service.always_label(bundle, name),
        frame=protocol.propose_action(uuid.uuid4().hex, frame_kind, (frame_target or name)[:300], detail),
        extra={"app": name, "bundle_id": bundle, **({"step": step[:200]} if step else {})})


async def _decide_app(app: dict, detail: str, *, step: str = ""):
    from server.services import hands_service, permissions
    await hands_service.migrate_always()          # the old Settings list becomes `app` rules, once
    return await permissions.decide(_app_request(app, detail, step=step), _context())


def _no(decision, what: str) -> dict:
    """What the model is told when a card did not allow it. Only the user's own no is a refusal: a
    card nobody answered is "no answer", and a run with nobody to ask says so (0.1.61 §A4). The
    reviewer of "Approve for me" (§A6, PR 7) says no in a whole sentence of its own (its reason and
    "find a safer way, or ask the user"), passed on as it is; any other `by` is passed on as
    permissions put it, never called the user's no or "nobody to ask". Every card comes before its
    action, so none of these ran (H2)."""
    if decision.by == "user":
        said = f" They said: {decision.note}" if decision.note else ""
        return _not_run({"ok": False, "external": False, "code": "declined",
                         "error": f"The user did not allow {what}.{said} Do not retry; report it."})
    if decision.by == "expired":
        return _not_run({"ok": False, "external": False, "code": "no_answer", "error": decision.model_text})
    if decision.by == "policy":
        return _not_run({"ok": False, "external": False, "code": "no_one_to_ask", "error": decision.model_text})
    if decision.by == "reviewer":
        return _not_run({"ok": False, "external": False, "code": "reviewer_denied",
                         "error": decision.model_text or (
                             f"The reviewer that approves for the user did not allow {what}: "
                             f"{decision.note or 'no reason given'} Find a safer way to do what the user asked, "
                             "or ask the user; only they can let it run anyway.")})
    return _not_run({"ok": False, "external": False, "code": "not_allowed",
                     "error": decision.model_text or f"{what[:1].upper()}{what[1:]} was not allowed."})


def forget_job(job_id: str) -> None:
    _session_locks.pop(job_id, None)
    if job_id in _takeovers:                     # a job's takeover ends with it (§6.4)
        _takeovers.discard(job_id)
        try:
            asyncio.get_running_loop().create_task(_end_takeover())
        except RuntimeError:
            pass
    from server.services import hands_service, look_diff
    look_diff.forget(job_id)
    _shot_notes_said.difference_update({k for k in _shot_notes_said if k[0] == job_id})
    session = hands_service.forget_job(job_id)
    if session:                     # hide the job's cursor; best effort, never blocks the job's end
        try:
            asyncio.get_running_loop().create_task(_end_session(session))
        except RuntimeError:
            pass


async def _end_session(session: str) -> None:
    from server.services import hands_client
    try:
        await hands_client.call("session_end", {"session": session}, timeout=10, start=False)
    except hands_client.HandsUnavailable:
        pass


def _origin(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.hostname}" if parts.hostname else None


# ── browser ──────────────────────────────────────────────────────────────────

class _BrowserTool:
    action = ""
    acts = False
    timeout_s = CARD_S + 2 * RUN_S     # one card; the first use sets the browser up (1–2 min)

    async def execute(self, args: dict) -> dict:
        from server.services import agent_browser
        args = dict(args or {})
        if self.acts:
            _, job_id = _conversation_and_job()
            if job_id is None:
                where = _origin(agent_browser.current_url()) or "*"
                return await _not_in_job("site", where, f"Act on {where}?")
            if self.action == "type" and _PASSWORD.search(str(args.get("element", ""))):
                return _not_run({"ok": False, "external": False, "code": "no_passwords",
                                 "error": "Arslan never types passwords. Ask the user to log in themselves in "
                                          "the Arslan browser window, then continue."})
            origin = _origin(agent_browser.current_url())
            if origin is None:
                return _not_run({"ok": False, "external": False, "code": "no_page",
                                 "error": "Open a page with browser_open first."})
            summary = {"click": "click", "type": "type text", "select": "choose options",
                       "press": "press keys"}[self.action]
            decision = await _decide(
                "site", origin, f"Act on {origin}?",
                f"Arslan wants to {summary} on {origin} ({args.get('element') or args.get('key') or ''})",
                "browser_site", origin, always_label=origin, extra={"site": origin, "action": self.action})
            if not decision.allowed:
                return _no(decision, "acting on this website")
        try:
            text = await _run_setting_up_once(self.action, args)
        except agent_browser.BrowserUnavailable as exc:
            return {"ok": False, "external": False, "code": "browser_unavailable",
                    "error": _unavailable_message(str(exc))}
        except ValueError as exc:
            return {"ok": False, "external": False, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "external": False, "error": f"browser: {str(exc)[:400]}"}
        # Page content is untrusted external text: framed as such by the tool loop.
        return {"ok": True, "external": True, "text": text,
                "summary": f"{self.action} · {agent_browser.current_url() or ''}"[:200]}


async def _run_setting_up_once(action: str, args: dict) -> str:
    """0.1.48: the first time Arslan needs its browser, it sets it up itself (a pinned,
    lockfile-exact download, ~1–2 minutes) instead of telling the user to go to Advanced
    and click. Only the "not set up yet" case is handled; a missing Node is reported."""
    from server.services import agent_browser, managed_browser
    try:
        return await agent_browser.run(action, args)
    except agent_browser.BrowserUnavailable as exc:
        if "setup_required" not in str(exc):
            raise
    try:
        await managed_browser.setup()
    except Exception as exc:  # noqa: BLE001
        raise agent_browser.BrowserUnavailable(f"setup_failed: {str(exc)[:300]}") from exc
    return await agent_browser.run(action, args)


def _unavailable_message(reason: str) -> str:
    if "node_required" in reason:
        return ("Arslan's browser needs Node.js on this Mac, and it is not installed. Tell the user; "
                "meanwhile read pages with web_extract.")
    if "macos_required" in reason:
        return "Arslan's browser only runs on macOS. Read pages with web_extract instead."
    return f"Arslan's browser could not start ({reason}). Read pages with web_extract instead, and tell the user."


class BrowserOpenExecutor(_BrowserTool):
    key = "browser_open"
    action = "open"


class BrowserLookExecutor(_BrowserTool):
    key = "browser_look"
    action = "look"


class BrowserBackExecutor(_BrowserTool):
    key = "browser_back"
    action = "back"


class BrowserClickExecutor(_BrowserTool):
    key = "browser_click"
    action = "click"
    acts = True


class BrowserTypeExecutor(_BrowserTool):
    key = "browser_type"
    action = "type"
    acts = True


class BrowserSelectExecutor(_BrowserTool):
    key = "browser_select"
    action = "select"
    acts = True


class BrowserPressExecutor(_BrowserTool):
    key = "browser_press"
    action = "press"
    acts = True


# ── Mac automation ───────────────────────────────────────────────────────────

async def _run(argv: list[str], *, timeout: float = 120) -> dict:
    process = await asyncio.create_subprocess_exec(*argv, stdout=asyncio.subprocess.PIPE,
                                                   stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await within(process.communicate(), timeout)
    except TimeoutError:
        process.kill()
        return {"ok": False, "external": False, "error": "timed out"}
    text = out.decode(errors="replace")[:_OUTPUT_LIMIT]
    if process.returncode != 0:
        return {"ok": False, "external": False, "error": err.decode(errors="replace")[:1000] or "failed"}
    return {"ok": True, "external": True, "text": text, "summary": text[:120]}


class MacListShortcutsExecutor:
    key = "mac_list_shortcuts"
    timeout_s = 40

    async def execute(self, args: dict) -> dict:
        return await _run(["/usr/bin/shortcuts", "list"], timeout=30)


class MacRunShortcutExecutor:
    key = "mac_run_shortcut"
    timeout_s = CARD_S + RUN_S + 30

    async def execute(self, args: dict) -> dict:
        name = str((args or {}).get("name") or "").strip()
        if not name or len(name) > 200:
            return _bad_request("name required")
        job_id = _conversation_and_job()[1]
        if job_id is None:
            return await _not_in_job("shortcut", name, f"Run the Shortcut “{name}”?")
        if (stop := _stopped(job_id)) is not None:
            return stop
        text_input = (args or {}).get("input")
        decision = await _decide(
            "shortcut", name, f"Run the Shortcut “{name}”?",
            f"Run the Shortcut “{name}”" + (f" with input: {str(text_input)[:300]}" if text_input else ""),
            "mac_shortcut", name, always_label=name, extra={"shortcut": name})
        if not decision.allowed:
            return _no(decision, f"running the Shortcut “{name}”")
        if (stop := _stopped(job_id)) is not None:
            return stop
        argv = ["/usr/bin/shortcuts", "run", name]
        if not text_input:
            return await _run(argv)
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory(prefix="arslan-shortcut-") as temp:
            path = Path(temp) / "input.txt"
            path.write_text(str(text_input)[:20_000])
            return await _run(argv + ["--input-path", str(path)])


class MacAppleScriptExecutor:
    key = "mac_applescript"
    timeout_s = CARD_S + RUN_S + 30

    async def execute(self, args: dict) -> dict:
        script = str((args or {}).get("script") or "")
        if not script.strip() or len(script) > 4000:
            return _bad_request("script required (max 4000 characters)")
        job_id = _conversation_and_job()[1]
        if job_id is None:
            return await _not_in_job("app_risky", "AppleScript", "Run this AppleScript?")
        if (stop := _stopped(job_id)) is not None:
            return stop
        from server.services import hands_contract, hands_service
        # v0.1.63 H4 (⓪Plan): the never-list is a refusal, and an app chosen while the script runs can't
        # be checked against it, so such a script is refused, not asked.
        if computed := hands_service.computed_app_target(script):
            return _bad_request(
                f"App names must be literal strings, like tell application \"Notes\" or application id "
                f"\"com.apple.Notes\" — not `{computed}`. Arslan checks every app a script talks to against "
                f"the apps it never touches, and an app chosen while the script runs can't be checked. "
                f"Write the app's name in quotes.")
        # The never-list holds for scripts too (0.1.61 §A11), and for a process System Events reaches (H4).
        if denied := hands_service.never_listed_target(script):
            return _failed(hands_contract.Result(ok=False, code="app_denied", refused=True), app=denied[:120])
        kind, named = hands_service.script_kind(script)
        # 0.1.61 release gate: a script runs outside the command sandbox, and script_kind reads what it
        # does past the app it names from its words only (raw «events», AppleScriptObjC and Standard
        # Additions' file writes among them since 0.1.63, #232, but still words). So no grant or rule
        # stands for a script — not an app's "for this task", "in this conversation" or "Always",
        # Hands' included: every script is asked, in full, in Arslan, as in 0.1.60. One that names apps
        # is `app_risky` (once, never remembered).
        # The rewrite is policy, so it stays here and script_kind keeps telling `app` from `app_risky`
        # (C2c, ⓪Plan 2026-10-21): that split is what lifting the gate needs. Removed when the 0.1.61
        # every-script-asks gate lifts, by its own card, together with the island's `scriptAlsoHands`
        # text coming back (C2c deletes it from the web while no `app` script card can exist).
        if kind == "app":
            kind = "app_risky"
        decision = await _decide(kind, ", ".join(named) or "AppleScript", "Run this AppleScript?", script,
                                 "mac_script", "AppleScript", extra={"apps": named[:8]})
        refused = None if decision.allowed else decision
        if refused is not None:
            return _no(refused, "this AppleScript")
        if (stop := _stopped(job_id)) is not None:
            return stop
        return await _run(["/usr/bin/osascript", "-e", script])


# ── Mac apps through Arslan Hands (0.1.53) ───────────────────────────────────

_VERBS = {"click": "clicking", "set_value": "typing in", "type": "typing in", "select": "choosing in",
          "scroll": "scrolling", "press": "pressing", "menu": "choosing the menu item"}
# P0 D6: the cursor label is on the user's screen, so it speaks the UI language.
_LABEL_VERBS = {
    "en": _VERBS,
    "zh": {"click": "点击", "set_value": "输入", "type": "输入", "select": "选择", "scroll": "滚动", "press": "按键",
           "menu": "菜单"},
    "ja": {"click": "クリック", "set_value": "入力", "type": "入力", "select": "選択", "scroll": "スクロール",
           "press": "キー操作", "menu": "メニュー"},
    "de": {"click": "klickt", "set_value": "schreibt in", "type": "schreibt in", "select": "wählt in",
           "scroll": "scrollt", "press": "drückt", "menu": "Menü"},
    "es": {"click": "haciendo clic", "set_value": "escribiendo en", "type": "escribiendo en",
           "select": "eligiendo en", "scroll": "desplazando", "press": "pulsando", "menu": "menú"},
    "fr": {"click": "clique", "set_value": "écrit dans", "type": "écrit dans", "select": "choisit dans",
           "scroll": "fait défiler", "press": "appuie", "menu": "menu"},
}


async def _label_verb(op: str) -> str:
    from server.services import runtime_messages
    try:
        locale = await runtime_messages.selected_locale()
    except Exception:  # noqa: BLE001 — a label must never stop an action
        locale = "en"
    return _LABEL_VERBS.get(locale, _VERBS).get(op, _VERBS.get(op, op))


_ASKS = {"click": "click", "set_value": "type into", "select": "choose", "scroll": "scroll", "press": "press",
         "menu": "choose the menu item"}
# What each limited tier may still do (Hands enforces the same; checked here first
# so the user is never asked to allow something Hands would refuse anyway).
_TIER_ALLOWS = {"look_only": set(), "click_only": {"click", "scroll"}}


def desktop_available() -> bool:
    from server.services import hands_client, hands_service
    return hands_client.available() and hands_service.settings()["enabled"]


# job id -> the lock its first session is started under
_session_locks: dict[str, asyncio.Lock] = {}


async def _job_session(job_id: str) -> str | None:
    """One agent-desktop session per job: it carries the cursor overlay and keeps
    the job's refs apart from everything else's. A look's snapshot and screenshot run at
    once (P2-1); without the lock each started its own session, the look's refs landed in
    one and the job kept the other, so the first action after a job's first look answered
    ref_unknown (P2-5 smoke, 2026-10-10)."""
    from server.services import hands_service
    existing = hands_service.session_for(job_id)
    if existing or not hands_service.settings()["cursor"]:
        return existing
    async with _session_locks.setdefault(job_id, asyncio.Lock()):
        return await _start_job_session(job_id)


async def _start_job_session(job_id: str) -> str | None:
    from server.services import hands_client, hands_contract, hands_service
    existing = hands_service.session_for(job_id)
    if existing:
        return existing
    try:
        result = hands_contract.parse(await hands_client.call("session_start", {"label": "Arslan"}, timeout=20))
    except hands_client.HandsUnavailable:
        return None
    session = (result.data or {}).get("session") if result.ok and isinstance(result.data, dict) else None
    if isinstance(session, str):
        hands_service.remember_session(job_id, session)
    return session if isinstance(session, str) else None


# Reads that may be repeated once on a TIMEOUT: measured on a busy Mac (simulator,
# many windows), agent-desktop's window inventory and big trees (Notes) time out
# intermittently and succeed on the next try. Actions are never repeated.
_RETRY_READS = {"snapshot", "find", "list_windows", "get", "describe"}


# Requests that need one of the app's windows (Hands' own list, `needs_window`): an app whose windows
# are all on another desktop is gone to for them, under the user's borrow switch (§15 A18).
_NEEDS_WINDOW = frozenset({"snapshot", "find", "get", "describe", "click", "type", "set_value", "select",
                           "press", "scroll", "list_windows", "wait"})

# §15 A18: what Arslan tells the model when Hands went to another desktop for this step (read by
# the look / action that made the request, in the same task).
_visit_note: contextvars.ContextVar[str | None] = contextvars.ContextVar("hands_visit_note", default=None)


def _went_to_window(reply: dict) -> None:
    """Hands went to the desktop where the app's window is: say so to the model, and come back
    when the work that went there (this chat turn or background job) ends."""
    from server.services import desktop_status
    app = ((reply.get("visit") or {}).get("app") if isinstance(reply.get("visit"), dict) else None) or "the app"
    _visit_note.set(f"Arslan went to the desktop where {app}'s window is (the screen edge glows; the user's "
                    "keys are held and given back). It comes back when this work ends, or at once if the user "
                    f"touches anything: keep the steps in {app} together.\n")
    desktop_status.when_work_ends(_come_back, key="hands.visit")


def _come_back() -> None:
    try:
        asyncio.get_running_loop().create_task(_visit_end())
    except RuntimeError:               # no loop (a test's plain call): Hands' own idle limit applies
        pass


async def _visit_end() -> None:
    from server.services import hands_client
    try:
        await hands_client.call("visit_end", {}, timeout=5, start=False)
    except hands_client.HandsUnavailable:
        pass


def _take_visit_note() -> str:
    note = _visit_note.get()
    if note:
        _visit_note.set(None)
    return note or ""


async def _hands(op: str, args: dict, *, job_id: str | None = None, timeout: float = 60.0):
    """One Hands request with the user's never-list (and the job's session). The user's "borrow
    the front when needed" switch goes with every request: a step on an app whose windows are on
    another desktop goes there under it (§15 A18)."""
    from server.services import hands_client, hands_contract, hands_service
    args = {**args, "never": hands_service.settings()["never"]}
    if op in _NEEDS_WINDOW:
        args.setdefault("borrow", hands_service.settings()["borrow"])
    if job_id is not None:
        session = await _job_session(job_id)
        if session:
            args["session"] = session
    try:
        reply = await hands_client.call(op, args, timeout=timeout)
    except hands_client.HandsUnavailable as exc:
        return hands_contract.Result(ok=False, code="hands_unavailable", refused=True,
                                     message=f"Arslan Hands is not available ({exc}). Tell the user.")
    result = hands_contract.parse(reply)
    if result.code == "TIMEOUT" and op in _RETRY_READS:
        try:
            result = hands_contract.parse(await hands_client.call(op, args, timeout=timeout))
        except hands_client.HandsUnavailable:
            pass
    if isinstance(result.reply, dict) and result.reply.get("visit_started"):
        _went_to_window(result.reply)
    if result.code == "PERM_DENIED" and hands_service.permission_prompt_once():
        try:                     # D3: macOS shows its own prompt for Arslan Hands, once
            await hands_client.call("request_permission", {}, timeout=10)
        except hands_client.HandsUnavailable:
            pass
    return result


def _failed(result, *, app: str = "", nothing_sent: bool = False) -> dict:
    """A Hands failure for the model. `executed: False` when its code is only said before the action,
    or when the caller knows no action request was sent in this call (`nothing_sent`: the app was being
    resolved or the target described, both reads), whatever the code (H2)."""
    text = result.advice()
    out = {"ok": False, "external": False, "code": result.code, "error": text.replace("<App>", app or "the app")}
    return _not_run(out) if nothing_sent or result.code in NOT_EXECUTED else out


def _trace(op: str, app: dict | str, outcome: str, started: float, **extra) -> None:
    from server.services import hands_service
    conversation_id, job_id = _conversation_and_job()
    name = app.get("name") if isinstance(app, dict) else app
    bundle = app.get("bundle_id") if isinstance(app, dict) else None
    try:
        hands_service.trace({"conversation": conversation_id, "job": job_id, "app": name, "bundle_id": bundle,
                             "op": op, "outcome": outcome, "ms": int((time.monotonic() - started) * 1000),
                             **extra})
    except OSError:
        pass


async def _resolve_app(name: str, job_id: str | None):
    """The running app a name or bundle id means, as Hands resolves it (§15 A19: one resolver, in
    Hands; it refuses never-list apps and says when a name is ambiguous). Hands is then given that
    app's bundle id (`_target`), so the card, the grant and the action are about the same app."""
    from server.services import hands_contract, hands_service
    result = await _hands("which_app", {"app": name}, job_id=None)
    if not result.ok:
        # A never-list app is said as such, running or not.
        if result.code == "app_not_running" and hands_service.never_touched(name):
            return None, hands_contract.Result(ok=False, code="app_denied", refused=True)
        return None, result
    app = (result.data or {}).get("app")
    if not isinstance(app, dict) or not app.get("name"):
        return None, hands_contract.Result(ok=False, code="app_not_running", refused=True)
    return app, None


def _target(app: dict) -> str:
    """How Hands is told which app (§15 A19): its bundle id — another running app may share its
    name (WeChat's helper is also "WeChat") — else its name."""
    return str(app.get("bundle_id") or app.get("name") or "")


async def _window_id(app: str, title: str, job_id: str | None) -> tuple[str | None, list[str], bool]:
    """The id of the app's window whose title contains `title`, the titles of its windows, and whether
    that id is the app's only window, taken because no title matched (§15 A19: the model often names
    a window after the app — "微信" for WeChat's window "Weixin"). Without Screen Recording (which
    Hands never asks for) the window list has no real titles — agent-desktop fills in the app's name
    (measured: every Finder window "Finder") — so a title that does not match is read from the
    window's own accessibility element: a one-level look at that window."""
    result = await _hands("list_windows", {"app": app}, job_id=job_id)
    if not result.ok or not isinstance(result.data, list):
        return None, [], False
    wanted = title.strip().lower()
    seen: list[tuple[str, str]] = []
    for window in result.data[:30]:
        if not isinstance(window, dict) or not window.get("id"):
            continue
        name = str(window.get("title") or "")
        if wanted not in name.lower():
            shallow = await _hands("snapshot", {"app": app, "window_id": window["id"], "max_depth": 1},
                                   job_id=job_id)
            data = shallow.data if shallow.ok and isinstance(shallow.data, dict) else {}
            name = str((data.get("tree") or {}).get("name") or (data.get("window") or {}).get("title") or "")
        if wanted in name.lower():
            return str(window["id"]), [name], False
        seen.append((str(window["id"]), name))
    if len(seen) == 1:
        return seen[0][0], [seen[0][1]], True
    return None, [name for _, name in seen if name], False


async def _look_one_window(op: str, args: dict, job_id: str | None):
    """A look; when the app has several windows and none was named, agent-desktop
    refuses (AMBIGUOUS_TARGET, seen with Notes) — look at its focused window
    instead (or its first)."""
    result = await _hands(op, args, job_id=job_id)
    if result.code != "AMBIGUOUS_TARGET" or args.get("window_id"):
        return result
    windows = await _hands("list_windows", {"app": args["app"]}, job_id=job_id)
    listed = [w for w in (windows.data if windows.ok and isinstance(windows.data, list) else [])
              if isinstance(w, dict) and w.get("id")]
    if not listed:
        return result
    chosen = next((w for w in listed if w.get("is_focused")), listed[0])
    return await _hands(op, {**args, "window_id": str(chosen["id"])}, job_id=job_id)


def _app_arg(args: dict) -> str | None:
    app = str((args or {}).get("app") or "").strip()
    return app if app and len(app) <= 120 else None


# Why a look came without a screenshot, said once per conversation (or job) and code.
_SHOT_NOTES = {
    "screen_recording_off": "No screenshot: Arslan Hands is not allowed to record the screen. Working from the "
                            "window's text. The user can allow it in Arslan's Settings → Arslan Hands.",
    "needs_macos_14": "No screenshot: window screenshots need macOS 14 or later. Working from the window's text.",
}
_shot_notes_said: set[tuple[str, str]] = set()


async def _screenshot(app: dict, window, conversation_id: str | None, job_id: str | None) -> tuple[dict | None, str]:
    """Hands' screenshot of the window just looked at (spec §4.2): the capture, or None and
    a note for the model (once per conversation for a lasting reason; never an error: the
    look stands on its text)."""
    args = {"app": _target(app)}
    if window:
        args["window"] = str(window)
    result = await _hands("capture_window", args, job_id=job_id)
    capture = (result.data or {}).get("capture") if result.ok and isinstance(result.data, dict) else None
    if isinstance(capture, dict) and capture.get("data") and capture.get("mime"):
        note = "" if capture.get("onscreen", True) else (
            "This window is not on the current screen (another Space, minimized or behind a full-screen app): "
            "the screenshot is what it last showed and may be incomplete or out of date.\n")
        return capture, note
    code = result.code or "capture_failed"
    scope = job_id or conversation_id or ""
    if code in _SHOT_NOTES:
        if (scope, code) in _shot_notes_said:
            return None, ""
        if len(_shot_notes_said) > 1_000:          # bounded; a reason said again is harmless
            _shot_notes_said.clear()
        _shot_notes_said.add((scope, code))
        return None, _SHOT_NOTES[code] + "\n"
    return None, f"No screenshot this time ({code}); working from the window's text.\n"


class DesktopAppsExecutor:
    key = "desktop_apps"
    timeout_s = RUN_S + 30

    async def execute(self, args: dict) -> dict:
        if not desktop_available():
            return _unavailable()
        result = await _hands("list_apps", {})
        if not result.ok:
            return _failed(result)
        notes = {"look_only": " (look only: act on web pages with Arslan's browser)",
                 "click_only": " (click and scroll only)"}
        # §15 A19: a helper may carry its app's name (WeChat's WeChatAppEx is also "WeChat").
        helper = " (a background helper with no Dock icon: usually not the app meant)"
        lines = [f"- {a.get('name')} — {a.get('bundle_id')}{notes.get(a.get('tier'), '')}"
                 f"{helper if a.get('regular') is False else ''}"
                 for a in (result.data or {}).get("apps") or []
                 if a.get("bundle_id")]    # helper processes (agent-desktop itself, measured) have none
        text = "Running apps Arslan may use:\n" + "\n".join(lines) if lines else "No apps Arslan may use are running."
        return {"ok": True, "external": False, "text": text, "summary": f"{len(lines)} apps"}


class DesktopLookExecutor:
    key = "desktop_look"
    timeout_s = CARD_S + 2 * RUN_S        # one card; window lookup + the look, tried twice

    async def execute(self, args: dict) -> dict:
        from server.services import hands_contract, hands_service, look_diff
        args = dict(args or {})
        name = _app_arg(args)
        if name is None:
            return _bad_request("app required (a name from desktop_apps)")
        if not desktop_available():
            return _unavailable()
        started = time.monotonic()
        conversation_id, job_id = _conversation_and_job()
        if (stop := _stopped(job_id)) is not None:    # a look borrows the front and goes to other desktops
            return stop
        app, failure = await _resolve_app(name, job_id)
        if app is None:
            return _failed(failure, app=name)
        bundle = str(app.get("bundle_id") or app.get("name"))
        # One card for looking and acting (0.1.61 §A11), remembered by the permission store.
        decision = await _decide_app(
            app, f"Arslan wants to use {app['name']} for this: read what is in its window (text, buttons, "
                 f"fields), and click, type and choose there. Deleting, sending and paying still ask every time.", step="look")
        if not decision.allowed:
            _trace("look", app, "declined" if decision.by == "user" else decision.by, started)
            return _no(decision, f"using {app['name']}")
        call = {"app": _target(app)}
        not_seen = ""
        window_note = ""
        if isinstance(args.get("window"), str) and args["window"].strip():
            asked = args["window"][:80]
            window, titles, only = await _window_id(_target(app), args["window"], job_id)
            if window is None:
                listed = ", ".join(f"“{t[:60]}”" for t in titles[:8])
                return _not_run({"ok": False, "external": False, "code": "window_not_found",
                                 "error": f"{app['name']} has no window titled like “{asked}” on this screen. "
                                          + (f"Its windows here: {listed}. Look with one of these titles, or "
                                             "without `window` to see its front window." if listed else
                                             "Look without `window` to see its front window.")})
            if only:
                shown = f", “{titles[0][:60]}”" if titles and titles[0] else ""
                window_note = (f"No window of {app['name']} is titled like “{asked}”; this is its only "
                               f"window{shown}.\n")
            call["window_id"] = window
        if isinstance(args.get("wait_for_text"), str) and args["wait_for_text"].strip():
            waited = await _hands("wait", {**call, "text": args["wait_for_text"][:200], "timeout_ms": 10_000},
                                  job_id=job_id)
            if not waited.ok and waited.code != "TIMEOUT":
                return _failed(waited, app=app["name"])
            if not waited.ok:      # P0 D4: say so; the look below is of a window without it
                not_seen = (f"“{args['wait_for_text'][:200]}” did not appear within 10 seconds; "
                            "this is the window as it is now.\n")
        if args.get("text") or args.get("role"):
            find = {k: str(args[k])[:200] for k in ("text", "role") if args.get(k)}
            result = await _look_one_window("find", {**call, **find}, job_id)
            if not result.ok:
                _trace("look", app, result.code or "error", started)
                return _failed(result, app=app["name"])
            text = f"{app['name']} — elements matching {find}:\n" + hands_contract.render_matches(result.data)
        else:
            snap = dict(call)
            if args.get("ref"):
                snap["root"] = str(args["ref"])[:200]
            screenshots = hands_service.settings()["screenshots"] and not hands_service.no_screenshots(
                str(app.get("name") or ""), str(app.get("bundle_id") or ""))
            shot = None
            if screenshots:
                snap["include_bounds"] = True
                # Asked together (§15 A8: a look under 400 ms): the named window, or the app's
                # front one, which is checked against the window the tree came from below.
                shot = asyncio.create_task(_screenshot(app, call.get("window_id"), conversation_id, job_id))
            result = await _look_one_window("snapshot", snap, job_id)
            if not result.ok:
                if shot is not None:
                    await shot
                _trace("look", app, result.code or "error", started)
                return _failed(result, app=app["name"])
            data = result.data if isinstance(result.data, dict) else {}
            window = (data.get("window") or {}).get("title") or ""
            capture, shot_note = (await shot) if shot is not None else (None, "")
            read = str((data.get("window") or {}).get("id") or "")
            if capture and read and str(capture.get("window_id")) != read.removeprefix("w-"):
                capture, shot_note = await _screenshot(app, read, conversation_id, job_id)
            changed = None if args.get("ref") else look_diff.since_last(
                job_id or conversation_id or "", bundle, window, data.get("tree") or {})
            text = (f"{app['name']} — window “{window}”. Refs [@…] work for actions in this piece of work; "
                    "an entry with “… inside” opens with desktop_look {app, ref}.\n")
            if capture:
                text += (f"A screenshot of this window ({capture['width']}×{capture['height']} px) is attached; "
                         "(x, y) after an element is its centre in that screenshot, in its pixels.\n")
            text += shot_note
            if changed:
                text += f"Changed since your last look: {changed}\n"
            elif changed == "":
                text += "Nothing changed since your last look.\n"
            text += hands_contract.render_tree(data.get("tree") or {},
                                               place=hands_contract.placer(capture) if capture else None)
            if capture:
                from server.services import desktop_status
                desktop_status.note_thumb(capture["data"])        # the island's thumbnail (§6.6)
                text = _take_visit_note() + window_note + (not_seen or "") + text
                _trace("look", app, "ok", started, screenshot=f"{capture['width']}x{capture['height']}",
                       screenshot_bytes=len(capture.get("data") or "") * 3 // 4)
                return {"ok": True, "external": True, "text": text, "summary": f"look · {app['name']}"[:200],
                        "images": [{"mime_type": capture["mime"], "data": capture["data"]}],
                        "image_label": f"{app['name']} · {window or capture.get('title') or 'window'}"[:120]}
        text = _take_visit_note() + window_note + (not_seen or "") + text
        _trace("look", app, "ok", started)
        # Window contents are other people's text: framed as untrusted by the tool loop.
        return {"ok": True, "external": True, "text": text, "summary": f"look · {app['name']}"[:200]}


def _front(args: dict) -> dict:
    """What Hands needs to borrow the front (§6.3): the user's switch, always; `front` only when the
    model asked for it (after a background try did nothing)."""
    from server.services import hands_service
    extra = {"borrow": hands_service.settings()["borrow"]}
    if args.get("front") is True:
        extra["front"] = True
    return extra


def _borrow_note(gave: dict) -> str:
    """What a borrow did, for the model (the user saw the glow)."""
    note = f" Arslan borrowed the front for {gave.get('borrowed_ms', 0)} ms"
    if gave.get("waited_ms"):
        note += f", after waiting {gave['waited_ms']} ms for the user to pause typing"
    keys = gave.get("keys_replayed") or 0
    if keys:
        note += f"; {keys} key events the user typed meanwhile were held and given back"
    note += "."
    if gave.get("yielded_to_user"):
        note += " The user moved the mouse while it ran: look before doing more."
    if gave.get("front_restored") is False:
        note += " The front could not be given back to the user's app: tell the user."
    return note


# Hands v2 §6.4: jobs holding a takeover (ended when the job ends).
_takeovers: set[str] = set()
TAKEOVER_WAIT_S = 30 * 60          # how long a paused takeover waits for the user


async def _end_takeover() -> None:
    from server.services import hands_client
    try:
        await hands_client.call("takeover_end", {}, timeout=5, start=False)
    except hands_client.HandsUnavailable:
        pass


async def _wait_for_the_user(job_id: str | None) -> dict:
    """A takeover paused because the user touched the keyboard or mouse (§6.4): the job waits —
    the island offers continue / I'll do it / stop — up to 30 minutes."""
    from server.services import hands_client, hands_service
    deadline = time.monotonic() + TAKEOVER_WAIT_S
    while time.monotonic() < deadline:
        if job_id is not None and hands_service.stopped(job_id):
            break
        try:
            reply = await hands_client.call("takeover_status", {}, timeout=5, start=False)
        except hands_client.HandsUnavailable:
            break
        state = reply.get("takeover") or {}
        if state.get("active") and not state.get("paused"):
            return {"ok": False, "external": False, "code": "takeover_resumed",
                    "error": "The user paused the takeover and has now let you continue. The screen may have "
                             "changed: look again (desktop_look) before the next action."}
        if not state.get("active"):
            break
        await asyncio.sleep(0.5)
    _takeovers.discard(job_id or "")
    await _end_takeover()
    return {"ok": False, "external": False, "code": "takeover_ended",
            "error": "The user took the screen back and the takeover ended. Nothing more was sent. Carry on in "
                     "the background if you can, or tell the user what is left."}


AWAY_AFTER_S = 180              # §6.5: no input for this long (the island's measure) = away


async def _user_away() -> bool:
    """§6.5: the user turned on "while I'm away" and has not touched the keyboard or mouse for
    three minutes (Hands' key tap measures it; unknown counts as here)."""
    from server.services import hands_client, hands_service
    if not hands_service.settings()["away"]:
        return False
    try:
        status = await hands_client.call("status", {}, timeout=5, start=False)
    except hands_client.HandsUnavailable:
        return False
    idle = status.get("user_idle_ms")
    return isinstance(idle, (int, float)) and idle >= AWAY_AFTER_S * 1000


class DesktopTakeoverExecutor:
    """Take the screen over for long foreground work (§6.4): background work only, a card every
    time (answered in Arslan, never from the island), the edge glows, and the user's first touch pauses it."""
    key = "desktop_takeover"
    timeout_s = CARD_S + 30

    async def execute(self, args: dict) -> dict:
        from server.services import hands_client, hands_contract
        args = dict(args or {})
        why = " ".join(str(args.get("why") or "").split())[:300]
        try:
            minutes = int(args.get("minutes") or 0)
        except (TypeError, ValueError):
            minutes = 0
        if not why or not 1 <= minutes <= 30:
            return _bad_request("why (what you will do, in words) and minutes (1 to 30) are required")
        conversation_id, job_id = _conversation_and_job()
        if job_id is None:
            if _scheduled_run() is not None:
                return await _refused_unattended("takeover", "*", "Take over the screen?")
            return _not_run({"ok": False, "external": False, "code": "act_in_background",
                             "error": "Taking the screen over runs in background work only. Call start_background_work."})
        if not desktop_available():
            return _unavailable()
        if (stop := _stopped(job_id)) is not None:
            return stop
        from server.services import permissions
        started = time.monotonic()
        away = await _user_away()
        request = _request(
            "takeover", "screen", f"Take over the screen for about {minutes} minutes?",
            f"Arslan wants to take over the screen for about {minutes} minutes: {why}. Please keep off the "
            "keyboard and mouse meanwhile — touching either pauses it at once, and Esc stops it. Deleting, "
            "sending and the like still ask you each time.",
            "desktop_takeover", f"{minutes} min · {why}", extra={"minutes": minutes, **({"away_mode": True} if away else {})})
        if away:
            # "While I'm away" (§6.5) lets it start without a card; it is still a ledger row, decided by
            # the mode (0.1.61 §A8). `away_mode` tells it apart: the row's `mode` is the permission mode.
            await permissions.record_standing(request, _context(), by="mode")
        else:
            decision = await permissions.decide(request, _context())
            if not decision.allowed:
                _trace("takeover", "screen", "declined" if decision.by == "user" else decision.by, started)
                return _no(decision, "taking the screen over")
        try:
            reply = await hands_client.call("takeover_begin", {"minutes": minutes}, timeout=10)
        except hands_client.HandsUnavailable as exc:      # never reached Hands (hands_client._NotSent)
            return _not_run({"ok": False, "external": False, "code": "hands_unavailable",
                             "error": f"Arslan Hands is not available ({exc})."})
        result = hands_contract.parse(reply)
        if not result.ok:
            return _failed(result)
        _takeovers.add(job_id)
        _trace("takeover", "screen", "ok", started, minutes=minutes, away=away)
        return {"ok": True, "external": False, "outcome": "done",
                "text": f"The screen is yours for up to {minutes} minutes (the edge glows). Actions may now use the "
                        "front without waiting. If the user touches the keyboard or mouse it pauses and the next "
                        "action tells you what they chose. It ends when this work ends."
                        + (" The user is away and allowed this without asking; risky actions still wait for them."
                           if away else ""),
                "summary": f"takeover · {minutes} min"}


# Hands v2 §5.7, kept for scheduled runs only (⓪Plan on #290, 2026-10-21): U8 lifts the cap for chat
# replies; a scheduled run acts with nobody at the Mac, and what scheduled runs may do is with the
# audit. At most this many actions, all in one app, per run (a batch counts its steps).
# Defence in depth since S1a (U14 a, #317): permissions.decide refuses every action when no asker is bound, as
# in a scheduled run, so this cap cannot be reached while that holds. DELETE-BY: v0.1.64 if M2 shows the policy
# refusal holding (no scheduled run acted on the Mac).
SCHEDULED_ACTIONS = 5
_scheduled: dict[int, tuple[int, str]] = {}      # desktop_status work id → (actions, app)


def _scheduled_run() -> int | None:
    """The desktop_status work id of the scheduled run this call is in, or None."""
    from server.services import desktop_status
    activity = desktop_status._current.get()
    return activity["id"] if activity is not None and activity.get("kind") == "scheduled" else None


def _scheduled_refusal(why: str) -> dict:
    return _not_run({"ok": False, "external": False, "code": "act_in_background",
                     "error": f"{why} {_SCHEDULED_INSTEAD}"})


def _scheduled_full(run: int | None) -> dict | None:
    if run is None:
        return None
    from server.services import desktop_status
    with desktop_status._lock:
        live = set(desktop_status._working)
    for gone in [r for r in _scheduled if r not in live]:
        del _scheduled[gone]
    if _scheduled.get(run, (0, ""))[0] >= SCHEDULED_ACTIONS:
        return _scheduled_refusal(f"This scheduled run has already acted {SCHEDULED_ACTIONS} times, the most a "
                                  "scheduled run may.")
    return None


def _scheduled_count(run: int | None, bundle: str) -> dict | None:
    """Count one action of a scheduled run in `bundle`; a refusal when it would be a second app."""
    if run is None:
        return None
    count, first = _scheduled.get(run, (0, bundle))
    if first != bundle:
        return _scheduled_refusal("This scheduled run already acted in another app; a scheduled run acts in one app.")
    _scheduled[run] = (count + 1, first)
    return None


def _in_a_conversation() -> bool:
    from server.services import personal_context
    ctx = personal_context.current()
    return ctx is not None and bool(ctx.conversation_id)


def _stopped(job_id: str | None) -> dict | None:
    """H3: Stop stops a chat turn's Hands calls as it stops a job's. Checked before the first request,
    and again after every card and before every step that sends (②Main's review of #290: a card can be
    answered after Stop; Stop does not close it)."""
    from server.services import hands_contract, hands_service
    if not hands_service.stopped(job_id):
        return None
    return _not_run({"ok": False, "external": False, "code": "stopped_by_user",
                     "error": hands_contract.REFUSALS["stopped_by_user"]})


# Roles named by what they hold, not by what clicking them does (§15 A19: in the L3 pilot a note's
# row, "a note for the delete task", asked as a delete). Every other role — buttons, menu items,
# links, groups (a web page's clickable element is often a group) — and an unknown one still do.
_CONTENT_ROLES = frozenset({"row", "cell", "treeitem", "textfield"})


class _DesktopAct:
    op = ""
    timeout_s = 2 * CARD_S + 2 * RUN_S    # the app card and a risky-action card; describe, act, Return

    def _risky(self, args: dict, target: dict, app: dict) -> str | None:
        """Why this action asks every time, or None."""
        from server.services import hands_service
        label = target.get("name") if isinstance(target, dict) else None
        role = str(target.get("role") or "").lower() if isinstance(target, dict) else ""
        if self.op in ("click", "select") and role not in _CONTENT_ROLES and hands_service.risky_label(label):
            return f"“{label}”"
        return None

    async def execute(self, args: dict) -> dict:
        from server.services import hands_contract, hands_service
        args = dict(args or {})
        name = _app_arg(args)
        if name is None:
            return _bad_request("app required (a name from desktop_apps)")
        conversation_id, job_id = _conversation_and_job()
        if job_id is None and not _in_a_conversation():
            return _not_run({"ok": False, "external": False, "code": "no_one_to_ask",
                             "error": "Acting in a Mac app needs a conversation to ask the user in."})
        if not desktop_available():
            return _unavailable()
        stop = _stopped(job_id)                     # before any request
        if stop is not None:
            return stop
        run = _scheduled_run() if job_id is None else None
        if (full := _scheduled_full(run)) is not None:
            return full
        started = time.monotonic()
        target: dict = {}
        if self.op in ("press", "menu"):
            app, failure = await _resolve_app(name, job_id)
            if app is None:
                return _failed(failure, app=name, nothing_sent=True)
            if app.get("tier") in _TIER_ALLOWS:
                return _failed(hands_contract.Result(ok=False, code=f"app_{app['tier']}", refused=True))
        else:
            ref = str(args.get("ref") or "")
            described = await _hands("describe", {"app": name, "ref": ref}, job_id=job_id)
            if not described.ok:
                _trace(self.op, name, described.code or "error", started)
                return _failed(described, app=name, nothing_sent=True)
            app = described.data.get("app") or {"name": name}
            target = described.data.get("target") or {}
            tier = described.data.get("tier")
            if tier in _TIER_ALLOWS and self.op not in _TIER_ALLOWS[tier]:
                return _failed(hands_contract.Result(ok=False, code=f"app_{tier}", refused=True))
            if target.get("password") and self.op in ("type", "set_value"):
                return _failed(hands_contract.Result(ok=False, code="password_field", refused=True))
        bundle = str(app.get("bundle_id") or app.get("name"))
        label = target.get("name") or args.get("element") or ""
        if self.op == "menu":
            label = " › ".join(_menu_path(args))
        if (other := _scheduled_count(run, bundle)) is not None:
            return other
        verb = _VERBS.get(self.op, self.op)
        first = f"{verb} “{label or args.get('keys', '')}”"
        decision = await _decide_app(
            app, f"Arslan wants to use {app.get('name')} for this: read what is in its window, and click, type "
                 f"and choose there. First: {first}. Deleting, sending and paying still ask every time.", step=first)
        if not decision.allowed:
            _trace(self.op, app, "declined" if decision.by == "user" else decision.by, started)
            return _no(decision, f"acting in {app.get('name')}")
        why = self._risky(args, target, app)
        if why:
            # Money moves ask in every mode; deleting, sending, submitting ask every time (0.1.61 §A11).
            name = str(app.get("name") or bundle)
            ask = _ASKS.get(self.op, self.op)
            decision = await _decide(
                "money" if hands_service.money_label(why) else "app_risky", bundle,
                f"{ask[:1].upper()}{ask[1:]} {why} in {name}?",
                f"Arslan wants to {ask} {why} in {name}. This may delete, send, pay or submit something.",
                "desktop_risky", f"{name} · {why}",
                extra={"app": name, "bundle_id": bundle, "op": self.op, "label": str(label)[:200],
                       "role": str(target.get("role") or "")[:40]})
            if not decision.allowed:
                _trace(self.op, app, "declined" if decision.by == "user" else decision.by, started, target=label)
                return _no(decision, why)
        if (stop := _stopped(job_id)) is not None:   # Stop while a card waited
            _trace(self.op, app, "stopped_by_user", started, target=label)
            return stop
        session = hands_service.session_for(job_id)
        if session:
            shown = await _label_verb(self.op)
            await _hands("session_label", {"session": session, "label": f"Arslan · {shown} {label}"[:80]})
        result = await self.run(args, app)
        _trace(self.op, app, "ok" if result.ok else (result.code or "error"), started, target=label,
               mode_used=(result.reply or {}).get("mode_used") if isinstance(result.reply, dict) else None,
               **self.trace_extra(args))
        if not result.ok and result.code == "takeover_paused":
            return await _wait_for_the_user(job_id)
        if not result.ok:
            return _failed(result, app=str(app.get("name")))
        # P0 D7: "sent" is not "done" — only a change agent-desktop read back is.
        outcome = hands_contract.outcome(result)
        if outcome == "done":
            text = (f"Done: {verb} “{label}” in {app.get('name')} (the change was read back). "
                    "Look again (desktop_look) to see the result before the next step.")
        elif outcome == "no_effect":
            text = (f"Nothing changed: {verb} “{label}” in {app.get('name')} was delivered but the app did not "
                    "react. Look again: the element may be disabled or need the app in front. Do not repeat it "
                    "blindly.")
        elif outcome == "partly_done":
            text = (f"Partly done: {verb} “{label}” in {app.get('name')} stopped part way. Look at what is there "
                    "now before doing anything else.")
        elif outcome == "refused":
            text = (f"Not done: {app.get('name')} refused {verb} “{label}”; nothing was delivered. Look again and "
                    "try another way.")
        else:
            text = (f"Sent, not confirmed: {verb} “{label}” in {app.get('name')}. Arslan could not read the "
                    "change back, so look (desktop_look) before the next step, and do not simply repeat it.")
        gave = (result.reply or {}).get("borrow") if (result.reply or {}).get("mode_used") == "borrow" else None
        if isinstance(gave, dict):
            text += _borrow_note(gave)
        routed = (result.reply or {}).get("menu_item") if (result.reply or {}).get("route") == "menu_item" else None
        if self.op == "press" and routed:
            text += (f" (The app had nothing focused, so it went to the menu item with that shortcut: "
                     f"“{' › '.join(map(str, routed))}”.)")
        if hands_contract.kept_the_front(result):
            text += (f" {app.get('name')} came to the front when this ran and could not be put back; "
                     "tell the user if it gets in their way.")
        note = _take_visit_note()
        if note:
            text += " " + note.strip()
        out = {"ok": outcome != "refused", "external": False, "outcome": outcome, "text": text,
               "summary": f"{self.op} · {app.get('name')} · {label}"[:200]}
        # `refused` is "nothing was delivered" in the outcome vocabulary (desktop/hands/src/outcome.rs);
        # only the Cua Driver path says it today.
        return _not_run({**out, "code": "app_refused"}) if outcome == "refused" else out

    def trace_extra(self, args: dict) -> dict:
        return {}

    async def run(self, args: dict, app: dict):
        _, job_id = _conversation_and_job()
        return await _hands(self.op, {"app": _target(app), "ref": str(args.get("ref") or ""), **_front(args)},
                            job_id=job_id)


class DesktopClickExecutor(_DesktopAct):
    key = "desktop_click"
    op = "click"


class DesktopTypeExecutor(_DesktopAct):
    """Sets a field's text (no focus taken: headless typing needs a focused field,
    measured), appends with mode=append, presses Return with submit=true."""
    key = "desktop_type"
    op = "set_value"

    def _risky(self, args, target, app):
        from server.services import hands_service
        text = str(args.get("text") or "")
        bundle, name = str(app.get("bundle_id") or ""), str(app.get("name") or "")
        if hands_service.risky_text(text, bundle_id=bundle, app=name) or (
                args.get("submit") and hands_service.risky_keys("return", bundle_id=bundle, app=name)):
            return "Return (it sends a message here)"
        return None

    def trace_extra(self, args):
        return {"typed_chars": len(str(args.get("text") or ""))}   # never the text itself

    async def run(self, args, app):
        _, job_id = _conversation_and_job()
        ref, text = str(args.get("ref") or ""), str(args.get("text") or "")
        if len(text) > 20_000:
            from server.services import hands_contract
            return hands_contract.Result(ok=False, code="too_long", refused=True, message="text too long")
        from server.services import hands_contract
        append = args.get("mode") == "append"
        if append:
            # P0 D2: without the old text, "append" would set the field to the new text alone.
            current = await _hands("get", {"app": _target(app), "ref": ref, "property": "value"}, job_id=job_id)
            if not (current.ok and isinstance(current.data, dict) and isinstance(current.data.get("value"), str)):
                return hands_contract.Result(ok=False, code="append_unreadable", refused=True)
            text = current.data["value"] + text
        result = await _hands("set_value", {"app": _target(app), "ref": ref, "value": text}, job_id=job_id)
        if not result.ok and result.code in ("ACTION_NOT_SUPPORTED", "POLICY_DENIED"):
            if append:
                # `type` inserts at the caret: old + new typed there would duplicate the old text.
                return hands_contract.Result(ok=False, code="append_needs_set_value", refused=True)
            result = await _hands("type", {"app": _target(app), "ref": ref, "text": text}, job_id=job_id)
        if result.ok and args.get("submit") and _stopped(job_id) is not None:
            return hands_contract.Result(ok=False, code="stopped_by_user", refused=True,
                                         message="Stopped by the user after the text was set; Return was not pressed.")
        if result.ok and args.get("submit"):
            # P0 D3: Return goes to whatever has the app's focus. Press it only when that
            # is this field, read live just before.
            states = await _hands("get", {"app": _target(app), "ref": ref, "property": "states"}, job_id=job_id)
            value = states.data.get("value") if states.ok and isinstance(states.data, dict) else None
            if not (isinstance(value, list) and "focused" in value):
                return hands_contract.Result(ok=False, code="submit_unsure", refused=True)
            result = await _hands("press", {"app": _target(app), "keys": "return"}, job_id=job_id)
        return result


class DesktopSelectExecutor(_DesktopAct):
    key = "desktop_select"
    op = "select"

    def _risky(self, args, target, app):
        from server.services import hands_service
        value = str(args.get("value") or "")
        return f"“{value}”" if hands_service.risky_label(value) else None

    async def run(self, args, app):
        _, job_id = _conversation_and_job()
        return await _hands("select", {"app": _target(app), "ref": str(args.get("ref") or ""),
                                       "value": str(args.get("value") or "")[:200], **_front(args)},
                            job_id=job_id)


class DesktopScrollExecutor(_DesktopAct):
    key = "desktop_scroll"
    op = "scroll"

    def _risky(self, args, target, app):
        return None

    async def run(self, args, app):
        _, job_id = _conversation_and_job()
        direction = str(args.get("direction") or "down")
        amount = args.get("amount") if isinstance(args.get("amount"), int) else 3
        return await _hands("scroll", {"app": _target(app), "ref": str(args.get("ref") or ""),
                                       "direction": direction, "amount": amount}, job_id=job_id)


def _menu_path(args: dict) -> list[str]:
    path = args.get("path")
    return [str(t)[:120] for t in path[:4]] if isinstance(path, list) else []


class DesktopMenuExecutor(_DesktopAct):
    """Hands v2 §5.5: a menu item chosen in the background by its path (Hands presses it through
    accessibility; nothing comes to the front). Risky labels (delete, send, quit…) ask every time."""
    key = "desktop_menu"
    op = "menu"

    def _risky(self, args, target, app):
        from server.services import hands_service
        path = _menu_path(args)
        if path and hands_service.risky_label(path[-1]):
            return f"the menu item “{' › '.join(path)}”"
        return None

    async def run(self, args, app):
        _, job_id = _conversation_and_job()
        return await _hands("menu", {"app": _target(app), "path": _menu_path(args)}, job_id=job_id)


class DesktopPressExecutor(_DesktopAct):
    key = "desktop_press"
    op = "press"

    def _risky(self, args, target, app):
        from server.services import hands_service
        keys = str(args.get("keys") or "")
        if hands_service.risky_keys(keys, bundle_id=str(app.get("bundle_id") or ""), app=str(app.get("name") or "")):
            return f"the keys {keys}"
        return None

    async def run(self, args, app):
        _, job_id = _conversation_and_job()
        return await _hands("press", {"app": _target(app), "keys": str(args.get("keys") or "").strip().lower(),
                                      **_front(args)}, job_id=job_id)


# Hands v2 §5.6: several steps on one app in one call, then one look.
_BATCH_STEPS = {"click": DesktopClickExecutor, "type": DesktopTypeExecutor, "select": DesktopSelectExecutor,
                "scroll": DesktopScrollExecutor, "press": DesktopPressExecutor, "menu": DesktopMenuExecutor}
BATCH_MAX = 8
# A step that went through (done) or was delivered without proof (sent_unconfirmed) lets the next
# one run: a step that changed the window's structure makes Hands refuse the next (`changed`),
# which stops the batch. Anything else stops it at once.
_BATCH_GOES_ON = {"done", "sent_unconfirmed"}


class DesktopBatchExecutor:
    """Run up to eight steps on one app, in order, each with every check a single call has (cards,
    risky labels, password fields, the structural-change check), stop at the first step that did
    not go through, and end with one look (screenshot and changes included)."""
    key = "desktop_batch"
    timeout_s = BATCH_MAX * (2 * CARD_S + 2 * RUN_S) + CARD_S + 2 * RUN_S

    async def execute(self, args: dict) -> dict:
        args = dict(args or {})
        name = _app_arg(args)
        steps = args.get("steps")
        if name is None:
            return _bad_request("app required (a name from desktop_apps)")
        if not isinstance(steps, list) or not 1 <= len(steps) <= BATCH_MAX:
            return _bad_request(f"steps: 1 to {BATCH_MAX} steps, each {{action, …that action's args}}")
        lines: list[str] = []
        stopped = None
        done = 0
        nothing_ran = False                 # H2: the batch stopped before its first step reached the app
        for number, step in enumerate(steps, 1):
            action = str(step.get("action") or "") if isinstance(step, dict) else ""
            executor = _BATCH_STEPS.get(action)
            if executor is None:
                stopped = f"step {number}: unknown action “{action[:40]}” ({', '.join(_BATCH_STEPS)})"
                nothing_ran = done == 0
                break
            call = {k: v for k, v in step.items() if k != "action"}
            call["app"] = name                      # one app per batch, whatever a step says
            result = await executor().execute(call)
            said = result.get("text") or result.get("error") or ""
            lines.append(f"{number}. {action}: {said}")
            if not result.get("ok") or result.get("outcome") not in _BATCH_GOES_ON:
                stopped = f"stopped at step {number} ({result.get('code') or result.get('outcome') or 'not done'})"
                nothing_ran = done == 0 and result.get("executed") is False
                break
            done += 1
        look = await DesktopLookExecutor().execute({"app": name})     # after Stop it sends nothing either (H3)
        head = (f"Batch in {name}: {done} of {len(steps)} steps went through"
                + (f"; {stopped}" if stopped else "") + ".\n")
        out = {"ok": stopped is None, "external": True,
               "text": head + "\n".join(lines) + "\n\nThe window now:\n" + (look.get("text") or look.get("error") or ""),
               "summary": f"batch · {name} · {done}/{len(steps)}"[:200]}
        if stopped is not None:
            out["code"] = "batch_stopped"
            if nothing_ran:                 # every step before it went through is "done"; there were none
                out["executed"] = False
        if look.get("images"):
            out["images"], out["image_label"] = look["images"], look.get("image_label")
        return out


class DesktopOpenExecutor:
    """Hands v2 §5.2, §15 A18: open an app — or a file in an app — in the background (`open -g`:
    behind the user's windows, never activated). The never-list is refused before anything starts;
    opening asks once, and that answer is also the app's acting grant. A running app with no window
    is asked for one, still in the background (macOS' reopen). If the window lands on another
    desktop, the next look or action goes there (with the user's borrow switch)."""
    key = "desktop_open"
    timeout_s = CARD_S + 30

    async def execute(self, args: dict) -> dict:
        from pathlib import Path
        from server.services import hands_contract, hands_service
        args = dict(args or {})
        name = _app_arg(args)
        if name is None:
            return _bad_request("app required (the app's name, as in /Applications)")
        path = None
        if args.get("path"):
            path = Path(str(args["path"])).expanduser()
            if not path.exists():
                return _not_run({"ok": False, "external": False, "code": "no_such_file",
                                 "error": f"There is no file or folder at {path}. Check the path (list_dir shows "
                                          "a folder)."})
        conversation_id, job_id = _conversation_and_job()
        if job_id is None and not _in_a_conversation():
            return _not_run({"ok": False, "external": False, "code": "no_one_to_ask",
                             "error": "Opening a Mac app needs a conversation to ask the user in."})
        if not desktop_available():
            return _unavailable()
        stop = _stopped(job_id)
        if stop is not None:
            return stop
        run = _scheduled_run() if job_id is None else None
        if (full := _scheduled_full(run)) is not None:
            return full
        if hands_service.never_touched(name):
            return _failed(hands_contract.Result(ok=False, code="app_denied", refused=True), app=name)
        running, _ = await _resolve_app(name, job_id)
        reopen = False
        if running is not None and path is None:
            # Its windows, without going anywhere for them (borrow off for this question).
            windows = await _hands("list_windows", {"app": _target(running), "borrow": False}, job_id=job_id)
            if windows.code == "window_elsewhere":
                return {"ok": True, "external": False, "outcome": "no_effect",
                        "text": f"{running['name']} is running with its windows on another desktop. Look at it or "
                                "act in it as usual: Arslan goes to that desktop (the screen edge glows) and comes "
                                "back when the work ends."}
            if windows.ok and (windows.data or []):
                return {"ok": True, "external": False, "outcome": "no_effect",
                        "text": f"{running['name']} is already running with a window. Look at it with desktop_look."}
            reopen = True                       # running with no window: ask it for one
        started = time.monotonic()
        shown = f"{path.name} in {name}" if path is not None else name
        # Opening is using the app: the same `app` card and grant as a look or an action, kept by the
        # bundle id (of the running app, else of the installed one), so the next step asks nothing.
        identity = running or hands_service.app_identity(name) or {}
        decision = await _decide_app(
            {"name": str(identity.get("name") or name), "bundle_id": str(identity.get("bundle_id") or name)},
            f"Arslan wants to open {shown} in the background (behind your windows) for this, and then look, "
            f"click, type and choose in it. Deleting, sending and paying still ask every time.", step="open")
        if not decision.allowed:
            _trace("open", name, "declined" if decision.by == "user" else decision.by, started)
            return _no(decision, f"opening {name}")
        if (stop := _stopped(job_id)) is not None:   # Stop while the card waited
            return stop
        if (other := _scheduled_count(run, str(identity.get("bundle_id") or name))) is not None:
            return other
        argv = ["/usr/bin/open", "-g", "-a", name] + ([str(path)] if path is not None else [])
        process = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        if await process.wait() != 0:
            _trace("open", name, "not_found", started)
            return _not_run({"ok": False, "external": False, "code": "app_not_found",
                             "error": f"macOS could not open {shown}. Check the app's name (desktop_apps lists "
                                      "running apps) and the path."})
        app = running
        for _ in range(40 if running is None else 0):     # up to ten seconds for a new app to start
            app, failure = await _resolve_app(name, job_id)
            if app is not None or (failure is not None and failure.code == "app_denied"):
                break
            await asyncio.sleep(0.25)
        if app is None:
            _trace("open", name, "not_listed", started)
            return {"ok": True, "external": False, "outcome": "sent_unconfirmed",
                    "text": f"Asked macOS to open {shown}; it is not running yet. Look again in a moment."}
        _trace("open", app, "ok", started)
        what = (f"Opened {path.name} in {app['name']}" if path is not None
                else f"Asked {app['name']} for a window" if reopen else f"Opened {app['name']}")
        return {"ok": True, "external": False, "outcome": "done",
                "text": f"{what} in the background. Look at it with desktop_look before acting; if its window "
                        "is on another desktop, Arslan goes there by itself (the screen edge glows) and comes back.",
                "summary": f"open · {app['name']}"[:200]}


_TIER_WORDS = {"full": "look and act", "look_only": "look only (a browser)",
               "click_only": "look, click and scroll only (runs commands)"}


class DesktopAccessExecutor:
    """Hands v2 §7.2: one card for several apps (instead of one card per app as each is first used).
    Allow = looking at each in this conversation, and acting in each in this piece of work (a chat
    reply, or the background job); apps on the never-list are left out and said."""
    key = "desktop_access"
    timeout_s = CARD_S + 2 * RUN_S

    async def execute(self, args: dict) -> dict:
        from server.services import hands_service, permissions
        args = dict(args or {})
        names = [str(n).strip()[:120] for n in args.get("apps") or [] if str(n).strip()][:8] \
            if isinstance(args.get("apps"), list) else []
        why = " ".join(str(args.get("why") or "").split())[:300]
        if not names or not why:
            return _bad_request("apps (1 to 8 app names) and why (what you will do, in words) are required")
        if not desktop_available():
            return _unavailable()
        conversation_id, job_id = _conversation_and_job()
        if conversation_id is None:
            return _not_run({"ok": False, "external": False, "code": "no_one_to_ask",
                             "error": "Asking for apps needs a conversation to ask the user in."})
        found, skipped = [], []
        for name in names:
            app, failure = await _resolve_app(name, job_id)
            if app is None:
                skipped.append(f"{name} ({failure.code if failure else 'not running'})")
            elif all(a["bundle_id"] != app.get("bundle_id") for a in found):
                found.append(app)
        if not found:
            return _not_run({"ok": False, "external": False, "code": "no_apps",
                             "error": "None of these can be used: " + "; ".join(skipped)})
        # One card for the apps not allowed yet (decide_many: one kind; those a rule or grant already
        # allows are left off it); one answer covers every app shown (0.1.61 §A11).
        await hands_service.migrate_always()
        requests = [_app_request(a, f"· {a['name']} — {_TIER_WORDS.get(str(a.get('tier') or 'full'), 'look and act')}",
                                 step="access") for a in found]
        decisions = await permissions.decide_many(
            requests, _context(),
            title=f"Use {', '.join(a['name'] for a in found)[:100]} for this: {why[:150]}? Deleting, sending and "
                  "paying still ask every time.")
        refused = next((d for d in decisions if not d.allowed), None)
        if refused is not None:
            return _no(refused, "these apps")
        text = "Allowed: " + ", ".join(a["name"] for a in found) + "."
        if skipped:
            text += " Not included: " + "; ".join(skipped) + "."
        return {"ok": True, "external": False, "outcome": "done", "text": text,
                "summary": f"access · {len(found)} apps"}
