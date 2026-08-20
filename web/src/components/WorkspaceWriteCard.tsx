import { useTranslation } from "react-i18next";

interface Props {
  callId: string;
  /** The directory being granted — the real subject of this decision. */
  workspace: string;
  /** "write_file" | "edit_file" — what triggered the ask. */
  action: string;
  /** The file that triggered it, shown as context. */
  path: string;
  onConfirm: (callId: string) => void;
  onCancel: (callId: string) => void;
}

/**
 * Grant card for a backend `propose_workspace_write` frame.
 *
 * This asks about a CAPABILITY, not a filename: approving lets Arslan write
 * anywhere in the named directory for the rest of this session. So the card
 * leads with the DIRECTORY (the thing actually being agreed to), shows the
 * triggering file only as context, and carries no "remember" checkbox —
 * approval already lasts the session, and a checkbox would imply the choice
 * was narrower than it is.
 */
export default function WorkspaceWriteCard({
  callId, workspace, action, path, onConfirm, onCancel,
}: Props) {
  const { t } = useTranslation();
  const verb = action === "edit_file" ? t("wswrite.action.edit") : t("wswrite.action.write");
  return (
    <div className="runcmd-card" data-testid="wswrite-card">
      <div className="runcmd-card__label">{t("wswrite.label")}</div>
      <p className="text-[12px] text-foreground font-sans">{t("wswrite.body")}</p>
      <pre className="runcmd-card__cmd">{workspace}</pre>
      <div className="runcmd-card__reason">
        {verb} · {path}
      </div>
      <p className="text-[10.5px] text-subtle-foreground font-sans">{t("wswrite.scope")}</p>
      <div className="runcmd-card__actions">
        <button
          type="button"
          className="runcmd-card__btn runcmd-card__btn--primary"
          data-testid="wswrite-allow"
          onClick={() => onConfirm(callId)}
        >
          {t("wswrite.allow")}
        </button>
        <button
          type="button"
          className="runcmd-card__btn"
          data-testid="wswrite-deny"
          onClick={() => onCancel(callId)}
        >
          {t("wswrite.deny")}
        </button>
      </div>
    </div>
  );
}
