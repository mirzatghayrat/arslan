import type { ReactNode } from "react";
import AskSlot from "../AskSlot";
import { AnswerGuardScope, useAnswerGuardState } from "../kit";
import { AwayEntries, StoppedJobCards } from "./WhileAway";

/**
 * INB5b (v0.1.64): the ask slot and the conversation under it, in ONE answer guard. This is App's composition, made a component of
 * its own so it is tested as drawn (#602 review). A card leaving the slot holds what moved into place under the pointer in the
 * conversation: the away entries on top, a stopped job's card at the end. Those changing holds the slot's card. A temporary
 * conversation gets neither piece, since what waited belongs to a conversation that is kept.
 */
export default function ConversationStage({ send, conversationId, temporary, onOpenConversation, onOpenModelSettings, children }: {
  send: (frame: Record<string, unknown>) => void;
  conversationId: string;
  temporary: boolean;
  /** `created` is true when the app must first make a conversation with this id for the job to report into. */
  onOpenConversation: (conversationId: string, created: boolean) => void;
  /** Where "add a model first" sends the user. */
  onOpenModelSettings: () => void;
  /** The conversation itself, given what it shows on top of its messages and after them. */
  children: (pieces: { header?: ReactNode; footer?: ReactNode }) => ReactNode;
}) {
  const guard = useAnswerGuardState();
  return (
    <AnswerGuardScope value={guard}>
      <AskSlot send={send} />
      {children(temporary ? {} : {
        header: <AwayEntries conversationId={conversationId} />,
        footer: <StoppedJobCards conversationId={conversationId} onOpenConversation={onOpenConversation}
          onOpenModelSettings={onOpenModelSettings} />,
      })}
    </AnswerGuardScope>
  );
}
