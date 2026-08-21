"""Builders for WebSocket JSON messages (single source of truth for the wire format)."""
from __future__ import annotations

from typing import Any


def question(
    node_id: str,
    text: str,
    options: list[str] | None,
    multi_select: bool,
    hint: str,
) -> dict[str, Any]:
    return {
        "type": "question",
        "node_id": node_id,
        "text": text,
        "options": options,
        "multi_select": multi_select,
        "hint": hint,
    }


def progress(step: int, total: int, node_id: str) -> dict[str, Any]:
    return {"type": "progress", "step": step, "total": total, "node_id": node_id}


def build_complete(spawn_id: int, spawn_name: str) -> dict[str, Any]:
    return {"type": "build_complete", "spawn_id": spawn_id, "spawn_name": spawn_name}


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


def routing(
    spawn_id: int, spawn_name: str | None = None, announcement: str | None = None
) -> dict[str, Any]:
    """The dispatch handoff frame. `announcement` (optional) is the routing brief —
    need restatement + @-mention duty lines — included only when non-empty so the
    frame stays byte-identical for plain routings."""
    frame: dict[str, Any] = {"type": "routing", "spawn_id": spawn_id, "spawn_name": spawn_name}
    if announcement:
        frame["announcement"] = announcement
    return frame


def stream_start_src(source: str, spawn_id: int | None = None,
                     run_id: int | None = None) -> dict[str, Any]:
    # run_id (S3-M1): only on recorded runs — the cancel target for POST /runs/{id}/cancel.
    # Key omitted when unset so unrecorded streams stay byte-identical.
    frame: dict[str, Any] = {"type": "stream_start", "source": source, "spawn_id": spawn_id}
    if run_id is not None:
        frame["run_id"] = run_id
    return frame


