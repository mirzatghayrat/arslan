"""Builders for WebSocket JSON messages (single source of truth for the wire format)."""
from __future__ import annotations

from typing import Any


def stream_start(message_id: int, run_id: int | None = None) -> dict[str, Any]:
    # run_id (S3-M1): only on recorded runs — the cancel target for POST /runs/{id}/cancel.
    # Key omitted when unset so unrecorded streams stay byte-identical.
    frame: dict[str, Any] = {"type": "stream_start", "message_id": message_id}
    if run_id is not None:
        frame["run_id"] = run_id
    return frame


def stream_chunk(content: str) -> dict[str, Any]:
    return {"type": "stream_chunk", "content": content}


def stream_end(message_id: int) -> dict[str, Any]:
    return {"type": "stream_end", "message_id": message_id}


def message(message_id: int, content: str, role: str = "assistant") -> dict[str, Any]:
    return {"type": "message", "message_id": message_id, "content": content, "role": role}


def error(code: str, msg: str, recoverable: bool = False) -> dict[str, Any]:
    return {"type": "error", "code": code, "message": msg, "recoverable": recoverable}


def ping(ts: int) -> dict[str, Any]:
    return {"type": "ping", "ts": ts}


def run_in_progress(run_id: int) -> dict[str, Any]:
    """S3-M2 reattach: announces an in-flight run to a (re)connecting socket.
    The frames that follow are that run's journal REPLAY, after which the live
    stream continues on the same socket — the client flips straight back into
    streaming state with run_id as its cancel handle."""
    return {"type": "run_in_progress", "run_id": run_id}


def stream_start_src(source: str, spawn_id: int | None = None,
                     run_id: int | None = None) -> dict[str, Any]:
    # run_id (S3-M1): only on recorded runs — the cancel target for POST /runs/{id}/cancel.
    # Key omitted when unset so unrecorded streams stay byte-identical.
    frame: dict[str, Any] = {"type": "stream_start", "source": source, "spawn_id": spawn_id}
    if run_id is not None:
        frame["run_id"] = run_id
    return frame


def fact_saved(content: str, sensitive: bool, entry_id: str | None = None,
               version: int | None = None, reply_message_id: int | None = None) -> dict[str, Any]:
    """D1 (0.1.55): carries the entry id and version, so the chat's quiet line can
    Undo exactly that entry (DELETE at the version it was created with). K2b: and the reply
    its turn ended with, so the window puts the line under it even once the next message is
    in (facts are looked for after the turn). The window's frame only: the phone never gets it."""
    frame: dict[str, Any] = {"type": "fact_saved", "content": content, "sensitive": sensitive}
    if entry_id:
        frame["entry_id"] = entry_id
    if version is not None:
        frame["version"] = version
    if reply_message_id is not None:
        frame["reply_message_id"] = reply_message_id
    return frame


def tool_call(tool: str, args_summary: str) -> dict[str, Any]:
    return {"type": "tool_call", "tool": tool, "args_summary": args_summary}


def tool_result(tool: str, ok: bool, summary: str, artifact: dict | None = None,
                artifacts: list[dict] | None = None) -> dict[str, Any]:
    frame: dict[str, Any] = {"type": "tool_result", "tool": tool, "ok": ok, "summary": summary}
    if artifact is not None:
        frame["artifact"] = artifact
    if artifacts:
        frame["artifacts"] = artifacts
    return frame


def propose_run_command(call_id: str, command: str, argv: list[str], reason: str = "",
                        remote_host: str | None = None,
                        fingerprints: list[str] | None = None,
                        rule: str | None = None,
                        sandbox: str | None = None, why: str = "",
                        network: bool = False) -> dict[str, Any]:
    """Arslan proposes running ONE command. Emitting this frame runs NOTHING — the
    frontend renders a confirm card showing the full command; only the user's
    `confirm_run_command {call_id}` lets it execute (or `cancel_run_command`).

    `reason` says why it asks (0.1.48: the terminal rule, e.g. "sends email"); `rule`
    is what "don't ask again" would remember, so the card can name it.
    `remote_host` non-empty means the command runs on ANOTHER machine (P3b), and the
    card must say so. `fingerprints` are that machine's host keys.
    `sandbox` (0.1.51 P3) is "outside" (the model asks to leave the workspace sandbox,
    `why` is its reason) or "retry" (the sandbox stopped it; running again starts over).
    `network` (S2a-2): this turn read outside content and the command would use the network, so the
    card asks for that too, this time (one card, not two); the reason says so, and the island never
    answers it (an extra key the web and the phone ignore)."""
    if network:
        reason = f"{reason}; uses the network" if reason else "uses the network"
    frame = {"type": "propose_run_command", "call_id": call_id, "command": command,
             "argv": argv, "pretty": " ".join([command, *argv]), "reason": reason}
    if network:
        frame["network"] = True
    if sandbox in ("outside", "retry"):
        frame["sandbox"] = sandbox
        if why:
            frame["why"] = why[:300]
    if rule:
        frame["rule"] = rule
    if remote_host:
        frame["remote_host"] = remote_host
        frame["fingerprints"] = list(fingerprints or [])
    return frame


