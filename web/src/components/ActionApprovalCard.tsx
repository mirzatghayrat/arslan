import { AppWindow, Eye, Globe, LockKeyhole, Terminal, TriangleAlert, Zap } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { ActionKind } from "../api/client.types";
import { AskCard, CodeBox, type AskQueuePosition } from "./kit";
import { lineIcon, scriptRiskLine } from "./kit/askParts";

const ICONS = { browser_site: Globe, mac_shortcut: Zap, mac_script: Terminal,
  desktop_look: Eye, desktop_app: AppWindow, desktop_risky: TriangleAlert } as const;

/**
 * 0.1.45 / 0.1.53: a job asks before it acts — browser (once per website per job),
 * Shortcut (once per Shortcut per job), AppleScript (every time, shown in full), Mac
 * apps through Arslan Hands (looking: once per app per conversation; acting: once
 * per app per job; a button that deletes / sends / pays / buys / transfers / submits:
 * every time, named by its real label). 0.1.55: in the AskCard; for AppleScript the
 * risk line is read from the script itself (decision 1), never from a summary.
 */
export default function ActionApprovalCard({ kind, target, detail, expiresAt, queue, onOpenContext, onConfirm, onCancel }: {
  kind: ActionKind; target: string; detail: string;
  expiresAt?: number | null; queue?: AskQueuePosition; onOpenContext?: () => void;
  onConfirm: () => void; onCancel: () => void;
}) {
  const { t } = useTranslation();
  const Icon = ICONS[kind] ?? Terminal;
  const script = kind === "mac_script";
  return (
    <AskCard testId="action-card" attrs={{ "data-kind": kind, "data-risky": String(kind === "desktop_risky") }}
      who={kind === "desktop_look" ? t("kit.whoArslan") : t("jobs.askingBadge")}
      title={<span className="inline-flex items-start gap-2">{lineIcon(Icon)}<span>{t(`hands.title.${kind}`, { target })}</span></span>}
      risk={script ? scriptRiskLine(detail, t) : null}
      destructive={kind === "desktop_risky"}
      detail={script
        ? <div data-testid="action-script"><CodeBox code={detail} marks={["delete", "send", "move", "do shell script", "quit"]} /></div>
        : <p className="text-[13px] text-muted-foreground">{detail}</p>}
      context={[{ icon: lineIcon(LockKeyhole), text: t(`hands.scope.${kind}`) }]}
      expiresAt={expiresAt} queue={queue} onOpenContext={onOpenContext}
      allowLabel={t("hands.allow")} declineLabel={t("hands.deny")}
      allowTestId="action-allow" declineTestId="action-deny"
      onAllow={onConfirm} onDecline={onCancel} />
  );
}
