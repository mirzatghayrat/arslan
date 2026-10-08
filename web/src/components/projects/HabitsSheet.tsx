import { useCallback, useEffect, useState } from "react";
import { ChevronLeft } from "lucide-react";
import { useTranslation } from "react-i18next";
import { projectsApi, type Habits, type PaceRow, type PlanRule } from "../../api/projects";
import { companionError } from "../companion/errors";
import { Button, Notice, Tag } from "../kit";
import { templateOf } from "./NewProject";

/** A rule in the user's words: learned ones are worded here, a decline's line is quoted. */
export function ruleText(t: (key: string, o?: Record<string, unknown>) => string, rule: PlanRule): string {
  if (rule.value.code === "add_level") return t("projectsUI.ruleAddLevel", { name: rule.value.name ?? "" });
  if (rule.value.code === "cut_scope") return t("projectsUI.ruleCutScope");
  return t("projectsUI.ruleSaid", { text: rule.text });
}

function PaceLine({ row, onSave, busy }: { row: PaceRow; onSave: (days: number | null) => void; busy?: boolean }) {
  const { t } = useTranslation();
  const [value, setValue] = useState(row.override_days != null ? String(row.override_days) : "");
  const shown = row.override_days ?? row.median_days;
  return (
    <li className="flex flex-wrap items-center gap-2 border-t border-border px-3.5 py-2 text-[12.5px] first:border-t-0"
      data-testid={`pace-${row.template}-${row.band}`}>
      <Tag>{t(`projectsUI.type_${templateOf(row.template, null)}`)}</Tag>
      <span className="text-muted-foreground">{t(`projectsUI.col_${row.band === "done" ? "doing" : row.band}`)}</span>
      <span className="min-w-0 flex-1 font-semibold">{shown != null ? t("projectsUI.paceDays", { count: shown }) : "—"}</span>
      {row.median_days != null && <span className="text-[11.5px] text-subtle-foreground">
        {t("projectsUI.paceFrom", { count: row.levels, days: row.median_days })}</span>}
      <input type="number" min={0.5} max={365} step={0.5} value={value} onChange={e => setValue(e.target.value)}
        className="w-20 rounded-lg border border-border bg-background px-2 py-1 text-[12px]" aria-label={t("projectsUI.paceOverride")}
        placeholder={t("projectsUI.paceOverridePh")} data-testid={`pace-input-${row.template}-${row.band}`} />
      <Button size="sm" disabled={busy} data-testid={`pace-save-${row.template}-${row.band}`}
        onClick={() => onSave(value.trim() ? Number(value) : null)}>{t("projectsUI.paceSave")}</Button>
    </li>
  );
}

/**
 * "看它学到了什么" (0.1.56 §6): the shadow numbers and the last miss, the plan rules Arslan
 * wrote (each with its source and a switch), and the user's pace. Stays on this Mac; rules are
 * only used when the user asks Arslan to draft a plan.
 */
