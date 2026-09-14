import { useCallback, useEffect, useState } from "react";
import { Archive, FolderOpen, Pencil, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import { api, type CollectionOut } from "../../api/client";
import { companionApi, type Project, type ProjectInput } from "../../api/companion";
import CompanionDialog, { buttonClass, inputClass, primaryClass } from "./CompanionDialog";
import { companionError } from "./errors";

function ProjectEditor({ project, onClose, onSaved }: { project?: Project; onClose: () => void; onSaved: () => void }) {
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
  const field = (key: "name" | "summary" | "workspace_ref", value: string) => setDraft(row => ({ ...row, [key]: value }));
  async function save(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError(null);
    try {
      const body = { ...draft, name: draft.name.trim(), workspace_ref: draft.workspace_ref?.trim() || null };
      if (project) await companionApi.editProject(project, body); else await companionApi.createProject(body);
      onSaved();
    } catch (cause) { setError(companionError(cause)); }
    finally { setBusy(false); }
  }
  return <CompanionDialog title={t(project ? "companion.editProject" : "companion.addProject")} onClose={onClose} busy={busy}>
    <form onSubmit={event => void save(event)} className="space-y-4 text-sm">
      <label className="block">{t("companion.name")}<input className={`${inputClass} mt-1`} value={draft.name} maxLength={160} required onChange={e => field("name", e.target.value)} /></label>
      <label className="block">{t("companion.kind")}<select className={`${inputClass} mt-1`} value={draft.kind} onChange={e => setDraft(row => ({ ...row, kind: e.target.value as ProjectInput["kind"] }))}>
        {["general", "software", "research", "design"].map(kind => <option key={kind} value={kind}>{t(`companion.${kind}`)}</option>)}</select></label>
      <label className="block">{t("companion.summary")}<textarea rows={3} maxLength={4000} className={`${inputClass} mt-1`} value={draft.summary} onChange={e => field("summary", e.target.value)} /></label>
      <label className="block">{t("companion.workspace")}<input className={`${inputClass} mt-1`} value={draft.workspace_ref ?? ""} onChange={e => field("workspace_ref", e.target.value)} /></label>
      <fieldset className="space-y-2 rounded-lg border border-border p-3"><legend className="px-1">{t("companion.collectionIds")}</legend>
        {loading && <p role="status">{t("companion.loading")}</p>}
        {collections.map(collection => <label className="flex items-center gap-2" key={collection.id}>
          <input type="checkbox" checked={draft.collection_ids.includes(collection.id)} onChange={e => setDraft(row => ({ ...row,
            collection_ids: e.target.checked ? [...row.collection_ids, collection.id] : row.collection_ids.filter(id => id !== collection.id),
          }))} />{collection.name}</label>)}
      </fieldset>
      {draft.kind === "software" && <div className="grid gap-3 sm:grid-cols-2">{(["app_id", "bundle_id"] as const).map(key => <label key={key}>
        {t(key === "app_id" ? "companion.appId" : "companion.bundleId")}<input className={`${inputClass} mt-1`} value={draft.app_binding?.[key] ?? ""}
          onChange={e => setDraft(row => ({ ...row, app_binding: { app_id: null, bundle_id: null, ...row.app_binding, [key]: e.target.value || null } }))} />
      </label>)}</div>}
      {error && <p role="alert" className="text-destructive">{t(error)}</p>}
      <div className="flex justify-end gap-2"><button type="button" className={buttonClass} disabled={busy} onClick={onClose}>{t("companion.cancel")}</button>
        <button className={primaryClass} disabled={busy || !draft.name.trim()}>{t("companion.save")}</button></div>
    </form>
  </CompanionDialog>;
}

export default function ProjectsSection({ onStart }: { onStart: (project: Project) => Promise<void> }) {
  const { t } = useTranslation();
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [archived, setArchived] = useState(false);
  const [editor, setEditor] = useState<{ project?: Project } | null>(null);
  const reload = useCallback(async () => {
    setLoading(true); setError(null);
    try { setProjects(await companionApi.projects(true)); } catch { setError("brain.read_failed"); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void reload(); }, [reload]);
  async function act(operation: () => Promise<unknown>) {
    setBusy(true); setError(null);
    try { await operation(); } catch (cause) { setError(companionError(cause)); }
    finally { setBusy(false); }
  }
  return <section className="h-full overflow-y-auto px-5 py-6 sm:px-8">
    <div className="mx-auto max-w-5xl space-y-5"><div className="flex flex-wrap items-start justify-between gap-4">
      <div><h1 className="text-xl font-semibold">{t("companion.projects")}</h1><p className="mt-2 text-sm text-muted-foreground">{t("companion.projectIntro")}</p></div>
      <button className={primaryClass} onClick={() => setEditor({})}><Plus size={16} />{t("companion.addProject")}</button></div>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={archived} onChange={e => setArchived(e.target.checked)} />{t("companion.showArchived")}</label>
      {error && <p role="alert" className="text-sm text-destructive">{t(error)} <button className="underline" onClick={() => void reload()}>{t("companion.refresh")}</button></p>}
      {loading && <p role="status">{t("companion.loading")}</p>}
      {!loading && !error && !projects.length && <p className="rounded-xl border border-dashed border-border p-12 text-center text-sm text-muted-foreground">{t("companion.emptyProjects")}</p>}
      <ul className="grid gap-4 lg:grid-cols-2">{projects.filter(p => archived || p.status === "active").map(project => <li key={project.id} className="rounded-xl border border-border p-5">
        <div className="flex items-center gap-2"><FolderOpen size={18} className="text-primary" /><h2 className="min-w-0 flex-1 break-words font-medium">{project.name}</h2>
          <span className="text-xs text-muted-foreground">{t(`companion.${project.status === "archived" ? "archived" : project.kind}`)}</span></div>
        <p className="mt-3 whitespace-pre-wrap break-words text-sm text-muted-foreground">{project.summary}</p>
        <div className="mt-4 flex flex-wrap gap-2"><button className={buttonClass} disabled={busy} onClick={() => setEditor({ project })}><Pencil size={14} />{t("companion.edit")}</button>
          <button className={buttonClass} disabled={busy} onClick={() => void act(async () => { await companionApi.editProject(project, project, project.status === "active" ? "archived" : "active"); await reload(); })}><Archive size={14} />{t(project.status === "active" ? "companion.archive" : "companion.resume")}</button>
          {project.status === "active" && <button className={primaryClass} disabled={busy} onClick={() => void act(() => onStart(project))}>{t("companion.startTask")}</button>}</div>
      </li>)}</ul>
    </div>
    {editor && <ProjectEditor project={editor.project} onClose={() => setEditor(null)} onSaved={() => { setEditor(null); void reload(); }} />}
  </section>;
}
