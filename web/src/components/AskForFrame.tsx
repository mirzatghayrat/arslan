import ActionApprovalCard from "./ActionApprovalCard";
import RunCommandCard from "./RunCommandCard";
import ScheduleGrantCard from "./ScheduleGrantCard";
import WindowOnlyCard from "./WindowOnlyCard";
import WorkspaceWriteCard from "./WorkspaceWriteCard";
import type { AskQueuePosition } from "./kit";
import { WINDOW_ONLY_KINDS } from "./kit/askParts";

/** A pending card as the server keeps it (GET /approvals/pending). */
export interface PendingAsk {
  call_id: string;
  conversation_id: string;
  frame: Record<string, unknown> & { type: string; call_id: string };
  opened_at: number;
  expires_at: number;
}

/** 0.1.61 §A4: what an answer from outside the chat carries — a v2 card's scope on a yes (one it offered), the user's note on a No.
 *  Absent for an old card, whose answer is exactly as before. */
export type AnswerExtra = { scope?: string; note?: string };

/** Kinds that may be answered outside the chat (they share the reply rule in approvals.ANSWERS). */
export const ANSWERABLE = new Set(["propose_run_command", "propose_action", "propose_workspace_write", "propose_schedule"]);

/**
 * The right asking card for a registered frame (0.1.55): the Inbox's "现在就要你批准". The card
 * answers through `onAnswer`, which goes to POST /approvals/{call_id}/answer — never a socket.
 * 0.1.61 §A4: the same card, with the same choices, the same question and the same countdown (the
 * server's own expiry) as in the chat; its permission kind and the model's why reach it too.
 *
 * A card that is answered only where its whole card is shown (a new capability: `WINDOW_ONLY_KINDS`) has no Allow here, whatever its type: the
 * server refuses the Inbox's yes, so "Open in Arslan" stands in its place (WindowOnlyCard) and saying no stays.
 */
export default function AskForFrame({ ask, queue, onAnswer, onOpenContext }: {
  ask: PendingAsk; queue?: AskQueuePosition;
  onAnswer: (approve: boolean, extra?: AnswerExtra) => void; onOpenContext?: () => void;
}) {
  const f = ask.frame;
  const str = (k: string) => (typeof f[k] === "string" ? (f[k] as string) : "");
  const options = Array.isArray(f.options) ? f.options.filter((o): o is string => typeof o === "string") : [];
  const v2 = { options: options.length ? options : undefined, alwaysLabel: str("always_label") || undefined };
  const common = { expiresAt: ask.expires_at * 1000, queue, onOpenContext };
  const yes = (scope?: string) => onAnswer(true, scope ? { scope } : undefined);
  const no = (note?: string) => onAnswer(false, note ? { note } : undefined);
  if (ANSWERABLE.has(f.type) && typeof f.perm_kind === "string" && WINDOW_ONLY_KINDS.has(f.perm_kind)) {
    // What it asks, in the frame's own words: its title, else what it names; the literal subject under it unless that is the heading itself.
    const what = str("target") || str("pretty") || str("path") || str("name");
    const heading = str("title") || what || str("kind");
    return <WindowOnlyCard heading={heading} subject={what && what !== heading ? what : ""} background={f.background === true}
      expiresAt={common.expiresAt} queue={queue} onOpen={() => onOpenContext?.()} onNo={no} onOpenContext={onOpenContext} />;
  }
  switch (f.type) {
    case "propose_run_command":
      // The server never keeps "remember" from the Inbox: an old card's tick is not offered here.
      return <RunCommandCard callId={ask.call_id} pretty={str("pretty")} reason={str("reason")}
        remoteHost={str("remote_host")} fingerprints={(f.fingerprints as string[]) ?? []}
        background={f.background === true} why={str("why")} permKind={str("perm_kind") || undefined}
        sandbox={f.sandbox === "outside" || f.sandbox === "retry" ? f.sandbox : undefined} noRemember {...v2}
        {...common} onConfirm={(_id, _remember, scope) => yes(scope)} onCancel={(_id, note) => no(note)} />;
    case "propose_action":
      return <ActionApprovalCard kind={str("kind")} target={str("target")} detail={str("detail")} {...v2}
        title={str("title") || undefined} why={str("why") || undefined} permKind={str("perm_kind") || undefined}
        background={f.background === true}
        {...common} onConfirm={(scope) => yes(scope)} onCancel={(note) => no(note)} />;
    case "propose_workspace_write":
      return <WorkspaceWriteCard callId={ask.call_id} workspace={str("workspace")} action={str("action")}
        path={str("path")} background={f.background === true} {...v2}
        {...common} onConfirm={(_id, scope) => yes(scope)} onCancel={(_id, note) => no(note)} />;
    case "propose_schedule":
      return <ScheduleGrantCard callId={ask.call_id} name={str("name")} when={str("when")} background={f.background === true} {...v2}
        {...common} onConfirm={(_id, scope) => yes(scope)} onCancel={(_id, note) => no(note)} />;
    default:
      return null;
  }
}
