import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, type CollectionOut } from "../../api/client";
import { companionApi, type Project, type ProjectInput } from "../../api/companion";
import { projectsApi, type Board, type BoardCard } from "../../api/projects";
import { Notice } from "../kit";
import NewProject, { TEMPLATES } from "../projects/NewProject";
import ProjectPage from "../projects/ProjectPage";
import ProjectsBoard from "../projects/ProjectsBoard";
import CompanionDialog, { buttonClass, inputClass, primaryClass } from "./CompanionDialog";
import { companionError } from "./errors";

/** A project's settings (name, type, finish line, folder, materials, App Store binding). */
export function ProjectEditor({ project, onClose, onSaved }: { project?: Project; onClose: () => void; onSaved: () => void }) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState<ProjectInput>(project ?? {
    name: "", kind: "general", summary: "", workspace_ref: null, collection_ids: [], app_binding: null,
  });
  const [collections, setCollections] = useState<CollectionOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    api.listCollections().then(rows => { if (alive) setCollections(rows); })
      .catch(() => { if (alive) setError("brain.read_failed"); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, []);
  const field = (key: "name" | "summary" | "workspace_ref" | "finish_line", value: string) => setDraft(row => ({ ...row, [key]: value }));
  async function save(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError(null);
    try {
      const body = { ...draft, name: draft.name.trim(), workspace_ref: draft.workspace_ref?.trim() || null,
        finish_line: draft.finish_line?.trim() || null };
      if (project) await companionApi.editProject(project, body); else await companionApi.createProject(body);
      onSaved();
    } catch (cause) { setError(companionError(cause)); }
    finally { setBusy(false); }
  }
  return <CompanionDialog title={t(project ? "companion.editProject" : "companion.addProject")} onClose={onClose} busy={busy}>
    <form onSubmit={event => void save(event)} className="space-y-4 text-sm">
      <label className="block">{t("companion.name")}<input className={`${inputClass} mt-1`} value={draft.name} maxLength={200} required onChange={e => field("name", e.target.value)} /></label>
      <label className="block">{t("projectsUI.typeLabel")}<select data-testid="project-editor-type" className={`${inputClass} mt-1`} value={draft.template ?? "other"}
        onChange={e => setDraft(row => ({ ...row, template: e.target.value as ProjectInput["template"] }))}>
        {TEMPLATES.map(key => <option key={key} value={key}>{t(`projectsUI.type_${key}`)}</option>)}</select></label>
      <label className="block">{t("projectsUI.q2")}<input data-testid="project-editor-finish" className={`${inputClass} mt-1`} value={draft.finish_line ?? ""} maxLength={400}
        onChange={e => field("finish_line", e.target.value)} /></label>
      <label className="block">{t("companion.kind")}<select className={`${inputClass} mt-1`} value={draft.kind} onChange={e => setDraft(row => ({ ...row, kind: e.target.value as ProjectInput["kind"] }))}>
        {["general", "software", "research", "design"].map(kind => <option key={kind} value={kind}>{t(`companion.${kind}`)}</option>)}</select></label>
      <label className="block">{t("companion.summary")}<textarea rows={3} maxLength={10000} className={`${inputClass} mt-1`} value={draft.summary} onChange={e => field("summary", e.target.value)} /></label>
      <label className="block">{t("projectsUI.q3")}<input className={`${inputClass} mt-1`} value={draft.workspace_ref ?? ""} onChange={e => field("workspace_ref", e.target.value)} /></label>
      <fieldset className="space-y-2 rounded-lg border border-border p-3"><legend className="px-1">{t("companion.collectionIds")}</legend>
        {loading && <p role="status">{t("companion.loading")}</p>}
        {collections.map(collection => <label className="flex items-center gap-2" key={collection.id}>
          <input type="checkbox" checked={draft.collection_ids.includes(collection.id)} onChange={e => setDraft(row => ({ ...row,
            collection_ids: e.target.checked ? [...row.collection_ids, collection.id] : row.collection_ids.filter(id => id !== collection.id),
          }))} />{collection.name}</label>)}
      </fieldset>
      {draft.kind === "software" && <div className="grid gap-3 sm:grid-cols-2">{(["app_id", "bundle_id", "version_id"] as const).map(key => <label key={key}>
        {t(key === "app_id" ? "companion.appId" : key === "version_id" ? "companion.appVersionId" : "companion.bundleId")}<input className={`${inputClass} mt-1`} value={draft.app_binding?.[key] ?? ""}
          onChange={e => setDraft(row => ({ ...row, app_binding: { app_id: null, bundle_id: null, ...row.app_binding, [key]: e.target.value || null } }))} />
      </label>)}
        <label>{t("companion.appPlatform")}<select className={`${inputClass} mt-1`} value={draft.app_binding?.platform ?? ""}
          onChange={e => setDraft(row => ({ ...row, app_binding: { app_id: null, bundle_id: null, ...row.app_binding,
            platform: (e.target.value || null) as NonNullable<ProjectInput["app_binding"]>["platform"] } }))}>
          <option value="">{t("companion.appPlatformUnset")}</option>
          <option value="IOS">iOS</option><option value="MAC_OS">macOS</option><option value="TV_OS">tvOS</option><option value="VISION_OS">visionOS</option>
        </select></label>
        <p className="text-xs text-muted-foreground sm:col-span-2">{t("companion.ascDisabled")}</p>
      </div>}
      {error && <p role="alert" className="text-destructive">{t(error)}</p>}
      <div className="flex justify-end gap-2"><button type="button" className={buttonClass} disabled={busy} onClick={onClose}>{t("companion.cancel")}</button>
        <button className={primaryClass} disabled={busy || !draft.name.trim()}>{t("companion.save")}</button></div>
    </form>
  </CompanionDialog>;
}

