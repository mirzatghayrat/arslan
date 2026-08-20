import { useTranslation } from "react-i18next";

interface Props {
  callId: string;
  /** The task's name, as Arslan proposed it. */
  name: string;
  /** Raw cadence from the backend: "every: 3600" or "cron: 0 9 * * *". */
  when: string;
  onConfirm: (callId: string) => void;
  onCancel: (callId: string) => void;
}

/**
 * Turn a backend cadence into something a person can judge in one second.
 *
 * `every: 3600` and `every: 86400` differ by 24× in what they will cost, and
 * neither number says so at a glance. A cron expression is left ALONE on
 * purpose: rendering "0 9 * * *" as prose invites a confident wrong reading
 * (which timezone? which days?), and the person approving it can read the
 * expression they are being shown.
 */
export function humanCadence(when: string): string {
  const m = /^\s*every\s*:\s*(\d+)\s*$/i.exec(when || "");
  if (!m) return when;
  const seconds = Number(m[1]);
  if (seconds % 86400 === 0) {
    const d = seconds / 86400;
    return d === 1 ? "every day" : `every ${d} days`;
  }
  if (seconds % 3600 === 0) {
    const h = seconds / 3600;
    return h === 1 ? "every hour" : `every ${h} hours`;
  }
  const minutes = Math.round(seconds / 60);
  return minutes === 1 ? "every minute" : `every ${minutes} minutes`;
}

/**
 * Grant card for a backend `propose_schedule` frame.
 *
 * Asks ONCE per session about a capability, so no "remember" checkbox — the
 * same reasoning as the workspace-write card. What differs is that the thing
 * being agreed to recurs and therefore keeps costing, so the cadence leads,
 * and the card states what a scheduled run cannot do: those runs happen with
 * nobody watching, and the fact that they can only look and report is part of
 * what makes this safe to approve.
 */
export default function ScheduleGrantCard({
  callId, name, when, onConfirm, onCancel,
}: Props) {
  const { t } = useTranslation();
  return (
    <div className="runcmd-card" data-testid="schedule-card">
      <div className="runcmd-card__label">{t("schedgrant.label")}</div>
      <p className="text-[12px] text-foreground font-sans">{t("schedgrant.body")}</p>
      <pre className="runcmd-card__cmd">{name}</pre>
      <div className="runcmd-card__reason">{humanCadence(when)}</div>
      <p className="text-[10.5px] text-subtle-foreground font-sans" data-testid="schedule-scope">
        {t("schedgrant.scope")}
      </p>
      <div className="runcmd-card__actions">
        <button
          type="button"
          className="runcmd-card__btn runcmd-card__btn--primary"
          data-testid="schedule-allow"
          onClick={() => onConfirm(callId)}
        >
          {t("schedgrant.allow")}
        </button>
        <button
          type="button"
          className="runcmd-card__btn"
          data-testid="schedule-deny"
          onClick={() => onCancel(callId)}
        >
          {t("schedgrant.deny")}
        </button>
      </div>
    </div>
  );
}
