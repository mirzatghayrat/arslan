import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { companionApi, type Project, type ProjectInput, type ProjectTemplate } from "../../api/companion";
import { projectsApi, type Level } from "../../api/projects";
import { Button, Notice } from "../kit";
import { companionError } from "../companion/errors";
import PlanEditor, { planIsValid } from "./PlanEditor";

export const TEMPLATES: ProjectTemplate[] = ["game", "app", "website", "research", "writing", "video", "skill", "trip", "job", "other"];
const KIND: Record<string, ProjectInput["kind"]> = { app: "software", research: "research", website: "design" };
const TEMPLATE_OF_KIND: Record<string, ProjectTemplate> = { software: "app", research: "research", design: "website", general: "other" };
/** A project from before 0.1.56 has a `kind` and no template: the template it starts from. */
export const templateOf = (template: ProjectTemplate | null | undefined, kind?: string): ProjectTemplate =>
  template ?? TEMPLATE_OF_KIND[kind ?? "general"] ?? "other";
const input = "w-full rounded-lg border border-border bg-background px-3 py-2 text-[14px] outline-none focus:border-foreground/40";

/**
 * New project (0.1.56 §3): type, what "done" is in one sentence, an optional folder, and the
 * levels Arslan drafts for that type — editable before anything is saved. Also how a
 * project from before 0.1.56 gets its levels ("给它排关卡": `project` is given).
 */
export default function NewProject({ project, onDone, onCancel }: {
  project?: Project; onDone: (projectId: string) => void; onCancel: () => void;
}) {
  const { t, i18n } = useTranslation();
  const lang = i18n.resolvedLanguage ?? i18n.language ?? "en";
  const [template, setTemplate] = useState<ProjectTemplate>(templateOf(project?.template, project?.kind));
  const [name, setName] = useState(project?.name ?? "");
  const [finish, setFinish] = useState(project?.finish_line ?? "");
  const [folder, setFolder] = useState(project?.workspace_ref ?? "");
  const [levels, setLevels] = useState<Level[]>([]);
  const [drafting, setDrafting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const conditionTouched = useRef(false);

  useEffect(() => {
    let alive = true;
    setDrafting(true);
    projectsApi.draft(template, finish, lang)
      .then(d => { if (alive) { setLevels(d.levels); conditionTouched.current = false; } })
      .catch(() => { if (alive) setError("projectsUI.draftFailed"); })
      .finally(() => { if (alive) setDrafting(false); });
    return () => { alive = false; };
    // Re-draft when the type changes; the finish line only updates the last level below.
  }, [template, lang]);   // eslint-disable-line react-hooks/exhaustive-deps

  const setFinishLine = (value: string) => {
    setFinish(value);
    if (conditionTouched.current || !levels.length) return;
    setLevels(prev => prev.map((lv, i) => (i === prev.length - 1 ? { ...lv, clear_condition: value } : lv)));
  };
  const editLevels = (next: Level[]) => {
    const lastBefore = levels[levels.length - 1];
    const lastAfter = next[next.length - 1];
    if (lastBefore && lastAfter && lastBefore.clear_condition !== lastAfter.clear_condition) conditionTouched.current = true;
    setLevels(next);
  };

  async function create() {
    setBusy(true); setError(null);
    try {
      const body: ProjectInput = {
        name: name.trim(), kind: project?.kind ?? KIND[template] ?? "general", summary: project?.summary ?? "",
        workspace_ref: folder.trim() || null, collection_ids: project?.collection_ids ?? [],
        app_binding: project?.app_binding ?? null, template, finish_line: finish.trim() || null,
      };
      const saved = project ? await companionApi.editProject(project, body) : await companionApi.createProject(body);
      await projectsApi.savePlan(saved.id, 0, levels);
      onDone(saved.id);
    } catch (cause) {
      setError(companionError(cause));
    } finally { setBusy(false); }
  }

  const ready = name.trim() && planIsValid(levels) && !drafting;
  return (
    <section className="flex h-full min-h-0 flex-col gap-4 overflow-y-auto px-5 py-5 sm:px-8" data-testid="new-project">
      <header>
        <h1 className="text-[20px] font-bold">{t(project ? "projectsUI.planTitle" : "projectsUI.newTitle")}</h1>
        <p className="mt-0.5 max-w-3xl text-[12.5px] text-muted-foreground">{t("projectsUI.newIntro")}</p>
      </header>
      <div className="flex flex-col gap-6 lg:flex-row">
        <div className="flex w-full shrink-0 flex-col gap-3 lg:w-[320px]">
          <span className="text-[13px] font-semibold">1 {t("projectsUI.q1")}</span>
          <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label={t("projectsUI.q1")}>
            {TEMPLATES.map(key => <button key={key} type="button" role="radio" aria-checked={template === key}
              data-testid={`new-project-type-${key}`} onClick={() => setTemplate(key)}
              className={`h-9 truncate rounded-lg px-3 text-left text-[13px] ${template === key ? "bg-foreground font-semibold text-background"
                : "border border-border bg-background hover:bg-fill"}`}>{t(`projectsUI.type_${key}`)}</button>)}
          </div>
          <label className="mt-1 flex flex-col gap-1.5 text-[13px] font-semibold">{t("projectsUI.nameLabel")}
            <input className={input} value={name} maxLength={200} data-testid="new-project-name" onChange={e => setName(e.target.value)} /></label>
          <label className="flex flex-col gap-1.5 text-[13px] font-semibold">2 {t("projectsUI.q2")}
            <input className={input} value={finish} maxLength={400} placeholder={t("projectsUI.q2ph")} data-testid="new-project-finish"
              onChange={e => setFinishLine(e.target.value)} /></label>
          <span className="-mt-1 text-[12px] text-subtle-foreground">{t("projectsUI.q2hint")}</span>
          <label className="flex flex-col gap-1.5 text-[13px] font-semibold">
            <span>3 {t("projectsUI.q3")} <span className="font-normal text-subtle-foreground">{t("projectsUI.optional")}</span></span>
            <input className={`${input} font-mono text-[13px]`} value={folder} maxLength={200} data-testid="new-project-folder"
              placeholder={`~/Arslan/${name.trim() || "…"}`} onChange={e => setFolder(e.target.value)} /></label>
          <span className="-mt-1 text-[12px] text-subtle-foreground">{t("projectsUI.q3hint")}</span>
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <span className="text-[13px] font-semibold">4 {t("projectsUI.q4", { count: levels.length })}
            {drafting && <span className="ml-2 font-normal text-subtle-foreground">{t("projectsUI.drafting")}</span>}</span>
          {levels.length > 0 && <PlanEditor levels={levels} onChange={editLevels} />}
        </div>
      </div>
      {error && <Notice tone="error">{t(error)}</Notice>}
      <footer className="flex justify-end gap-2">
        <Button onClick={onCancel} disabled={busy}>{t("projectsUI.cancel")}</Button>
        <Button tone="primary" onClick={() => void create()} disabled={!ready || busy} data-testid="new-project-create">
          {t(project ? "projectsUI.savePlan" : "projectsUI.create")}</Button>
      </footer>
    </section>
  );
}
