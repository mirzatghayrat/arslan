import { useEffect, useState } from "react";
import { Settings2, Shield } from "lucide-react";
import { useTranslation } from "react-i18next";
import { companionApi, type ConversationContext, type Project } from "../../api/companion";
import CompanionDialog, { buttonClass, inputClass, primaryClass } from "./CompanionDialog";
import { companionError } from "./errors";

export default function ConversationControls({ conversationId, running, empty, onChanged, compact = false }: {
  conversationId: string; running: boolean; empty: boolean; onChanged: (context: ConversationContext) => void; compact?: boolean;
}) {
  const { t } = useTranslation();
  const [context, setContext] = useState<ConversationContext | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [draft, setDraft] = useState<ConversationContext | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    setContext(null); setDraft(null); setError(null);
    Promise.all([companionApi.context(conversationId), companionApi.projects()]).then(([settings, rows]) => {
      if (alive) { setContext(settings); setProjects(rows); onChanged(settings); }
    }).catch(() => { if (alive) setError("brain.read_failed"); });
    return () => { alive = false; };
    // The parent callback only reports metadata; identity must not trigger a refetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId]);
  const projectName = context?.project_id ? projects.find(p => p.id === context.project_id)?.name ?? t("companion.project") : null;
  async function save() {
    if (!draft || !context || running) return;
    setBusy(true); setError(null);
    try {
      const next = await companionApi.saveContext(context, draft.temporary
        ? { ...draft, no_memory: true, no_learning: true, cloud_memory_allowed: false, allow_sensitive: false }
        : draft);
      setContext(next); onChanged(next); setDraft(null);
    } catch (cause) { setError(companionError(cause)); }
    finally { setBusy(false); }
  }
  return <div className={compact ? "min-w-0 text-xs" : "shrink-0 border-b border-border/60 px-5 py-2 text-xs"}>
    <div className={compact ? "flex min-w-0 items-center gap-3 whitespace-nowrap" : "flex flex-wrap items-center gap-3"}><button className="inline-flex min-w-0 items-center gap-2 text-muted-foreground hover:text-foreground disabled:opacity-50"
      aria-label={t("companion.conversationSettings")} title={t("companion.conversationSettings")}
      disabled={!context} onClick={() => { setError(null); setDraft(context); }}><Settings2 size={14} className="shrink-0" />
      {/* In the one-line header the project IS the button; with none it says what it opens. */}
      <span className="truncate">{compact && projectName ? projectName : t("companion.conversationSettings")}</span></button>
      {!compact && context?.project_id && <span className="text-primary">{projectName ?? t("companion.project")}</span>}
      {context?.temporary ? <span className="inline-flex items-center gap-1 text-primary"><Shield size={13} />{t("companion.temporary")}</span> : <>
        {context?.no_memory && <span>{t("companion.noMemory")}</span>}{context?.no_learning && <span>{t("companion.noLearning")}</span>}
      </>}
      {!draft && error && <span role="alert" className="text-destructive">{t(error)}</span>}
    </div>
    {!compact && context?.temporary && <p className="mt-2 leading-relaxed text-muted-foreground">{t("companion.temporaryHint")}</p>}
    {draft && <CompanionDialog title={t("companion.conversationSettings")} onClose={() => setDraft(null)} busy={busy}>
      <div className="space-y-4 text-sm">
        <label className="block">{t("companion.project")}<select className={`${inputClass} mt-1`} disabled={busy || running || draft.temporary} value={draft.project_id ?? ""}
          onChange={e => setDraft(row => row && ({ ...row, project_id: e.target.value || null }))}>
          <option value="">{t("companion.noProject")}</option>{projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}
        </select></label>
        {(draft.memory_by_default
          ? [["no_memory", "noMemory"], ["no_learning", "noLearning"]] as const
          : [["no_memory", "noMemory"], ["no_learning", "noLearning"], ["cloud_memory_allowed", "conversationCloud"], ["allow_sensitive", "allowSensitive"]] as const
        ).map(([field, key]) => <label key={field} className="flex items-start gap-2">
          <input type="checkbox" checked={draft[field]} disabled={busy || running || draft.temporary} onChange={e => setDraft(row => row && ({ ...row, [field]: e.target.checked }))} />{t(`companion.${key}`)}
        </label>)}
        {draft.memory_by_default && <>
          {/* 0.1.52 (D1): normal memory is on for every conversation. Sensitive memory still
              needs this conversation's own two permissions, given here by one explicit tick. */}
          <p data-testid="memory-by-default-note" className="text-xs leading-relaxed text-muted-foreground">{t("companion.memoryByDefaultNote")}</p>
          <label className="flex items-start gap-2">
            <input type="checkbox" data-testid="allow-sensitive-cloud" checked={draft.allow_sensitive && draft.cloud_memory_allowed}
              disabled={busy || running || draft.temporary}
              onChange={e => setDraft(row => row && ({ ...row, allow_sensitive: e.target.checked, cloud_memory_allowed: e.target.checked }))} />
            {t("companion.allowSensitiveHere")}
          </label>
        </>}
        <label className="flex items-start gap-2"><input type="checkbox" checked={draft.temporary} disabled={busy || running || !empty || context?.temporary}
          onChange={e => setDraft(row => row && ({ ...row, temporary: e.target.checked }))} />{t("companion.temporary")}</label>
        <p className="text-xs leading-relaxed text-muted-foreground">{t("companion.temporaryHint")}</p>
        {running && <p role="status">{t("companion.runningSettings")}</p>}
        {error && <p role="alert" className="text-destructive">{t(error)}</p>}
        <div className="flex justify-end gap-2"><button className={buttonClass} disabled={busy} onClick={() => setDraft(null)}>{t("companion.cancel")}</button>
          <button className={primaryClass} disabled={busy || running} onClick={() => void save()}>{t("companion.save")}</button></div>
      </div>
    </CompanionDialog>}
  </div>;
}
