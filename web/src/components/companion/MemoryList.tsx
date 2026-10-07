import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { FileText, Globe, KeyRound, Laptop, PinOff, Search, Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";
import { api } from "../../api/client";
import { companionApi, type MemoryEntry, type MemoryProposal, type MemoryRevision, type MemoryStats, type MemoryWrite, type Project } from "../../api/companion";
import { lessonsApi, type Lesson } from "../../api/lessons";
import { announceProactiveChange } from "../../api/proactive";
import { loadPendingMemory, type PendingMemoryItem } from "../../lib/pendingMemory";
import { openSection } from "../../lib/sections";
import { Button, Notice, ProposalRow, Tag, confirmSheet } from "../kit";
import CompanionDialog, { buttonClass, primaryClass } from "./CompanionDialog";
import MemoryEditor from "./MemoryEditor";
import StyleReferenceView from "./StyleReferenceView";
import { companionError } from "./errors";

function ReviewProposal({ proposal, scopeLabel, onClose, onSaved }: {
  proposal: MemoryProposal; scopeLabel: string; onClose: () => void; onSaved: () => void;
}) {
  const { t } = useTranslation();
  const [ack, setAck] = useState(false);
  // 0.1.52 (D1): a normal memory is usable with the chosen model by default.
  const [cloud, setCloud] = useState((proposal.candidate?.sensitivity ?? proposal.entry.sensitivity) === "normal");
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
      {proposal.candidate && <div><h3 className="mb-1 text-muted-foreground">{t("companion.current")}</h3><p className="whitespace-pre-wrap rounded-lg bg-fill p-3">{proposal.entry.content}</p></div>}
      <div><h3 className="mb-1 text-muted-foreground">{t("companion.suggested")}</h3><p className="whitespace-pre-wrap rounded-lg border border-border p-3">{proposal.candidate?.content ?? proposal.entry.content}</p></div>
      <p>{t("companion.scope")}: {scopeLabel}</p>
      <StyleReferenceView reference={proposal.candidate ? proposal.candidate.style_reference : proposal.entry.style_reference} />
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
        <StyleReferenceView reference={row.style_reference} />
      </li>)}</ol>}
  </CompanionDialog>;
}

/** The two always-in-view sets; budgets come from the server (`/memory/stats`). */
const CORE_SETS = [
  { key: "about_you", kind: "preference", label: "memoryPage.inViewAbout" },
  { key: "notes", kind: "experience", label: "memoryPage.inViewNotes" },
] as const;
const coreSetFor = (entry: MemoryEntry) => entry.scope.kind === "global"
  ? CORE_SETS.find(set => set.kind === entry.kind) : undefined;
/** Same entry, with only its always-in-view membership changed. */
export function withCore(entry: MemoryEntry, core: MemoryWrite["core"]): MemoryWrite {
  return { content: entry.content ?? "", kind: entry.kind, scope: entry.scope,
    sensitivity: entry.sensitivity === "secret" ? "unknown" : entry.sensitivity,
    use_policy: entry.use_policy === "never" ? "local_only" : entry.use_policy,
    topic: entry.topic ?? null, valid_from: entry.valid_from, review_at: entry.review_at,
    expires_at: entry.expires_at, core };
}

/** Most recently used first; never-used ones after, newest edit first. */
export function byRecentUse(a: MemoryEntry, b: MemoryEntry): number {
  const used = (b.last_used_at ?? "").localeCompare(a.last_used_at ?? "");
  return used || (b.updated_at ?? "").localeCompare(a.updated_at ?? "");
}

const LIVE = new Set(["active", "paused"]);
const FIRST_ROWS = 12;

/** A titled block on the page: a quiet heading, then rows on one surface. */
function Block({ title, aside, children, testId }: { title: ReactNode; aside?: ReactNode; children: ReactNode; testId?: string }) {
  return <section data-testid={testId} className="flex flex-col gap-1.5">
    <h2 className="flex items-baseline gap-2 px-1 text-[12px] font-semibold text-muted-foreground">{title}
      {aside ? <span className="ml-auto font-normal">{aside}</span> : null}</h2>
    <div className="overflow-hidden rounded-xl border border-border bg-surface">{children}</div>
  </section>;
}

