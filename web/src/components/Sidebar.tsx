import BrandMark from './BrandMark';
import React, { useEffect, useState } from "react";
import type { Section } from "../lib/sections";
import { MessageSquare, Settings2, Plus, ChevronDown, ChevronUp, ChevronRight, Boxes, Network, Archive, Folder, FolderOpen, Inbox, Activity, PanelLeft } from "lucide-react";
import { useTranslation } from "react-i18next";
import ThreadRowMenu from "./ThreadRowMenu";
import type { BackendStatus } from "../hooks/useBackendStatus";
import BackgroundJobs from "./companion/BackgroundJobs";
import { threadDisplayTitle } from "../lib/threadTitles";
import ConversationGlyph from "./ConversationGlyph";
import type { ConversationMeta } from "../lib/conversationMeta";
import { groupByDay, newestFirst } from "../lib/sidebarOrder";
import { useRecency } from "../stores/recencyStore";
import { useSidebar } from "../stores/sidebarStore";
export { COLLAPSED_KEY } from "../stores/sidebarStore";
import { Smartphone } from "lucide-react";

interface ArslanThread { id: string; title: string; archived?: boolean; temporary?: boolean; defaultTitle?: boolean; projectId?: string }
/** A project the sidebar can group under (0.1.58 §4). */
export interface SidebarProject { id: string; name: string; updated_at?: string }

/** At most this many projects in the group; the rest are one click away (全部项目). */
export const SIDEBAR_PROJECTS = 8;
/** Conversations shown under an expanded project before "全部 N 个". */
export const PROJECT_CHATS = 5;
const OPEN_KEY = "arslan_sidebar_projects_open";
/** SB1: ⌃⌘S, Apple's standard Show/Hide Sidebar (unused elsewhere in Arslan: no key handler or native menu item takes it). */
export function isToggleSidebarKey(event: KeyboardEvent): boolean {
  return event.ctrlKey && event.metaKey && !event.altKey && !event.shiftKey && (event.code === "KeyS" || event.key.toLowerCase() === "s");
}


