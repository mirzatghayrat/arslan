"""Reading what Arslan Hands returns (0.1.53): the backend half of the contract.

The fixtures in tests/fixtures/hands_contract/ hold real agent-desktop 0.9.4
envelopes for the twelve commands Arslan uses and the error codes it handles;
the tests check this module against every one of them. Whatever binary sits
behind Hands — upstream's, our fork's, a trimmed rewrite — must produce
envelopes this reads the same way (scripts/hands_contract_check.py).

Two kinds of "no": Hands' own refusals (its never-list, a ref from another app,
a password field, Stop) and agent-desktop's error codes. Both become a code, a
message for the model, and a hint naming the way forward.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# agent-desktop error code → what to do next (the model reads the message).
HINTS = {
    "STALE_REF": "look_again", "SNAPSHOT_NOT_FOUND": "look_again", "TIMEOUT": "look_again",
    "AMBIGUOUS_TARGET": "look_closer", "ELEMENT_NOT_FOUND": "look_again",
    "APP_NOT_FOUND": "open_app", "WINDOW_NOT_FOUND": "open_app",
    "PERM_DENIED": "allow_hands", "POLICY_DENIED": "use_set_value",
    "ACTION_NOT_SUPPORTED": "other_way", "ACTION_FAILED": "other_way", "APP_UNRESPONSIVE": "look_again",
}

MESSAGES = {
    "look_again": "The window changed or the element is gone. Look again with desktop_look, then retry once "
                  "with a ref from that new look.",
    "look_closer": "More than one element matches. Look again (drill into the right group with `ref`) and use "
                   "a more specific ref.",
    "open_app": "That app (or a window of it) is not open on the current screen. Open it first — e.g. "
                "run_command `open -a \"<App>\"` — or ask the user to bring it up; Hands never launches apps.",
    # Measured 2026-10-05: with a stale grant (a development build of the same bundle id) the switch shows
    # on, macOS shows no prompt, and the model fell back to AppleScript — one approval card per script.
    "allow_hands": "Arslan Hands does not have Accessibility permission: macOS refused it, even if its switch "
                   "looks on. Stop this part of the task: do not do it with AppleScript, osascript or the "
                   "terminal instead (every script would ask the user again). Tell the user exactly this: open "
                   "System Settings → Privacy & Security → Accessibility; if “Arslan Hands” is listed, remove "
                   "it with “−”; then in Arslan open Settings → Arslan Hands, click “Ask macOS” and turn "
                   "Arslan Hands on. Then try again.",
    "use_set_value": "This field cannot take typed text without taking focus, which Arslan never does.",
    "other_way": "That element cannot do this. Look for another way (a menu item, a different button).",
}

REFUSALS = {
    "app_denied": "Arslan never touches this app (it is on the never-list: passwords, system settings, "
                  "security prompts, Arslan itself). Do not retry; tell the user what you needed.",
    "app_look_only": "This is a web browser: Hands may read it but not act in it. Act on web pages with "
                     "browser_open / browser_click instead.",
    "app_click_only": "This app runs commands (a terminal or code editor): Hands may click and scroll there but "
                      "never type or press keys — that would bypass the command sandbox. Use run_command.",
    "ref_wrong_app": "That ref was read from a different app. Look at this app with desktop_look and use a ref "
                     "from that look.",
    "ref_unknown": "That ref is not from a look in this piece of work. Look again with desktop_look and use a "
                   "ref from that result.",
    "bad_ref": "Refs look like @s1a2b3c4:e7 and come from desktop_look. Look first.",
    "password_field": "Arslan never types into password fields. Ask the user to fill it in themselves.",
    "target_unreadable": "Could not read the field before typing. Look again and retry once.",
    "stopped_by_user": "The user stopped Arslan's hands. Do not retry; finish and report what was done.",
    "app_not_running": "That app is not running. Open it first — e.g. run_command `open -a \"<App>\"` — or ask "
                       "the user; Hands never launches apps.",
    "app_ambiguous": "More than one running app has that name; use its bundle id (from desktop_apps).",
    "TIMEOUT": "It took too long. Look again.",
    # P0 (spec 2026-10-08-0157 §1)
    "unknown": "The reply from Arslan Hands was lost, so this may or may not have happened. Look again with "
               "desktop_look before doing anything else; do not simply repeat it.",
    "append_unreadable": "Could not read what the field holds now, so adding to it could erase it. Look again "
                         "and retry once, or ask the user.",
    "append_needs_set_value": "This field does not take its whole text at once, so Arslan cannot add to the end "
                              "without risking a duplicate. Tell the user what you wanted to add.",
    "submit_unsure": "The text is in the field, but Return was NOT pressed: the field does not have the focus, "
                     "so Return could have gone somewhere else. Click the form's own button (send, OK, search) "
                     "with desktop_click instead.",
    "op_not_allowed": "Hands does not do that.",
}


@dataclass
class Result:
    ok: bool
    command: str = ""
    data: object = None
    code: str | None = None
    message: str = ""
    hint: str | None = None
    refused: bool = False                  # Hands said no (vs. agent-desktop reporting an error)
    reply: dict = field(default_factory=dict)

    def advice(self) -> str:
        """What the model should be told, in one paragraph."""
        if self.ok:
            return ""
        if self.refused:
            return REFUSALS.get(self.code or "", self.message or "Arslan Hands refused.")
        base = MESSAGES.get(self.hint or "", "")
        return f"{self.code}: {self.message}. {base}".strip()


def parse(reply: dict) -> Result:
    """One Hands reply → Result."""
    if not isinstance(reply, dict):
        return Result(ok=False, code="bad_reply", message="not a reply", refused=True)
    if reply.get("ok") is not True:
        refused = reply.get("refused") or {}
        return Result(ok=False, code=str(refused.get("code") or "refused"), message=str(refused.get("message") or ""),
                      refused=True, reply=reply)
    envelope = reply.get("envelope")
    if envelope is None:                  # Hands' own answer (status, list_apps, describe, sessions)
        return Result(ok=True, data=reply, reply=reply)
    return parse_envelope(envelope, reply)


def parse_envelope(envelope: dict, reply: dict | None = None) -> Result:
    if not isinstance(envelope, dict) or not isinstance(envelope.get("ok"), bool):
        return Result(ok=False, code="bad_output", message="not an agent-desktop envelope", refused=True)
    command = str(envelope.get("command") or "")
    if envelope["ok"]:
        return Result(ok=True, command=command, data=envelope.get("data"), reply=reply or {})
    error = envelope.get("error") or {}
    code = str(error.get("code") or "INTERNAL")
    return Result(ok=False, command=command, code=code, message=str(error.get("message") or ""),
                  hint=HINTS.get(code), reply=reply or {})


OUTCOMES = ("done", "sent_unconfirmed", "no_effect", "partly_done", "refused")


def outcome(result: Result) -> str:
    """What an action that succeeded really achieved, in one vocabulary for both engines
    (spec 2026-10-08-0157 §5.3). Hands says it (`outcome` in its reply); a Hands too old
    to say it is read the P0 way: agent-desktop's `delivered_verified` is done, anything
    else was sent without proof and the model must look before building on it. A word
    this backend does not know is never taken for done."""
    said = (result.reply or {}).get("outcome")
    if isinstance(said, str):
        return said if said in OUTCOMES else "sent_unconfirmed"
    data = result.data if isinstance(result.data, dict) else {}
    delivery = (data.get("disposition") or {}).get("delivery")
    return "done" if delivery == "delivered_verified" else "sent_unconfirmed"


def kept_the_front(result: Result) -> bool:
    """The app acted on came to the front and Hands could not give it back."""
    reply = result.reply or {}
    front = reply.get("front") or {}
    pid = (reply.get("app") or {}).get("pid")
    return (reply.get("focus_restored") is False and pid is not None and front.get("after") == pid
            and front.get("before") != pid)


# ── showing a tree to the model ──────────────────────────────────────────────

def placer(capture: dict):
    """Element frame (screen points) → its centre in the screenshot's pixels, or None when it
    is not inside the image. `capture` is Hands' capture_window answer: `frame` in points,
    `scale` pixels per point, `width`/`height` in pixels."""
    frame = capture.get("frame") or {}
    try:
        x0, y0, scale = float(frame["x"]), float(frame["y"]), float(capture["scale"])
        width, height = int(capture["width"]), int(capture["height"])
    except (KeyError, TypeError, ValueError):
        return None

    def place(bounds) -> tuple[int, int] | None:
        try:
            x = (float(bounds["x"]) + float(bounds["width"]) / 2 - x0) * scale
            y = (float(bounds["y"]) + float(bounds["height"]) / 2 - y0) * scale
        except (KeyError, TypeError, ValueError):
            return None
        return (round(x), round(y)) if 0 <= x < width and 0 <= y < height else None
    return place


def _node_line(node: dict, place=None) -> str:
    role = str(node.get("role") or "?")
    parts = [role]
    name = node.get("name")
    if name:
        parts.append(f"“{str(name)[:120]}”")
    states = [str(s) for s in node.get("states") or []]      # "focused" included: it says where typing goes
    if node.get("value") not in (None, "") and "secure" not in states:
        value = str(node["value"]).replace("\n", "⏎")
        parts.append(f"= {value[:200]}{'…' if len(value) > 200 else ''}")
    if states:
        parts.append("(" + ", ".join(str(s) for s in states[:6]) + ")")
    if node.get("ref_id"):
        parts.append(f"[{node['ref_id']}]")
    spot = place(node["bounds"]) if place and isinstance(node.get("bounds"), dict) else None
    if spot:
        parts.append(f"({spot[0]}, {spot[1]})")
    if node.get("children_count") and not node.get("children"):
        parts.append(f"… {node['children_count']} inside: look with ref to open")
    return " ".join(parts)


LONG_RUN = 15
SHOW_OF_RUN = 10


def render_tree(tree: dict, limit: int = 12_000, place=None) -> str:
    """An indented outline: role “name” = value (states) [ref] (x, y). Truncated with a
    note when long, so the model drills in with `ref` instead. (x, y), with a `placer`, is
    the element's centre in the window's screenshot, in its pixels."""
    lines: list[str] = []
    size = 0

    def walk(node: dict, depth: int) -> bool:
        nonlocal size
        line = "  " * depth + _node_line(node, place)
        if size + len(line) > limit:
            lines.append("  " * depth + "… (more not shown: look again with a ref to open a part)")
            return False
        lines.append(line)
        size += len(line) + 1
        children = [c for c in node.get("children") or [] if isinstance(c, dict)]
        roles = [c.get("role") for c in children]
        for i, child in enumerate(children):
            # A long run of one kind (Notes' list: 100+ rows) would eat the whole
            # outline before the editor and toolbar; show the first few.
            if roles.count(child.get("role")) > LONG_RUN and roles[:i].count(child.get("role")) >= SHOW_OF_RUN:
                if roles[:i].count(child.get("role")) == SHOW_OF_RUN:
                    more = roles.count(child.get("role")) - SHOW_OF_RUN
                    where = f" [{node['ref_id']}]" if node.get("ref_id") else ""
                    lines.append("  " * (depth + 1) + f"… {more} more {child.get('role')} (look with ref{where} to see them)")
                continue
            if not walk(child, depth + 1):
                return False
        return True

    if isinstance(tree, dict):
        walk(tree, 0)
    return "\n".join(lines)


def render_matches(data: dict, limit: int = 30) -> str:
    matches = (data or {}).get("matches") or []
    if not matches:
        return "No matching elements."
    lines = [_node_line(m) for m in matches[:limit] if isinstance(m, dict)]
    total = (data or {}).get("total_matches")
    if isinstance(total, int) and total > len(lines):
        lines.append(f"… {total - len(lines)} more")
    return "\n".join(lines)
