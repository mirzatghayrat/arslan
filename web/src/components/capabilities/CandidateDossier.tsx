import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { capabilitiesApi, type CapabilityCandidate, type InstallResult } from "../../api/capabilities";
import { companionApi, type Project } from "../../api/companion";
import { companionError } from "../companion/errors";
import { Button, Dialog, Notice, Tag } from "../kit";
import { runLine } from "./DiscoverResults";

export const START_PROJECT_EVENT = "arslan:start-project";
/** A path, the same in every language. */
const FOLDER_EXAMPLE = "~/Downloads";

function Fact({ label, value, verdict, testId }: { label: string; value: React.ReactNode; verdict?: string; testId?: string }) {
  return (
    <div className="grid grid-cols-[88px_1fr_auto] items-start gap-3 border-b border-border py-2 text-[13px] last:border-b-0" data-testid={testId}>
      <span className="text-muted-foreground">{label}</span><span className="min-w-0">{value}</span>
      {verdict && <span className="text-[11.5px] text-subtle-foreground">{verdict}</span>}
    </div>
  );
}

/**
 * A candidate's dossier (0.1.57 §7, board Capability-Dossier): the license read from the
 * source file itself, activity, how it would run, what it needs; then 加进能力库 (install,
 * scan, test, switch on — the same steps as the card in a conversation) or 用进项目 as
 * material, as a dependency (a project conversation with the request typed, not sent), or as
 * a capability.
 */
