"""0.1.45 hands: Arslan's browser and Mac automation.

Looking (open a page, read it, go back, list Shortcuts) is free. Acting (click,
type, choose, press; run a Shortcut or an AppleScript) happens only inside a
background job, and asks first through that job's confirmation cards
(approvals.ask): once per website per job for the browser, once per Shortcut
per job, and every time for an AppleScript (shown in full). macOS adds its own
Automation consent the first time a script controls an app.

Arslan never types into a password field: the user logs in themselves in the
visible browser window, and that profile keeps the session.
"""
from __future__ import annotations

import asyncio
import re
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


def _origin(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.hostname}" if parts.hostname else None


# ── browser ──────────────────────────────────────────────────────────────────

class _BrowserTool:
    action = ""
    acts = False

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
            text = await agent_browser.run(self.action, args)
        except agent_browser.BrowserUnavailable as exc:
            return {"ok": False, "external": False, "code": "browser_unavailable",
                    "error": f"The Arslan browser is not ready ({exc}). The user can set it up in Settings → Advanced."}
        except ValueError as exc:
            return {"ok": False, "external": False, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "external": False, "error": f"browser: {str(exc)[:400]}"}
        # Page content is untrusted external text: framed as such by the tool loop.
        return {"ok": True, "external": True, "text": text,
                "summary": f"{self.action} · {agent_browser.current_url() or ''}"[:200]}


class BrowserOpenExecutor(_BrowserTool):
    key, action = "browser_open", "open"


class BrowserLookExecutor(_BrowserTool):
    key, action = "browser_look", "look"


class BrowserBackExecutor(_BrowserTool):
    key, action = "browser_back", "back"


class BrowserClickExecutor(_BrowserTool):
    key, action, acts = "browser_click", "click", True


class BrowserTypeExecutor(_BrowserTool):
    key, action, acts = "browser_type", "type", True


class BrowserSelectExecutor(_BrowserTool):
    key, action, acts = "browser_select", "select", True


class BrowserPressExecutor(_BrowserTool):
    key, action, acts = "browser_press", "press", True


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

    async def execute(self, args: dict) -> dict:
        return await _run(["/usr/bin/shortcuts", "list"], timeout=30)


class MacRunShortcutExecutor:
    key = "mac_run_shortcut"

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

    async def execute(self, args: dict) -> dict:
        script = str((args or {}).get("script") or "")
        if not script.strip() or len(script) > 4000:
            return {"ok": False, "external": False, "error": "script required (max 4000 characters)"}
        if _conversation_and_job()[1] is None:
            return _not_in_job()
        if not await _ask_once(f"script:{uuid.uuid4().hex}", "mac_script", "AppleScript", script):
            return {"ok": False, "external": False, "code": "declined", "error": "The user did not allow it."}
        return await _run(["/usr/bin/osascript", "-e", script])
