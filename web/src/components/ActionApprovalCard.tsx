import { useState } from "react";
import { AppWindow, Eye, Globe, LockKeyhole, Terminal, TriangleAlert, Zap } from "lucide-react";
import { useTranslation } from "react-i18next";
import { AskCard, CodeBox, type AskQueuePosition } from "./kit";
import { DeclineNote, ScopeChoice, lineIcon, scopeToSend, scriptRiskLine, visibleScopes } from "./kit/askParts";

const ICONS: Record<string, typeof Globe> = { browser_site: Globe, mac_shortcut: Zap, mac_script: Terminal,
  desktop_look: Eye, desktop_app: AppWindow, desktop_risky: TriangleAlert };
/** 0.1.61 §A11: the permission kinds whose Allow is drawn red (the step pays, or cannot be undone). */
const RED_KINDS = new Set(["money", "app_risky", "destructive"]);

/**
 * 0.1.45 / 0.1.53: a job asks before it acts — browser (once per website per job),
 * Shortcut (once per Shortcut per job), AppleScript (every time, shown in full), Mac
 * apps through Arslan Hands (looking: once per app per conversation; acting: once
 * per app per job; a button that deletes / sends / pays / buys / transfers / submits:
 * every time, named by its real label). 0.1.55: in the AskCard; for AppleScript the
 * risk line is read from the script itself (decision 1), never from a summary.
 * 0.1.61: a card from the permission layer (a frame with `options`) offers its choices and takes a
 * note on No; a kind this card has no words for reads the frame's own question.
 */
export default function ActionApprovalCard({ kind, target, detail, expiresAt, options, alwaysLabel, title, permKind,
  background, busy, queue, onOpenContext, onConfirm, onCancel }: {
  kind: string; target: string; detail: string;
  expiresAt?: number | null;
  /** 0.1.61 §A4: a card from the permission layer — its choices, its literal "Always" scope, its
   *  one-line question (the server's words, used only for a kind this card has no words for) and
   *  its permission kind (money, app_risky…). All absent on an old frame. */
  options?: string[]; alwaysLabel?: string; title?: string; permKind?: string; background?: boolean;
  /** An answer is on its way: the card is inert (its buttons, its keys and its note). */
  busy?: boolean;
  queue?: AskQueuePosition; onOpenContext?: () => void;
  /** An old card answers (); a v2 card answers (scope). */
  onConfirm: (scope?: string) => void;
  /** A v2 card's No may carry the user's note. */
  onCancel: (note?: string) => void;
}) {
  const { t } = useTranslation();
  const known = kind in ICONS;
  const Icon = ICONS[kind] ?? Terminal;
  const script = kind === "mac_script";
  const v2 = Boolean(options?.length);
  // Starts on the narrowest choice the card shows: Always is never the default, whatever its place.
  const [scope, setScope] = useState(() => scopeToSend(options, undefined, alwaysLabel) ?? "");
  // A fixed-scope line ("for this piece of work only") would contradict a choice shown below it.
  const choice = visibleScopes(options, alwaysLabel).length > 1;
  const heading = known ? t(`hands.title.${kind}`, { target }) : (title || target);
  return (
    <AskCard testId="action-card" attrs={{ "data-kind": kind, "data-risky": String(kind === "desktop_risky") }}
      who={v2 ? (background ? t("jobs.askingBadge") : t("kit.whoArslan"))
        : kind === "desktop_look" ? t("kit.whoArslan") : t("jobs.askingBadge")}
      title={<span className="inline-flex items-start gap-2">{lineIcon(Icon)}<span data-testid="action-title">{heading}</span></span>}
      risk={script ? scriptRiskLine(detail, t) : null}
      destructive={kind === "desktop_risky" || RED_KINDS.has(permKind ?? "")}
      detail={script
        ? <div data-testid="action-script"><CodeBox code={detail} marks={["delete", "send", "move", "do shell script", "quit"]} /></div>
        : <p className="text-[13px] text-muted-foreground">{detail}</p>}
      context={known && !choice ? [{ icon: lineIcon(LockKeyhole), text: t(`hands.scope.${kind}`) }] : []}
      options={v2 ? <ScopeChoice options={options} value={scope} onChange={setScope} alwaysLabel={alwaysLabel} testId="action-scope" /> : undefined}
      extra={v2 ? <DeclineNote testId="action-note" disabled={busy}
        onDeclineWithNote={(note) => (note ? onCancel(note) : onCancel())} /> : undefined}
      expiresAt={expiresAt} queue={queue} busy={busy} onOpenContext={onOpenContext}
      allowLabel={t("hands.allow")} declineLabel={t("hands.deny")}
      allowTestId="action-allow" declineTestId="action-deny"
      onAllow={() => (v2 ? onConfirm(scopeToSend(options, scope, alwaysLabel)) : onConfirm())}
      onDecline={() => onCancel()} />
  );
}
