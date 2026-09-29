import { Globe, Terminal, Zap } from "lucide-react";
import { useTranslation } from "react-i18next";

// 0.1.45: a background job asks before it acts. Browser: once per website for
// this job. Shortcut: once per Shortcut for this job. AppleScript: every time,
// shown in full. Only a click here approves; nothing spoken does.
export default function ActionApprovalCard({ kind, target, detail, onConfirm, onCancel }: {
  kind: "browser_site" | "mac_shortcut" | "mac_script"; target: string; detail: string;
  onConfirm: () => void; onCancel: () => void;
}) {
  const { t } = useTranslation();
  const Icon = kind === "browser_site" ? Globe : kind === "mac_shortcut" ? Zap : Terminal;
  return <div className="runcmd-card" data-testid="action-card" data-kind={kind}>
    <div className="runcmd-card__reason">{t("jobs.askingBadge")}</div>
    <div className="runcmd-card__label flex items-center gap-2"><Icon size={14} aria-hidden />{t(`hands.title.${kind}`, { target })}</div>
    {kind === "mac_script"
      ? <pre className="runcmd-card__cmd" data-testid="action-script">{detail}</pre>
      : <div className="runcmd-card__reason">{detail}</div>}
    <div className="runcmd-card__reason">{t(`hands.scope.${kind}`)}</div>
    <div className="runcmd-card__actions">
      <button type="button" className="runcmd-card__btn runcmd-card__btn--primary" data-testid="action-allow" onClick={onConfirm}>{t("hands.allow")}</button>
      <button type="button" className="runcmd-card__btn runcmd-card__btn--ghost" data-testid="action-deny" onClick={onCancel}>{t("hands.deny")}</button>
    </div>
  </div>;
}
