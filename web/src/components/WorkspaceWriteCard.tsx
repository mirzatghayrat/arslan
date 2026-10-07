import { useTranslation } from "react-i18next";
import { FileText, LockKeyhole } from "lucide-react";
import { AskCard, CodeBox, type AskQueuePosition } from "./kit";
import { lineIcon } from "./kit/askParts";

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
  queue?: AskQueuePosition;
  onOpenContext?: () => void;
  onConfirm: (callId: string) => void;
  onCancel: (callId: string) => void;
}

/**
 * A `propose_workspace_write` grant. It asks about a CAPABILITY, not a filename:
 * approving lets Arslan write anywhere in the folder for the rest of the session,
 * so the FOLDER leads and the file is context; no "remember" — it already lasts.
 */
export default function WorkspaceWriteCard({ callId, workspace, action, path, background, expiresAt, queue,
                                             onOpenContext, onConfirm, onCancel }: Props) {
  const { t } = useTranslation();
  const verb = action === "edit_file" ? t("wswrite.action.edit") : t("wswrite.action.write");
  return (
    <AskCard testId="wswrite-card" who={background ? t("jobs.askingBadge") : t("kit.whoArslan")}
      title={t("wswrite.label")}
      detail={<><p className="text-[13px] text-muted-foreground">{t("wswrite.body")}</p><CodeBox code={workspace} numbered={false} /></>}
      context={[{ icon: lineIcon(FileText), text: `${verb} · ${path}` },
                { icon: lineIcon(LockKeyhole), text: t("wswrite.scope") }]}
      expiresAt={expiresAt} queue={queue} onOpenContext={onOpenContext}
      allowLabel={t("wswrite.allow")} declineLabel={t("wswrite.deny")}
      allowTestId="wswrite-allow" declineTestId="wswrite-deny"
      onAllow={() => onConfirm(callId)} onDecline={() => onCancel(callId)} />
  );
}