type View = { kind: "board" } | { kind: "new"; project?: Project } | { kind: "page"; id: string };

/**
 * Projects (0.1.56): the board, a project's page, and new / plan-it. The board reloads
 * whenever something on a page changed.
 */
export default function ProjectsSection({ onStart }: { onStart: (project: Project, prefill?: string) => Promise<void> }) {
  const { t } = useTranslation();
  const [board, setBoard] = useState<Board | null>(null);
  const [view, setView] = useState<View>({ kind: "board" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const reload = useCallback(async () => {
    setError(null);
    try { setBoard(await projectsApi.board()); } catch (cause) { setError(companionError(cause)); }
  }, []);
  useEffect(() => { void reload(); }, [reload]);

  async function projectById(id: string): Promise<Project | undefined> {
    return (await companionApi.projects(true)).find(p => p.id === id);
  }
  async function decide(card: BoardCard, accept: boolean) {
    if (!card.proposal) return;
    setBusy(true);
    try { await projectsApi.decide(card.id, card.proposal.id, accept); await reload(); }
    catch (cause) { setError(companionError(cause)); }
    finally { setBusy(false); }
  }

  if (view.kind === "new") return <NewProject project={view.project}
    onCancel={() => setView({ kind: "board" })}
    onDone={id => { void reload(); setView({ kind: "page", id }); }} />;
  if (view.kind === "page") return <ProjectPage projectId={view.id} onBack={() => { setView({ kind: "board" }); void reload(); }}
    onStart={onStart} onChanged={() => void reload()} onPlan={project => setView({ kind: "new", project })} />;
  return <>
    {error && <div className="px-5 pt-4 sm:px-8"><Notice tone="error">{t(error)}</Notice></div>}
    {!board && !error && <p role="status" className="p-8 text-[13px] text-muted-foreground">{t("companion.loading")}</p>}
    {board && <ProjectsBoard board={board} busy={busy} onNew={() => setView({ kind: "new" })}
      onOpen={id => setView({ kind: "page", id })}
      onPlan={id => void projectById(id).then(project => { if (project) setView({ kind: "new", project }); })}
      onDecide={(card, accept) => void decide(card, accept)} />}
  </>;
}
