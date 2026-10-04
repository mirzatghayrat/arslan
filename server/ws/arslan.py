"""WebSocket endpoint for the unified Arslan orchestrator conversation."""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Coroutine
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select

from server import security
from server.auth import is_ws_token_valid
from server.db import session as db_session
from server.db.models import ArslanMessage
from server.orchestrator import arslan
from server.services import approvals, background_jobs, desktop_status
from server.services import (
    distill_service,
    mcp_service,
    run_registry,
    settings_service,
    turn_journal,
)
from server.ws import protocol

logger = logging.getLogger(__name__)

# S3-M2 heartbeat interval (seconds). Module-level so tests can shrink it.
_HEARTBEAT_INTERVAL_S = 30


def effective_risk(remote_host: str | None, command: str, argv: list) -> str:
    """The grade a confirmation is decided on.

    Remote is HIGH unconditionally (P3b 裁决③): the local rules describe this machine,
    and `git` at the other end of an ssh connection is a different program. Local
    (0.1.48): terminal_policy — run → LOW, ask → MEDIUM, forbid → HIGH."""
    from server.services import terminal_policy
    if remote_host:
        return "HIGH"
    return terminal_policy.risk_grade(terminal_policy.as_shell(command, argv))


def may_skip_card(remote_host: str | None, *, in_session_allow: bool,
                  policy: str, risk: str, always_allowed: bool = False) -> bool:
    """Whether a confirmation may be answered without showing a card.

    Every shortcut is local-only: a remote command always gets a card, because the
    thing being asked (which machine) is not in the command text the shortcuts key
    on. HIGH (forbidden) never skips. "Always allowed" is the user's standing
    answer for a rule, and holds even under ask_all."""
    if remote_host or risk == "HIGH":
        return False
    if in_session_allow or always_allowed:
        return True
    return policy == "ask_risky" and risk == "LOW"


def may_remember(remote_host: str | None, *, risk: str, remember: bool) -> bool:
    """Whether "don't ask again" may be honoured. Never for HIGH, and never for
    remote — a remembered remote command would be a trusted node with no gate,
    which is precisely the thing the C4 ruling refused to build."""
    return bool(remember) and risk != "HIGH" and not remote_host


def _cmd_sig(command: str, argv: list) -> str:
    # signature = binary + subcommand (kept literal) + arg SHAPE of the rest
    # (flags kept, free values blanked). Keeping the FIRST non-flag token — the
    # git/gh subcommand, the risk-bearing token — is what stops "remember git
    # status" from auto-approving "git push".
    sig_parts: list[str] = []
    seen_subcommand = False
    for a in argv:
        if a.startswith("-"):
            sig_parts.append(a)            # flags kept verbatim
        elif not seen_subcommand:
            sig_parts.append(a)            # first non-flag token = subcommand, kept
            seen_subcommand = True
        else:
            sig_parts.append("·")          # later free values blanked
    return command + "\x1f" + "\x1f".join(sig_parts)


async def _history(conversation_id: str) -> list[dict]:
    async with db_session.AsyncSessionLocal() as db:
        rows = await db.execute(
            select(ArslanMessage)
            .where(ArslanMessage.conversation_id == conversation_id)
            .order_by(ArslanMessage.id)
        )
        msgs = rows.scalars().all()
    return [
        {
            "message_id": m.id,
            "role": m.role,
            "content": m.display_content or m.content,  # DISPLAY copy
            "spawn_id": m.spawn_id,
            # S3-M2: run linkage (set at finalize) so RunReplay entry points
            # survive a reload. Key always emitted; None when unlinked.
            "run_id": m.run_id,
            # 0.1.42: a background job's result keeps its checked outcome.
            "job_outcome": m.job_outcome,
            # Mobile bridge: "phone" when a paired iPhone sent it (shown "from iPhone").
            "source": m.source,
        }
        for m in msgs
    ]


def message_source(frame: dict) -> str | None:
    """Only the one known source is kept; anything else is the window (NULL)."""
    return "phone" if frame.get("source") == "phone" else None


