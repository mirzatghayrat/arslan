import { useState } from "react";
import { useTranslation } from "react-i18next";
import { companionApi, type MemoryEntry, type MemoryScope, type MemoryWrite, type Project, type StyleReference } from "../../api/companion";
import CompanionDialog, { buttonClass, inputClass, primaryClass } from "./CompanionDialog";
import { companionError } from "./errors";

export default function MemoryEditor({ entry, projects, onClose, onSaved }: {
  entry?: MemoryEntry; projects: Project[]; onClose: () => void; onSaved: () => void;
}) {
  const { t } = useTranslation();
  const [content, setContent] = useState(entry?.content ?? "");
  const [kind, setKind] = useState<MemoryWrite["kind"]>(entry?.kind ?? "preference");
  const [scope, setScope] = useState<MemoryScope>(entry?.scope ?? { kind: "global", id: null });
  const [sensitive, setSensitive] = useState(!!entry && entry.sensitivity !== "normal");
  const [acknowledged, setAcknowledged] = useState(false);
  const [cloud, setCloud] = useState(entry?.use_policy === "cloud_allowed");
  const [scopeConfirmed, setScopeConfirmed] = useState(false);
  const [referenceEnabled, setReferenceEnabled] = useState(!!entry?.style_reference);
  const [reference, setReference] = useState<StyleReference>(entry?.style_reference ?? {
    source_kind: "file", source_ref: "", polarity: "positive", rationale: "", interpretation: "tentative",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const changedScope = !!entry && JSON.stringify(scope) !== JSON.stringify(entry.scope);
  const valid = !!content.trim() && (scope.kind === "global" || !!scope.id?.trim())
    && (!sensitive || acknowledged) && (!changedScope || scopeConfirmed)
    && (!referenceEnabled || (!!reference.source_ref.trim() && !!reference.rationale.trim() && scope.kind === "project"));

  async function save() {
    setBusy(true); setError(null);
    const body: MemoryWrite = { content, kind, scope, sensitivity: sensitive ? "sensitive" : "normal",
      sensitive_acknowledged: acknowledged, use_policy: cloud ? "cloud_allowed" : "local_only",
      topic: entry?.topic ?? null, valid_from: entry?.valid_from ?? null,
      review_at: entry?.review_at ?? null, expires_at: entry?.expires_at ?? null,
      ...(referenceEnabled ? { style_reference: reference } : entry?.style_reference ? { style_reference: null } : {}) };
    try {
      if (entry) await companionApi.editMemory(entry, body, scopeConfirmed);
      else await companionApi.createMemory(body);
      onSaved();
    } catch (cause) { setError(companionError(cause)); }
    finally { setBusy(false); }
  }
  return <CompanionDialog title={t(entry ? "companion.editMemory" : "companion.addMemory")} onClose={onClose} busy={busy}>
    <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); if (valid) void save(); }}>
      <label className="block space-y-1 text-sm">{t("companion.content")}
        <textarea className={inputClass} value={content} maxLength={8000} rows={5} onChange={(event) => setContent(event.target.value)} required />
      </label>
      <div className="grid grid-cols-2 gap-3">
        <label className="space-y-1 text-sm">{t("companion.kind")}
          <select className={inputClass} value={kind} onChange={(event) => setKind(event.target.value as MemoryWrite["kind"])}>
            {(["preference", "project_fact", "style_rule", "experience"] as const).map(value => <option key={value} value={value} disabled={referenceEnabled && value !== "style_rule"}>{t(`companion.${value}`)}</option>)}
          </select>
        </label>
        <label className="space-y-1 text-sm">{t("companion.scope")}
          <select className={inputClass} value={scope.kind} onChange={(event) => { setScope({ kind: event.target.value as MemoryScope["kind"], id: null }); setScopeConfirmed(false); }}>
            {(["global", "project", "expert", "domain"] as const).map(value => <option key={value} value={value} disabled={referenceEnabled && value !== "project"}>{t(`companion.${value}`)}</option>)}
          </select>
        </label>
      </div>
      {scope.kind === "project" && <label className="block space-y-1 text-sm">{t("companion.project")}
        <select className={inputClass} value={scope.id ?? ""} onChange={event => setScope({ ...scope, id: event.target.value || null })} required>
          <option value="">{t("companion.noProject")}</option>
          {projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}
        </select>
      </label>}
      {(scope.kind === "expert" || scope.kind === "domain") && <label className="block space-y-1 text-sm">{t("companion.scopeId")}
        <input className={inputClass} value={scope.id ?? ""} maxLength={100} onChange={event => setScope({ ...scope, id: event.target.value || null })} required />
      </label>}
      {changedScope && <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={scopeConfirmed} onChange={event => setScopeConfirmed(event.target.checked)} />{t("companion.changeScope")}</label>}
      <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={referenceEnabled} onChange={event => {
        setReferenceEnabled(event.target.checked);
        if (event.target.checked) { setKind("style_rule"); if (scope.kind !== "project") setScope({ kind: "project", id: null }); setScopeConfirmed(false); }
      }} />{t("design.addReference")}</label>
      {referenceEnabled && <fieldset className="space-y-3 rounded-xl border border-border p-3">
        <legend className="px-1 text-sm font-medium">{t("design.reference")}</legend>
        <p className="text-xs text-muted-foreground">{t("design.scopeHint")}</p>
        <div className="grid grid-cols-2 gap-3">
          <label className="space-y-1 text-sm">{t("design.sourceKind")}<select className={inputClass} value={reference.source_kind} onChange={event => setReference({ ...reference, source_kind: event.target.value as StyleReference["source_kind"] })}>
            <option value="file">{t("design.file")}</option><option value="url">{t("design.url")}</option><option value="library">{t("design.library")}</option><option value="artifact">{t("design.artifact")}</option>
          </select></label>
          <label className="space-y-1 text-sm">{t("design.polarity")}<select className={inputClass} value={reference.polarity} onChange={event => setReference({ ...reference, polarity: event.target.value as StyleReference["polarity"] })}>
            <option value="positive">{t("design.positive")}</option><option value="negative">{t("design.negative")}</option>
          </select></label>
        </div>
        <label className="block space-y-1 text-sm">{t("design.sourceRef")}<input className={inputClass} maxLength={1000} value={reference.source_ref} onChange={event => setReference({ ...reference, source_ref: event.target.value })} required /></label>
        <label className="block space-y-1 text-sm">{t("design.rationale")}<textarea className={inputClass} maxLength={2000} rows={3} value={reference.rationale} onChange={event => setReference({ ...reference, rationale: event.target.value })} required /></label>
        <label className="block space-y-1 text-sm">{t("design.interpretation")}<select className={inputClass} value={reference.interpretation} onChange={event => setReference({ ...reference, interpretation: event.target.value as StyleReference["interpretation"] })}>
          <option value="tentative">{t("design.tentative")}</option><option value="confirmed">{t("design.confirmed")}</option>
        </select></label>
        <p className="text-xs text-muted-foreground">{t("design.referenceHint")}</p>
      </fieldset>}
      <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={sensitive} onChange={event => { setSensitive(event.target.checked); setAcknowledged(false); }} />{t("companion.sensitive")}</label>
      {sensitive && <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={acknowledged} onChange={event => setAcknowledged(event.target.checked)} />{t("companion.sensitiveAck")}</label>}
      <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={cloud} onChange={event => setCloud(event.target.checked)} />{t("companion.cloud")}</label>
      <p className="text-xs text-muted-foreground">{t("companion.cloudHint")}</p>
      {error && <p role="alert" className="text-sm text-destructive">{t(error)}</p>}
      <div className="flex justify-end gap-2"><button type="button" className={buttonClass} disabled={busy} onClick={onClose}>{t("companion.cancel")}</button>
        <button className={primaryClass} disabled={!valid || busy}>{t(busy ? "companion.loading" : "companion.save")}</button></div>
    </form>
  </CompanionDialog>;
}
