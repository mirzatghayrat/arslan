"""0.1.45 hands: Arslan's browser and Mac automation.

Looking (open a page, read it, go back, list Shortcuts) is free. Acting (click,
type, choose, press; run a Shortcut or an AppleScript) happens only inside a
background job, and asks first through that job's confirmation cards
(approvals.ask): once per website per job for the browser, once per Shortcut
per job, and every time for an AppleScript (shown in full). macOS adds its own
Automation consent the first time a script controls an app.

Arslan never types into a password field: the user logs in themselves in the
visible browser window, and that profile keeps the session.

0.1.53 adds Mac apps through Arslan Hands (agent-desktop behind a separate
helper app that alone holds Accessibility; spec
docs/specs/2026-10-03-0153-hands-agent-desktop.md). Looking at an app asks once
per app per conversation; acting runs only inside a background job and asks once
per app per job; an action whose real label deletes, sends, pays, buys,
transfers or submits asks every time.
"""
from __future__ import annotations

import asyncio
import re
import time
import uuid
from urllib.parse import urlsplit

_PASSWORD = re.compile(r"pass(word|code|phrase)|密码|口令|パスワード|contraseña|mot de passe|passwort|\bpin\b", re.I)
_OUTPUT_LIMIT = 8_000
# job id -> things already approved for that job
_grants: dict[str, set[str]] = {}


def _conversation_and_job() -> tuple[str | None, str | None]:
    from server.services import background_jobs, personal_context
    ctx = personal_context.current()
    return (ctx.conversation_id if ctx is not None else None), background_jobs._inside_job.get()


def _not_in_job() -> dict:
    return {"ok": False, "external": False, "code": "act_in_background",
            "error": "Actions (clicking, typing, running Shortcuts or scripts) run as background work. "
                     "Call start_background_work with this goal; looking at pages is fine here."}


# The tool loop stops a tool after TOOL_TIMEOUT_S (20 s) unless the tool declares `timeout_s`.
# These tools wait for the user's card (approvals.TIMEOUT_S each) and for slow apps, so 20 s cut
# them off mid-card. Measured on the user's Mac, 2026-10-05: a Notes look died twice while its
# card was open; an unanswered AppleScript card expired after 20 s and the model asked again.
CARD_S = 300                       # approvals.TIMEOUT_S; a test keeps the two equal
RUN_S = 120                        # _run's default; a Hands call is 60 s, a read is tried twice


async def _ask_once(grant: str, kind: str, target: str, detail: str) -> bool:
    """True if already granted for this job (or, in a chat reply, this conversation), else ask the
    user (card + notification)."""
    from server.services import approvals
    from server.ws import protocol
    conversation_id, job_id = _conversation_and_job()
    if conversation_id is None:
        return False
    granted = _grants.setdefault(job_id or f"conversation:{conversation_id}", set())
    if grant in granted:
        return True
    ok = await approvals.ask(conversation_id, protocol.propose_action(uuid.uuid4().hex, kind, target, detail))
    if ok:                                     # a script's grant key is unique: asked every time
        granted.add(grant)
    return ok


def forget_job(job_id: str) -> None:
    _grants.pop(job_id, None)
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
                return _not_in_job()
            if self.action == "type" and _PASSWORD.search(str(args.get("element", ""))):
                return {"ok": False, "external": False, "code": "no_passwords",
                        "error": "Arslan never types passwords. Ask the user to log in themselves in the "
                                 "Arslan browser window, then continue."}
            origin = _origin(agent_browser.current_url())
            if origin is None:
                return {"ok": False, "external": False, "error": "Open a page with browser_open first."}
            summary = {"click": "click", "type": "type text", "select": "choose options",
                       "press": "press keys"}[self.action]
            if not await _ask_once(f"site:{origin}", "browser_site", origin,
                                   f"Arslan wants to {summary} on {origin} ({args.get('element') or args.get('key') or ''})"):
                return {"ok": False, "external": False, "code": "declined",
                        "error": "The user did not allow acting on this website. Do not retry; report it."}
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
        out, err = await asyncio.wait_for(process.communicate(), timeout)
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
            return {"ok": False, "external": False, "error": "name required"}
        if _conversation_and_job()[1] is None:
            return _not_in_job()
        text_input = (args or {}).get("input")
        if not await _ask_once(f"shortcut:{name}", "mac_shortcut", name,
                               f"Run the Shortcut “{name}”" + (f" with input: {str(text_input)[:300]}" if text_input else "")):
            return {"ok": False, "external": False, "code": "declined", "error": "The user did not allow it."}
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
            return {"ok": False, "external": False, "error": "script required (max 4000 characters)"}
        if _conversation_and_job()[1] is None:
            return _not_in_job()
        if not await _ask_once(f"script:{uuid.uuid4().hex}", "mac_script", "AppleScript", script):
            return {"ok": False, "external": False, "code": "declined", "error": "The user did not allow it."}
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


