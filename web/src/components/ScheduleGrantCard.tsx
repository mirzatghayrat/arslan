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
  /** A yes answers (callId, scope). */
  onConfirm: (callId: string, scope?: string) => void;
  /** A No may carry the user's note. */
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
 * the cadence leads. The card says what an unattended run does: it never waits for anyone, so a
 * step that needs an OK is skipped; what needs none (reading, ordinary commands in the sandbox,
 * writing in Arslan's own folder) still runs (scheduler.run_arslan_turn). The person chooses how
 * long the yes lasts (the frame's options, 0.1.61: permissions.decide sends every schedule card),
 * and a No takes a note.
 */
export default function ScheduleGrantCard({ callId, name, when, background, expiresAt, options, alwaysLabel, busy, queue,
                                            onOpenContext, onConfirm, onCancel }: Props) {
  const { t } = useTranslation();
  // Starts on the narrowest choice the card shows: Always is never the default, whatever its place.
  const [scope, setScope] = useState(() => scopeToSend(options, undefined, alwaysLabel) ?? "");
  return (
    <AskCard testId="schedule-card" who={background ? t("jobs.askingBadge") : t("kit.whoArslan")}
      title={t("schedgrant.label")}
      detail={<><p className="text-[13px] text-muted-foreground">{t("schedgrant.body")}</p><CodeBox code={name} numbered={false} /></>}
      context={[{ icon: lineIcon(CalendarClock), text: humanCadence(when, t) },
                // The choice says how long the yes lasts; this line says only what an unattended run
                // does (it never waits: a step that needs you is skipped).
                { icon: lineIcon(Eye), text: <span data-testid="schedule-unattended">{t("schedgrant.unattended")}</span> }]}
      // "In this conversation" lets it create ANY scheduled task here without asking (the grant's target is every schedule).
      options={<ScopeChoice options={options} value={scope} onChange={setScope} alwaysLabel={alwaysLabel}
        conversationLabel={t("schedgrant.anyTask")} testId="schedule-choice" />}
      extra={<DeclineNote testId="schedule-note" disabled={busy}
        onDeclineWithNote={(note) => (note ? onCancel(callId, note) : onCancel(callId))} />}
      expiresAt={expiresAt} queue={queue} busy={busy} onOpenContext={onOpenContext}
      allowDisabled={scopeToSend(options, scope, alwaysLabel) === undefined}
      allowLabel={t("schedgrant.allow")} declineLabel={t("schedgrant.deny")}
      allowTestId="schedule-allow" declineTestId="schedule-deny"
      onAllow={() => onConfirm(callId, scopeToSend(options, scope, alwaysLabel))}
      onDecline={() => onCancel(callId)} />
  );
}
