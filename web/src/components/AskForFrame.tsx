import ActionApprovalCard from "./ActionApprovalCard";
import RunCommandCard from "./RunCommandCard";
import ScheduleGrantCard from "./ScheduleGrantCard";
import WorkspaceWriteCard from "./WorkspaceWriteCard";
import type { AskQueuePosition } from "./kit";

/** A pending card as the server keeps it (GET /approvals/pending). */
export interface PendingAsk {
  call_id: string;
  conversation_id: string;
  frame: Record<string, unknown> & { type: string; call_id: string };
  opened_at: number;
  expires_at: number;
}

/** Kinds that may be answered outside the chat (they share the reply rule in approvals.ANSWERS). */
export const ANSWERABLE = new Set(["propose_run_command", "propose_action", "propose_workspace_write", "propose_schedule"]);

/**
 * The right asking card for a registered frame (0.1.55): the Inbox's "现在就要你批准",
 * and the island. The card answers through `onAnswer`, which goes to
 * POST /approvals/{call_id}/answer — never a socket.
 */
export default function AskForFrame({ ask, queue, onAnswer, onOpenContext }: {
  ask: PendingAsk; queue?: AskQueuePosition;
  onAnswer: (approve: boolean) => void; onOpenContext?: () => void;
}) {
  const f = ask.frame;
  const str = (k: string) => (typeof f[k] === "string" ? (f[k] as string) : "");
  const common = { expiresAt: ask.expires_at * 1000, queue, onOpenContext };
  switch (f.type) {
    case "propose_run_command":
      return <RunCommandCard callId={ask.call_id} pretty={str("pretty")} reason={str("reason")}
        remoteHost={str("remote_host")} fingerprints={(f.fingerprints as string[]) ?? []}
        background={f.background === true} why={str("why")}
        sandbox={f.sandbox === "outside" || f.sandbox === "retry" ? f.sandbox : undefined}
        {...common} onConfirm={() => onAnswer(true)} onCancel={() => onAnswer(false)} />;
    case "propose_action":
      return <ActionApprovalCard kind={f.kind as never} target={str("target")} detail={str("detail")}
        {...common} onConfirm={() => onAnswer(true)} onCancel={() => onAnswer(false)} />;
    case "propose_workspace_write":
      return <WorkspaceWriteCard callId={ask.call_id} workspace={str("workspace")} action={str("action")}
        path={str("path")} background={f.background === true}
        {...common} onConfirm={() => onAnswer(true)} onCancel={() => onAnswer(false)} />;
    case "propose_schedule":
      return <ScheduleGrantCard callId={ask.call_id} name={str("name")} when={str("when")} background={f.background === true}
        {...common} onConfirm={() => onAnswer(true)} onCancel={() => onAnswer(false)} />;
    default:
      return null;
  }
}