async def _job_session(job_id: str) -> str | None:
    """One agent-desktop session per job: it carries the cursor overlay and keeps
    the job's refs apart from everything else's."""
    from server.services import hands_client, hands_contract, hands_service
    existing = hands_service.session_for(job_id)
    if existing or not hands_service.settings()["cursor"]:
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


async def _hands(op: str, args: dict, *, job_id: str | None = None, timeout: float = 60.0):
    """One Hands request with the user's never-list (and the job's session)."""
    from server.services import hands_client, hands_contract, hands_service
    args = {**args, "never": hands_service.settings()["never"]}
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
    if result.code == "PERM_DENIED" and hands_service.permission_prompt_once():
        try:                     # D3: macOS shows its own prompt for Arslan Hands, once
            await hands_client.call("request_permission", {}, timeout=10)
        except hands_client.HandsUnavailable:
            pass
    return result


def _failed(result, *, app: str = "") -> dict:
    text = result.advice()
    return {"ok": False, "external": False, "code": result.code,
            "error": text.replace("<App>", app or "the app")}


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
    """The running app a name means, through Hands (which hides the never-list)."""
    from server.services import hands_contract
    result = await _hands("list_apps", {}, job_id=None)
    if not result.ok:
        return None, result
    wanted = name.strip().lower()
    for app in (result.data or {}).get("apps") or []:
        if wanted in (str(app.get("name", "")).lower(), str(app.get("bundle_id", "")).lower()):
            return app, None
    # Hands leaves never-list apps out of the list; say so instead of "not running".
    from server.services import hands_service
    if hands_service.never_touched(name):
        return None, hands_contract.Result(ok=False, code="app_denied", refused=True)
    return None, hands_contract.Result(ok=False, code="app_not_running", refused=True)


async def _window_id(app: str, title: str, job_id: str | None) -> str | None:
    """The id of the app's window whose title contains `title`. Without Screen
    Recording (which Hands never asks for) the window list has no real titles —
    agent-desktop fills in the app's name (measured: every Finder window
    "Finder") — so a title that does not match is read from the window's own
    accessibility element: a one-level look at that window."""
    result = await _hands("list_windows", {"app": app}, job_id=job_id)
    if not result.ok or not isinstance(result.data, list):
        return None
    wanted = title.strip().lower()
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
            return str(window["id"])
    return None


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
    args = {"app": app["name"]}
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
            return {"ok": False, "external": False, "error": "Arslan Hands is not available on this Mac."}
        result = await _hands("list_apps", {})
        if not result.ok:
            return _failed(result)
        notes = {"look_only": " (look only: act on web pages with Arslan's browser)",
                 "click_only": " (click and scroll only)"}
        lines = [f"- {a.get('name')} — {a.get('bundle_id')}{notes.get(a.get('tier'), '')}"
                 for a in (result.data or {}).get("apps") or []
                 if a.get("bundle_id")]    # helper processes (agent-desktop itself, measured) have none
        text = "Running apps Arslan may use:\n" + "\n".join(lines) if lines else "No apps Arslan may use are running."
        return {"ok": True, "external": False, "text": text, "summary": f"{len(lines)} apps"}