#: The most of a card's `detail` a propose_action frame carries. S1: an MCP call whose arguments are
#: longer is refused rather than carded, since a cut card would hide what the yes covers.
DETAIL_MAX = 4000


def propose_action(call_id: str, kind: str, target: str, detail: str) -> dict[str, Any]:
    """0.1.45: a background job asks before it acts — kind is browser_site (first
    click/typing on a website), mac_shortcut (run a Shortcut) or mac_script (run an
    AppleScript, shown in full). Answered by confirm_action / cancel_action."""
    return {"type": "propose_action", "call_id": call_id, "kind": kind, "target": target[:300],
            "detail": detail[:DETAIL_MAX]}


def card_resolved(call_id: str, outcome: str, by: str | None = None) -> dict[str, Any]:
    """A card shown in more than one place was decided — every window and the
    phone close their copy. outcome: approved / declined / expired (timed out,
    or the turn that asked ended); by: "phone" or "mac" when someone answered."""
    frame: dict[str, Any] = {"type": "card_resolved", "call_id": call_id, "outcome": outcome}
    if by:
        frame["by"] = by
    return frame


def propose_schedule(call_id: str, name: str, when: str, prompt: str = "") -> dict[str, Any]:
    """Arslan asks to create a recurring task — once per session (裁决①).
    Emitting this schedules NOTHING; only `confirm_schedule {call_id}` does.
    The card shows the CADENCE, because that is what the cost depends on, and (S1, U14 d) the text the
    task runs each time. The phone's Bridge reads `name` and `when` only (FrameMapper, pinned by ①iOS's
    test in #319); the tool loop refuses a prompt longer than DETAIL_MAX rather than cut it here."""
    frame = {"type": "propose_schedule", "call_id": call_id, "name": name, "when": when}
    if prompt:
        frame["prompt"] = prompt[:DETAIL_MAX]
    return frame


def propose_capability(call_id: str, card: dict) -> dict[str, Any]:
    """0.1.57 §3.1: Arslan wants to add a capability to retry a step. Emitting this installs
    NOTHING; only `confirm_capability {call_id, keys?, folders?}` from THIS window does (the
    Inbox, the phone and the island cannot approve it: the card may carry a key). `card` is
    built by the server from the search result, never from the model's words."""
    return {"type": "propose_capability", "call_id": call_id, **card}


def capability_result(call_id: str, source_id: str | None, state: str, **detail: Any) -> dict[str, Any]:
    """How the install the user approved ended: on (tested), failed (where), blocked (scan)."""
    return {"type": "capability_result", "call_id": call_id, "source_id": source_id, "state": state, **detail}


def propose_workspace_write(call_id: str, workspace: str, action: str, path: str) -> dict[str, Any]:
    """Arslan asks for write access to the workspace — ONCE per session, not per
    file. Emitting this frame writes NOTHING; only the user's
    `confirm_workspace_write {call_id}` grants it (or `cancel_workspace_write`).
    The card names the directory, because that — not this one filename — is what
    is being agreed to."""
    return {"type": "propose_workspace_write", "call_id": call_id,
            "workspace": workspace, "action": action, "path": path}


def propose_enroll_node(*, call_id: str, name: str, host: str, user: str,
                        fingerprints: list[str]) -> dict[str, Any]:
    """Arslan proposes enrolling a machine (P3c). Emitting this enrolls NOTHING.

    The card is where the person acts, and the write goes over REST from their click. Enrolment is
    the highest-consequence thing in this feature, so it must never be reachable
    as a side effect of Arslan having looked at a machine.

    The fingerprint is on the card because that is the one thing only the user
    can check — against the machine itself, not against anything we can show
    them a second time."""
    return {"type": "propose_enroll_node", "call_id": call_id, "name": name,
            "host": host, "user": user, "fingerprints": list(fingerprints)}


def clarify_options(question: str, options: list[dict[str, Any]]) -> dict[str, Any]:
    """Arslan needs the user to pick a direction (PA-3): a structured choice card.

    `options` is 2-4 items of {label, hint} (already validated/clamped by the tool
    loop). The frontend renders one-click buttons; a click sends the chosen label back
    as a normal `user_message` — emitting this frame runs NOTHING by itself."""
    return {
        "type": "clarify_options",
        "question": question,
        "options": [{"label": str(o.get("label", "")), "hint": str(o.get("hint") or "")}
                    for o in options],
    }