def suggest_create(
    draft: dict[str, Any],
    task_brief: str | None = None,
    overlaps: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {"type": "suggest_create", "draft": draft, "task_brief": task_brief, "overlaps": overlaps}


def spawn_meta(
    *, arslan_message_id: int, spawn_id: int, assistant_message_id: int, task_brief: str
) -> dict[str, Any]:
    return {
        "type": "spawn_meta",
        "arslan_message_id": arslan_message_id,
        "spawn_id": spawn_id,
        "assistant_message_id": assistant_message_id,
        "task_brief": task_brief,
    }


def fact_saved(content: str, sensitive: bool) -> dict[str, Any]:
    return {"type": "fact_saved", "content": content, "sensitive": sensitive}


def spawn_created(
    spawn_id: int,
    spawn_name: str,
    equipment: dict[str, Any] | None = None,
    intro: str | None = None,
    capability_warnings: list[str] | None = None,
) -> dict[str, Any]:
    # capability_warnings (HX-6/P2): advisory persona-vs-equipment delivery lint —
    # non-empty when the persona promises a format the spawn's tools/system channels
    # cannot actually deliver. Never blocks creation.
    return {
        "type": "spawn_created",
        "spawn_id": spawn_id,
        "spawn_name": spawn_name,
        "equipment": equipment or {"toolsets": [], "skills": []},
        "intro": intro,
        "capability_warnings": capability_warnings or [],
    }


def tool_call(tool: str, args_summary: str) -> dict[str, Any]:
    return {"type": "tool_call", "tool": tool, "args_summary": args_summary}


def tool_result(tool: str, ok: bool, summary: str, artifact: dict | None = None) -> dict[str, Any]:
    frame: dict[str, Any] = {"type": "tool_result", "tool": tool, "ok": ok, "summary": summary}
    if artifact is not None:
        frame["artifact"] = artifact
    return frame


def escalation(spawn_id: int, spawn_name: str | None, kind: str, need: str) -> dict[str, Any]:
    return {"type": "escalation", "spawn_id": spawn_id, "spawn_name": spawn_name,
            "kind": kind, "need": need}


def escalation_refused(spawn_id: int, why: str) -> dict[str, Any]:
    return {"type": "escalation_refused", "spawn_id": spawn_id, "why": why}


def escalation_resolved(spawn_id: int, how: str, detail: str = "") -> dict[str, Any]:
    return {"type": "escalation_resolved", "spawn_id": spawn_id, "how": how, "detail": detail}


def orchestrator_action(tool: str, reason: str) -> dict[str, Any]:
    return {"type": "orchestrator_action", "tool": tool, "reason": reason}


def proposal(spawn_id: int, spawn_name: str | None) -> dict[str, Any]:
    return {"type": "proposal", "spawn_id": spawn_id, "spawn_name": spawn_name}


def roster_update(members: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "roster_update", "members": members}


def attachment_stored(spawn_name: str | None, chunks: int) -> dict[str, Any]:
    return {"type": "attachment_stored", "spawn_name": spawn_name, "chunks": chunks}


def propose_invite(spawn_id: int, reason: str) -> dict[str, Any]:
    """Arslan proposes bringing an existing spawn into the conversation.

    The frontend renders a confirmation card; on confirm it sends the existing
    `roster_invite {spawn_id, origin: "invite_card"}` frame which joins exactly that
    one spawn. The `origin` is load-bearing: it marks a CARD accept (which promised a
    consequence) so the handler can answer with an honest `joined_no_pending` notice
    when the parked task is gone, instead of joining silently. Build it via
    web/src/lib/rosterInvite.ts, never inline. Emitting this frame does NOT join the
    roster — the join awaits the user's confirmation.
    """
    return {"type": "propose_invite", "spawn_id": spawn_id, "reason": reason}


def suggest_update(spawn_id: int, spawn_name: str, current: dict[str, Any],
                   changes: dict[str, Any], reason: str = "",
                   capability_warnings: list[str] | None = None) -> dict[str, Any]:
    """Arslan proposes CHANGES to an existing spawn (persona/tone/capabilities/equipment).

    Like suggest_create, emitting this frame changes NOTHING — the frontend renders a
    confirm card showing before→after; only the user's `confirm_update` applies it.
    capability_warnings (HX-6/P2): advisory delivery lint on the PROPOSED persona vs
    the resulting equipment, so the confirm card can surface the mismatch pre-apply."""
    return {"type": "suggest_update", "spawn_id": spawn_id, "spawn_name": spawn_name,
            "current": current, "changes": changes, "reason": reason,
            "capability_warnings": capability_warnings or []}


def spawn_updated(spawn_id: int, spawn_name: str, applied: dict[str, Any],
                  equipment: dict[str, Any] | None = None) -> dict[str, Any]:
    """Ack after a confirmed update was applied: what changed + the fresh equipment."""
    return {"type": "spawn_updated", "spawn_id": spawn_id, "spawn_name": spawn_name,
            "applied": applied, "equipment": equipment or {"toolsets": [], "skills": []}}


def propose_staffing(candidates: list[dict], create_draft: dict) -> dict[str, Any]:
    """Arslan offers a staffing choice: pick one of the comparable existing spawns
    (each {spawn_id, name, score, why}) OR create a fresh one from `create_draft`.

    Like `propose_invite`, emitting this frame joins NOTHING and creates NOTHING —
    the frontend renders a picker card; the user's choice drives a `roster_invite`
    (pick, sent with `origin: "invite_card"` — see propose_invite) or a
    `confirm_create` (create) on the existing single, idempotent paths.
    """
    return {"type": "propose_staffing", "candidates": candidates, "create_draft": create_draft}


def propose_run_command(call_id: str, command: str, argv: list[str], reason: str = "",
                        remote_host: str | None = None,
                        fingerprints: list[str] | None = None) -> dict[str, Any]:
    """Arslan proposes running ONE whitelisted command. Emitting this frame runs
    NOTHING — the frontend renders a confirm card showing the full command; only the
    user's `confirm_run_command {call_id}` lets it execute (or `cancel_run_command`).

    `remote_host` non-empty means the command runs on ANOTHER machine (P3b), and the
    card must say so: the difference between "this runs here" and "this runs on the
    machine in the other room" is the whole decision the user is being asked to make.
    `fingerprints` are that machine's host keys, shown so a person can compare them
    against the machine itself."""
    frame = {"type": "propose_run_command", "call_id": call_id, "command": command,
             "argv": argv, "pretty": " ".join([command, *argv]), "reason": reason}
    if remote_host:
        frame["remote_host"] = remote_host
        frame["fingerprints"] = list(fingerprints or [])
    return frame


def propose_schedule(call_id: str, name: str, when: str) -> dict[str, Any]:
    """Arslan asks to create a recurring task — once per session (裁决①).
    Emitting this schedules NOTHING; only `confirm_schedule {call_id}` does.
    The card shows the CADENCE, because that is what the cost depends on."""
    return {"type": "propose_schedule", "call_id": call_id, "name": name, "when": when}


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

    Same shape as propose_connect_mcp and for the same reason: the card is where
    the person acts, and the write goes over REST from their click. Enrolment is
    the highest-consequence thing in this feature, so it must never be reachable
    as a side effect of Arslan having looked at a machine.

    The fingerprint is on the card because that is the one thing only the user
    can check — against the machine itself, not against anything we can show
    them a second time."""
    return {"type": "propose_enroll_node", "call_id": call_id, "name": name,
            "host": host, "user": user, "fingerprints": list(fingerprints)}


def propose_connect_mcp(*, call_id: str, key: str, label: str, transport: str,
                        command: str, argv: list[str], url: str | None,
                        env_keys: list[dict], prerequisites: str = "",
                        requires_path: bool = False,
                        path_placeholder: str | None = None) -> dict[str, Any]:
    """Arslan proposes connecting a preset MCP server. Emitting this frame connects
    NOTHING — the frontend renders a confirm card; the user reviews prerequisites, enters
    any required credentials (in the card's password fields, NEVER here), and the apply
    runs over REST. `env_keys` carries credential NAMES + metadata only, never values.
    `requires_path`/`path_placeholder` (Filesystem/Git) flag a local filesystem path the
    card must collect in a PLAIN TEXT field (not a secret) and append to `argv` client-side
    before connecting."""
    return {"type": "propose_connect_mcp", "call_id": call_id, "key": key, "label": label,
            "transport": transport, "command": command, "argv": argv, "url": url,
            "env_keys": [{"name": str(e["name"]), "description": str(e.get("description", "")),
                          "get_it_url": str(e.get("get_it_url", "")), "paid": bool(e.get("paid", False))}
                         for e in env_keys],
            "prerequisites": prerequisites,
            "requires_path": requires_path,
            "path_placeholder": path_placeholder}


def mcp_connect_followup(*, server_id: int, tool_count: int, safe_count: int,
                         restricted_count: int, assignable: bool) -> dict[str, Any]:
    """Honest, tier-aware result after a connect card completed. assignable=False means
    no tool is safe+wired → connected but must be reviewed in Settings before equipping."""
    return {"type": "mcp_connect_followup", "server_id": server_id, "tool_count": tool_count,
            "safe_count": safe_count, "restricted_count": restricted_count, "assignable": assignable}


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


def roster_event(action: str, spawn_id: int, spawn_name: str | None) -> dict[str, Any]:
    """Notify the client of a roster membership change.

    `action` is one of:
      • "joined"            — the spawn entered the roster
      • "left"              — the spawn was kicked
      • "recruited"         — a cell-6 recruiting invite was accepted (enroll only,
                              the task Arslan already answered is NOT re-dispatched)
      • "joined_no_pending" — a CARD accept found no parked task: joined only, so the
                              client explains that nothing was queued (BUG2: never silent)
    The renderer falls back to the neutral joined label for unknown actions, so adding
    one here is safe — but update web/src/types.ts and adapters.ts alongside it.
    """
    return {"type": "roster_event", "action": action, "spawn_id": spawn_id, "spawn_name": spawn_name}