export default function HabitsSheet({ onBack }: { onBack: () => void }) {
  const { t } = useTranslation();
  const [habits, setHabits] = useState<Habits | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try { setHabits(await projectsApi.habits()); } catch (cause) { setError(companionError(cause)); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  async function act(call: () => Promise<Habits>) {
    setBusy(true); setError(null);
    try { setHabits(await call()); } catch (cause) { setError(companionError(cause)); } finally { setBusy(false); }
  }
  const s = habits?.shadow;
  return (
    <section className="flex h-full min-h-0 flex-col gap-4 overflow-y-auto px-5 py-5 sm:px-8" data-testid="habits-sheet"
      aria-label={t("projectsUI.habitsTitle")}>
      <button type="button" onClick={onBack} className="inline-flex items-center gap-1 self-start text-[12px] text-muted-foreground hover:text-foreground"
        data-testid="habits-back"><ChevronLeft size={13} />{t("projectsUI.title")}</button>
      <header className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <h1 className="text-[20px] font-bold leading-tight">{t("projectsUI.habitsTitle")}</h1>
          <p className="mt-0.5 max-w-3xl text-[12.5px] text-muted-foreground">{t("projectsUI.habitsIntro")}</p>
        </div>
      </header>
      {error && <Notice tone="error">{t(error)}</Notice>}
      {!habits && !error && <p role="status" className="text-[13px] text-muted-foreground">{t("companion.loading")}</p>}
      {habits && s && <>
        <div className="flex flex-col gap-1.5">
          <h2 className="px-1 text-[12px] font-semibold text-muted-foreground">{t("projectsUI.habitsMeter")}</h2>
          <div className="rounded-xl border border-border bg-background px-3.5 py-2.5 text-[13px]" data-testid="habits-meter">
            <p>{s.proposed > 0 ? t(s.auto_advance ? "projectsUI.shadowAuto" : "projectsUI.shadow",
              { proposed: s.proposed, accepted: s.accepted, streak: s.streak, askAt: s.ask_at }) : t("projectsUI.shadowNone")}</p>
            {s.last_miss && <p className="mt-1 text-[12.5px] text-muted-foreground" data-testid="habits-last-miss">
              {t(s.last_miss.outcome === "declined" ? "projectsUI.lastMissDeclined" : "projectsUI.lastMissUndone", { level: s.last_miss.level ?? "" })}
              {s.last_miss.note ? ` ${t("projectsUI.lastMissLearned", { text: s.last_miss.note })}` : ""}</p>}
          </div>
        </div>

        <div className="flex flex-col gap-1.5">
          <h2 className="px-1 text-[12px] font-semibold text-muted-foreground">{t("projectsUI.habitsRules")}</h2>
          {!habits.rules.length && <p className="rounded-xl border border-dashed border-border px-3.5 py-3 text-[12.5px] text-muted-foreground">
            {t("projectsUI.habitsRulesNone")}</p>}
          {habits.rules.length > 0 && <ul className="overflow-hidden rounded-xl border border-border bg-background" data-testid="habits-rules">
            {habits.rules.map(rule => (
              <li key={rule.id} className="flex items-start gap-3 border-t border-border px-3.5 py-2.5 first:border-t-0" data-testid={`habit-rule-${rule.id}`}>
                <div className="min-w-0 flex-1">
                  <p className={`text-[13px] ${rule.enabled ? "" : "text-muted-foreground line-through"}`}>
                    {rule.template && <span className="mr-1.5"><Tag>{t(`projectsUI.type_${templateOf(rule.template, null)}`)}</Tag></span>}
                    {ruleText(t, rule)}</p>
                  {rule.sources.length > 0 && <p className="mt-0.5 text-[11.5px] text-subtle-foreground">
                    {t("projectsUI.ruleFrom", { names: rule.sources.join(", ") })}</p>}
                </div>
                <input type="checkbox" className="kit-switch mt-0.5" checked={rule.enabled} disabled={busy}
                  aria-label={ruleText(t, rule)} data-testid={`habit-rule-switch-${rule.id}`}
                  onChange={e => void act(() => projectsApi.setRule(rule.id, e.target.checked))} />
              </li>))}
          </ul>}
        </div>

        <div className="flex flex-col gap-1.5">
          <h2 className="px-1 text-[12px] font-semibold text-muted-foreground">{t("projectsUI.habitsPace")}</h2>
          {habits.pace.length === 0
            ? <p className="rounded-xl border border-dashed border-border px-3.5 py-3 text-[12.5px] text-muted-foreground" data-testid="habits-pace-none">
              {t("projectsUI.habitsPaceNone", { count: habits.pace_min_levels, done: habits.cleared_levels })}</p>
            : <ul className="overflow-hidden rounded-xl border border-border bg-background" data-testid="habits-pace">
              {habits.pace.map(row => <PaceLine key={`${row.template}-${row.band}`} row={row} busy={busy}
                onSave={days => void act(() => projectsApi.setPace(row.template, row.band, days))} />)}
            </ul>}
        </div>
      </>}
    </section>
  );
}
