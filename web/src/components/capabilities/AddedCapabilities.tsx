import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { capabilitiesApi, type CapabilitySource, type UpdateInfo } from "../../api/capabilities";
import { companionError } from "../companion/errors";
import { Button, Dialog, Notice, Tag, confirmSheet } from "../kit";

function SourceDossier({ source, onClose, onChanged }: { source: CapabilitySource; onClose: () => void; onChanged: () => void }) {
  const { t } = useTranslation();
  const [row, setRow] = useState(source);
  const [folders, setFolders] = useState((source.grants.folders ?? []).join("\n"));
  const [update, setUpdate] = useState<UpdateInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  async function act(fn: () => Promise<void>) {
    setBusy(true); setError(null); setNote(null);
    try { await fn(); } catch (cause) { setError(companionError(cause)); } finally { setBusy(false); }
  }
  const scanLevel = row.scan?.level ?? null;
  return (
    <Dialog open onClose={onClose} width={640} testId="source-dossier"
      title={<span className="flex items-center gap-2"><Tag>{t(`discover.kind_${row.kind}`)}</Tag>{row.name}</span>}>
      <div className="flex flex-col gap-2 text-[13px]">
        <p data-testid="source-license">{t("discover.card_license")}: {row.license.spdx ?? "—"}{row.license.read_from ? ` · ${row.license.read_from}` : ""}</p>
        <p data-testid="source-version">{t("discover.dossier_version")}: {row.version ?? "—"}
          {row.lock_sha256 && <span className="block font-mono text-[11px] text-muted-foreground">{t("discover.source_lock", { sha: row.lock_sha256.slice(0, 16) })}</span>}
          {row.commit_sha && <span className="block font-mono text-[11px] text-muted-foreground">{t("discover.source_commit", { sha: row.commit_sha.slice(0, 12) })}</span>}</p>
        <p data-testid="source-scan">{t("discover.card_checks")}: {scanLevel ? t(`discover.scan_${scanLevel}`) : "—"}
          {row.scan?.findings.map(f => <span key={`${f.rule}-${f.file}`} className="block text-[11.5px] text-muted-foreground">
            {f.rule} · {f.file}{f.line ? `:${f.line}` : ""}</span>)}</p>
        <p data-testid="source-test">{t("discover.source_test")}: {row.test ? (row.test.ok
          ? t("discover.source_testOk", { count: row.test.tools?.length ?? 0 }) : t("discover.source_testFail", { stage: row.test.stage ?? "", detail: row.test.detail ?? "" })) : "—"}</p>
        {row.kind === "mcp" && row.runtime !== "remote" && <label className="flex flex-col gap-1">
          <span className="text-muted-foreground">{t("discover.source_folders")}</span>
          <textarea rows={2} value={folders} onChange={e => setFolders(e.target.value)} data-testid="source-folders"
            className="rounded-lg border border-border bg-background px-2.5 py-1.5 font-mono text-[12px]" />
          <Button size="sm" className="self-start" disabled={busy} data-testid="source-folders-save"
            onClick={() => void act(async () => {
              setRow(await capabilitiesApi.setFolders(row.id, folders.split("\n").map(f => f.trim()).filter(Boolean)));
              setNote(t("discover.source_foldersSaved"));
            })}>{t("discover.source_foldersSave")}</Button>
        </label>}
        {error && <Notice tone="error">{t(error)}</Notice>}
        {note && <Notice tone="info">{note}</Notice>}
        {update && <Notice tone="info" testId="source-update">
          {update.newer ? t("discover.source_newer", { current: update.current ?? "", latest: update.latest ?? "" })
            : t("discover.source_current")}
          {update.compare_url && <a className="ml-1 underline" href={update.compare_url} target="_blank" rel="noopener noreferrer">
            {t("discover.source_whatChanged")}</a>}</Notice>}
        <div className="flex flex-wrap gap-2 border-t border-border pt-3">
          <Button size="sm" disabled={busy} data-testid="source-check-update"
            onClick={() => void act(async () => setUpdate(await capabilitiesApi.checkUpdate(row.id)))}>{t("discover.source_checkUpdate")}</Button>
          {update?.newer && <Button size="sm" tone="primary" disabled={busy} data-testid="source-apply-update"
            onClick={() => void act(async () => {
              const r = await capabilitiesApi.update(row.id);
              setNote(r.state === "on" ? t("discover.source_updated", { latest: update.latest ?? "" }) : t("discover.source_updateKept"));
              onChanged();
            })}>{t("discover.source_applyUpdate", { latest: update.latest ?? "" })}</Button>}
          <span className="flex-1" />
          <Button size="sm" tone="plain" disabled={busy} data-testid="source-remove"
            onClick={() => void (async () => {
              const ok = await confirmSheet({ title: t("discover.source_removeTitle", { name: row.name }),
                body: t("discover.source_removeBody"), action: t("discover.source_remove") });
              if (!ok) return;
              await act(async () => { await capabilitiesApi.remove(row.id); onChanged(); onClose(); });
            })()}>{t("discover.source_remove")}</Button>
        </div>
      </div>
    </Dialog>
  );
}

/** "Arslan 加的" (0.1.57 §7): what was installed through the loop, each with its dossier. */
export default function AddedCapabilities() {
  const { t } = useTranslation();
  const [rows, setRows] = useState<CapabilitySource[] | null>(null);
  const [open, setOpen] = useState<CapabilitySource | null>(null);
  const load = useCallback(async () => {
    try { setRows(await capabilitiesApi.sources()); } catch { setRows([]); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  if (!rows || rows.length === 0) return null;
  return (
    <section className="mt-6 flex flex-col gap-1.5" data-testid="added-capabilities">
      <h3 className="px-1 text-[12px] font-semibold text-muted-foreground">{t("discover.added_title")}</h3>
      <ul className="overflow-hidden rounded-xl border border-border bg-background">
        {rows.map(r => <li key={r.id} className="flex items-center gap-3 border-t border-border px-3.5 py-2 text-[13px] first:border-t-0"
          data-testid={`added-${r.id}`}>
          <Tag>{t(`discover.kind_${r.kind}`)}</Tag>
          <span className="min-w-0 flex-1 truncate font-medium">{r.name}</span>
          <span className="font-mono text-[11.5px] text-muted-foreground">{r.version ?? ""}</span>
          <span className={`text-[12px] ${r.state === "installed" && r.test?.ok !== false ? "text-success" : "text-danger-strong"}`}>
            {t(r.state === "installed" && r.test?.ok !== false ? "discover.added_on" : "discover.added_failed")}</span>
          <Button size="sm" onClick={() => setOpen(r)} data-testid={`added-open-${r.id}`}>{t("discover.added_dossier")}</Button>
        </li>)}
      </ul>
      {open && <SourceDossier source={open} onClose={() => setOpen(null)} onChanged={() => void load()} />}
    </section>
  );
}
