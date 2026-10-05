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
    """True if already granted for this job, else ask the user (card + notification)."""
    from server.services import approvals
    from server.ws import protocol
    conversation_id, job_id = _conversation_and_job()
    if conversation_id is None or job_id is None:
        return False
    granted = _grants.setdefault(job_id, set())
    if grant in granted:
        return True
    ok = await approvals.ask(conversation_id, protocol.propose_action(uuid.uuid4().hex, kind, target, detail))
    if ok:                                     # a script's grant key is unique: asked every time
        granted.add(grant)
    return ok


def forget_job(job_id: str) -> None:
    _grants.pop(job_id, None)
    from server.services import hands_service
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
          "scroll": "scrolling", "press": "pressing"}
_ASKS = {"click": "click", "set_value": "type into", "select": "choose", "scroll": "scroll", "press": "press"}
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
        from server.services import approvals, hands_contract, hands_service
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
            result = await _look_one_window("snapshot", snap, job_id)
            if not result.ok:
                _trace("look", app, result.code or "error", started)
                return _failed(result, app=app["name"])
            data = result.data if isinstance(result.data, dict) else {}
            window = (data.get("window") or {}).get("title") or ""
            text = (f"{app['name']} — window “{window}”. Refs [@…] work for actions in this piece of work; "
                    "an entry with “… inside” opens with desktop_look {app, ref}.\n"
                    + hands_contract.render_tree(data.get("tree") or {}))
        _trace("look", app, "ok", started)
        # Window contents are other people's text: framed as untrusted by the tool loop.
        return {"ok": True, "external": True, "text": text, "summary": f"look · {app['name']}"[:200]}


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
        if job_id is None:
            return {"ok": False, "external": False, "code": "act_in_background",
                    "error": "Acting in Mac apps (clicking, typing, choosing, pressing keys) runs as background "
                             "work. Call start_background_work with this goal; looking is fine here."}
        if not desktop_available():
            return {"ok": False, "external": False, "error": "Arslan Hands is not available on this Mac."}
        if hands_service.stopped(job_id):
            return {"ok": False, "external": False, "code": "stopped_by_user",
                    "error": hands_contract.REFUSALS["stopped_by_user"]}
        started = time.monotonic()
        target: dict = {}
        if self.op == "press":
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
            await _hands("session_label", {"session": session, "label": f"Arslan · {verb} {label}"[:80]})
        result = await self.run(args, app)
        _trace(self.op, app, "ok" if result.ok else (result.code or "error"), started, target=label,
               **self.trace_extra(args))
        if not result.ok:
            return _failed(result, app=str(app.get("name")))
        return {"ok": True, "external": False, "text": f"Done: {verb} “{label}” in {app.get('name')}. "
                "Look again (desktop_look) to see the result before the next step.",
                "summary": f"{self.op} · {app.get('name')} · {label}"[:200]}

    def trace_extra(self, args: dict) -> dict:
        return {}

    async def run(self, args: dict, app: dict):
        _, job_id = _conversation_and_job()
        return await _hands(self.op, {"app": app["name"], "ref": str(args.get("ref") or "")}, job_id=job_id)


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
        if args.get("mode") == "append":
            current = await _hands("get", {"app": app["name"], "ref": ref, "property": "value"}, job_id=job_id)
            if current.ok and isinstance(current.data, dict) and isinstance(current.data.get("value"), str):
                text = current.data["value"] + text
        result = await _hands("set_value", {"app": app["name"], "ref": ref, "value": text}, job_id=job_id)
        if not result.ok and result.code in ("ACTION_NOT_SUPPORTED", "POLICY_DENIED"):
            result = await _hands("type", {"app": app["name"], "ref": ref, "text": text}, job_id=job_id)
        if result.ok and args.get("submit"):
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
                                       "value": str(args.get("value") or "")[:200]}, job_id=job_id)


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
        return await _hands("press", {"app": app["name"], "keys": str(args.get("keys") or "").strip().lower()},
                            job_id=job_id)