async def arslan_endpoint(ws: WebSocket, conversation_id: str) -> None:
    # Reject a cross-site WebSocket open BEFORE accept (fail-closed): a browser page
    # on another origin must not drive spawn dispatch / roster edits over this socket.
    if not security.ws_origin_allowed(ws.headers.get("origin"), ws.headers.get("host")):
        await ws.close(code=4403)
        return
    if not is_ws_token_valid(ws.query_params.get("token")):
        await ws.close(code=4001)
        return

    await ws.accept()

    # S3-M2 heartbeat: deterministic dead-peer detection. The pinger only ever
    # SENDS — it never touches ws.receive, so the confirm_command flow below
    # (which temporarily OWNS ws.receive while a command card is pending) is
    # never raced by it. Client pong handling shipped in web/src/api/ws.ts;
    # inbound ping/pong frames are ignored by the receive loop here.
    async def _pinger() -> None:
        try:
            while True:
                await asyncio.sleep(_HEARTBEAT_INTERVAL_S)
                await ws.send_json(protocol.ping(int(time.time())))
        except Exception:  # noqa: BLE001 — socket closed/failing; receive loop owns teardown
            return

    keepalive = asyncio.create_task(_pinger())

    # Per-connection frame queue. `sink` is its ONLY writer and lives in the
    # run_registry sink registry (S3-M2): every frame producer in this endpoint
    # emits through the fan-out `emit` below, which delivers to EVERY sink
    # attached to this conversation — so frames outlive this socket (reattach)
    # and reach other tabs on the same conversation.
    queue: asyncio.Queue[dict] = asyncio.Queue()

    def sink(ev: dict) -> None:
        queue.put_nowait(ev)

    emit = run_registry.make_emit(conversation_id)
    drainer: asyncio.Task | None = None

    async def _drain() -> None:
        """Resident sender: the single consumer of `queue` for this socket's whole
        life (started AFTER the reattach replay below so a live frame that arrived
        during it — newer than every snapshot frame — is delivered after it; it is
        cancelled in the endpoint's finally). On send failure the sink detaches
        (idempotent — stops dead-queue growth) and the drainer switches to
        swallowing frames so the queue.join() flushes below can never deadlock;
        the receive loop sees the disconnect and tears the connection down."""
        dead = False
        while True:
            ev = await queue.get()
            try:
                if not dead:
                    await ws.send_json(_to_frame(ev))
            except Exception:  # noqa: BLE001 — client gone
                dead = True
                run_registry.detach_sink(conversation_id, sink)
            finally:
                queue.task_done()

    async def run_with_live_frames(coro: Coroutine[Any, Any, object]) -> None:
        outcome = "error"
        try:
            with desktop_status.working(conversation_id):
                await coro
            outcome = "ok"
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        finally:
            desktop_status.push("turn_finished", conversation_id=conversation_id, outcome=outcome, work="turn")
            # Flush: every frame the coroutine emitted is on the socket (or
            # swallowed by a dead drainer) before the caller's next direct
            # ws.send_json — same ordering guarantee the old sentinel gave.
            await queue.join()

    async def run_with_confirm_frames(coro: Coroutine[Any, Any, object], title: str | None = None) -> None:
        """Run a plain-message orchestration. run_command pauses mid-loop via the
        injected `confirm_command`, which OWNS ws.receive itself (see below) only
        while a command is pending — so there is never a blocked receiver to cancel,
        and the outer loop cleanly resumes receiving once orchestration finishes."""
        from server.services.task_repository import TaskError
        from arslan.companion.memory import MemoryError
        from arslan.execution_budget import BudgetExceeded
        outcome = "error"
        try:
            with desktop_status.working(conversation_id, title=title):
                await coro
            outcome = "ok"
        except (TaskError, MemoryError, BudgetExceeded) as exc:
            outcome = "needs_review"
            code = exc.code if isinstance(exc, (TaskError, MemoryError)) else "task_budget_exhausted"
            await ws.send_json(protocol.error("TASK_REVIEW_REQUIRED", code, recoverable=True))
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        finally:
            desktop_status.push("turn_finished", conversation_id=conversation_id, outcome=outcome, title=title,
                                work="turn")
            await queue.join()

    async def run_connect_mcp_followup(server_id: int) -> None:
        """Task 3: after a connect card completes, report the honest tier split —
        counts are ALWAYS recomputed from the DB here, never trusted from the client."""
        async def _followup() -> None:
            counts = await mcp_service.tier_counts(server_id)
            emit(protocol.mcp_connect_followup(server_id=server_id, **counts))
        await run_with_live_frames(_followup())

    # Per-connection run_command confirmation state (Task 6).
    import uuid

    session_cmd_allow: set[str] = set()  # command signatures auto-approved this session

    # T1 workspace-write grant (P1b): ONE per connection, not per file — the
    # user ruling is "first use asks, the rest of the session does not".
    workspace_write_granted = {"yes": False}
    # 0.1.52 S2: the user's latest message on this socket — the judge's tool.approval
    # question needs the user's own words, whether or not a memory context is bound.
    latest_request = {"text": ""}
    # Mobile bridge: whether the turn running on this socket was started by the iPhone
    # (only the Arslan Bridge's socket ever sends source "phone").
    phone_turn = {"on": False}
    # A frame read while a shared card was being decided elsewhere, kept for the next reader.
    pushback: list[dict] = []

    async def _receive() -> dict:
        return pushback.pop(0) if pushback else await ws.receive_json()

    async def _ask(frame: dict) -> dict:
        """Show one card and wait for its answer: {"approved", "remember"}.

        A window's own turn: the card is private to THIS socket — deliberately NOT
        emit(): only this connection's receive-router below can answer the call_id,
        so fanning it out would paint an unanswerable card on every other tab. It is
        also deliberately un-journaled (raw ws.send_json, never a recorder tee), so a
        reattaching socket cannot replay a dead interactive card.

        A turn the iPhone started: see `_ask_everywhere`."""
        if phone_turn["on"]:
            return await _ask_everywhere(frame)
        kind, call_id = frame["type"].removeprefix("propose_"), frame["call_id"]
        await ws.send_json(frame)
        # Own ws.receive HERE, only while this one card is pending. The orchestration
        # coro that led here is blocked awaiting this call, so the outer
        # `while True: ws.receive_json()` loop is not receiving — there is exactly one
        # receiver. We loop until THIS call_id is answered; any other frame arriving
        # mid-confirmation gets a recoverable BUSY notice (ping/pong ignored). On the
        # matching confirm/cancel we return, and the outer loop resumes receiving. A
        # client vanishing mid-confirmation raises WebSocketDisconnect out of here, so
        # the outer handler's disconnect path runs (clean socket teardown).
        with desktop_status.awaiting_approval(conversation_id):
            while True:
                try:
                    data = await asyncio.wait_for(_receive(), timeout=300)
                except TimeoutError:
                    return {"approved": False, "remember": False}
                t = data.get("type")
                if t in ("ping", "pong"):
                    continue
                if t in (f"confirm_{kind}", f"cancel_{kind}") and data.get("call_id") == call_id:
                    return {"approved": t == f"confirm_{kind}", "remember": bool(data.get("remember"))}
                # Any other frame (including a confirm for an unknown/stale call_id) is
                # not actionable while we are paused — tell the client, keep waiting.
                if approvals.answer(data):   # a background job's card, not this one
                    continue
                await ws.send_json(protocol.error(
                    "BUSY", "An action is awaiting your confirmation.", recoverable=True))

    async def _ask_everywhere(frame: dict) -> dict:
        """A turn the iPhone started shows its cards everywhere: on the phone (through
        this socket, the Bridge's) and in every Mac window open on the conversation.
        The first answer from any of them decides — a window's reply reaches the
        registry through its own receive loop, the phone's through this one — and
        `card_resolved` closes the copies nobody answered (approvals.open_card /
        close_card). Like every foreground card it is never journaled."""
        loop = asyncio.get_running_loop()
        pending = approvals.open_card(conversation_id, frame)
        deadline = loop.time() + approvals.TIMEOUT_S
        receiving: asyncio.Future | None = None
        try:
            with desktop_status.awaiting_approval(conversation_id):
                while not pending.future.done() and loop.time() < deadline:
                    if receiving is None:
                        receiving = asyncio.ensure_future(_receive())
                    await asyncio.wait({receiving, pending.future}, timeout=deadline - loop.time(),
                                       return_when=asyncio.FIRST_COMPLETED)
                    if not receiving.done():
                        continue
                    data = receiving.result()        # a disconnect raises here
                    receiving = None
                    t = data.get("type")
                    if t in ("ping", "pong"):
                        continue
                    if t in approvals.ANSWERS:
                        approvals.answer(data)       # this card's answer, or a late second one
                        continue
                    if pending.future.done():
                        pushback.append(data)        # decided meanwhile: the next reader gets it
                        continue
                    await ws.send_json(protocol.error(
                        "BUSY", "An action is awaiting your confirmation.", recoverable=True))
        finally:
            if receiving is not None and not receiving.done():
                receiving.cancel()
                await asyncio.wait({receiving})
                if not receiving.cancelled() and receiving.exception() is None:
                    pushback.append(receiving.result())
            decision = approvals.close_card(pending)
        return {"approved": bool(decision["approved"]), "remember": bool(decision["remember"])}

    async def confirm_workspace_write(action: str, path: str) -> bool:
        from server.services import settings_service
        if workspace_write_granted["yes"]:
            return True
        async with db_session.AsyncSessionLocal() as db:
            ws_root = await settings_service.workspace_dir(db)
        if ws_root is None:
            return False                     # nothing to grant access to
        decision = (await _ask(protocol.propose_workspace_write(
            uuid.uuid4().hex, str(ws_root), action, path)))["approved"]
        if decision:
            workspace_write_granted["yes"] = True     # session-wide, per the ruling
        return decision

    # Scheduling grant (P2 裁决①): one per connection, like the workspace write.
    schedule_granted = {"yes": False}

    async def confirm_schedule(name: str, when: str) -> bool:
        if schedule_granted["yes"]:
            return True
        decision = (await _ask(protocol.propose_schedule(uuid.uuid4().hex, name, when)))["approved"]
        if decision:
            schedule_granted["yes"] = True
        return decision

    async def _sandbox_card(command: str, argv: list, sandbox: str, why: str, verdict) -> bool:
        from server.services import command_sandbox
        call_id = uuid.uuid4().hex
        from server.services import judgment
        judgment.shadow("tool.approval", judgment.approval_state(command, rule=verdict.rule, reason=verdict.reason,
                                                                 sandboxed=False,
                                                                 user_request=latest_request["text"]),
                        ref=call_id, conversation_id=conversation_id)
        decision = await _ask(protocol.propose_run_command(
            call_id, command, argv, reason=verdict.reason if verdict.level == "ask" else "",
            sandbox=sandbox, why=why))
        if decision["approved"] and decision.get("remember"):
            command_sandbox.grant(conversation_id)    # this conversation only, never saved
        judgment.record_outcome_later(call_id, "approved" if decision["approved"] else "declined",
                                      point="tool.approval")
        return bool(decision["approved"])

    async def confirm_command(command: str, argv: list, *,
                              remote_host: str | None = None,
                              fingerprints: list | None = None,
                              sandbox: str | None = None, why: str = "") -> bool:
        """`sandbox` (0.1.51 P3): "outside" — the model asks to run this command
        outside the workspace sandbox; "retry" — the sandbox stopped it and it would
        run again outside, from the start. Either always shows a card; its checkbox
        means "for the rest of this conversation" (memory only), never a saved rule."""
        from server.services import settings_service
        # A remote command takes NONE of the shortcuts below. Not the session
        # allow-list, not ask_risky, not "remember this one" — because the local
        # risk grade describes a binary on THIS machine, and `git` over there is
        # not the same program (P3b 裁决③). Remote is HIGH, always, and HIGH is
        # already the grade this function refuses to remember.
        from server.services import terminal_policy
        sig = _cmd_sig(command, argv)
        risk = effective_risk(remote_host, command, argv)
        verdict = terminal_policy.assess(terminal_policy.as_shell(command, argv))
        if sandbox in ("outside", "retry"):
            from server.services import command_sandbox
            if command_sandbox.granted(conversation_id):
                return True
            return await _sandbox_card(command, argv, sandbox, why, verdict)
        policy, standing = "", False
        if not remote_host:
            # 'ask_risky' (the 0.1.48 default) runs harmless commands without a card.
            async with db_session.AsyncSessionLocal() as db:
                policy = await settings_service.shell_confirm_policy(db)
                standing = verdict.rule in await terminal_policy.always_allowed(db)
        if may_skip_card(remote_host, in_session_allow=sig in session_cmd_allow,
                         policy=policy, risk=risk, always_allowed=standing):
            return True
        call_id = uuid.uuid4().hex
        # 0.1.52 S2: shadow judgment — what the judge would say about this card, recorded
        # with the user's real answer below; it changes nothing (task book C2.1).
        from server.services import judgment
        if not remote_host:
            judgment.shadow("tool.approval", judgment.approval_state(
                terminal_policy.as_shell(command, argv), rule=verdict.rule, reason=verdict.reason,
                user_request=latest_request["text"]),
                ref=call_id, conversation_id=conversation_id)
        # The card (private to this socket, or everywhere for a phone turn): see `_ask`.
        decision = await _ask(
            protocol.propose_run_command(call_id, command, argv, reason=verdict.reason or f"risk: {risk}",
                                         remote_host=remote_host,
                                         fingerprints=list(fingerprints or []),
                                         rule=None if remote_host else verdict.rule)
        )
        if not remote_host:
            judgment.record_outcome_later(call_id, "approved" if decision.get("approved") else "declined",
                                          point="tool.approval")
        # Never permanently auto-approve a HIGH-risk (e.g. network) command, even if
        # the user checked "remember" — those always require a fresh card.
        if may_remember(remote_host, risk=risk, remember=bool(decision.get("remember"))):
            # 0.1.48: "don't ask again" is a standing answer for this KIND of command
            # (its rule), kept across sessions and listed in Settings, where it can be
            # withdrawn. A forbidden rule can never be remembered (HIGH never gets here).
            session_cmd_allow.add(sig)
            if verdict.rule:
                async with db_session.AsyncSessionLocal() as db:
                    await terminal_policy.allow_always(db, verdict.rule)
        return bool(decision.get("approved"))

    try:
        await ws.send_json({"type": "history", "messages": await _history(conversation_id)})

        # Reattach (S3-M2): snapshot the run journals + attach the sink in ONE
        # SYNCHRONOUS block — no await may sit between the two lines. A frame
        # broadcast concurrently is then either already in the snapshot (it was
        # journaled before) or delivered live to the freshly attached sink
        # (after) — never both, never neither.
        snapshots = run_registry.journal_snapshots(conversation_id)
        turn_events = turn_journal.snapshot(conversation_id)
        run_registry.attach_sink(conversation_id, sink)

        # Replay: announce each in-flight run, then its journaled frames. Live
        # frames arriving meanwhile buffer in `queue` (drainer not started yet)
        # so they follow the replay in order.
        for run_id, events in snapshots:
            await ws.send_json(protocol.run_in_progress(run_id))
            for ev in events:
                try:
                    await ws.send_json(_to_frame(ev))
                except Exception:  # noqa: BLE001 — client gone mid-replay; receive loop sees it
                    break

        # Same replay for Arslan's own in-flight answer turn: the journaled
        # stream_start is the preamble without which the store discards every
        # live frame the freshly attached sink is about to deliver.
        for ev in turn_events:
            try:
                await ws.send_json(_to_frame(ev))
            except Exception:  # noqa: BLE001 — client gone mid-replay; receive loop sees it
                break

        # 0.1.42: background jobs outlive sockets — show this tab the cards of
        # jobs still running and any confirmation still waiting for an answer.
        # A finished job is already in the history as its labelled result.
        for job in background_jobs.jobs_for(conversation_id):
            if job.phase != "finished":
                await ws.send_json(job.frame())
        for card in approvals.pending_cards(conversation_id):
            await ws.send_json(card)

        drainer = asyncio.create_task(_drain())

        while True:
            data = await _receive()
            msg_type = data.get("type")

            if msg_type in ("ping", "pong"):
                continue
            if msg_type in approvals.ANSWERS and approvals.answer(data):
                continue
            if msg_type in approvals.ANSWERS and data.get("source") == "phone":
                continue    # the phone answered a card the Mac had already decided; it got card_resolved

            from server.services import task_context, temporary_turn
            if await task_context.is_temporary(conversation_id):
                if msg_type == "user_message":
                    latest_request["text"] = str(data.get("content") or "")
                    phone_turn["on"] = message_source(data) == "phone"
                    with_context = await task_context.load(conversation_id)
                    from server.services.personal_context import bind
                    with bind(with_context):
                        await run_with_confirm_frames(arslan.handle_user_message(
                            conversation_id, data.get("content", ""), emit,
                            attached_context=data.get("attached_context") or None,
                            images=data.get("images") or None,
                            source=message_source(data),
                        ), title=data.get("content") or None)
                elif msg_type == "session_ended":
                    temporary_turn.clear(conversation_id)
                    await ws.send_json({"type": "session_ended_ack", "conversation_id": conversation_id})
                elif msg_type != "resume":
                    await ws.send_json(protocol.error("TEMPORARY_ACTION_UNAVAILABLE",
                        "Temporary conversations do not save memories or perform external actions."))
                continue

            if msg_type == "resume":
                last_id = int(data.get("last_message_id", 0))
                for m in await _history(conversation_id):
                    if m["message_id"] > last_id:
                        await ws.send_json(protocol.message(m["message_id"], m["content"], m["role"]))
                continue

            if msg_type == "resume_task":
                from server.services import task_service
                from server.services.task_repository import TaskError
                from arslan.execution_budget import BudgetExceeded
                task_id, version = data.get("task_id"), data.get("expected_version")
                if not isinstance(task_id, str) or not isinstance(version, int) or isinstance(version, bool) or version < 1:
                    await ws.send_json(protocol.error("INVALID_TASK_RESUME", "invalid_task_resume", recoverable=True))
                    continue
                phone_turn["on"] = False
                try:
                    await run_with_confirm_frames(task_service.resume_turn(
                        task_id, version, conversation_id, emit, confirm_command=confirm_command,
                        confirm_workspace_write=confirm_workspace_write, confirm_schedule=confirm_schedule))
                except (TaskError, BudgetExceeded) as exc:
                    code = exc.code if isinstance(exc, TaskError) else "task_budget_exhausted"
                    await ws.send_json(protocol.error("TASK_REVIEW_REQUIRED", code, recoverable=True))
                continue

            if msg_type == "confirm_connect_mcp":
                raw_id = data.get("server_id")
                try:
                    sid = int(raw_id)
                except (TypeError, ValueError):
                    await ws.send_json(protocol.error("INVALID_INPUT", "server_id required"))
                    continue
                await run_connect_mcp_followup(sid)
                continue

            if msg_type == "session_ended":
                old_cid = data.get("conversation_id")
                if old_cid and (run_registry.active_for(str(old_cid))
                                or turn_journal.active(str(old_cid))):
                    # The conversation the user LEFT is still mid-run/mid-turn
                    # (a thread switch fires session_ended immediately).
                    # Distilling now would capture a half-written session and
                    # roster-clear would yank membership from under the live
                    # run — skip both; the next session_ended after the work
                    # completes distills. Ack regardless: the client is waiting.
                    logger.info("session_ended for %s deferred: run/turn in flight", old_cid)
                    await ws.send_json({"type": "session_ended_ack", "conversation_id": old_cid})
                    continue
                if old_cid:
                    # Best-effort: an optional feature must never suppress the ack or close the socket.
                    try:
                        async with db_session.AsyncSessionLocal() as _s:
                            enabled = await settings_service.distill_enabled(_s)
                        if enabled:
                            asyncio.create_task(distill_service.distill_session(str(old_cid)))
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("session_ended distill trigger failed (non-fatal): %s", exc)
                await ws.send_json({"type": "session_ended_ack", "conversation_id": old_cid})
                continue

            if msg_type != "user_message":
                await ws.send_json(protocol.error("INVALID_INPUT", "Unknown message type"))
                continue

            content = data.get("content", "")
            latest_request["text"] = str(content or "")
            phone_turn["on"] = message_source(data) == "phone"
            # Images ride in the frame itself (base64), not through /extract:
            # decision ③A means they are needed for exactly one turn, so there
            # is nothing to store and nothing to fetch back.
            images = data.get("images") or []
            attached = (data.get("attached_context") or "").strip()

            await run_with_confirm_frames(
                arslan.handle_user_message(conversation_id, content, emit,
                                           attached_context=attached or None,
                                           images=images or None,
                                           source=message_source(data),
                                           confirm_command=confirm_command,
                                           confirm_workspace_write=confirm_workspace_write,
                                           confirm_schedule=confirm_schedule),
                title=content or None,
            )
    except WebSocketDisconnect:
        return
    except Exception as exc:  # noqa: BLE001
        try:
            await ws.send_json(protocol.error("INTERNAL_ERROR", str(exc), recoverable=True))
            await ws.close(code=1011)
        except Exception:  # noqa: BLE001
            pass
        return
    finally:
        # Covers EVERY exit: normal return, WebSocketDisconnect (including one
        # surfacing mid-run through a confirm_command receive), internal errors,
        # and task cancellation (server shutdown). detach_sink is idempotent —
        # the drainer may already have detached on a send failure, and if the
        # history push raised before attach_sink ran this is a no-op.
        run_registry.detach_sink(conversation_id, sink)
        from server.services.temporary_turn import clear as clear_temporary
        clear_temporary(conversation_id)
        if drainer is not None:
            drainer.cancel()
        keepalive.cancel()


