import type { TFunction } from "i18next";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { CalendarClock, Eye } from "lucide-react";
import { AskCard, CodeBox, type AskQueuePosition } from "./kit";
import { DeclineNote, ScopeChoice, lineIcon, scopeToSend } from "./kit/askParts";

interface Props {
  callId: string;
  /** The task's name, as Arslan proposed it. */
  name: string;
  /** Raw cadence from the backend: "every: 3600" or "cron: 0 9 * * *". */
  when: string;
  background?: boolean;
  expiresAt?: number | null;
  /** 0.1.61 §A4: Once / In this conversation (a card from the permission layer); absent on an old frame. */
  options?: string[];
  alwaysLabel?: string;
  /** An answer is on its way: the card is inert (its buttons, its keys and its note). */
  busy?: boolean;
  queue?: AskQueuePosition;
  onOpenContext?: () => void;
  /** An old card answers (callId); a v2 card answers (callId, scope). */
  onConfirm: (callId: string, scope?: string) => void;
  /** A v2 card's No may carry the user's note. */
  onCancel: (callId: string, note?: string) => void;
}

/**
 * A backend cadence a person can judge in one second ("every: 3600" vs "every:
 * 86400" differ 24× in cost). A cron expression is left ALONE: prose invites a
 * confident wrong reading (which timezone? which days?). 0.1.55: localised (it
 * was hard-coded English); without `t`, English — kept for callers outside React.
 */
export function humanCadence(when: string, t?: TFunction): string {
  const m = /^\s*every\s*:\s*(\d+)\s*$/i.exec(when || "");
  if (!m) return when;
  const seconds = Number(m[1]);
  const say = (unit: "day" | "hour" | "minute", n: number, en: string) =>
    t ? t(n === 1 ? `schedgrant.every_${unit}` : `schedgrant.every_n_${unit}s`, { count: n }) : en;
  if (seconds % 86400 === 0) {
    const d = seconds / 86400;
    return say("day", d, d === 1 ? "every day" : `every ${d} days`);
  }
  if (seconds % 3600 === 0) {
    const h = seconds / 3600;
    return say("hour", h, h === 1 ? "every hour" : `every ${h} hours`);
  }
  const minutes = Math.round(seconds / 60);
  return say("minute", minutes, minutes === 1 ? "every minute" : `every ${minutes} minutes`);
}

/**
 * A `propose_schedule` grant: no "remember". The thing agreed to recurs and keeps costing, so
 * the cadence leads; the card says what a scheduled run cannot do (it only looks and reports,
 * with nobody watching). An old card is asked once per session; a card from the permission layer
 * (0.1.61) lets the person choose how long, and takes a note on No.
 */
export default function ScheduleGrantCard({ callId, name, when, background, expiresAt, options, alwaysLabel, busy, queue,
                                            onOpenContext, onConfirm, onCancel }: Props) {
  const { t } = useTranslation();
  const v2 = Boolean(options?.length);
  // Starts on the narrowest choice the card shows: Always is never the default, whatever its place.
  const [scope, setScope] = useState(() => scopeToSend(options, undefined, alwaysLabel) ?? "");
  return (
    <AskCard testId="schedule-card" who={background ? t("jobs.askingBadge") : t("kit.whoArslan")}
      title={t("schedgrant.label")}
      detail={<><p className="text-[13px] text-muted-foreground">{t("schedgrant.body")}</p><CodeBox code={name} numbered={false} /></>}
      context={[{ icon: lineIcon(CalendarClock), text: humanCadence(when, t) },
                // 0.1.61: a v2 card's choice says how long the yes lasts; this line says only what an
                // unattended run does (it never waits: a step that needs you is skipped).
                v2 ? { icon: lineIcon(Eye), text: <span data-testid="schedule-unattended">{t("schedgrant.unattended")}</span> }
                   : { icon: lineIcon(Eye), text: <span data-testid="schedule-scope">{t("schedgrant.scope")}</span> }]}
      options={v2 ? <ScopeChoice options={options} value={scope} onChange={setScope} alwaysLabel={alwaysLabel} testId="schedule-choice" /> : undefined}
      extra={v2 ? <DeclineNote testId="schedule-note" disabled={busy}
        onDeclineWithNote={(note) => (note ? onCancel(callId, note) : onCancel(callId))} /> : undefined}
      expiresAt={expiresAt} queue={queue} busy={busy} onOpenContext={onOpenContext}
      allowLabel={t("schedgrant.allow")} declineLabel={t("schedgrant.deny")}
      allowTestId="schedule-allow" declineTestId="schedule-deny"
      onAllow={() => (v2 ? onConfirm(callId, scopeToSend(options, scope, alwaysLabel)) : onConfirm(callId))}
      onDecline={() => onCancel(callId)} />
  );
}
