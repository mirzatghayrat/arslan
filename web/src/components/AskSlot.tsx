import { useArslanStore } from "../stores/arslanStore";
import ActionApprovalCard from "./ActionApprovalCard";
import CapabilityProposeCard from "./capabilities/CapabilityProposeCard";
import ConnectMcpCard from "./ConnectMcpCard";
import EnrollNodeCard from "./EnrollNodeCard";
import RunCommandCard from "./RunCommandCard";
import ScheduleGrantCard from "./ScheduleGrantCard";
import WorkspaceWriteCard from "./WorkspaceWriteCard";
import { AskQueue, type AskQueuePosition, type QueuedAsk } from "./kit";

/**
 * The one place asking cards appear in the chat (0.1.55 S2): every pending ask,
 * oldest first, in one AskQueue ("‹ 1 / 3 ›"). They used to render six overlays
 * into the same absolute spot, so two waiting at once sat on top of each other.
 * Same frames in, same confirm / cancel frames out.
 */
export default function AskSlot({ send }: { send: (frame: Record<string, unknown>) => void }) {
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

  // 0.1.55 S2: the pending asks, oldest first, for the one AskQueue slot. 300 s is the
  // server's card expiry (approvals.TIMEOUT_S and the chat socket's own wait).
  const ASK_MS = 300_000;
  const expires = (at?: number) => (at ? at + ASK_MS : null);
  const items: QueuedAsk[] = [
    pendingCommand && { at: pendingCommand.receivedAt ?? 0, key: `cmd:${pendingCommand.callId}`, render: (queue: AskQueuePosition) => (
      <RunCommandCard callId={pendingCommand.callId} pretty={pendingCommand.pretty} reason={pendingCommand.reason}
        remoteHost={pendingCommand.remoteHost} fingerprints={pendingCommand.fingerprints}
        background={pendingCommand.background} sandbox={pendingCommand.sandbox} why={pendingCommand.why}
        expiresAt={expires(pendingCommand.receivedAt)} queue={queue}
        onConfirm={(callId, remember) => { send({ type: 'confirm_run_command', call_id: callId, remember }); clearPendingCommand(); }}
        onCancel={(callId) => { send({ type: 'cancel_run_command', call_id: callId }); clearPendingCommand(); }} />) },
    pendingEnrollNode && { at: pendingEnrollNode.receivedAt ?? 0, key: `node:${pendingEnrollNode.callId}`, render: (queue: AskQueuePosition) => (
      <EnrollNodeCard callId={pendingEnrollNode.callId} name={pendingEnrollNode.name} host={pendingEnrollNode.host}
        user={pendingEnrollNode.user} fingerprints={pendingEnrollNode.fingerprints}
        expiresAt={expires(pendingEnrollNode.receivedAt)} queue={queue} onDone={() => clearPendingEnrollNode()} />) },
    pendingWorkspaceWrite && { at: pendingWorkspaceWrite.receivedAt ?? 0, key: `ws:${pendingWorkspaceWrite.callId}`, render: (queue: AskQueuePosition) => (
      <WorkspaceWriteCard callId={pendingWorkspaceWrite.callId} workspace={pendingWorkspaceWrite.workspace}
        action={pendingWorkspaceWrite.action} path={pendingWorkspaceWrite.path} background={pendingWorkspaceWrite.background}
        expiresAt={expires(pendingWorkspaceWrite.receivedAt)} queue={queue}
        onConfirm={(callId) => { send({ type: 'confirm_workspace_write', call_id: callId }); clearPendingWorkspaceWrite(); }}
        onCancel={(callId) => { send({ type: 'cancel_workspace_write', call_id: callId }); clearPendingWorkspaceWrite(); }} />) },
    pendingAction && { at: pendingAction.receivedAt ?? 0, key: `act:${pendingAction.callId}`, render: (queue: AskQueuePosition) => (
      <ActionApprovalCard kind={pendingAction.kind} target={pendingAction.target} detail={pendingAction.detail}
        expiresAt={expires(pendingAction.receivedAt)} queue={queue}
        onConfirm={() => { send({ type: 'confirm_action', call_id: pendingAction.callId }); clearPendingAction(); }}
        onCancel={() => { send({ type: 'cancel_action', call_id: pendingAction.callId }); clearPendingAction(); }} />) },
    pendingSchedule && { at: pendingSchedule.receivedAt ?? 0, key: `sched:${pendingSchedule.callId}`, render: (queue: AskQueuePosition) => (
      <ScheduleGrantCard callId={pendingSchedule.callId} name={pendingSchedule.name} when={pendingSchedule.when}
        background={pendingSchedule.background} expiresAt={expires(pendingSchedule.receivedAt)} queue={queue}
        onConfirm={(callId) => { send({ type: 'confirm_schedule', call_id: callId }); clearPendingSchedule(); }}
        onCancel={(callId) => { send({ type: 'cancel_schedule', call_id: callId }); clearPendingSchedule(); }} />) },
    pendingCapability && { at: pendingCapability.receivedAt ?? 0, key: `cap:${pendingCapability.callId}`, render: (queue: AskQueuePosition) => (
      <CapabilityProposeCard card={pendingCapability} callId={pendingCapability.callId}
        expiresAt={expires(pendingCapability.receivedAt)} queue={queue}
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

  if (!items.length) return null;
  return (
    <div className="ask-slot" data-testid="ask-slot">
      <AskQueue items={items} />
    </div>
  );
}