/** Row actions: shown on hover or keyboard focus, so a long list reads as text, not as buttons. */
function HoverActions({ children }: { children: ReactNode }) {
  return <span className="memory-row__actions flex shrink-0 items-center gap-0.5 rounded-lg border border-border bg-background p-0.5 text-[12px]">{children}</span>;
}
const actionClass = "rounded-md px-2 py-0.5 text-foreground hover:bg-fill disabled:opacity-50";

function RailRow({ icon, title, sub, children }: { icon: ReactNode; title: ReactNode; sub?: ReactNode; children?: ReactNode }) {
  return <div className="flex items-start gap-2.5 border-t border-border px-3.5 py-2.5 first:border-t-0">
    <span className="mt-0.5 shrink-0 text-subtle-foreground">{icon}</span>
    <div className="flex min-w-0 flex-1 flex-col gap-0.5"><span className="text-[13px]">{title}</span>
      {sub ? <span className="text-[12px] text-subtle-foreground">{sub}</span> : null}{children}</div>
  </div>;
}

function IndexLine() {
  const { t } = useTranslation();
  const [line, setLine] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    api.embeddingStatus().then(s => {
      if (!alive) return;
      const total = s?.total ?? ((s?.embedded ?? 0) + (s?.pending ?? 0));
      setLine(!s ? t("memoryPage.indexUnknown") : total === 0 ? t("memoryPage.indexEmpty")
        : (s.pending ?? 0) > 0 ? t("memoryPage.indexPending", { count: s.pending }) : t("memoryPage.indexOk"));
    }).catch(() => { if (alive) setLine(t("memoryPage.indexUnknown")); });
    return () => { alive = false; };
  }, [t]);
  return line ? <span data-testid="memory-index-line">{line}</span> : null;
}

/** 0.1.52 S5: what Arslan learned from your corrections and its own detours, with its record. */
function LearnedPractices({ lessons, busy, change }: {
  lessons: Lesson[]; busy: boolean; change: (operation: () => Promise<unknown>) => Promise<void>;
}) {
  const { t } = useTranslation();
  const [showRetired, setShowRetired] = useState(false);
  const current = lessons.filter(lesson => lesson.status === "active");
  const retired = lessons.filter(lesson => lesson.status === "archived");
  const source = { user_correction: "companion.sourceUser", detour: "companion.sourceDetour", machine_quirk: "companion.sourceQuirk" } as const;
  const remove = async (lesson: Lesson) => {
    if (await confirmSheet({ title: t("memoryPage.deletePracticeTitle"), body: t("memoryPage.deletePracticeBody"), action: t("companion.remove") }))
      await change(() => lessonsApi.remove(lesson.id));
  };
  const row = (lesson: Lesson) => <div key={lesson.id} data-testid={`practice-${lesson.id}`} className="memory-row group flex items-center gap-3 border-t border-border px-4 py-2.5 first:border-t-0">
    <div className="flex min-w-0 flex-1 flex-col gap-1">
      <span className="break-words text-[14px] leading-snug">{lesson.text}</span>
      <span className="flex flex-wrap items-center gap-1.5 text-[11px] text-subtle-foreground">
        <Tag>{t(source[lesson.source])}</Tag>{lesson.pinned ? <Tag>{t("companion.practiceUnpin")}</Tag> : null}
        <span>{t("companion.practiceCounts", { recalled: lesson.recalled, followed: lesson.followed, succeeded: lesson.succeeded, failed: lesson.failed })}</span>
      </span>
    </div>
    <HoverActions>
      {lesson.status === "archived"
        ? <button className={actionClass} disabled={busy} onClick={() => void change(() => lessonsApi.setStatus(lesson.id, "active"))}>{t("companion.practiceRestore")}</button>
        : <button className={actionClass} disabled={busy} onClick={() => void change(() => lessonsApi.setStatus(lesson.id, "archived"))}>{t("companion.practiceRetire")}</button>}
      <button className={actionClass} disabled={busy} onClick={() => void change(() => lessonsApi.pin(lesson.id, !lesson.pinned))}>{t(lesson.pinned ? "companion.practiceUnpin" : "companion.practicePin")}</button>
      <button className={`${actionClass} !text-destructive`} disabled={busy} onClick={() => void remove(lesson)}>{t("companion.remove")}</button>
    </HoverActions>
  </div>;
  if (!current.length && !retired.length) return null;
  return <div data-testid="learned-practices" className="flex flex-col gap-1.5">
    <Block title={t("memoryPage.practices")}>
      {current.map(row)}
      {!current.length && <p className="px-4 py-3 text-[13px] text-subtle-foreground">{t("companion.practicesHint")}</p>}
    </Block>
    {retired.length > 0 && <button className="self-start px-1 text-[12px] text-muted-foreground hover:text-foreground" aria-expanded={showRetired}
      onClick={() => setShowRetired(value => !value)}>{t("companion.practiceRetired", { count: retired.length })}</button>}
    {showRetired && <div className="overflow-hidden rounded-xl border border-border bg-surface opacity-75">{retired.map(row)}</div>}
  </div>;
}