class DesktopLookExecutor:
    key = "desktop_look"
    timeout_s = CARD_S + 2 * RUN_S        # one card; window lookup + the look, tried twice

    async def execute(self, args: dict) -> dict:
        from server.services import approvals, hands_contract, hands_service, look_diff
        from server.ws import protocol
        args = dict(args or {})
        name = _app_arg(args)
        if name is None:
            return {"ok": False, "external": False, "error": "app required (a name from desktop_apps)"}
        if not desktop_available():
            return {"ok": False, "external": False, "error": "Arslan Hands is not available on this Mac."}
        started = time.monotonic()
        conversation_id, job_id = _conversation_and_job()
        app, failure = await _resolve_app(name, job_id)
        if app is None:
            return _failed(failure, app=name)
        bundle = str(app.get("bundle_id") or app.get("name"))
        if not (conversation_id and hands_service.looked(conversation_id, bundle)):
            if conversation_id is None:
                return {"ok": False, "external": False, "code": "no_one_to_ask",
                        "error": "Looking at an app needs the user's OK in a conversation."}
            detail = (f"Arslan wants to read what is in {app['name']}'s window (text, buttons, fields) "
                      "to help with this. It asks once per app in a conversation.")
            if not await approvals.ask(conversation_id, protocol.propose_action(
                    uuid.uuid4().hex, "desktop_look", str(app["name"]), detail)):
                _trace("look", app, "declined", started)
                return {"ok": False, "external": False, "code": "declined",
                        "error": f"The user did not allow looking at {app['name']}. Do not retry; ask them."}
            hands_service.allow_look(conversation_id, bundle)
        call = {"app": app["name"]}
        not_seen = ""
        if isinstance(args.get("window"), str) and args["window"].strip():
            window = await _window_id(app["name"], args["window"], job_id)
            if window is None:
                return {"ok": False, "external": False, "code": "window_not_found",
                        "error": f"{app['name']} has no window titled like “{args['window'][:80]}” on this "
                                 "screen. Look without `window` to see its front window."}
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
            screenshots = hands_service.settings()["screenshots"]
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
                if not_seen:
                    text = not_seen + text
                _trace("look", app, "ok", started, screenshot=f"{capture['width']}x{capture['height']}",
                       screenshot_bytes=len(capture.get("data") or "") * 3 // 4)
                return {"ok": True, "external": True, "text": text, "summary": f"look · {app['name']}"[:200],
                        "images": [{"mime_type": capture["mime"], "data": capture["data"]}],
                        "image_label": f"{app['name']} · {window or capture.get('title') or 'window'}"[:120]}
        if not_seen:
            text = not_seen + text
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


class DesktopTakeoverExecutor:
    """Take the screen over for long foreground work (§6.4): background work only, a card every
    time (the island may answer it), the edge glows, and the user's first touch pauses it."""
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
            return {"ok": False, "external": False, "code": "bad_request",
                    "error": "why (what you will do, in words) and minutes (1 to 30) are required"}
        conversation_id, job_id = _conversation_and_job()
        if job_id is None:
            return {"ok": False, "external": False, "code": "act_in_background",
                    "error": "Taking the screen over runs in background work only. Call start_background_work."}
        if not desktop_available():
            return {"ok": False, "external": False, "error": "Arslan Hands is not available on this Mac."}
        started = time.monotonic()
        if not await _ask_once(f"takeover:{uuid.uuid4().hex}", "desktop_takeover", f"{minutes} min · {why}",
                               f"Arslan wants to take over the screen for about {minutes} minutes: {why}. Please "
                               "keep off the keyboard and mouse meanwhile — touching either pauses it at once, and "
                               "Esc stops it. Deleting, sending and the like still ask you each time."):
            _trace("takeover", "screen", "declined", started)
            return {"ok": False, "external": False, "code": "declined",
                    "error": "The user did not allow taking the screen over. Do not retry; work in the background "
                             "or report it."}
        try:
            reply = await hands_client.call("takeover_begin", {"minutes": minutes}, timeout=10)
        except hands_client.HandsUnavailable as exc:
            return {"ok": False, "external": False, "error": f"Arslan Hands is not available ({exc})."}
        result = hands_contract.parse(reply)
        if not result.ok:
            return _failed(result)
        _takeovers.add(job_id)
        _trace("takeover", "screen", "ok", started, minutes=minutes)
        return {"ok": True, "external": False, "outcome": "done",
                "text": f"The screen is yours for up to {minutes} minutes (the edge glows). Actions may now use the "
                        "front without waiting. If the user touches the keyboard or mouse it pauses and the next "
                        "action tells you what they chose. It ends when this work ends.",
                "summary": f"takeover · {minutes} min"}


# Hands v2 §5.7: in a chat reply (not background work) at most this many actions, all in one app.
INLINE_ACTIONS = 5
_inline: dict[tuple[str, str], tuple[int, str]] = {}      # (conversation, turn) → (actions, app)


def _inline_refusal(why: str) -> dict:
    return {"ok": False, "external": False, "code": "act_in_background",
            "error": f"{why} Call start_background_work with this goal; the work continues there."}


def _inline_turn() -> tuple[str, str] | None:
    from server.services import personal_context
    ctx = personal_context.current()
    if ctx is None or not ctx.conversation_id:
        return None
    return ctx.conversation_id, str(ctx.run_id or "")


class _DesktopAct:
    op = ""
    timeout_s = 2 * CARD_S + 2 * RUN_S    # the app card and a risky-action card; describe, act, Return

    def _risky(self, args: dict, target: dict, app: dict) -> str | None:
        """Why this action asks every time, or None."""
        from server.services import hands_service
        label = target.get("name") if isinstance(target, dict) else None
        if self.op in ("click", "select") and hands_service.risky_label(label):
            return f"“{label}”"
        return None

    async def execute(self, args: dict) -> dict:
        from server.services import hands_contract, hands_service
        args = dict(args or {})
        name = _app_arg(args)
        if name is None:
            return {"ok": False, "external": False, "error": "app required (a name from desktop_apps)"}
        conversation_id, job_id = _conversation_and_job()
        turn = _inline_turn() if job_id is None else None
        if job_id is None:
            if turn is None:
                return {"ok": False, "external": False, "code": "no_one_to_ask",
                        "error": "Acting in a Mac app needs a conversation to ask the user in."}
            if _inline.get(turn, (0, ""))[0] >= INLINE_ACTIONS:
                return _inline_refusal(f"This reply has already acted {INLINE_ACTIONS} times, the most a chat "
                                       "reply may.")
        if not desktop_available():
            return {"ok": False, "external": False, "error": "Arslan Hands is not available on this Mac."}
        if job_id is not None and hands_service.stopped(job_id):
            return {"ok": False, "external": False, "code": "stopped_by_user",
                    "error": hands_contract.REFUSALS["stopped_by_user"]}
        started = time.monotonic()
        target: dict = {}
        if self.op in ("press", "menu"):
            app, failure = await _resolve_app(name, job_id)
            if app is None:
                return _failed(failure, app=name)
            if app.get("tier") in _TIER_ALLOWS:
                return _failed(hands_contract.Result(ok=False, code=f"app_{app['tier']}", refused=True))
        else:
            ref = str(args.get("ref") or "")
            described = await _hands("describe", {"app": name, "ref": ref}, job_id=job_id)
            if not described.ok:
                _trace(self.op, name, described.code or "error", started)
                return _failed(described, app=name)
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
        if turn is not None:
            count, first = _inline.get(turn, (0, bundle))
            if first != bundle:
                return _inline_refusal("This reply already acted in another app; a chat reply acts in one app.")
            if len(_inline) > 500:
                _inline.clear()
            _inline[turn] = (count + 1, first)
        verb = _VERBS.get(self.op, self.op)
        if not await _ask_once(f"desktop:{bundle}", "desktop_app", str(app.get("name")),
                               f"Arslan wants to click, type and choose in {app.get('name')} for this piece of "
                               f"work. First: {verb} “{label or args.get('keys', '')}”."):
            _trace(self.op, app, "declined", started)
            return {"ok": False, "external": False, "code": "declined",
                    "error": f"The user did not allow acting in {app.get('name')}. Do not retry; report it."}
        why = self._risky(args, target, app)
        if why and not await _ask_once(f"risky:{uuid.uuid4().hex}", "desktop_risky",
                                       f"{app.get('name')} · {why}"[:300],
                                       f"Arslan wants to {_ASKS.get(self.op, self.op)} {why} in "
                                       f"{app.get('name')}. This may delete, send, pay or submit something."):
            _trace(self.op, app, "declined", started, target=label)
            return {"ok": False, "external": False, "code": "declined",
                    "error": f"The user did not allow {why}. Do not retry; report it."}
        session = hands_service.session_for(job_id)
        if session:
            shown = await _label_verb(self.op)
            await _hands("session_label", {"session": session, "label": f"Arslan · {shown} {label}"[:80]})
        result = await self.run(args, app)
        _trace(self.op, app, "ok" if result.ok else (result.code or "error"), started, target=label,
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
        return {"ok": outcome != "refused", "external": False, "outcome": outcome, "text": text,
                "summary": f"{self.op} · {app.get('name')} · {label}"[:200]}

    def trace_extra(self, args: dict) -> dict:
        return {}

    async def run(self, args: dict, app: dict):
        _, job_id = _conversation_and_job()
        return await _hands(self.op, {"app": app["name"], "ref": str(args.get("ref") or ""), **_front(args)},
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
            current = await _hands("get", {"app": app["name"], "ref": ref, "property": "value"}, job_id=job_id)
            if not (current.ok and isinstance(current.data, dict) and isinstance(current.data.get("value"), str)):
                return hands_contract.Result(ok=False, code="append_unreadable", refused=True)
            text = current.data["value"] + text
        result = await _hands("set_value", {"app": app["name"], "ref": ref, "value": text}, job_id=job_id)
        if not result.ok and result.code in ("ACTION_NOT_SUPPORTED", "POLICY_DENIED"):
            if append:
                # `type` inserts at the caret: old + new typed there would duplicate the old text.
                return hands_contract.Result(ok=False, code="append_needs_set_value", refused=True)
            result = await _hands("type", {"app": app["name"], "ref": ref, "text": text}, job_id=job_id)
        if result.ok and args.get("submit"):
            # P0 D3: Return goes to whatever has the app's focus. Press it only when that
            # is this field, read live just before.
            states = await _hands("get", {"app": app["name"], "ref": ref, "property": "states"}, job_id=job_id)
            value = states.data.get("value") if states.ok and isinstance(states.data, dict) else None
            if not (isinstance(value, list) and "focused" in value):
                return hands_contract.Result(ok=False, code="submit_unsure", refused=True)
            result = await _hands("press", {"app": app["name"], "keys": "return"}, job_id=job_id)
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
        return await _hands("select", {"app": app["name"], "ref": str(args.get("ref") or ""),
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
        return await _hands("scroll", {"app": app["name"], "ref": str(args.get("ref") or ""),
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
        return await _hands("menu", {"app": app["name"], "path": _menu_path(args)}, job_id=job_id)


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
        return await _hands("press", {"app": app["name"], "keys": str(args.get("keys") or "").strip().lower(),
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
            return {"ok": False, "external": False, "error": "app required (a name from desktop_apps)"}
        if not isinstance(steps, list) or not 1 <= len(steps) <= BATCH_MAX:
            return {"ok": False, "external": False, "code": "bad_request",
                    "error": f"steps: 1 to {BATCH_MAX} steps, each {{action, …that action's args}}"}
        lines: list[str] = []
        stopped = None
        done = 0
        for number, step in enumerate(steps, 1):
            action = str(step.get("action") or "") if isinstance(step, dict) else ""
            executor = _BATCH_STEPS.get(action)
            if executor is None:
                stopped = f"step {number}: unknown action “{action[:40]}” ({', '.join(_BATCH_STEPS)})"
                break
            call = {k: v for k, v in step.items() if k != "action"}
            call["app"] = name                      # one app per batch, whatever a step says
            result = await executor().execute(call)
            said = result.get("text") or result.get("error") or ""
            lines.append(f"{number}. {action}: {said}")
            if not result.get("ok") or result.get("outcome") not in _BATCH_GOES_ON:
                stopped = f"stopped at step {number} ({result.get('code') or result.get('outcome') or 'not done'})"
                break
            done += 1
        look = await DesktopLookExecutor().execute({"app": name})
        head = (f"Batch in {name}: {done} of {len(steps)} steps went through"
                + (f"; {stopped}" if stopped else "") + ".\n")
        out = {"ok": stopped is None, "external": True,
               "text": head + "\n".join(lines) + "\n\nThe window now:\n" + (look.get("text") or look.get("error") or ""),
               "summary": f"batch · {name} · {done}/{len(steps)}"[:200]}
        if stopped is not None:
            out["code"] = "batch_stopped"
        if look.get("images"):
            out["images"], out["image_label"] = look["images"], look.get("image_label")
        return out


class DesktopOpenExecutor:
    """Hands v2 §5.2: open an app in the background (`open -g`: launched behind the user's windows,
    never activated). The never-list is refused before anything starts; an app already running is
    left as it is; opening asks once, and that answer is also the app's acting grant."""
    key = "desktop_open"
    timeout_s = CARD_S + 30

    async def execute(self, args: dict) -> dict:
        from server.services import hands_contract, hands_service
        name = _app_arg(dict(args or {}))
        if name is None:
            return {"ok": False, "external": False, "error": "app required (the app's name, as in /Applications)"}
        conversation_id, job_id = _conversation_and_job()
        turn = _inline_turn() if job_id is None else None
        if job_id is None:
            if turn is None:
                return {"ok": False, "external": False, "code": "no_one_to_ask",
                        "error": "Opening a Mac app needs a conversation to ask the user in."}
            if _inline.get(turn, (0, ""))[0] >= INLINE_ACTIONS:
                return _inline_refusal(f"This reply has already acted {INLINE_ACTIONS} times, the most a chat "
                                       "reply may.")
        if not desktop_available():
            return {"ok": False, "external": False, "error": "Arslan Hands is not available on this Mac."}
        if hands_service.never_touched(name):
            return _failed(hands_contract.Result(ok=False, code="app_denied", refused=True), app=name)
        running, _ = await _resolve_app(name, job_id)
        if running is not None:
            return {"ok": True, "external": False, "outcome": "no_effect",
                    "text": f"{running['name']} is already running; nothing was opened. Look at it with desktop_look."}
        started = time.monotonic()
        if not await _ask_once(f"open:{name.lower()}", "desktop_app", name,
                               f"Arslan wants to open {name} in the background (behind your windows) for this "
                               "piece of work, and then click, type and choose in it."):
            _trace("open", name, "declined", started)
            return {"ok": False, "external": False, "code": "declined",
                    "error": f"The user did not allow opening {name}. Do not retry; report it."}
        if turn is not None:
            _inline[turn] = (_inline.get(turn, (0, name))[0] + 1, _inline.get(turn, (0, name))[1])
        process = await asyncio.create_subprocess_exec(
            "/usr/bin/open", "-g", "-a", name, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        if await process.wait() != 0:
            _trace("open", name, "not_found", started)
            return {"ok": False, "external": False, "code": "app_not_found",
                    "error": f"macOS has no app called “{name}”. Check the name (desktop_apps lists running apps)."}
        app = None
        for _ in range(40):                       # up to ten seconds for it to start
            app, failure = await _resolve_app(name, job_id)
            if app is not None or (failure is not None and failure.code == "app_denied"):
                break
            await asyncio.sleep(0.25)
        if app is None:
            _trace("open", name, "not_listed", started)
            return {"ok": True, "external": False, "outcome": "sent_unconfirmed",
                    "text": f"Asked macOS to open {name}; it is not running yet. Look again in a moment."}
        _grants.setdefault(job_id or f"conversation:{conversation_id}", set()).add(
            f"desktop:{app.get('bundle_id') or app.get('name')}")
        _trace("open", app, "ok", started)
        return {"ok": True, "external": False, "outcome": "done",
                "text": f"Opened {app['name']} in the background. Look at it with desktop_look before acting.",
                "summary": f"open · {app['name']}"[:200]}
