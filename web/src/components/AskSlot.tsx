import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useArslanStore } from "../stores/arslanStore";
import ActionApprovalCard from "./ActionApprovalCard";
import CapabilityProposeCard from "./capabilities/CapabilityProposeCard";
import ConnectMcpCard from "./ConnectMcpCard";
import EnrollNodeCard from "./EnrollNodeCard";
import RunCommandCard from "./RunCommandCard";
import ScheduleGrantCard from "./ScheduleGrantCard";
import WorkspaceWriteCard from "./WorkspaceWriteCard";
import { AnswerGuardScope, AskQueue, CARD_MS, Notice, scopeToSend, useAnswerGuardState, type AskQueuePosition, type QueuedAsk } from "./kit";

/** A window's own card gets no word from the server when it runs out; it leaves this slot
 *  this long after its expiry, so the server has closed it first. */
const EXPIRE_GRACE_MS = 2_000;

/** An expires_at more than this long before the card arrived is not a time (a duration sent as an epoch, `1800`): it counts
 *  as none. One a little in the past is a real time that has gone by — a card the server has already closed. */
const MAX_PAST_MS = 86_400_000;

/** The chat's message box (OrchestratorChat): the one under an open conversation, or the first-run one. */
function focusComposer() {
  (document.getElementById("chat-message-input") ?? document.getElementById("landing-message-input"))?.focus();
}

/**
 * The one place asking cards appear in the chat (0.1.55 S2): every pending ask,
 * oldest first, in one AskQueue ("‹ 1 / 3 ›"). They used to render six overlays
 * into the same absolute spot, so two waiting at once sat on top of each other.
 * Same frames in, same confirm / cancel frames out — and, for a card from the
 * permission layer (0.1.61 §A4), its scope on a yes and the user's note on a No.
 *
 * An answer here is a socket write and its card leaves in the same tick: nothing is in flight to wait
 * for, except on the two cards that call the REST API themselves (enrolling a machine, connecting a server),
 * and while that is in flight their ‹ › are off. (The queue keys each ask by its identity: what one card had
 * picked or typed never reaches the ask that moves up into its place.)
 *
 * One gesture answers one card (0.1.61 §A4, fix round 2): for 500 ms after a card leaves the top — answered,
 * resolved elsewhere, run out or paged away — nothing answers the one that comes up (kit/guard.ts).
 *
 * Every pending card of every kind is in that queue (0.1.61 §A4, fix round 1): the store keeps a list per kind
 * keyed by call id, so a second card of a kind — a window's own and a job's — waits behind the first and never
 * hides it. An answer, a `card_resolved` and an expiry take a card out by its id, and each runs out on its own clock.
 */
export default function AskSlot({ send }: { send: (frame: Record<string, unknown>) => void }) {
  // What holds an answer for a moment after a card leaves (kit/guard.ts) is kept here, above the queue: the queue is not on screen
  // while no card waits, and the card that comes up in that gap — the next command of the turn — must be held too.
  const guard = useAnswerGuardState();
  return <AnswerGuardScope value={guard}><AskCards send={send} /></AnswerGuardScope>;
}