type Dialog = { kind: "edit"; entry?: MemoryEntry } | { kind: "history" | "source"; entry: MemoryEntry } | { kind: "proposal"; proposal: MemoryProposal };

export interface MemoryListProps {
  /** Bumped by the page's "Add › Remember something": opens the editor. */
  addRequest?: number;
  /** Called once the editor is open, so a later remount does not open it again. */
  onAddHandled?: () => void;
  /** Feed material / write a note / browse: the page shows its materials view. */
  onOpenMaterials?: (mode: "browse" | "feed" | "note") => void;
}

/**
 * Memory, as one page (0.1.55 §13, board Memory-List-v3): what waits for you, what is
 * always in view, what Arslan knows about you (most recently used first, with how
 * often it was used this week), and what it learned — with materials, this week's
 * use and who can use memory on the right.
 */
export default function MemoryList({ addRequest = 0, onAddHandled, onOpenMaterials }: MemoryListProps) {
  const { t } = useTranslation();
  const [entries, setEntries] = useState<MemoryEntry[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [pending, setPending] = useState<PendingMemoryItem[]>([]);
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [moreEntries, setMoreEntries] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState("all");
  const [showAll, setShowAll] = useState(false);
  const [showPending, setShowPending] = useState(false);
  const [showOther, setShowOther] = useState(false);
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [noticed, setNoticed] = useState(0);
  const [practices, setPractices] = useState<Lesson[]>([]);
  const generation = useRef(0);
  const offset = useRef(0);
  const reload = useCallback(async () => {
    const request = ++generation.current;
    setLoading(true); setError(null);
    try {
      const [memories, projectRows, waiting, earlier, learned, numbers] = await Promise.all([companionApi.memories(), companionApi.projects(),
        loadPendingMemory(t).catch(() => [] as PendingMemoryItem[]), companionApi.noticedEarlier().catch(() => ({ count: 0 })),
        lessonsApi.list().catch(() => [] as Lesson[]), companionApi.memoryStats().catch(() => null)]);
      if (request === generation.current) {
        setNoticed(earlier.count); setPractices(learned); setStats(numbers);
        setEntries(memories); setProjects(projectRows); setPending(waiting);
        setMoreEntries(memories.length === 100);
        offset.current = memories.length;
      }
    } catch { if (request === generation.current) setError("brain.read_failed"); }
    finally { if (request === generation.current) setLoading(false); }
  }, [t]);
  async function loadMore() {
    if (loading || busy) return;
    const request = generation.current;
    setBusy(true); setError(null);
    try {
      const rows = await companionApi.memories(offset.current);
      if (request === generation.current) {
        offset.current += rows.length;
        setEntries(old => [...old, ...rows.filter(row => !old.some(item => item.id === row.id))]);
        setMoreEntries(rows.length === 100);
      }
    } catch { if (request === generation.current) setError("brain.read_failed"); }
    finally { setBusy(false); }
  }
  useEffect(() => { void reload(); return () => { generation.current++; }; }, [reload]);
  useEffect(() => {
    if (addRequest > 0) { setDialog({ kind: "edit" }); onAddHandled?.(); }
  }, [addRequest, onAddHandled]);
  const saved = () => { setDialog(null); void reload(); };
  const scopeName = (entry: MemoryEntry) => entry.scope.kind === "project"
    ? projects.find(project => project.id === entry.scope.id)?.name ?? t("companion.project")
    : `${t(`companion.${entry.scope.kind}`)}${entry.scope.id ? ` · ${entry.scope.id}` : ""}`;
  const sourceName = (kind: string) => t(`companion.${["manual", "user_message", "host", "worker", "extractor", "legacy"].includes(kind) ? kind : "unknownSource"}`);

  async function change(operation: () => Promise<unknown>) {
    setBusy(true); setError(null);
    try { await operation(); setDialog(null); await reload(); }
    catch (cause) { setError(companionError(cause)); }
    finally { setBusy(false); }
  }
  async function answer(run: () => Promise<unknown>) {
    await change(run);
    announceProactiveChange();
  }
  async function remove(entry: MemoryEntry) {
    if (await confirmSheet({ title: t("memoryPage.deleteTitle"), body: t("memoryPage.deleteBody"), action: t("companion.remove") }))
      await change(() => companionApi.deleteMemory(entry));
  }

  const needle = query.toLocaleLowerCase().trim();
  const inScope = (entry: MemoryEntry) => scope === "all" || (scope === "global" ? entry.scope.kind === "global"
    : entry.scope.kind === "project" && entry.scope.id === scope.slice("project:".length));
  const matches = (entry: MemoryEntry) => inScope(entry) && (entry.content ?? "").toLocaleLowerCase().includes(needle);
  const live = useMemo(() => entries.filter(entry => LIVE.has(entry.status)).sort(byRecentUse), [entries]);
  const visible = live.filter(matches);
  const other = entries.filter(entry => !LIVE.has(entry.status) && entry.status !== "proposed" && matches(entry));
  const shown = showAll || needle ? visible : visible.slice(0, FIRST_ROWS);
  const waitingShown = showPending ? pending : pending.slice(0, 3);

  const entryRow = (entry: MemoryEntry) => {
    const set = coreSetFor(entry);
    const uses = entry.uses_this_week ?? 0;
    return <div key={entry.id} data-testid={`memory-${entry.id}`} className={`memory-row group flex items-center gap-3 border-t border-border px-4 py-2.5 first:border-t-0 ${entry.status === "active" ? "" : "opacity-70"}`}>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <span className="whitespace-pre-wrap break-words text-[14px] leading-snug">{entry.content ?? t("companion.credentialError")}</span>
        <span className="flex flex-wrap items-center gap-1.5 text-[11px] text-subtle-foreground">
          <Tag>{t(`companion.${entry.kind}`)}</Tag>
          {entry.scope.kind !== "global" && <Tag tone="info">{scopeName(entry)}</Tag>}
          {entry.core && <Tag>{t("memoryPage.inViewTag")}</Tag>}
          {entry.status === "paused" && <Tag>{t("memoryPage.paused")}</Tag>}
          {entry.status !== "active" && entry.status !== "paused" && <Tag>{t(`companion.${entry.status}`)}</Tag>}
          {entry.sensitivity !== "normal" && <Tag tone="danger">{t("memoryPage.sensitive")}</Tag>}
          {entry.use_policy !== "cloud_allowed" && <Tag>{t("memoryPage.localOnly")}</Tag>}
          {entry.confirmation_kind && <span>{t(`memoryPage.origin_${entry.confirmation_kind}`, { defaultValue: "" })}</span>}
          <button className="hover:text-foreground" onClick={() => setDialog({ kind: "source", entry })}>{t("companion.source")}</button>
        </span>
      </div>
      <span data-testid={`memory-uses-${entry.id}`} className="memory-row__meta shrink-0 text-[12px] text-subtle-foreground">
        {uses > 0 ? t("memoryPage.usedTimes", { count: uses }) : t("memoryPage.notUsed")}</span>
      <HoverActions>
        {set && entry.status === "active" && entry.content && <button className={actionClass} disabled={busy || loading}
          onClick={() => void change(() => companionApi.editMemory(entry, withCore(entry, entry.core ? null : set.key), false))}>
          {t(entry.core ? "companion.takeOutOfView" : "companion.keepInView")}</button>}
        <button className={actionClass} disabled={busy || loading || entry.sensitivity === "secret"} onClick={() => setDialog({ kind: "edit", entry })}>{t("companion.edit")}</button>
        {LIVE.has(entry.status) && <button className={actionClass} disabled={busy || loading}
          onClick={() => void change(() => companionApi.setMemoryStatus(entry, entry.status === "active" ? "paused" : "active"))}>{t(entry.status === "active" ? "companion.pause" : "companion.resume")}</button>}
        <button className={actionClass} disabled={busy || loading} onClick={() => setDialog({ kind: "history", entry })}>{t("companion.history")}</button>
        <button className={`${actionClass} !text-destructive`} disabled={busy || loading} onClick={() => void remove(entry)}>{t("companion.remove")}</button>
      </HoverActions>
    </div>;
  };

  const coreRows = (key: "about_you" | "notes") => entries.filter(entry => entry.core === key && entry.status === "active");
  const coreCard = (set: (typeof CORE_SETS)[number]) => {
    const rows = coreRows(set.key);
    const budget = stats?.core[set.key];
    const used = budget?.used ?? rows.reduce((sum, entry) => sum + (entry.content ?? "").replace(/\s+/g, " ").trim().length, 0);
    const cap = budget?.cap ?? 0;
    return <div key={set.key} data-testid={`in-view-${set.key}`} className="flex min-w-0 flex-1 flex-col gap-2 rounded-xl border border-border bg-surface px-3.5 py-3">
      <span className="flex items-baseline justify-between gap-2 text-[13px] font-semibold">{t(set.label)}
        {cap > 0 && <span className="font-mono text-[11px] font-normal text-subtle-foreground">{t("memoryPage.inViewChars", { used, cap })}</span>}</span>
      {cap > 0 && <div className="h-1 rounded-full bg-fill" aria-hidden="true"><div className="h-full rounded-full bg-foreground" style={{ width: `${Math.min(100, Math.round(100 * used / cap))}%` }} /></div>}
      {rows.length ? <ul className="flex flex-col gap-1">{rows.map(entry => <li key={entry.id} className="group flex items-start gap-2 text-[12px] text-muted-foreground">
        <span className="min-w-0 flex-1 line-clamp-2 break-words">{entry.content}</span>
        <button className="shrink-0 text-subtle-foreground hover:text-foreground" aria-label={t("companion.takeOutOfView")} title={t("companion.takeOutOfView")} disabled={busy || loading}
          onClick={() => void change(() => companionApi.editMemory(entry, withCore(entry, null), false))}><PinOff size={13} /></button>
      </li>)}</ul> : <span className="text-[12px] text-subtle-foreground">{t("memoryPage.inViewEmpty")}</span>}
      {(budget?.left_out ?? 0) > 0 && <span className="text-[11px] text-ask">{t("memoryPage.inViewLeftOut", { count: budget!.left_out })}</span>}
    </div>;
  };

  const pendingLabel = (item: PendingMemoryItem) => item.source === "curation" ? t("pendingMemory.apply")
    : item.source === "lesson" ? t("pendingMemory.use") : item.sensitive ? t("pendingMemory.keepLocal") : t("pendingMemory.keep");

  return <section className="h-full overflow-y-auto px-5 py-5 sm:px-8" aria-label={t("memoryPage.title")}>
    <div className="mx-auto flex max-w-6xl flex-col gap-5 lg:flex-row lg:items-start">
      <div className="flex min-w-0 flex-1 flex-col gap-5">
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex h-8 min-w-40 flex-1 items-center gap-1.5 rounded-lg bg-fill px-2.5 text-[13px] text-subtle-foreground">
            <Search size={13} aria-hidden="true" />
            <input type="search" className="min-w-0 flex-1 bg-transparent text-foreground outline-none placeholder:text-subtle-foreground"
              aria-label={t("memoryPage.search")} placeholder={t("memoryPage.search")} value={query} onChange={event => setQuery(event.target.value)} />
          </label>
          <select data-testid="memory-scope" className="h-8 rounded-lg border border-border bg-background px-2 text-[12px] text-muted-foreground"
            aria-label={t("companion.scope")} value={scope} onChange={event => setScope(event.target.value)}>
            <option value="all">{t("memoryPage.scopeAll")}</option>
            <option value="global">{t("memoryPage.scopeGlobal")}</option>
            {projects.map(project => <option key={project.id} value={`project:${project.id}`}>{project.name}</option>)}
          </select>
        </div>

        {error && <Notice tone="error" role="alert">{t(error)}</Notice>}
        {loading && !entries.length && <p role="status" className="text-sm text-muted-foreground">{t("companion.loading")}</p>}

        {(pending.length > 0 || noticed > 0) && <section data-testid="memory-waiting" className="overflow-hidden rounded-xl bg-ask-soft">
          <h2 className="flex items-baseline gap-2 px-4 pb-1 pt-2.5 text-[12px] font-semibold text-ask">
            {t("memoryPage.waiting")} <span className="font-mono">{pending.length + (noticed > 0 ? 1 : 0)}</span>
            <span className="truncate font-normal text-muted-foreground">· {t("memoryPage.waitingHint")}</span>
            {pending.length > 3 && <button className="ml-auto shrink-0 font-normal text-muted-foreground hover:text-foreground" aria-expanded={showPending}
              onClick={() => setShowPending(value => !value)}>{showPending ? t("memoryPage.showFewer") : `${t("memoryPage.waitingMore", { count: pending.length - 3 })} ›`}</button>}
          </h2>
          {noticed > 0 && <div data-testid="noticed-earlier" className="border-t border-ask/10 first:border-t-0">
            <ProposalRow text={t("companion.noticedEarlier", { count: noticed })} actions={<>
              <Button size="sm" tone="primary" disabled={busy} onClick={async () => {
                setBusy(true);
                try { await companionApi.acceptNoticedEarlier(); setNoticed(0); await reload(); }
                catch { setError("brain.read_failed"); }
                finally { setBusy(false); }
              }}>{t("companion.useAll")}</Button>
              <Button size="sm" disabled={busy} onClick={() => setShowPending(true)}>{t("companion.reviewEach")}</Button>
            </>} />
          </div>}
          {waitingShown.map(item => <div key={item.key} className="border-t border-ask/10">
            <ProposalRow testId={`pending-memory-${item.key}`} text={item.text}
              meta={<><Tag>{t(`pendingMemory.source.${item.source}`)}</Tag>{item.sensitive ? <Tag tone="danger">{t("memoryPage.sensitive")}</Tag> : null}
                {item.proposal && <button className="hover:text-foreground" onClick={() => setDialog({ kind: "proposal", proposal: item.proposal! })}>{t("memoryPage.review")} ›</button>}</>}
              actions={<>
                <Button size="sm" tone="primary" disabled={busy} onClick={() => void answer(item.accept)}>{pendingLabel(item)}</Button>
                <Button size="sm" disabled={busy} onClick={() => void answer(item.reject)}>{t("pendingMemory.drop")}</Button>
              </>} />
          </div>)}
        </section>}

        <section data-testid="in-view" className="flex flex-col gap-1.5">
          <h2 className="px-1 text-[12px] font-semibold text-muted-foreground">{t("memoryPage.inView")}</h2>
          <div className="flex flex-col gap-3 sm:flex-row">{CORE_SETS.map(coreCard)}</div>
        </section>

        <Block testId="memory-about" title={t("memoryPage.aboutYou")}
          aside={visible.length > FIRST_ROWS && !needle && <button className="hover:text-foreground" aria-expanded={showAll} onClick={() => setShowAll(value => !value)}>
            {showAll ? t("memoryPage.showFewer") : `${t("memoryPage.showAll", { count: visible.length })} ›`}</button>}>
          {shown.map(entryRow)}
          {!loading && !error && !visible.length && <p className="px-4 py-8 text-center text-[13px] text-subtle-foreground">{t(live.length ? "memoryPage.noMatches" : "memoryPage.empty")}</p>}
        </Block>
        {moreEntries && (showAll || needle) && <div className="flex flex-col items-start gap-2 px-1"><p className="text-xs text-muted-foreground">{t("companion.loadedSearch")}</p>
          <Button size="sm" disabled={loading || busy} onClick={() => void loadMore()}>{t("companion.loadMore")}</Button></div>}
        {other.length > 0 && <div className="flex flex-col gap-1.5">
          <button className="self-start px-1 text-[12px] text-muted-foreground hover:text-foreground" aria-expanded={showOther}
            onClick={() => setShowOther(value => !value)}>{t("memoryPage.notInUse", { count: other.length })}</button>
          {showOther && <div className="overflow-hidden rounded-xl border border-border bg-surface">{other.map(entryRow)}</div>}
        </div>}

        <LearnedPractices lessons={practices} busy={busy || loading} change={change} />
      </div>

      <aside data-testid="memory-rail" className="flex w-full shrink-0 flex-col gap-4 lg:w-[262px]">
        <Block title={t("memoryPage.materials")}>
          <RailRow icon={<FileText size={14} />} title={t("memoryPage.materialsCount", { materials: stats?.materials.count ?? 0, notes: stats?.notes.count ?? 0 })}
            sub={stats?.materials.latest || stats?.notes.latest ? t("memoryPage.latest", { name: stats?.materials.latest ?? stats?.notes.latest }) : undefined} />
          <div className="flex flex-wrap gap-1.5 border-t border-border px-3.5 py-2.5">
            <Button size="sm" onClick={() => onOpenMaterials?.("feed")}>{t("memoryPage.feed")}</Button>
            <Button size="sm" onClick={() => onOpenMaterials?.("note")}>{t("memoryPage.writeNote")}</Button>
            <Button size="sm" tone="plain" onClick={() => onOpenMaterials?.("browse")}>{t("memoryPage.browse")} ›</Button>
          </div>
        </Block>
        {stats && <Block testId="memory-week" title={t("memoryPage.week")}>
          <RailRow icon={<Sparkles size={14} />} title={t("memoryPage.weekRecalled", { count: stats.retrievals })} sub={t("memoryPage.weekConversations", { count: stats.conversations })} />
          <RailRow icon={<Sparkles size={14} />} title={t("memoryPage.weekNew", { count: stats.new_entries })} />
          <RailRow icon={<Sparkles size={14} />} title={t("memoryPage.weekEdits", { count: stats.user_edits })} />
        </Block>}
        <div className="flex flex-col gap-1.5">
          <Block testId="memory-who" title={t("memoryPage.who")}>
            <RailRow icon={<Laptop size={14} />} title={t("memoryPage.whoLocal")} sub={t("memoryPage.whoLocalValue")} />
            <RailRow icon={<Globe size={14} />} title={t("memoryPage.whoCloud")}
              sub={t(stats?.remember_in_conversations === false ? "memoryPage.whoCloudOff" : "memoryPage.whoCloudOn")} />
            <RailRow icon={<KeyRound size={14} />} title={t("memoryPage.whoSensitive")} sub={t("memoryPage.whoSensitiveValue")} />
          </Block>
          <p className="flex flex-col gap-0.5 px-1 text-[12px] text-subtle-foreground">
            <button className="self-start hover:text-foreground" onClick={() => openSection("settings", "memory")}>{t("memoryPage.whoFoot")} ›</button>
            <IndexLine />
          </p>
        </div>
      </aside>
    </div>
    {dialog?.kind === "edit" && <MemoryEditor entry={dialog.entry} projects={projects} onClose={() => setDialog(null)} onSaved={saved} />}
    {dialog?.kind === "history" && <MemoryHistory entry={dialog.entry} onClose={() => setDialog(null)} />}
    {dialog?.kind === "proposal" && <ReviewProposal proposal={dialog.proposal} scopeLabel={scopeName(dialog.proposal.entry)} onClose={() => setDialog(null)} onSaved={saved} />}
    {dialog?.kind === "source" && <CompanionDialog title={t("companion.source")} onClose={() => setDialog(null)}>
      <StyleReferenceView reference={dialog.entry.style_reference} />
      <ul className="space-y-3">{dialog.entry.sources.map(source => <li key={source.id} className="rounded-lg border border-border p-3 text-sm">
        <p>{sourceName(source.kind)}</p><dl className="mt-2 space-y-1 break-all text-xs text-muted-foreground">{Object.entries(source.reference).map(([key, value]) => <div key={key}><dt className="inline">{key}: </dt><dd className="inline">{String(value)}</dd></div>)}</dl>
      </li>)}</ul>
      {!dialog.entry.sources.length && <p className="text-sm">{t("companion.unknownSource")}</p>}
    </CompanionDialog>}
  </section>;
}
