import { useState } from "react";
import { useTranslation } from "react-i18next";
import { FileText } from "lucide-react";
import { AskCard, CodeBox, type AskQueuePosition } from "./kit";
import { DeclineNote, ScopeChoice, lineIcon, scopeToSend } from "./kit/askParts";

interface Props {
  callId: string;
  /** The directory being granted — the real subject of this decision. */
  workspace: string;
  /** "write_file" | "edit_file" — what triggered the ask. */
  action: string;
  /** The file that triggered it, shown as context. */
  path: string;
  background?: boolean;
  expiresAt?: number | null;
  /** 0.1.61 §A4: Once / In this conversation (a card from the permission layer); absent on an old frame. */
  options?: string[];
  alwaysLabel?: string;
  /** An answer is on its way: the card is inert (its buttons, its keys and its note). */
  busy?: boolean;
  queue?: AskQueuePosition;
  onOpenContext?: () => void;
  /** A yes answers (callId, scope). */
  onConfirm: (callId: string, scope?: string) => void;
  /** A No may carry the user's note. */
  onCancel: (callId: string, note?: string) => void;
}

/**
 * A `propose_workspace_write` grant. It asks about a CAPABILITY, not a filename:
 * approving lets Arslan write anywhere in the folder, so the FOLDER leads and the file is
 * context; no "remember". The person chooses how long the yes lasts (the frame's options, 0.1.61:
 * permissions.decide sends every write card), and a No takes a note.
 */
export default function WorkspaceWriteCard({ callId, workspace, action, path, background, expiresAt, options, alwaysLabel,
                                             busy, queue, onOpenContext, onConfirm, onCancel }: Props) {
  const { t } = useTranslation();
  const verb = action === "edit_file" ? t("wswrite.action.edit") : t("wswrite.action.write");
  // Starts on the narrowest choice the card shows: Always is never the default, whatever its place.
  const [scope, setScope] = useState(() => scopeToSend(options, undefined, alwaysLabel) ?? "");
  return (
    <AskCard testId="wswrite-card" who={background ? t("jobs.askingBadge") : t("kit.whoArslan")}
      title={t("wswrite.label")}
      detail={<><p className="text-[13px] text-muted-foreground">{t("wswrite.body")}</p><CodeBox code={workspace} numbered={false} /></>}
      context={[{ icon: lineIcon(FileText), text: `${verb} · ${path}` }]}
      // "In this conversation" covers any file in the folder, not the one shown (the grant's target is the folder).
      options={<ScopeChoice options={options} value={scope} onChange={setScope} alwaysLabel={alwaysLabel}
        conversationLabel={t("wswrite.anyFile")} testId="wswrite-scope" />}
      extra={<DeclineNote testId="wswrite-note" disabled={busy}
        onDeclineWithNote={(note) => (note ? onCancel(callId, note) : onCancel(callId))} />}
      expiresAt={expiresAt} queue={queue} busy={busy} onOpenContext={onOpenContext}
      allowDisabled={scopeToSend(options, scope, alwaysLabel) === undefined}
      allowLabel={t("wswrite.allow")} declineLabel={t("wswrite.deny")}
      allowTestId="wswrite-allow" declineTestId="wswrite-deny"
      onAllow={() => onConfirm(callId, scopeToSend(options, scope, alwaysLabel))}
      onDecline={() => onCancel(callId)} />
  );
}