function AskCards({ send }: { send: (frame: Record<string, unknown>) => void }) {
  const { t } = useTranslation();
  const pendingCommands = useArslanStore((s) => s.pendingCommands);
  const pendingEnrollNodes = useArslanStore((s) => s.pendingEnrollNodes);
  const pendingWorkspaceWrites = useArslanStore((s) => s.pendingWorkspaceWrites);
  const pendingSchedules = useArslanStore((s) => s.pendingSchedules);
  const pendingActions = useArslanStore((s) => s.pendingActions);
  const pendingCapabilities = useArslanStore((s) => s.pendingCapabilities);
  const clearPendingCapability = useArslanStore((s) => s.clearPendingCapability);
  // Security-load-bearing: secrets never leave this card except over REST (ConnectMcpCard.tsx).
  const pendingConnectMcps = useArslanStore((s) => s.pendingConnectMcps);
  const markConnectApplied = useArslanStore((s) => s.markConnectApplied);
  const clearPendingCommand = useArslanStore((s) => s.clearPendingCommand);
  const clearPendingEnrollNode = useArslanStore((s) => s.clearPendingEnrollNode);
  const clearPendingWorkspaceWrite = useArslanStore((s) => s.clearPendingWorkspaceWrite);
  const clearPendingAction = useArslanStore((s) => s.clearPendingAction);
  const clearPendingSchedule = useArslanStore((s) => s.clearPendingSchedule);
  const clearPendingConnectMcp = useArslanStore((s) => s.clearPendingConnectMcp);
  const cardExpired = useArslanStore((s) => s.cardExpired);
  const expireCard = useArslanStore((s) => s.expireCard);
  const dismissCardExpired = useArslanStore((s) => s.dismissCardExpired);

  // 0.1.61 §A4: the countdown is the server's own expiry (the frame's expires_at, so a reload
  // shows the time really left). A frame without one waits approvals.TIMEOUT_S like every card
  // the Mac waits on: its arrival + 30 minutes.
  // Capped at arrival + 30 minutes (what the Mac waits): a frame's far-off or zero expires_at must neither overflow
  // setTimeout (> 24.8 days fires at once) nor close the card at once.
  const expires = (p: { receivedAt?: number; expiresAt?: number }) => {
    const wait = p.receivedAt ? p.receivedAt + CARD_MS : null;
    const own = p.expiresAt && p.expiresAt > 0 && (!p.receivedAt || p.expiresAt >= p.receivedAt - MAX_PAST_MS) ? p.expiresAt : null;
    return own === null ? wait : wait === null ? own : Math.min(own, wait);
  };
  // Every card here runs out on its own clock (the Mac waits 30 minutes: approvals.TIMEOUT_S; a proposal to enrol a
  // machine or connect a server is held as long). The soonest to run out leaves the slot then.
  const next = [...pendingCommands, ...pendingEnrollNodes, ...pendingWorkspaceWrites, ...pendingSchedules, ...pendingActions,
                ...pendingCapabilities, ...pendingConnectMcps]
    .flatMap((p) => { const at = expires(p); return at != null ? [{ callId: p.callId, at }] : []; })
    .reduce<{ callId: string; at: number } | null>((a, b) => (!a || b.at < a.at ? b : a), null);
  useEffect(() => {
    if (!next) return;
    const id = window.setTimeout(() => expireCard(next.callId), Math.max(0, next.at + EXPIRE_GRACE_MS - Date.now()));
    return () => window.clearTimeout(id);
  }, [next?.callId, next?.at, expireCard]);

  /** A yes: a v2 card's carries its scope (one the card offered), an old card's frame is exactly as before. */
  const yes = (type: string, callId: string, card: { options?: string[]; alwaysLabel?: string }, scope: string | undefined,
               old: Record<string, unknown> = {}) => {
    const s = scope === undefined ? undefined : scopeToSend(card.options, scope, card.alwaysLabel);
    send(s !== undefined ? { type, call_id: callId, scope: s } : { type, call_id: callId, ...old });
  };
  /** A No: with the user's note when there is one, else exactly as before. A note is typed in a field on the
   *  card, which leaves with the card: the composer takes the focus the field held. */
  const no = (type: string, callId: string, note?: string) => {
    send(note ? { type, call_id: callId, note } : { type, call_id: callId });
    if (note) focusComposer();
  };

  // 0.1.55 S2: the pending asks, oldest first, for the one AskQueue slot. Keyed by the ask (kind and call id). Oldest is exact:
  // by the sequence number each card got on arrival, so two that arrive in one millisecond keep their order whatever their
  // kinds. A proposal to connect a server (rank 1) waits behind every ask that needs an answer.
  const items: (QueuedAsk & { rank: number; seq: number })[] = [
    ...pendingCommands.map((c) => ({ rank: 0, seq: c.seq ?? 0, key: `cmd:${c.callId}`, render: (queue: AskQueuePosition) => (
      <RunCommandCard callId={c.callId} pretty={c.pretty} reason={c.reason}
        remoteHost={c.remoteHost} fingerprints={c.fingerprints}
        background={c.background} sandbox={c.sandbox} why={c.why}
        options={c.options} alwaysLabel={c.alwaysLabel} permKind={c.permKind}
        expiresAt={expires(c)} queue={queue}
        onConfirm={(callId, remember, scope) => { yes('confirm_run_command', callId, c, scope, { remember }); clearPendingCommand(c.callId); }}
        onCancel={(callId, note) => { no('cancel_run_command', callId, note); clearPendingCommand(c.callId); }} />) })),
    ...pendingEnrollNodes.map((n) => ({ rank: 0, seq: n.seq ?? 0, key: `node:${n.callId}`, render: (queue: AskQueuePosition) => (
      <EnrollNodeCard callId={n.callId} name={n.name} host={n.host}
        user={n.user} fingerprints={n.fingerprints}
        expiresAt={expires(n)} queue={queue} onDone={() => clearPendingEnrollNode(n.callId)} />) })),
    ...pendingWorkspaceWrites.map((w) => ({ rank: 0, seq: w.seq ?? 0, key: `ws:${w.callId}`, render: (queue: AskQueuePosition) => (
      <WorkspaceWriteCard callId={w.callId} workspace={w.workspace}
        action={w.action} path={w.path} background={w.background}
        options={w.options} alwaysLabel={w.alwaysLabel}
        expiresAt={expires(w)} queue={queue}
        onConfirm={(callId, scope) => { yes('confirm_workspace_write', callId, w, scope); clearPendingWorkspaceWrite(w.callId); }}
        onCancel={(callId, note) => { no('cancel_workspace_write', callId, note); clearPendingWorkspaceWrite(w.callId); }} />) })),
    ...pendingActions.map((a) => ({ rank: 0, seq: a.seq ?? 0, key: `act:${a.callId}`, render: (queue: AskQueuePosition) => (
      <ActionApprovalCard kind={a.kind} target={a.target} detail={a.detail}
        options={a.options} alwaysLabel={a.alwaysLabel} title={a.title} why={a.why}
        permKind={a.permKind} background={a.background}
        expiresAt={expires(a)} queue={queue}
        onConfirm={(scope) => { yes('confirm_action', a.callId, a, scope); clearPendingAction(a.callId); }}
        onCancel={(note) => { no('cancel_action', a.callId, note); clearPendingAction(a.callId); }} />) })),
    ...pendingSchedules.map((s) => ({ rank: 0, seq: s.seq ?? 0, key: `sched:${s.callId}`, render: (queue: AskQueuePosition) => (
      <ScheduleGrantCard callId={s.callId} name={s.name} when={s.when}
        background={s.background} options={s.options} alwaysLabel={s.alwaysLabel}
        expiresAt={expires(s)} queue={queue}
        onConfirm={(callId, scope) => { yes('confirm_schedule', callId, s, scope); clearPendingSchedule(s.callId); }}
        onCancel={(callId, note) => { no('cancel_schedule', callId, note); clearPendingSchedule(s.callId); }} />) })),
    ...pendingCapabilities.map((k) => ({ rank: 0, seq: k.seq ?? 0, key: `cap:${k.callId}`, render: (queue: AskQueuePosition) => (
      <CapabilityProposeCard card={k} callId={k.callId}
        expiresAt={expires(k)} queue={queue}
        onConfirm={(callId, keys, folders) => { send({ type: 'confirm_capability', call_id: callId, keys, folders }); clearPendingCapability(k.callId); }}
        onCancel={(callId) => { send({ type: 'cancel_capability', call_id: callId }); clearPendingCapability(k.callId); }} />) })),
    ...pendingConnectMcps.map((m) => ({ rank: 1, seq: m.seq ?? 0, key: `mcp:${m.callId}`, render: (queue: AskQueuePosition) => (
      <ConnectMcpCard callId={m.callId} label={m.label} labelKey={m.labelKey}
        transport={m.transport} command={m.command} args={m.argv}
        url={m.url} envKeys={m.envKeys} prerequisites={m.prerequisites}
        requiresPath={m.requiresPath} pathPlaceholder={m.pathPlaceholder}
        expiresAt={expires(m)} queue={queue}
        onApplied={(res) => {
          // Secret-free confirm: server_id + tool_count only — no env values, no
          // client-computed tier counts (the backend recomputes the honest tier split
          // and emits mcp_connect_followup, which names the server: this card is the one that
          // connected it, so it is marked, and the follow-up closes it).
          if (res.ok) {
            markConnectApplied(m.callId, res.serverId);
            send({ type: 'confirm_connect_mcp', call_id: m.callId, server_id: res.serverId, tool_count: res.toolCount });
          }
        }}
        onCancel={() => clearPendingConnectMcp(m.callId)} />) })),
  ].sort((a, b) => a.rank - b.rank || a.seq - b.seq);

  if (!items.length) {
    // 0.1.61 §A4: a card that ran out unanswered is "waiting for you", never "declined".
    if (!cardExpired) return null;
    return (
      <div className="ask-slot" data-testid="ask-slot">
        <Notice testId="ask-expired" title={t("kit.expiredTitle")}
          action={<button type="button" onClick={dismissCardExpired} data-testid="ask-expired-close"
            className="text-[13px] text-muted-foreground hover:text-foreground">{t("kit.close")}</button>}>
          {t("kit.expiredBody")}
        </Notice>
      </div>
    );
  }
  return (
    <div className="ask-slot" data-testid="ask-slot">
      <AskQueue items={items} />
    </div>
  );
}
