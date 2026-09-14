import { useCallback, useEffect, useRef, useState } from "react";
import { History, LockKeyhole, Pencil, Plus, RefreshCw, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { companionApi, type MemoryEntry, type MemoryProposal, type MemoryRevision, type Project } from "../../api/companion";
import CompanionDialog, { buttonClass, inputClass, primaryClass } from "./CompanionDialog";
import MemoryEditor from "./MemoryEditor";
import { companionError } from "./errors";

function ReviewProposal({ proposal, scopeLabel, onClose, onSaved }: {
  proposal: MemoryProposal; scopeLabel: string; onClose: () => void; onSaved: () => void;
}) {
  const { t } = useTranslation();
  const [ack, setAck] = useState(false);
  const [cloud, setCloud] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sensitive = (proposal.candidate?.sensitivity ?? proposal.entry.sensitivity) !== "normal";
  const stale = proposal.target_version !== proposal.entry.version;
  const unavailable = !(proposal.candidate?.content ?? proposal.entry.content) || proposal.entry.sensitivity === "secret";
  async function decide(accept: boolean) {
    setBusy(true); setError(null);
    try { await companionApi.resolveProposal(proposal.id, accept, ack, cloud); onSaved(); }
    catch (cause) { setError(companionError(cause)); }
    finally { setBusy(false); }
  }
  return <CompanionDialog title={t("companion.pending")} onClose={onClose} busy={busy}>
    <div className="space-y-4 text-sm">
      {proposal.candidate && <div><h3 className="mb-1 text-muted-foreground">{t("companion.current")}</h3><p className="whitespace-pre-wrap rounded-lg bg-foreground/5 p-3">{proposal.entry.content}</p></div>}
      <div><h3 className="mb-1 text-muted-foreground">{t("companion.suggested")}</h3><p className="whitespace-pre-wrap rounded-lg border border-primary/30 p-3">{proposal.candidate?.content ?? proposal.entry.content}</p></div>
      <p>{t("companion.scope")}: {scopeLabel}</p>
      {sensitive && <label className="flex items-start gap-2"><input type="checkbox" checked={ack} onChange={event => setAck(event.target.checked)} />{t("companion.sensitiveAck")}</label>}
      <label className="flex items-start gap-2"><input type="checkbox" checked={cloud} onChange={event => setCloud(event.target.checked)} />{t("companion.cloud")}</label>
      <p className="text-xs text-muted-foreground">{t("companion.cloudHint")}</p>
      {stale && <p role="alert" className="text-destructive">{t("companion.conflict")}</p>}
      {unavailable && <p role="alert" className="text-destructive">{t("companion.credentialError")}</p>}
      {error && <p role="alert" className="text-destructive">{t(error)}</p>}
      <div className="flex justify-end gap-2">
        <button className={buttonClass} disabled={busy} onClick={() => void decide(false)}>{t("companion.dismiss")}</button>
        <button className={primaryClass} disabled={busy || stale || unavailable || (sensitive && !ack)} onClick={() => void decide(true)}>{t("companion.confirm")}</button>
      </div>
    </div>
  </CompanionDialog>;
}

function MemoryHistory({ entry, onClose }: { entry: MemoryEntry; onClose: () => void }) {
  const { t, i18n } = useTranslation();
  const [rows, setRows] = useState<MemoryRevision[] | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let alive = true;
    companionApi.history(entry.id).then(value => { if (alive) setRows(value); }).catch(() => { if (alive) setError(true); });
    return () => { alive = false; };
  }, [entry.id]);
  return <CompanionDialog title={t("companion.history")} onClose={onClose}>
    {error ? <p role="alert">{t("brain.read_failed")}</p> : !rows ? <p role="status">{t("companion.loading")}</p> :
      <ol className="space-y-4">{rows.map(row => <li key={row.id} className="rounded-xl border border-border p-3">
        <div className="mb-2 flex justify-between gap-2 text-xs text-muted-foreground"><span>{t("companion.version", { version: row.version })}</span>
          <time dateTime={row.created_at}>{new Date(row.created_at).toLocaleString(i18n.resolvedLanguage)}</time></div>
        <p className="whitespace-pre-wrap break-words text-sm">{row.content}</p>
      </li>)}</ol>}
  </CompanionDialog>;
}

