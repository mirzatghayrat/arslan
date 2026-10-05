import { AppWindow, Eye, Globe, Terminal, TriangleAlert, Zap } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { ActionKind } from "../api/client.types";

const ICONS = { browser_site: Globe, mac_shortcut: Zap, mac_script: Terminal,
  desktop_look: Eye, desktop_app: AppWindow, desktop_risky: TriangleAlert } as const;

// 0.1.45: a background job asks before it acts. Browser: once per website for
// this job. Shortcut: once per Shortcut for this job. AppleScript: every time,
// shown in full. 0.1.53 Mac apps (Arslan Hands): looking at an app once per
// conversation (also from a chat turn, so no "background job" badge); acting
// in an app once per job; a button that deletes, sends, pays, buys, transfers
// or submits every time, named by its real label. Only a click here approves;
// nothing spoken does.
export default function ActionApprovalCard({ kind, target, detail, onConfirm, onCancel }: {
  kind: ActionKind; target: string; detail: string;
  onConfirm: () => void; onCancel: () => void;
}) {
  const { t } = useTranslation();
  const Icon = ICONS[kind] ?? Terminal;
  return <div className={`runcmd-card${kind === "desktop_risky" ? " runcmd-card--risky" : ""}`}
    data-testid="action-card" data-kind={kind}>
    {kind !== "desktop_look" && <div className="runcmd-card__reason">{t("jobs.askingBadge")}</div>}
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