function loadOpen(): string[] {
  try { const v = JSON.parse(localStorage.getItem(OPEN_KEY) ?? "[]"); return Array.isArray(v) ? v.filter((x) => typeof x === "string") : []; }
  catch { return []; }
}
interface SidebarProps {
  threads: ArslanThread[]; activeThreadId: string; onSelectThread: (id: string) => void; onAddThread: () => void;
  activeSection: Section; onChangeSection: (section: Section) => void;
  onArchiveThread: (id: string) => void;
  onUnarchiveThread: (id: string) => void; onDeleteThread: (id: string) => void;
  backendStatus: BackendStatus;
  onOpenConversation?: (conversationId: string) => void;
  /** Inbox badge: items not yet looked at, and how many of those need a look. */
  inboxUnread?: number; inboxHigh?: number;
  /** Each conversation's kind and state (GET /conversations), for the glyphs and the Remote trace. */
  meta?: Record<string, ConversationMeta>;
  /** 0.1.58 §4: projects whose conversations live under them instead of in 最近. */
  projects?: SidebarProject[];
  onStartInProject?: (projectId: string) => void;
  onOpenProject?: (projectId: string) => void;
  onMoveToProject?: (threadId: string, projectId: string | null) => void;
  /** SB1-2: pin or unpin a conversation (App stores it on the server). */
  onPinThread?: (threadId: string, pinned: boolean) => void;
}
/** SB1-2: what a dragged conversation row carries, so a project header takes only a conversation. */
const DRAG_TYPE = "application/x-arslan-conversation";
export default function Sidebar(props: SidebarProps) {
  const { threads, activeThreadId, onSelectThread, onAddThread,
    activeSection, onChangeSection, onArchiveThread, onUnarchiveThread,
    onDeleteThread, backendStatus, onOpenConversation, inboxUnread = 0, inboxHigh = 0, meta = {},
    projects = [], onStartInProject, onOpenProject, onMoveToProject, onPinThread } = props;
  const { t, i18n } = useTranslation();
  const [archivedOpen, setArchivedOpen] = useState(false);
  const [openMonths, setOpenMonths] = useState<string[]>([]);
  const [openedFor, setOpenedFor] = useState<string | null>(null);
  const collapsed = useSidebar((s) => s.collapsed);
  const setCollapsed = useSidebar((s) => s.setCollapsed);
  const touched = useRecency((s) => s.touched);
  const pins = useSidebar((s) => s.pins);
  const [dropTarget, setDropTarget] = useState<string | null>(null);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!isToggleSidebarKey(event)) return;
      event.preventDefault();
      const state = useSidebar.getState();
      state.setCollapsed(!state.collapsed);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  // SB1: last activity, the later of this window's (a message sent, a reply, a new conversation) and
  // the server's. null = no time yet (a new conversation before its first message): newest.
  const at = (thread: ArslanThread): number | null => {
    const server = meta[thread.id]?.lastAt ? Date.parse(meta[thread.id]!.lastAt!) : NaN;
    const local = touched[thread.id];
    if (local == null && Number.isNaN(server)) return null;
    return Math.max(local ?? -Infinity, Number.isNaN(server) ? -Infinity : server);
  };
  const live = newestFirst(threads.filter(thread => !thread.archived), at);
  const projectOf = (thread: ArslanThread) => meta[thread.id]?.projectId ?? thread.projectId ?? null;
  // 0.1.58 §4: projects ranked by their latest conversation (`live` is newest first, SB1),
  // then the ones without any by when they changed; the top few form the group.
  const rank = new Map<string, number>();
  live.forEach((thread, i) => { const p = projectOf(thread); if (p && !rank.has(p)) rank.set(p, i); });
  const shownProjects = [...projects].sort((a, b) =>
    (rank.get(a.id) ?? Infinity) - (rank.get(b.id) ?? Infinity) || (b.updated_at ?? "").localeCompare(a.updated_at ?? ""))
    .slice(0, SIDEBAR_PROJECTS);
  const grouped = new Set(shownProjects.map(p => p.id));
  // 最近 keeps only conversations that are not under a project shown above.
  // SB1-2: pinned, by this window's latest choice, else the server's; a conversation in a project stays in its
  // project, so only one outside any can be pinned (the row menu offers the pin there only).
  const isPinned = (thread: ArslanThread) => !projectOf(thread) && (pins[thread.id] ?? meta[thread.id]?.pinned ?? false);
  const pinnedThreads = live.filter(isPinned);                 // newest first, as `live` is
  const activeThreads = live.filter(thread => !grouped.has(projectOf(thread) ?? "") && !isPinned(thread));
  const sections = groupByDay(activeThreads, at, new Date(), i18n?.resolvedLanguage || i18n?.language);
  // The month holding the open conversation opens with it, once per conversation (⓪Plan's review of
  // PR 543): the open row is never hidden in a fold; the user can still fold it again.
  const activeMonth = sections.months.find(month => month.rows.some(thread => thread.id === activeThreadId))?.id ?? null;
  if (activeMonth && openedFor !== activeThreadId) {
    setOpenedFor(activeThreadId);
    if (!openMonths.includes(activeMonth)) setOpenMonths([...openMonths, activeMonth]);
  }
  const activeProject = projectOf(threads.find(thread => thread.id === activeThreadId) ?? { id: "", title: "" });
  const [openProjects, setOpenProjects] = useState<string[]>(() => {
    const saved = loadOpen();
    return activeProject && !saved.includes(activeProject) ? [...saved, activeProject] : saved;
  });
  function toggleProject(id: string) {
    setOpenProjects(prev => {
      const next = prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id];
      try { localStorage.setItem(OPEN_KEY, JSON.stringify(next)); } catch { /* storage off: in memory only */ }
      return next;
    });
  }
  const archivedThreads = threads.filter(thread => thread.archived);
  // 0.1.44 one Arslan: the sidebar lists conversations only; former experts are
  // turned into skills from Capabilities.
  const navClass = (active: boolean) => `w-full flex items-center gap-2.5 rounded-lg border-l-2 px-3 py-2 text-left text-xs transition-colors ${active
    ? "border-primary bg-primary/10 text-foreground" : "border-transparent text-muted-foreground hover:bg-foreground/[0.03] hover:text-foreground"}`;
  const rowClass = (active: boolean) => `relative w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs text-left cursor-pointer group border-l-2 border-transparent ${active
    ? "bg-gradient-to-r from-primary/15 to-transparent text-foreground" : "text-muted-foreground hover:text-foreground hover:bg-foreground/[0.02]"}`;
  const marker = <span aria-hidden className="absolute left-0 top-1/2 -translate-y-1/2 h-4 w-[2px] bg-primary" />;
  function openThread(id: string) { onSelectThread(id); onChangeSection("arslan"); }
  function renderThread(thread: ArslanThread, archived: boolean) {
    const active = activeSection === "arslan" && activeThreadId === thread.id;
    // SB1-2: a conversation row drags onto a project (the same move as "Move to project…").
    const draggable = Boolean(onMoveToProject) && !archived && !thread.temporary;
    return <div key={thread.id} id={`active-thread-btn-${thread.id}`} role="button" tabIndex={0}
      draggable={draggable || undefined}
      onDragStart={draggable ? event => { event.dataTransfer.setData(DRAG_TYPE, thread.id); event.dataTransfer.effectAllowed = "move"; } : undefined}
      onClick={() => openThread(thread.id)} onKeyDown={event => {
        if (event.target !== event.currentTarget) return;
        if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openThread(thread.id); }
      }} className={rowClass(active)}>
      {active && marker}<ConversationGlyph meta={meta[thread.id]} />
      <span className="min-w-0 flex-1 truncate">{threadDisplayTitle(thread, t)}</span>
      {meta[thread.id]?.origin === "phone" &&
        <Smartphone size={11} className="shrink-0 text-subtle-foreground" role="img" aria-label={t("sidebar.fromPhone")} />}
      {!thread.temporary && <ThreadRowMenu threadId={thread.id} archived={archived}
        onArchive={onArchiveThread} onUnarchive={onUnarchiveThread} onDelete={onDeleteThread}
        projects={projects} projectId={projectOf(thread)} onMove={onMoveToProject}
        pinned={isPinned(thread)} onPin={onPinThread && !archived && !projectOf(thread) ? onPinThread : undefined} />}
    </div>;
  }
  function toggleMonth(id: string) {
    setOpenMonths(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
  }
  const heading = (key: string) => <div className="mb-1 mt-2 px-3 text-xs text-muted-foreground first:mt-0" data-testid={`sidebar-section-${key}`}>
    {t(`sidebar.${key}`)}</div>;
  function renderProject(project: SidebarProject) {
    const open = openProjects.includes(project.id);
    const chats = live.filter(thread => projectOf(thread) === project.id);      // newest first (SB1)
    const takes = (event: React.DragEvent) => Boolean(onMoveToProject) && event.dataTransfer.types.includes(DRAG_TYPE);
    return <div key={project.id} data-testid={`sidebar-project-${project.id}`}>
      <div data-testid={`sidebar-project-drop-${project.id}`} data-drop={dropTarget === project.id || undefined}
        onDragOver={event => { if (!takes(event)) return; event.preventDefault(); event.dataTransfer.dropEffect = "move"; setDropTarget(project.id); }}
        onDragLeave={() => setDropTarget(prev => (prev === project.id ? null : prev))}
        onDrop={event => {
          setDropTarget(null);
          const id = event.dataTransfer.getData(DRAG_TYPE);
          if (!takes(event) || !id) return;
          event.preventDefault();
          // Refused while the conversation runs, as the menu's move is: App shows today's "move failed" notice.
          if (projectOf(threads.find(thread => thread.id === id) ?? { id: "", title: "" }) !== project.id) onMoveToProject?.(id, project.id);
        }}
        className={`group flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-xs text-foreground hover:bg-foreground/[0.02] ${dropTarget === project.id ? "bg-primary/10 ring-1 ring-primary/40" : ""}`}>
        <button type="button" aria-expanded={open} onClick={() => toggleProject(project.id)}
          data-testid={`sidebar-project-toggle-${project.id}`} className="flex min-w-0 flex-1 items-center gap-1.5 text-left">
          {open ? <ChevronDown size={12} className="shrink-0 text-subtle-foreground" /> : <ChevronRight size={12} className="shrink-0 text-subtle-foreground" />}
          <Folder size={13} className="shrink-0 text-muted-foreground" />
          <span className="min-w-0 flex-1 truncate font-medium">{project.name}</span>
        </button>
        {onStartInProject && <button type="button" onClick={() => onStartInProject(project.id)}
          aria-label={t("sidebar.newInProject", { name: project.name })} title={t("sidebar.newInProject", { name: project.name })}
          data-testid={`sidebar-project-new-${project.id}`}
          className="shrink-0 rounded p-0.5 text-subtle-foreground opacity-0 hover:bg-primary/10 hover:text-primary focus:opacity-100 group-hover:opacity-100">
          <Plus size={13} /></button>}
      </div>
      {open && <div className="space-y-0.5 pl-4">
        {chats.slice(0, PROJECT_CHATS).map(thread => renderThread(thread, false))}
        {chats.length > PROJECT_CHATS && onOpenProject && <button type="button" onClick={() => onOpenProject(project.id)}
          data-testid={`sidebar-project-all-${project.id}`} className="px-3 py-1 text-[11px] text-subtle-foreground hover:text-foreground">
          {t("sidebar.allInProject", { count: chats.length })} ›</button>}
      </div>}
    </div>;
  }
  const toggleLabel = t(collapsed ? "sidebar.show" : "sidebar.hide");
  // SB1: collapsed, only the show button stays, beside the window's traffic lights (the mirror of the
  // workbench's PanelRight at the top right, user 2026-10-30).
  if (collapsed) return <button type="button" onClick={() => setCollapsed(false)} data-testid="sidebar-show"
    aria-label={toggleLabel} title={`${toggleLabel} (⌃⌘S)`}
    className="fixed left-[78px] top-[9px] z-50 rounded-md p-1.5 text-muted-foreground hover:bg-foreground/5 hover:text-foreground">
    <PanelLeft size={15} /></button>;
  return <aside className="relative z-40 flex h-full w-52 shrink-0 select-none flex-col border-r border-border bg-sidebar/95 lg:w-60">
    <div data-testid="window-chrome-strip" data-tauri-drag-region="deep" className="relative h-[41px] shrink-0">
      <button type="button" onClick={() => setCollapsed(true)} data-testid="sidebar-hide" aria-label={toggleLabel}
        title={`${toggleLabel} (⌃⌘S)`}
        className="absolute right-2 top-[9px] rounded-md p-1.5 text-muted-foreground hover:bg-foreground/5 hover:text-foreground">
        <PanelLeft size={15} /></button>
    </div>
    <div data-tauri-drag-region="deep" className="flex shrink-0 items-center gap-3 px-5 pb-3">
      <BrandMark alt="Arslan" className="h-9 w-9 object-contain" draggable={false} />
      <h1 className="text-sm font-semibold">Arslan</h1>
    </div>
    <div className="flex min-h-0 flex-1 flex-col px-2">
      <button id="btn-add-arslan-thread-primary" onClick={onAddThread} className={navClass(false)}>
        <Plus size={15} /><span>{t("workspace.newConversation")}</span>
      </button>
      <nav aria-label={t("workspace.navigation")} className="mt-2 shrink-0 space-y-1">
        <button id="nav-btn-inbox-deck" onClick={() => onChangeSection("inbox")} className={navClass(activeSection === "inbox")}>
          <Inbox size={15} /><span className="flex-1">{t("nav.inbox")}</span>
          {inboxUnread > 0 && <span data-testid="inbox-badge" aria-label={`${inboxUnread}`}
            className={`min-w-[18px] rounded-full px-1.5 text-center text-[10px] leading-[18px] tabular-nums ${inboxHigh > 0 ? "bg-warning text-background" : "bg-primary text-primary-foreground"}`}>{inboxUnread > 99 ? "99+" : inboxUnread}</span>}</button>
        <button id="nav-btn-projects-deck" onClick={() => onChangeSection("projects")} className={navClass(activeSection === "projects")}>
          <FolderOpen size={15} /><span>{t("companion.projects")}</span></button>
        <button id="nav-btn-brain-deck" onClick={() => onChangeSection("brain")} className={navClass(activeSection === "brain")}>
          <Network size={15} /><span>{t("companion.memory")}</span></button>
        <button id="nav-btn-capabilities-deck" onClick={() => onChangeSection("capabilities")} className={navClass(activeSection === "capabilities")}>
          <Boxes size={15} /><span className="flex-1">{t("sidebar.capabilities")}</span></button>
      </nav>
      <section aria-label={t("workspace.recentConversations")} className="mt-3 flex min-h-0 flex-1 flex-col border-t border-border/50 pt-2">
        {/* 0.1.47: no "Conversations" nav entry and no second "+" here. The rows below ARE the way
            back to a conversation (the open one is highlighted), and "New conversation" at the top
            is the one way to start one. */}
        <div className="min-h-0 flex-1 space-y-1 overflow-y-auto">
          {pinnedThreads.length > 0 && <div data-testid="sidebar-pinned" className="mb-2 space-y-0.5">
            {heading("pinned")}
            {pinnedThreads.map(thread => renderThread(thread, false))}
          </div>}
          {shownProjects.length > 0 && <div data-testid="sidebar-projects" className="mb-2 space-y-0.5">
            <div className="mb-1 px-3 text-xs text-muted-foreground">{t("sidebar.projects")}</div>
            {shownProjects.map(renderProject)}
            {projects.length > shownProjects.length && onOpenProject && <button type="button" onClick={() => onChangeSection("projects")}
              className="px-3 py-1 text-[11px] text-subtle-foreground hover:text-foreground">{t("sidebar.allProjects")} ›</button>}
          </div>}
          {/* SB1: the iPhone's sections (lib/sidebarOrder); time in the headings only, none on rows. */}
          {sections.today.length > 0 && <>{heading("today")}{sections.today.map(thread => renderThread(thread, false))}</>}
          {sections.yesterday.length > 0 && <>{heading("yesterday")}{sections.yesterday.map(thread => renderThread(thread, false))}</>}
          {sections.week.length > 0 && <>{heading("previous7")}{sections.week.map(thread => renderThread(thread, false))}</>}
          {sections.months.length > 0 && <>{heading("earlier")}
            {sections.months.map(month => {
              const open = openMonths.includes(month.id);
              return <div key={month.id} data-testid={`sidebar-month-${month.id}`}>
                <button type="button" aria-expanded={open} onClick={() => toggleMonth(month.id)}
                  className="flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-left text-xs text-foreground hover:bg-foreground/[0.02]">
                  <span className="min-w-0 flex-1 truncate">{month.title}</span>
                  <span className="shrink-0 tabular-nums text-subtle-foreground">{month.rows.length}</span>
                  <ChevronRight size={12} className={`shrink-0 text-subtle-foreground transition-transform ${open ? "rotate-90" : ""}`} aria-hidden />
                </button>
                {open && month.rows.map(thread => renderThread(thread, false))}
              </div>;
            })}</>}
          {archivedThreads.length > 0 && <div className="mt-2 border-t border-border/40 pt-2">
            <button id="btn-toggle-archived-threads" onClick={() => setArchivedOpen(value => !value)} aria-expanded={archivedOpen}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-muted-foreground">
              <Archive size={13} /><span className="flex-1">{t("sidebar.archived_section")} ({archivedThreads.length})</span>
              {archivedOpen ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
            </button>
            {archivedOpen && archivedThreads.map(thread => renderThread(thread, true))}
          </div>}
        </div>
      </section>
      {/* 0.1.42: only real background work shows here; experts live in the capability library. */}
      {onOpenConversation && <div className="shrink-0 border-t border-border/50 empty:hidden"><BackgroundJobs onOpen={onOpenConversation} /></div>}
    </div>
    <footer className="shrink-0 space-y-1 border-t border-border/60 p-3">
      <button id="nav-btn-settings-footer" onClick={() => onChangeSection("settings")} className={navClass(activeSection === "settings")}>
        <Settings2 size={15} /><span>{t("nav.settings")}</span></button>
      {/* 0.1.50 (user ruling): Activity takes the old "Local service · Online" slot. A
          permanent "Online" said nothing; the connection only shows when it is NOT fine. */}
      <button id="nav-btn-activity-footer" onClick={() => onChangeSection("activity")} className={navClass(activeSection === "activity")}>
        <Activity size={15} /><span className="flex-1">{t("nav.activity")}</span>
        {backendStatus !== "online" && <span data-testid="backend-status"
          className={`flex items-center gap-1 text-[10px] ${backendStatus === "offline" ? "text-danger" : "text-warning"}`}>
          <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${backendStatus === "offline" ? "bg-danger" : "bg-warning animate-pulse"}`} />
          {t(backendStatus === "offline" ? "common.offline" : "common.connecting")}
        </span>}
      </button>
    </footer>
  </aside>;
}
