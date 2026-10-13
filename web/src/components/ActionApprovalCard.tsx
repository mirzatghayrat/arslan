import { useState } from "react";
import { AppWindow, CircleQuestionMark, Eye, Globe, LockKeyhole, Terminal, TriangleAlert, Zap } from "lucide-react";
import { useTranslation } from "react-i18next";
import { AskCard, CodeBox, type AskQueuePosition } from "./kit";
import { DeclineNote, RED_KINDS, ScopeChoice, lineIcon, offeredScopes, scopeToSend, scriptRiskLine, visibleScopes } from "./kit/askParts";

const ICONS: Record<string, typeof Globe> = { browser_site: Globe, mac_shortcut: Zap, mac_script: Terminal,
  desktop_look: Eye, desktop_app: AppWindow, desktop_risky: TriangleAlert };
/** The Hands kinds whose card line says what is granted apart from for how long (`hands.grant.<kind>`,
 *  cut from `hands.scope.<kind>`). A Shortcut's line is only its scope, so it has none. */
const GRANTS = new Set(["browser_site", "mac_script", "desktop_look", "desktop_app", "desktop_risky"]);

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
export default function ActionApprovalCard({ kind, target, detail, expiresAt, options, alwaysLabel, title, why, permKind,
  background, busy, queue, onOpenContext, onConfirm, onCancel }: {
  kind: string; target: string; detail: string;
  expiresAt?: number | null;
  /** 0.1.61 §A4: a card from the permission layer — its choices, its literal "Always" scope, its
   *  one-line question (the server's words, used only for a kind this card has no words for), the
   *  model's own reason (`why`: for such a kind it is the question, ahead of the title; for a kind with
   *  words of its own it is shown as "Arslan says") and its permission kind (money, app_risky…). All
   *  absent on an old frame. */
  options?: string[]; alwaysLabel?: string; title?: string; why?: string; permKind?: string; background?: boolean;
  /** An answer is on its way: the card is inert (its buttons, its keys and its note). */
  busy?: boolean;
  queue?: AskQueuePosition; onOpenContext?: () => void;
  /** An old card answers (); a v2 card answers (scope). */
  onConfirm: (scope?: string) => void;
  /** A v2 card's No may carry the user's note. */
  onCancel: (note?: string) => void;
}) {
  const { t } = useTranslation();
  // Own keys only: a kind named "constructor" or "toString" is a kind this card has no words for.
  // (Object.hasOwn needs WebKit 15.4; the app still runs on macOS 11.)
  const known = Object.prototype.hasOwnProperty.call(ICONS, kind);
  const Icon = known ? ICONS[kind] : CircleQuestionMark;
  const script = kind === "mac_script";
  const offered = offeredScopes(options, permKind);
  const v2 = Boolean(offered?.length);
  // Starts on the narrowest choice the card shows: Always is never the default, whatever its place.
  const [scope, setScope] = useState(() => scopeToSend(offered, undefined, alwaysLabel) ?? "");
  // A scope sentence ("for this piece of work only") would contradict a choice shown below it.
  const choice = visibleScopes(offered, alwaysLabel).length > 1;
  // The kind's own line says what is granted and for how long. With a choice to pick, only the first is
  // left to say; a kind with nothing but a scope sentence says nothing.
  const grantLine = !known ? null : !choice ? t(`hands.scope.${kind}`) : GRANTS.has(kind) ? t(`hands.grant.${kind}`) : null;
  // The question for a kind this card has no words for (§A4): the model's own line when it gave one — it writes in
  // the person's language — else the frame's title, which is the server's English (plan R11: localised in PR 8);
  // a bare target is not words. A known kind keeps its own title, which names what is granted, and shows the model's
  // line as "Arslan says" (the way the command card shows a sandbox why) so it is not lost.
  const modelLine = (why ?? "").trim();
  const frameTitle = (title ?? "").trim();
  const fromFrame = !known && !modelLine && Boolean(frameTitle);
  const heading = known ? t(`hands.title.${kind}`, { target }) : (modelLine || frameTitle || target);
  // The model's line may frame the ask; it is never the only description of it (a prompt-injected model could word a
  // harmless-sounding one). So under it the card says what is being approved in the server's own words: the frame's
  // literal title, else the bare target. Not translated and not marked as the model's. Without a model line the title
  // (or the target) is the heading itself, and is not said twice.
  const subject = known || !modelLine ? "" : (frameTitle || target);
  const detailLine = detail ? <p className="text-[13px] text-muted-foreground">{detail}</p> : null;
  // Allow is red for a step that pays or cannot be undone (plan R14: the kit's one RED_KINDS, shared with the command card).
  const red = kind === "desktop_risky" || RED_KINDS.has(permKind ?? "");
  return (
    <AskCard testId="action-card" attrs={{ "data-kind": kind, "data-risky": String(red) }}
      who={v2 ? (background ? t("jobs.askingBadge") : t("kit.whoArslan"))
        : kind === "desktop_look" ? t("kit.whoArslan") : t("jobs.askingBadge")}
      title={<span className="inline-flex max-w-full items-start gap-2">{lineIcon(Icon)}
        <span data-testid="action-title" lang={fromFrame ? "en" : undefined} className="min-w-0 [overflow-wrap:anywhere]">{heading}</span></span>}
      said={known && modelLine ? modelLine : null} saidTestId="action-said"
      risk={script ? scriptRiskLine(detail, t) : null}
      destructive={red}
      detail={script
        ? <div data-testid="action-script"><CodeBox code={detail} marks={["delete", "send", "move", "do shell script", "quit"]} /></div>
        : subject ? (
          <div className="flex flex-col gap-1.5">
            <p data-testid="action-subject" lang={frameTitle ? "en" : undefined}
              className="break-words rounded-[10px] bg-surface-raised px-3 py-2.5 text-[15px] font-semibold leading-[1.4] text-foreground">{subject}</p>
            {detailLine}
          </div>)
        : detailLine}
      context={grantLine ? [{ icon: lineIcon(LockKeyhole), text: grantLine }] : []}
      options={v2 ? <ScopeChoice options={offered} value={scope} onChange={setScope} alwaysLabel={alwaysLabel} testId="action-scope" /> : undefined}
      extra={v2 ? <DeclineNote testId="action-note" disabled={busy}
        onDeclineWithNote={(note) => (note ? onCancel(note) : onCancel())} /> : undefined}
      expiresAt={expiresAt} queue={queue} busy={busy} onOpenContext={onOpenContext}
      allowDisabled={v2 && scopeToSend(offered, scope, alwaysLabel) === undefined}
      allowLabel={t("hands.allow")} declineLabel={t("hands.deny")}
      allowTestId="action-allow" declineTestId="action-deny"
      onAllow={() => (v2 ? onConfirm(scopeToSend(offered, scope, alwaysLabel)) : onConfirm())}
      onDecline={() => onCancel()} />
  );
}
