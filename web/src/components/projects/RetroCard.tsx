import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { projectsApi, type Retro } from "../../api/projects";
import { companionError } from "../companion/errors";
import { Button, Notice } from "../kit";

const skipKey = (projectId: string) => `arslan.projects.retroSkipped.${projectId}`;

/**
 * Done (0.1.56 §10): a short retro, written only when asked — one call on the user's own model
 * over counted facts (what took longer than usual, how the plan changed). Up to three rules,
 * each can be kept as a plan rule. Skippable; without a model the facts stand alone.
 */
export default function RetroCard({ projectId }: { projectId: string }) {
  const { t, i18n } = useTranslation();
  const [retro, setRetro] = useState<Retro | null | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [skipped, setSkipped] = useState(() => {
    try { return localStorage.getItem(skipKey(projectId)) === "1"; } catch { return false; }
  });
  const load = useCallback(async () => {
    try { setRetro(await projectsApi.retro(projectId)); } catch (cause) { setError(companionError(cause)); }
  }, [projectId]);
  useEffect(() => { void load(); }, [load]);
  async function act(call: () => Promise<Retro>) {
    setBusy(true); setError(null);
    try { setRetro(await call()); } catch (cause) { setError(companionError(cause)); } finally { setBusy(false); }
  }
  function skip() {
    setSkipped(true);
    try { localStorage.setItem(skipKey(projectId), "1"); } catch { /* offered again next time */ }
  }
  if (retro === undefined && !error) return null;
  if (!retro) {
    if (skipped) return null;
    return <Notice tone="info" testId="retro-offer" title={t("projectsUI.retroOffer")}
      action={<span className="flex gap-1.5">
        <Button size="sm" tone="primary" disabled={busy} data-testid="retro-write"
          onClick={() => void act(() => projectsApi.writeRetro(projectId, i18n.resolvedLanguage ?? i18n.language))}>
          {busy ? t("projectsUI.retroWriting") : t("projectsUI.retroWrite")}</Button>
        <Button size="sm" disabled={busy} data-testid="retro-skip" onClick={skip}>{t("projectsUI.retroSkip")}</Button>
      </span>}>
      {error ? t(error) : t("projectsUI.retroOfferBody")}</Notice>;
  }
  const f = retro.facts;
  const slower = f.levels.filter(lv => lv.slower);
  return (
    <section className="flex flex-col gap-2 rounded-xl border border-border bg-background px-4 py-3" data-testid="retro">
      <h2 className="text-[13px] font-bold">{t("projectsUI.retroTitle")}</h2>
      {retro.summary && <p className="text-[13px] leading-relaxed" data-testid="retro-summary">{retro.summary}</p>}
      <ul className="flex flex-col gap-0.5 text-[12.5px] text-muted-foreground" data-testid="retro-facts">
        {f.total_days != null && <li>{t("projectsUI.retroTotal", { count: Math.round(f.total_days) })}</li>}
        {slower.map(lv => <li key={lv.level}>{t("projectsUI.retroSlower", { level: lv.level, days: lv.days, usual: lv.usual })}</li>)}
        {slower.length === 0 && <li>{t("projectsUI.retroNoneSlower")}</li>}
        <li>{t("projectsUI.retroChanges", { count: f.plan_changes, cut: f.cut_checkpoints })}</li>
      </ul>
      {retro.rules.length > 0 && <ul className="flex flex-col gap-1.5" data-testid="retro-rules">
        {retro.rules.map((rule, i) => (
          <li key={i} className="flex items-center gap-2 text-[13px]">
            <span className="min-w-0 flex-1">{rule.text}</span>
            {rule.kept ? <span className="text-[12px] text-success" data-testid={`retro-kept-${i}`}>{t("projectsUI.retroKept")}</span>
              : <Button size="sm" disabled={busy} data-testid={`retro-keep-${i}`}
                onClick={() => void act(() => projectsApi.keepRetroRule(projectId, i))}>{t("projectsUI.retroKeep")}</Button>}
          </li>))}
      </ul>}
      {error && <Notice tone="error">{t(error)}</Notice>}
    </section>
  );
}
