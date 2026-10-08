import { useCallback, useEffect, useState } from "react";
import { ChevronLeft, FileText, Folder, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import { companionApi, type Project } from "../../api/companion";
import { projectsApi, type Level, type Plan, type ProjectEvent } from "../../api/projects";
import { OPEN_CONVERSATION_EVENT } from "../../lib/openConversation";
import { Button, Dialog, Notice, Tag, confirmSheet } from "../kit";
import { ProjectEditor } from "../companion/ProjectsSection";
import { companionError } from "../companion/errors";
import LevelMap from "./LevelMap";
import { templateOf } from "./NewProject";
import PlanEditor, { planIsValid } from "./PlanEditor";
import { daysSince, evidenceText } from "./projectUi";

type Tab = "levels" | "conversations" | "files" | "materials" | "settings";

/**
 * Layer 2 (0.1.56 §1): one project — its level map, the current level's checkpoints with
 * their evidence, what to do next, what Arslan did (each undoable), and its conversations,
 * folder, materials and settings.
 */
export default function ProjectPage({ projectId, onBack, onStart, onPlan, onChanged }: {
  projectId: string; onBack: () => void; onStart: (project: Project, prefill?: string) => Promise<void>;
  onPlan: (project: Project) => void; onChanged: () => void;
}) {
  const { t } = useTranslation();
  const [project, setProject] = useState<Project | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [events, setEvents] = useState<ProjectEvent[]>([]);
  const [conversations, setConversations] = useState<Awaited<ReturnType<typeof projectsApi.conversations>>>([]);
  const [files, setFiles] = useState<Awaited<ReturnType<typeof projectsApi.files>> | null>(null);
  const [tab, setTab] = useState<Tab>("levels");
  const [editing, setEditing] = useState<Level[] | null>(null);
  const [settings, setSettings] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [all, p, ev, conv] = await Promise.all([companionApi.projects(true), projectsApi.plan(projectId),
        projectsApi.events(projectId, 40), projectsApi.conversations(projectId)]);
      setProject(all.find(x => x.id === projectId) ?? null);
      setPlan(p); setEvents(ev); setConversations(conv);
    } catch (cause) { setError(companionError(cause)); }
  }, [projectId]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (tab !== "files") return;
    projectsApi.files(projectId).then(setFiles).catch(() => setFiles(null));
  }, [tab, projectId]);

  async function act(op: () => Promise<unknown>) {
    setBusy(true); setError(null);
    try { await op(); await load(); onChanged(); } catch (cause) { setError(companionError(cause)); }
    finally { setBusy(false); }
  }

  if (!project || !plan) return <section className="p-8 text-[13px] text-muted-foreground" role="status">
    {error ? <Notice tone="error">{t(error)}</Notice> : t("companion.loading")}</section>;

  const levels = plan.levels;
  const currentIndex = levels.findIndex(lv => lv.state === "current");
  const current = currentIndex >= 0 ? levels[currentIndex] : null;
  const left = levels.filter(lv => lv.state !== "cleared").length;
  const nextBest = current?.checkpoints.find(cp => cp.state !== "done") ?? null;
  const recent = events.filter(e => e.actor === "arslan" && (e.kind === "tick" || e.kind === "advance") && e.outcome !== "undone");
  const planChanges = events.filter(e => e.kind === "plan_change").length;
  const days = daysSince(current?.started_at);
  const ended = plan.stage === "done" || plan.stage === "dropped";

  const tabs: { key: Tab; label: string }[] = [
    { key: "levels", label: t("projectsUI.tab_levels") },
    { key: "conversations", label: t("projectsUI.tab_conversations", { count: conversations.length }) },
    { key: "files", label: t("projectsUI.tab_files") },
    { key: "materials", label: t("projectsUI.tab_materials") },
    { key: "settings", label: t("projectsUI.tab_settings") },
  ];

  return (
    <section className="flex h-full min-h-0 flex-col gap-3 overflow-y-auto px-5 py-4 sm:px-8" data-testid="project-page">
      <button type="button" onClick={onBack} className="inline-flex items-center gap-1 self-start text-[12px] text-muted-foreground hover:text-foreground"
        data-testid="project-back"><ChevronLeft size={13} />{t("projectsUI.title")}</button>
      <header className="flex flex-wrap items-start gap-4">
        <div className="min-w-0 flex-1">
          <h1 className="text-[20px] font-bold leading-tight">{project.name}</h1>
          <p className="mt-0.5 text-[12.5px] text-muted-foreground">{t(`projectsUI.type_${templateOf(project.template, project.kind)}`)}
            {project.finish_line ? <> · {t("projectsUI.finishLine")}{project.finish_line}</> : null}</p>
        </div>
        {levels.length > 0 && <span className="text-right" data-testid="project-left">
          <span className="block text-[22px] font-bold leading-tight">
            {plan.stage === "done" ? t("projectsUI.allClear") : t("projectsUI.left", { count: left })}</span></span>}
        <Button tone="primary" size="sm" onClick={() => void onStart(project)} data-testid="project-new-conversation">
          <Plus size={13} />{t("projectsUI.newConversation")}</Button>
      </header>

      <nav role="tablist" className="flex gap-1 border-b border-border">
        {tabs.map(x => <button key={x.key} role="tab" aria-selected={tab === x.key} type="button" data-testid={`project-tab-${x.key}`}
          onClick={() => setTab(x.key)} className={`-mb-px border-b-2 px-3 py-2 text-[13px] ${tab === x.key
            ? "border-foreground font-semibold" : "border-transparent text-muted-foreground hover:text-foreground"}`}>{x.label}</button>)}
      </nav>
      {error && <Notice tone="error">{t(error)}</Notice>}

      {tab === "levels" && !levels.length && (
        <Notice tone="info" title={t("projectsUI.noPlan")} action={<Button size="sm" onClick={() => onPlan(project)}>{t("projectsUI.planIt")}</Button>}>
          {t("projectsUI.noPlanBody")}</Notice>)}

      {tab === "levels" && levels.length > 0 && <>
        <LevelMap levels={levels} />
        {plan.stage === "idea" && <Notice tone="info" title={t("projectsUI.notStarted")}
          action={<Button size="sm" disabled={busy} onClick={() => void act(() => projectsApi.stage(projectId, { stage: "active" }))}
            data-testid="project-start">{t("projectsUI.start")}</Button>}>{t("projectsUI.notStartedBody")}</Notice>}
        <div className="flex flex-col gap-5 lg:flex-row">
          <div className="flex min-w-0 flex-1 flex-col gap-3">
            {current && <>
              <div className="flex flex-wrap items-baseline gap-2.5">
                <h2 className="text-[15px] font-bold">{t("projectsUI.levelTitle", { n: currentIndex + 1, name: current.name })}</h2>
                {current.description && <span className="text-[12px] text-muted-foreground">{current.description}</span>}
                {days !== null && <span className="text-[12px] text-subtle-foreground">{t("projectsUI.dayIn", { days: days + 1 })}</span>}
              </div>
              <ul className="overflow-hidden rounded-xl border border-border bg-background" data-testid="project-checkpoints">
                {current.checkpoints.map(cp => <li key={cp.id} className="flex items-center gap-3 border-t border-border px-4 py-2.5 first:border-t-0">
                  <input type="checkbox" className="h-4 w-4 accent-foreground" checked={cp.state === "done"} disabled={busy || ended}
                    aria-label={cp.text} data-testid={`checkpoint-${cp.id}`}
                    onChange={e => void act(() => projectsApi.tick(projectId, cp.id!, e.target.checked))} />
                  <span className={`min-w-0 flex-1 text-[13.5px] ${cp.state === "done" ? "text-muted-foreground" : ""}`}>{cp.text}</span>
                  {cp.progress && <span className="font-mono text-[11px] text-info-strong">{cp.progress}</span>}
                  {cp.state === "done" && cp.evidence && <span className="max-w-[45%] truncate text-[12px] text-subtle-foreground"
                    title={evidenceText(t, cp.evidence)}>{evidenceText(t, cp.evidence)}</span>}
                </li>)}
                <li className="border-t border-border px-4 py-2.5 text-[12.5px] text-muted-foreground first:border-t-0">
                  {current.clear_condition ? t("projectsUI.condition", { text: current.clear_condition }) : t("projectsUI.noCondition")}</li>
              </ul>
              {nextBest && !ended && <div className="flex flex-wrap items-center gap-3 rounded-xl bg-info-soft px-3.5 py-2.5" data-testid="project-next">
                <span className="min-w-0 flex-1 text-[13px]">{t("projectsUI.nextBest", { text: nextBest.text })}</span>
                <Button size="sm" tone="primary" onClick={() => void onStart(project, t("projectsUI.handOffText", {
                  checkpoint: nextBest.text, level: current.name, project: project.name }))} data-testid="project-hand-off">
                  {t("projectsUI.handOff")}</Button></div>}
              {!ended && <Button size="sm" className="self-start" disabled={busy} data-testid="project-clear-level"
                onClick={() => void act(() => projectsApi.advance(projectId))}>{t("projectsUI.clearByHand")}</Button>}
            </>}
            {!current && plan.stage === "active" && <Notice tone="info" title={t("projectsUI.allClear")}>{t("projectsUI.markDoneHint")}</Notice>}
          </div>

          <aside className="flex w-full shrink-0 flex-col gap-3 lg:w-[300px]">
            <div className="flex flex-col gap-1.5">
              <h3 className="px-1 text-[12px] font-semibold text-muted-foreground">{t("projectsUI.recent")}</h3>
              <ul className="overflow-hidden rounded-xl border border-border bg-background" data-testid="project-recent">
                {recent.slice(0, 6).map(e => <li key={e.id} className="flex items-start gap-2 border-t border-border px-3.5 py-2.5 first:border-t-0">
                  <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <span className="text-[13px]">{e.kind === "tick" ? t("projectsUI.recentTick", { text: e.payload.text ?? "" })
                      : t("projectsUI.recentAdvance", { level: e.payload.level ?? "", next: e.payload.next ?? "" })}</span>
                    {e.payload.evidence && <span className="text-[12px] text-subtle-foreground">{t("projectsUI.ev", { text: evidenceText(t, e.payload.evidence) })}</span>}
                  </span>
                  <button type="button" disabled={busy} className="shrink-0 text-[12px] text-muted-foreground hover:text-foreground"
                    data-testid={`project-undo-${e.id}`} onClick={() => void act(() => projectsApi.undo(projectId, e.id))}>{t("projectsUI.undo")}</button>
                </li>)}
                {!recent.length && <li className="px-3.5 py-2.5 text-[12.5px] text-subtle-foreground">{t("projectsUI.noRecent")}</li>}
              </ul>
            </div>
            {planChanges > 0 && <span className="px-1 text-[12px] text-subtle-foreground">{t("projectsUI.planChanged", { count: planChanges })}</span>}
            <div className="flex flex-wrap gap-1.5">
              {!ended && <Button size="sm" disabled={busy} data-testid="project-edit-plan" onClick={() => setEditing(levels.map(lv => ({ ...lv })))}>
                {t("projectsUI.editPlan")}</Button>}
              {!ended && <Button size="sm" disabled={busy} onClick={() => void act(() => projectsApi.stage(projectId, { paused: !plan.paused }))}
                data-testid="project-pause">{t(plan.paused ? "projectsUI.resume" : "projectsUI.pause")}</Button>}
              {!ended && <Button size="sm" disabled={busy} data-testid="project-done"
                onClick={() => void act(() => projectsApi.stage(projectId, { stage: "done" }))}>{t("projectsUI.markDone")}</Button>}
              {!ended && <Button size="sm" tone="plain" disabled={busy} data-testid="project-drop" onClick={async () => {
                if (await confirmSheet({ title: t("projectsUI.dropTitle"), body: t("projectsUI.dropBody"), action: t("projectsUI.drop"), destructive: false }))
                  await act(() => projectsApi.stage(projectId, { stage: "dropped" }));
              }}>{t("projectsUI.drop")}</Button>}
              {ended && <Button size="sm" disabled={busy} data-testid="project-reopen"
                onClick={() => void act(() => projectsApi.stage(projectId, { stage: "active" }))}>{t("projectsUI.reopen")}</Button>}
            </div>
          </aside>
        </div>
      </>}

      {tab === "conversations" && <ul className="overflow-hidden rounded-xl border border-border bg-background" data-testid="project-conversations">
        {conversations.map(c => <li key={c.conversation_id} className="border-t border-border first:border-t-0">
          <button type="button" className="flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-fill"
            onClick={() => window.dispatchEvent(new CustomEvent(OPEN_CONVERSATION_EVENT, { detail: c.conversation_id }))}>
            <span className="min-w-0 flex-1 truncate text-[13.5px]">{c.opening ?? t("projectsUI.untitled")}</span>
            <span className="shrink-0 text-[12px] text-subtle-foreground">{c.last_at ? new Date(c.last_at).toLocaleDateString() : ""}</span>
          </button></li>)}
        {!conversations.length && <li className="px-4 py-6 text-center text-[13px] text-subtle-foreground">{t("projectsUI.noConversations")}</li>}
      </ul>}

      {tab === "files" && <div className="flex flex-col gap-2" data-testid="project-files">
        {!files?.folder && <Notice tone="info">{t("projectsUI.noFolder")}</Notice>}
        {files?.folder && !files.exists && <Notice tone="warn">{t("projectsUI.missingFolder", { folder: files.folder })}</Notice>}
        {files?.exists && <>
          <span className="px-1 font-mono text-[12px] text-muted-foreground">{files.folder}</span>
          <ul className="overflow-hidden rounded-xl border border-border bg-background">
            {files.entries.map(f => <li key={f.name} className="flex items-center gap-2 border-t border-border px-4 py-2 text-[13px] first:border-t-0">
              {f.dir ? <Folder size={14} className="text-subtle-foreground" /> : <FileText size={14} className="text-subtle-foreground" />}{f.name}</li>)}
          </ul>
          {files.truncated && <span className="px-1 text-[12px] text-subtle-foreground">{t("projectsUI.truncated", { count: files.entries.length })}</span>}
        </>}
      </div>}

      {tab === "materials" && <div className="flex flex-col gap-2" data-testid="project-materials">
        <p className="text-[13px] text-muted-foreground">{t("projectsUI.materialsBody", { count: project.collection_ids.length })}</p>
        <Button size="sm" className="self-start" onClick={() => setSettings(true)}>{t("projectsUI.chooseMaterials")}</Button>
      </div>}

      {tab === "settings" && <div className="flex flex-col gap-2" data-testid="project-settings">
        <dl className="grid grid-cols-[140px_1fr] gap-x-4 gap-y-1.5 text-[13px]">
          <dt className="text-muted-foreground">{t("projectsUI.typeLabel")}</dt><dd><Tag>{t(`projectsUI.type_${templateOf(project.template, project.kind)}`)}</Tag></dd>
          <dt className="text-muted-foreground">{t("projectsUI.q2")}</dt><dd>{project.finish_line ?? "—"}</dd>
          <dt className="text-muted-foreground">{t("projectsUI.q3")}</dt><dd className="font-mono text-[12px]">{project.workspace_ref ?? "—"}</dd>
        </dl>
        <Button size="sm" className="self-start" onClick={() => setSettings(true)} data-testid="project-edit">{t("projectsUI.editProject")}</Button>
      </div>}

      <Dialog open={editing !== null} onClose={() => setEditing(null)} title={t("projectsUI.editPlan")} width={720} busy={busy}
        footer={<><Button onClick={() => setEditing(null)}>{t("projectsUI.cancel")}</Button>
          <Button tone="primary" disabled={!editing || !planIsValid(editing) || busy} data-testid="project-save-plan"
            onClick={() => void act(async () => { await projectsApi.savePlan(projectId, plan.version, editing ?? []); setEditing(null); })}>
            {t("projectsUI.savePlan")}</Button></>}>
        {editing && <PlanEditor levels={editing} onChange={setEditing} />}
      </Dialog>
      {settings && <ProjectEditor project={project} onClose={() => setSettings(false)} onSaved={() => { setSettings(false); void load(); onChanged(); }} />}
    </section>
  );
}