export default function CandidateDossier({ candidate, onClose, onInstalled }: {
  candidate: CapabilityCandidate; onClose: () => void; onInstalled?: (r: InstallResult) => void;
}) {
  const { t } = useTranslation();
  const [checked, setChecked] = useState<{ candidate: CapabilityCandidate; installable: boolean; why_not: string | null } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [folder, setFolder] = useState("");
  const [keys, setKeys] = useState<Record<string, string>>({});
  const [result, setResult] = useState<InstallResult | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState("");
  const [projectNote, setProjectNote] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    capabilitiesApi.checkCandidate(candidate.id).then(r => { if (alive) setChecked(r); })
      .catch(cause => { if (alive) setError(companionError(cause)); });
    companionApi.projects(false).then(p => { if (alive) setProjects(p); }).catch(() => {});
    return () => { alive = false; };
  }, [candidate.id]);

  const c = checked?.candidate ?? candidate;
  const required = c.needs.keys.filter(k => k.required);
  const missing = required.some(k => !(keys[k.name] ?? "").trim());

  async function install() {
    setBusy(true); setError(null);
    try {
      const r = await capabilitiesApi.install(c.id, folder.trim() ? [folder.trim()] : [], keys);
      setResult(r);
      onInstalled?.(r);
    } catch (cause) { setError(companionError(cause)); } finally { setBusy(false); }
  }
  async function useIn(mode: "material" | "dependency") {
    if (!projectId) return;
    setError(null); setProjectNote(null);
    if (mode === "dependency") {
      window.dispatchEvent(new CustomEvent(START_PROJECT_EVENT, { detail: { projectId,
        prefill: t("discover.dossier_dependencyPrefill", { name: c.name, url: c.source_url ?? c.repo ?? "" }) } }));
      onClose();
      return;
    }
    setBusy(true);
    try {
      await capabilitiesApi.asMaterial(projectId, c.id);
      setProjectNote(t("discover.dossier_materialDone"));
    } catch (cause) { setError(companionError(cause)); } finally { setBusy(false); }
  }

  const v = c.license.verdict;
  return (
    <Dialog open onClose={onClose} width={640} testId="candidate-dossier"
      title={<span className="flex items-center gap-2"><Tag>{t(`discover.kind_${c.kind}`)}</Tag>{c.name}</span>}>
      <div className="flex flex-col gap-3">
        {c.summary && <p className="text-[13px]">{c.summary}</p>}
        <div className="flex flex-col" data-testid="dossier-facts">
          <Fact label={t("discover.card_license")} testId="dossier-license"
            value={v === "usable" ? `${c.license.spdx}${c.license.read_from ? ` · ${c.license.read_from}` : ""}`
              : t(v === "reference_only" ? "discover.lic_reference" : "discover.lic_unknown")}
            verdict={checked ? t(v === "usable" ? "discover.dossier_ok" : "discover.dossier_notUsable") : t("discover.dossier_checking")} />
          <Fact label={t("discover.dossier_activity")}
            value={[c.stars != null ? t("discover.stars", { stars: c.stars }) : null,
              c.pushed_days != null ? t("discover.pushed", { count: c.pushed_days }) : null].filter(Boolean).join(" · ") || "—"} />
          <Fact label={t("discover.card_runs")} value={runLine(t, c)} />
          <Fact label={t("discover.card_needs")} value={required.length ? required.map(k => k.name).join(", ") : t("discover.dossier_noKeys")} />
          <Fact label={t("discover.dossier_version")} value={c.version ?? "—"} verdict={t("discover.dossier_pinned")} />
          <Fact label={t("discover.card_checks")} value={t("discover.card_checksText")} />
        </div>
        {error && <Notice tone="error">{t(error)}</Notice>}
        {checked && !checked.installable && checked.why_not && <Notice tone="info" testId="dossier-why-not">
          {t(`discover.why_${checked.why_not}`, { defaultValue: t("discover.why_other") })}</Notice>}
        {checked?.installable && !result && (
          <div className="flex flex-col gap-2 rounded-xl border border-border p-3" data-testid="dossier-install">
            {c.kind === "mcp" && c.runtime !== "remote" && <label className="flex flex-col gap-1 text-[12.5px]">
              <span className="text-muted-foreground">{t("discover.dossier_folder")}</span>
              <input value={folder} onChange={e => setFolder(e.target.value)} placeholder={FOLDER_EXAMPLE}
                className="rounded-lg border border-border bg-background px-2.5 py-1.5 font-mono text-[12.5px]" data-testid="dossier-folder" />
            </label>}
            {required.map(k => <label key={k.name} className="flex flex-col gap-1 text-[12.5px]">
              <span className="font-mono">{k.name}</span>
              <input type={k.secret ? "password" : "text"} autoComplete="off" value={keys[k.name] ?? ""}
                onChange={e => setKeys({ ...keys, [k.name]: e.target.value })} data-testid={`dossier-key-${k.name}`}
                className="rounded-lg border border-border bg-background px-2.5 py-1.5 text-[12.5px]" />
            </label>)}
            <Button tone="primary" size="sm" className="self-start" disabled={busy || missing} onClick={() => void install()}
              data-testid="dossier-add">{busy ? t("discover.dossier_adding") : t("discover.dossier_add")}</Button>
          </div>
        )}
        {result && <Notice tone={result.state === "on" ? "info" : "error"} testId="dossier-result">
          {result.state === "on" ? t("discover.result_on", { name: c.name, count: result.tools?.length ?? 0 })
            : result.state === "blocked" ? t("discover.result_blocked", { name: c.name })
            : t("discover.result_failed", { name: c.name, stage: result.stage ?? "", detail: result.detail ?? result.code ?? "" })}</Notice>}
        {projects.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3" data-testid="dossier-projects">
            <span className="text-[12.5px] text-muted-foreground">{t("discover.dossier_useIn")}</span>
            <select value={projectId} onChange={e => setProjectId(e.target.value)} data-testid="dossier-project"
              className="rounded-lg border border-border bg-background px-2 py-1 text-[12.5px]">
              <option value="">{t("discover.dossier_pickProject")}</option>
              {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
            <Button size="sm" disabled={!projectId || busy} onClick={() => void useIn("material")} data-testid="dossier-as-material">
              {t("discover.dossier_asMaterial")}</Button>
            <Button size="sm" disabled={!projectId || busy} onClick={() => void useIn("dependency")} data-testid="dossier-as-dependency">
              {t("discover.dossier_asDependency")}</Button>
            {projectNote && <span className="text-[12px] text-success" data-testid="dossier-project-note">{projectNote}</span>}
          </div>
        )}
      </div>
    </Dialog>
  );
}
