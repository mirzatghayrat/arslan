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
import { AskQueue, CARD_MS, Notice, scopeToSend, type AskQueuePosition, type QueuedAsk } from "./kit";

/** A window's own card gets no word from the server when it runs out; it leaves this slot
 *  this long after its expiry, so the server has closed it first. */
const EXPIRE_GRACE_MS = 2_000;

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
 * An answer here is a socket write and its card leaves in the same tick, so no card is ever "busy":
 * nothing is in flight to wait for. (The queue keys each ask by its identity: what one card had picked
 * or typed never reaches the ask that moves up into its place.)
 */
export default function AskSlot({ send }: { send: (frame: Record<string, unknown>) => void }) {
  const { t } = useTranslation();
  const pendingCommand = useArslanStore((s) => s.pendingCommand);
  const pendingEnrollNode = useArslanStore((s) => s.pendingEnrollNode);
  const pendingWorkspaceWrite = useArslanStore((s) => s.pendingWorkspaceWrite);
  const pendingSchedule = useArslanStore((s) => s.pendingSchedule);
  const pendingAction = useArslanStore((s) => s.pendingAction);
  const pendingCapability = useArslanStore((s) => s.pendingCapability);
  const clearPendingCapability = useArslanStore((s) => s.clearPendingCapability);
  // Security-load-bearing: secrets never leave this card except over REST (ConnectMcpCard.tsx).
  const pendingConnectMcp = useArslanStore((s) => s.pendingConnectMcp);
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
    return p.expiresAt && p.expiresAt > 0 ? (wait === null ? p.expiresAt : Math.min(p.expiresAt, wait)) : wait;
  };
  // The cards the Mac waits on (approvals.TIMEOUT_S). The soonest to run out leaves the slot then.
  const next = [pendingCommand, pendingWorkspaceWrite, pendingSchedule, pendingAction, pendingCapability]
    .flatMap((p) => { const at = p ? expires(p) : null; return p && at != null ? [{ callId: p.callId, at }] : []; })
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

  // 0.1.55 S2: the pending asks, oldest first, for the one AskQueue slot. Keyed by the ask (kind and call id).
  const items: QueuedAsk[] = [
    pendingCommand && { at: pendingCommand.receivedAt ?? 0, key: `cmd:${pendingCommand.callId}`, render: (queue: AskQueuePosition) => (
      <RunCommandCard callId={pendingCommand.callId} pretty={pendingCommand.pretty} reason={pendingCommand.reason}
        remoteHost={pendingCommand.remoteHost} fingerprints={pendingCommand.fingerprints}
        background={pendingCommand.background} sandbox={pendingCommand.sandbox} why={pendingCommand.why}
        options={pendingCommand.options} alwaysLabel={pendingCommand.alwaysLabel} permKind={pendingCommand.permKind}
        expiresAt={expires(pendingCommand)} queue={queue}
        onConfirm={(callId, remember, scope) => { yes('confirm_run_command', callId, pendingCommand, scope, { remember }); clearPendingCommand(); }}
        onCancel={(callId, note) => { no('cancel_run_command', callId, note); clearPendingCommand(); }} />) },
    pendingEnrollNode && { at: pendingEnrollNode.receivedAt ?? 0, key: `node:${pendingEnrollNode.callId}`, render: (queue: AskQueuePosition) => (
      <EnrollNodeCard callId={pendingEnrollNode.callId} name={pendingEnrollNode.name} host={pendingEnrollNode.host}
        user={pendingEnrollNode.user} fingerprints={pendingEnrollNode.fingerprints}
        expiresAt={expires(pendingEnrollNode)} queue={queue} onDone={() => clearPendingEnrollNode()} />) },
    pendingWorkspaceWrite && { at: pendingWorkspaceWrite.receivedAt ?? 0, key: `ws:${pendingWorkspaceWrite.callId}`, render: (queue: AskQueuePosition) => (
      <WorkspaceWriteCard callId={pendingWorkspaceWrite.callId} workspace={pendingWorkspaceWrite.workspace}
        action={pendingWorkspaceWrite.action} path={pendingWorkspaceWrite.path} background={pendingWorkspaceWrite.background}
        options={pendingWorkspaceWrite.options} alwaysLabel={pendingWorkspaceWrite.alwaysLabel}
        expiresAt={expires(pendingWorkspaceWrite)} queue={queue}
        onConfirm={(callId, scope) => { yes('confirm_workspace_write', callId, pendingWorkspaceWrite, scope); clearPendingWorkspaceWrite(); }}
        onCancel={(callId, note) => { no('cancel_workspace_write', callId, note); clearPendingWorkspaceWrite(); }} />) },
    pendingAction && { at: pendingAction.receivedAt ?? 0, key: `act:${pendingAction.callId}`, render: (queue: AskQueuePosition) => (
      <ActionApprovalCard kind={pendingAction.kind} target={pendingAction.target} detail={pendingAction.detail}
        options={pendingAction.options} alwaysLabel={pendingAction.alwaysLabel} title={pendingAction.title} why={pendingAction.why}
        permKind={pendingAction.permKind} background={pendingAction.background}
        expiresAt={expires(pendingAction)} queue={queue}
        onConfirm={(scope) => { yes('confirm_action', pendingAction.callId, pendingAction, scope); clearPendingAction(); }}
        onCancel={(note) => { no('cancel_action', pendingAction.callId, note); clearPendingAction(); }} />) },
    pendingSchedule && { at: pendingSchedule.receivedAt ?? 0, key: `sched:${pendingSchedule.callId}`, render: (queue: AskQueuePosition) => (
      <ScheduleGrantCard callId={pendingSchedule.callId} name={pendingSchedule.name} when={pendingSchedule.when}
        background={pendingSchedule.background} options={pendingSchedule.options} alwaysLabel={pendingSchedule.alwaysLabel}
        expiresAt={expires(pendingSchedule)} queue={queue}
        onConfirm={(callId, scope) => { yes('confirm_schedule', callId, pendingSchedule, scope); clearPendingSchedule(); }}
        onCancel={(callId, note) => { no('cancel_schedule', callId, note); clearPendingSchedule(); }} />) },
    pendingCapability && { at: pendingCapability.receivedAt ?? 0, key: `cap:${pendingCapability.callId}`, render: (queue: AskQueuePosition) => (
      <CapabilityProposeCard card={pendingCapability} callId={pendingCapability.callId}
        expiresAt={expires(pendingCapability)} queue={queue}
        onConfirm={(callId, keys, folders) => { send({ type: 'confirm_capability', call_id: callId, keys, folders }); clearPendingCapability(); }}
        onCancel={(callId) => { send({ type: 'cancel_capability', call_id: callId }); clearPendingCapability(); }} />) },
    pendingConnectMcp && { at: Number.MAX_SAFE_INTEGER, key: `mcp:${pendingConnectMcp.callId}`, render: (queue: AskQueuePosition) => (
      <ConnectMcpCard callId={pendingConnectMcp.callId} label={pendingConnectMcp.label} labelKey={pendingConnectMcp.labelKey}
        transport={pendingConnectMcp.transport} command={pendingConnectMcp.command} args={pendingConnectMcp.argv}
        url={pendingConnectMcp.url} envKeys={pendingConnectMcp.envKeys} prerequisites={pendingConnectMcp.prerequisites}
        requiresPath={pendingConnectMcp.requiresPath} pathPlaceholder={pendingConnectMcp.pathPlaceholder} queue={queue}
        onApplied={(res) => {
          // Secret-free confirm: server_id + tool_count only — no env values, no
          // client-computed tier counts (the backend recomputes the honest tier split
          // and emits mcp_connect_followup, which clears this card).
          if (res.ok) {
            send({ type: 'confirm_connect_mcp', call_id: pendingConnectMcp.callId, server_id: res.serverId, tool_count: res.toolCount });
          }
        }}
        onCancel={() => clearPendingConnectMcp()} />) },
  ].filter((x): x is QueuedAsk & { at: number } => !!x).sort((a, b) => a.at - b.at);

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