type Dialog = { kind: "edit"; entry?: MemoryEntry } | { kind: "delete" | "history" | "source"; entry: MemoryEntry } | { kind: "proposal"; proposal: MemoryProposal };
export default function MemoryList() {
  const { t, i18n } = useTranslation();
  const [entries, setEntries] = useState<MemoryEntry[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [proposals, setProposals] = useState<MemoryProposal[]>([]);
  const [loading, setLoading] = useState(true);
  const [moreEntries, setMoreEntries] = useState(false);
  const [moreProposals, setMoreProposals] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [showPending, setShowPending] = useState(false);
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const generation = useRef(0);
  const offsets = useRef({ entries: 0, proposals: 0 });
  const reload = useCallback(async () => {
    const request = ++generation.current;
    setLoading(true); setError(null);
    try {
      const [memories, projectRows, pending] = await Promise.all([companionApi.memories(), companionApi.projects(), companionApi.proposals()]);
      if (request === generation.current) {
        setEntries(memories); setProjects(projectRows); setProposals(pending);
        setMoreEntries(memories.length === 100); setMoreProposals(pending.length === 100);
        offsets.current = { entries: memories.length, proposals: pending.length };
      }
    } catch { if (request === generation.current) setError("brain.read_failed"); }
    finally { if (request === generation.current) setLoading(false); }
  }, []);
  async function loadMore(pending: boolean) {
    if (loading || busy) return;
    const request = generation.current;
    setBusy(true); setError(null);
    try {
      if (pending) {
        const rows = await companionApi.proposals(offsets.current.proposals);
        if (request === generation.current) {
          offsets.current.proposals += rows.length;
          setProposals(old => [...old, ...rows.filter(row => !old.some(item => item.id === row.id))]);
          setMoreProposals(rows.length === 100);
        }
      } else {
        const rows = await companionApi.memories(offsets.current.entries);
        if (request === generation.current) {
          offsets.current.entries += rows.length;
          setEntries(old => [...old, ...rows.filter(row => !old.some(item => item.id === row.id))]);
          setMoreEntries(rows.length === 100);
        }
      }
    } catch { if (request === generation.current) setError("brain.read_failed"); }
    finally { setBusy(false); }
  }
  useEffect(() => { void reload(); return () => { generation.current++; }; }, [reload]);
  const saved = () => { setDialog(null); void reload(); };
  const scopeName = (entry: MemoryEntry) => entry.scope.kind === "project"
    ? projects.find(project => project.id === entry.scope.id)?.name ?? t("companion.project")
    : `${t(`companion.${entry.scope.kind}`)}${entry.scope.id ? ` · ${entry.scope.id}` : ""}`;
  const sourceName = (kind: string) => t(`companion.${["manual", "user_message", "host", "worker", "extractor", "legacy"].includes(kind) ? kind : "unknownSource"}`);
  const visible = entries.filter(entry => (filter === "all" || entry.status === filter)
    && (entry.content ?? "").toLocaleLowerCase().includes(query.toLocaleLowerCase().trim()));

  async function change(operation: () => Promise<unknown>) {
    setBusy(true); setError(null);
    try { await operation(); setDialog(null); await reload(); }
    catch (cause) { setError(companionError(cause)); }
    finally { setBusy(false); }
  }
  return <section className="h-full overflow-y-auto px-5 py-6 sm:px-8" aria-label={t("companion.about")}>
    <div className="mx-auto max-w-5xl space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-4"><div><h1 className="text-xl font-semibold">{t("companion.about")}</h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground">{t("companion.memoryIntro")}</p></div>
        <button className={primaryClass} onClick={() => setDialog({ kind: "edit" })}><Plus size={16} />{t("companion.addMemory")}</button></div>
      <div className="flex flex-wrap gap-2">
        <input className={`${inputClass} min-w-40 flex-1`} type="search" aria-label={t("companion.search")} placeholder={t("companion.search")} value={query} onChange={event => setQuery(event.target.value)} />
        <select className={`${inputClass} !w-auto`} aria-label={t("companion.active")} value={filter} onChange={event => setFilter(event.target.value)}>
          {["all", "active", "proposed", "paused", "quarantined", "expired", "superseded"].map(value => <option key={value} value={value}>{t(`companion.${value}`)}</option>)}
        </select>
        <button className={buttonClass} aria-pressed={showPending} onClick={() => setShowPending(value => !value)}>{t("companion.pending")} <span className="rounded-full bg-primary/10 px-2 text-primary">{proposals.length}</span></button>
        <button className={buttonClass} aria-label={t("companion.refresh")} disabled={loading || busy} onClick={() => void reload()}><RefreshCw size={16} /></button>
      </div>
      {error && <p role="alert" className="rounded-lg border border-destructive/30 p-3 text-sm text-destructive">{t(error)}</p>}
      {loading && <p role="status" className="text-sm text-muted-foreground">{t("companion.loading")}</p>}
      {showPending && <div className="space-y-2 rounded-xl border border-primary/20 bg-primary/5 p-4">
        <h2 className="text-sm font-semibold">{t("companion.pending")}</h2>
        {!proposals.length && <p className="text-sm text-muted-foreground">{t("companion.pendingEmpty")}</p>}
        {proposals.map(proposal => <button key={proposal.id} className="block w-full rounded-lg bg-background p-3 text-left text-sm hover:outline hover:outline-primary/40"
          onClick={() => setDialog({ kind: "proposal", proposal })}><span className="line-clamp-2">{proposal.candidate?.content ?? proposal.entry.content}</span>
          <span className="mt-1 block text-xs text-muted-foreground">{scopeName(proposal.entry)}</span></button>)}
        {moreProposals && <button className={buttonClass} disabled={loading || busy} onClick={() => void loadMore(true)}>{t("companion.loadMore")}</button>}
      </div>}
      {!loading && !error && !visible.length && <p className="rounded-xl border border-dashed border-border px-5 py-12 text-center text-sm text-muted-foreground">{t(entries.length ? "companion.noMatches" : "companion.emptyMemory")}</p>}
      <ul className="space-y-3" aria-busy={loading || busy}>
        {visible.map(entry => <li key={entry.id} className="rounded-xl border border-border bg-background/60 p-4">
          <div className="flex flex-wrap items-start justify-between gap-3"><p className="min-w-0 flex-1 whitespace-pre-wrap break-words text-sm leading-relaxed">{entry.content ?? t("companion.credentialError")}</p>
            <span className={`rounded-full px-2 py-1 text-xs ${entry.status === "active" ? "bg-primary/10 text-primary" : "bg-foreground/5 text-muted-foreground"}`}>{t(`companion.${entry.status}`)}</span></div>
          <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 text-xs text-muted-foreground">
            <span>{scopeName(entry)}</span><span>{t(`companion.${entry.kind}`)}</span>
            <span className="inline-flex items-center gap-1">{entry.sensitivity !== "normal" && <LockKeyhole size={12} />}{t(entry.use_policy === "cloud_allowed" ? "companion.cloudAllowed" : "companion.localOnly")}</span>
            <time dateTime={entry.updated_at}>{new Date(entry.updated_at).toLocaleDateString(i18n.resolvedLanguage)}</time>
            <button className="underline underline-offset-2 hover:text-foreground" onClick={() => setDialog({ kind: "source", entry })}>{t("companion.source")}</button>
          </div>
          <div className="mt-3 flex flex-wrap justify-end gap-2">
            <button className={buttonClass} disabled={busy || loading} onClick={() => setDialog({ kind: "history", entry })}><History size={14} />{t("companion.history")}</button>
            <button className={buttonClass} disabled={busy || loading || entry.sensitivity === "secret"} onClick={() => setDialog({ kind: "edit", entry })}><Pencil size={14} />{t("companion.edit")}</button>
            {(entry.status === "active" || entry.status === "paused") && <button className={buttonClass} disabled={busy || loading}
              onClick={() => void change(() => companionApi.setMemoryStatus(entry, entry.status === "active" ? "paused" : "active"))}>{t(entry.status === "active" ? "companion.pause" : "companion.resume")}</button>}
            <button className={`${buttonClass} text-destructive`} disabled={busy || loading} onClick={() => setDialog({ kind: "delete", entry })}><Trash2 size={14} />{t("companion.remove")}</button>
          </div>
        </li>)}
      </ul>
      {moreEntries && <div className="space-y-2"><p className="text-xs text-muted-foreground">{t("companion.loadedSearch")}</p>
        <button className={buttonClass} disabled={loading || busy} onClick={() => void loadMore(false)}>{t("companion.loadMore")}</button></div>}
    </div>
    {dialog?.kind === "edit" && <MemoryEditor entry={dialog.entry} projects={projects} onClose={() => setDialog(null)} onSaved={saved} />}
    {dialog?.kind === "history" && <MemoryHistory entry={dialog.entry} onClose={() => setDialog(null)} />}
    {dialog?.kind === "proposal" && <ReviewProposal proposal={dialog.proposal} scopeLabel={scopeName(dialog.proposal.entry)} onClose={() => setDialog(null)} onSaved={saved} />}
    {dialog?.kind === "delete" && <CompanionDialog title={t("companion.deleteTitle")} onClose={() => setDialog(null)} busy={busy}>
      <p className="mb-3 whitespace-pre-wrap text-sm">{dialog.entry.content}</p><p className="mb-5 text-sm text-muted-foreground">{t("companion.deleteHint")}</p>
      {error && <p role="alert" className="mb-3 text-sm text-destructive">{t(error)}</p>}
      <div className="flex justify-end gap-2"><button className={buttonClass} disabled={busy} onClick={() => setDialog(null)}>{t("companion.cancel")}</button>
        <button className={`${buttonClass} border-destructive/40 text-destructive`} disabled={busy} onClick={() => void change(() => companionApi.deleteMemory(dialog.entry))}>{t("companion.remove")}</button></div>
    </CompanionDialog>}
    {dialog?.kind === "source" && <CompanionDialog title={t("companion.source")} onClose={() => setDialog(null)}>
      <ul className="space-y-3">{dialog.entry.sources.map(source => <li key={source.id} className="rounded-lg border border-border p-3 text-sm">
        <p>{sourceName(source.kind)}</p><dl className="mt-2 space-y-1 break-all text-xs text-muted-foreground">{Object.entries(source.reference).map(([key, value]) => <div key={key}><dt className="inline">{key}: </dt><dd className="inline">{String(value)}</dd></div>)}</dl>
      </li>)}</ul>
      {!dialog.entry.sources.length && <p className="text-sm">{t("companion.unknownSource")}</p>}
    </CompanionDialog>}
  </section>;
}