def _to_frame(ev: dict) -> dict:
    """Map an orchestration event dict to a wire frame (already frame-shaped here)."""
    t = ev.get("type")
    if t == "routing":
        return protocol.routing(ev.get("spawn_id"), ev.get("spawn_name"),
                                announcement=ev.get("announcement"))
    if t == "stream_start":
        # run_id must ride through the rebuild — it is the client's cancel handle (S3-M1).
        return protocol.stream_start_src(ev.get("source", "arslan"), ev.get("spawn_id"),
                                         run_id=ev.get("run_id"))
    if t == "suggest_create":
        return protocol.suggest_create(
            ev.get("draft") or {}, task_brief=ev.get("task_brief"), overlaps=ev.get("overlaps")
        )
    if t == "fact_saved":
        return protocol.fact_saved(ev.get("content", ""), bool(ev.get("sensitive")))
    if t == "tool_call":
        return protocol.tool_call(ev.get("tool", ""), ev.get("args_summary", ""))
    if t == "tool_result":
        return protocol.tool_result(ev.get("tool", ""), bool(ev.get("ok")),
                                    ev.get("summary", ""), ev.get("artifact"), ev.get("artifacts"))
    if t == "escalation":
        return protocol.escalation(
            ev.get("spawn_id"), ev.get("spawn_name"), ev.get("kind", "data"), ev.get("need", "")
        )
    if t == "escalation_refused":
        return protocol.escalation_refused(ev.get("spawn_id"), ev.get("why", ""))
    if t == "escalation_resolved":
        return protocol.escalation_resolved(
            ev.get("spawn_id"), ev.get("how", ""), ev.get("detail", "")
        )
    if t == "orchestrator_action":
        return protocol.orchestrator_action(ev.get("tool", ""), ev.get("reason", ""))
    if t == "roster_event":
        return protocol.roster_event(ev.get("action", ""), ev.get("spawn_id"), ev.get("spawn_name"))
    if t == "roster_update":
        return protocol.roster_update(ev.get("members", []))
    if t == "propose_connect_mcp":
        return protocol.propose_connect_mcp(
            call_id=ev.get("call_id", ""), key=ev.get("key", ""), label=ev.get("label", ""),
            transport=ev.get("transport", ""), command=ev.get("command", ""),
            argv=ev.get("argv") or [], url=ev.get("url"), env_keys=ev.get("env_keys") or [],
            prerequisites=ev.get("prerequisites", ""),
            requires_path=ev.get("requires_path", False),
            path_placeholder=ev.get("path_placeholder"))
    if t == "mcp_connect_followup":
        return protocol.mcp_connect_followup(
            server_id=ev.get("server_id"), tool_count=ev.get("tool_count", 0),
            safe_count=ev.get("safe_count", 0), restricted_count=ev.get("restricted_count", 0),
            assignable=bool(ev.get("assignable")))
    return ev  # stream_chunk / stream_end / error / spawn_meta already match the wire shape
