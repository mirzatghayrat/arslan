import BrandMark from './BrandMark';
import React, { useState } from "react";
import type { Section } from "../lib/sections";
import { MessageSquare, Settings2, Plus, ChevronDown, ChevronUp, ChevronRight, Boxes, Network, Archive, Folder, FolderOpen, Inbox, Activity } from "lucide-react";
import { useTranslation } from "react-i18next";
import ThreadRowMenu from "./ThreadRowMenu";
import type { BackendStatus } from "../hooks/useBackendStatus";
import BackgroundJobs from "./companion/BackgroundJobs";
import { threadDisplayTitle } from "../lib/threadTitles";
import ConversationGlyph from "./ConversationGlyph";
import { remoteFirst, type ConversationMeta } from "../lib/conversationMeta";
import { Smartphone } from "lucide-react";

interface ArslanThread { id: string; title: string; archived?: boolean; temporary?: boolean; defaultTitle?: boolean; projectId?: string }
/** A project the sidebar can group under (0.1.58 §4). */
export interface SidebarProject { id: string; name: string; updated_at?: string }

/** At most this many projects in the group; the rest are one click away (全部项目). */
export const SIDEBAR_PROJECTS = 8;
/** Conversations shown under an expanded project before "全部 N 个". */
export const PROJECT_CHATS = 5;
const OPEN_KEY = "arslan_sidebar_projects_open";

function loadOpen(): string[] {
  try { const v = JSON.parse(localStorage.getItem(OPEN_KEY) ?? "[]"); return Array.isArray(v) ? v.filter((x) => typeof x === "string") : []; }
  catch { return []; }
}
interface SidebarProps {
  threads: ArslanThread[]; activeThreadId: string; onSelectThread: (id: string) => void; onAddThread: () => void;
  activeSection: Section; onChangeSection: (section: Section) => void;
  onDistillThread: (id: string) => void; onArchiveThread: (id: string) => void;
  onUnarchiveThread: (id: string) => void; onDeleteThread: (id: string) => void;
  backendStatus: BackendStatus;
  onOpenConversation?: (conversationId: string) => void;
  /** Inbox badge: items not yet looked at, and how many of those need a look. */
  inboxUnread?: number; inboxHigh?: number;
  /** 0.1.57: what Arslan found and kept for later — a quiet count, never a notification. */
  capabilityFinds?: number;
  /** Each conversation's kind and state (GET /conversations), for the glyphs and the Remote trace. */
  meta?: Record<string, ConversationMeta>;
  /** 0.1.58 §4: projects whose conversations live under them instead of in 最近. */
  projects?: SidebarProject[];
  onStartInProject?: (projectId: string) => void;
  onOpenProject?: (projectId: string) => void;
  onMoveToProject?: (threadId: string, projectId: string | null) => void;
}
export default function Sidebar(props: SidebarProps) {
  const { threads, activeThreadId, onSelectThread, onAddThread,
    activeSection, onChangeSection, onDistillThread, onArchiveThread, onUnarchiveThread,
    onDeleteThread, backendStatus, onOpenConversation, inboxUnread = 0, inboxHigh = 0, capabilityFinds = 0, meta = {},
    projects = [], onStartInProject, onOpenProject, onMoveToProject } = props;
  const { t } = useTranslation();
  const [archivedOpen, setArchivedOpen] = useState(false);
  const live = threads.filter(thread => !thread.archived);
  const projectOf = (thread: ArslanThread) => meta[thread.id]?.projectId ?? thread.projectId ?? null;
  // 0.1.58 §4: projects ranked by their latest conversation (the thread list is newest first),
  // then the ones without any by when they changed; the top few form the group.
  const rank = new Map<string, number>();
  live.forEach((thread, i) => { const p = projectOf(thread); if (p && !rank.has(p)) rank.set(p, i); });
  const shownProjects = [...projects].sort((a, b) =>
    (rank.get(a.id) ?? Infinity) - (rank.get(b.id) ?? Infinity) || (b.updated_at ?? "").localeCompare(a.updated_at ?? ""))
    .slice(0, SIDEBAR_PROJECTS);
  const grouped = new Set(shownProjects.map(p => p.id));
  // 最近 keeps only conversations that are not under a project shown above.
  const activeThreads = remoteFirst(live.filter(thread => !grouped.has(projectOf(thread) ?? "")), meta);
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
    return <div key={thread.id} id={`active-thread-btn-${thread.id}`} role="button" tabIndex={0}
      onClick={() => openThread(thread.id)} onKeyDown={event => {
        if (event.target !== event.currentTarget) return;
        if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openThread(thread.id); }
      }} className={rowClass(active)}>
      {active && marker}<ConversationGlyph meta={meta[thread.id]} />
      <span className={`min-w-0 flex-1 truncate ${meta[thread.id]?.kind === "remote" ? "font-semibold" : ""}`}>{threadDisplayTitle(thread, t, meta[thread.id]?.kind)}</span>
      {meta[thread.id]?.origin === "phone" && meta[thread.id]?.kind !== "remote" &&
        <Smartphone size={11} className="shrink-0 text-subtle-foreground" role="img" aria-label={t("sidebar.fromPhone")} />}
      {!thread.temporary && <ThreadRowMenu threadId={thread.id} archived={archived}
        onDistill={onDistillThread} onArchive={onArchiveThread} onUnarchive={onUnarchiveThread} onDelete={onDeleteThread}
        projects={projects} projectId={projectOf(thread)} onMove={onMoveToProject} />}
    </div>;
  }
  function renderProject(project: SidebarProject) {
    const open = openProjects.includes(project.id);
    const chats = live.filter(thread => projectOf(thread) === project.id);
    return <div key={project.id} data-testid={`sidebar-project-${project.id}`}>
      <div className="group flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-xs text-foreground hover:bg-foreground/[0.02]">
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
  return <aside className="relative z-40 flex h-full w-52 shrink-0 select-none flex-col border-r border-border bg-sidebar/95 lg:w-60">
    <div data-testid="window-chrome-strip" data-tauri-drag-region="deep" className="h-[41px] shrink-0" />
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
          <Boxes size={15} /><span className="flex-1">{t("sidebar.capabilities")}</span>
          {capabilityFinds > 0 && <span data-testid="capabilities-badge" aria-label={`${capabilityFinds}`}
            className="min-w-[18px] rounded-full bg-fill px-1.5 text-center text-[10px] leading-[18px] tabular-nums text-muted-foreground">
            {capabilityFinds > 99 ? "99+" : capabilityFinds}</span>}</button>
      </nav>
      <section aria-label={t("workspace.recentConversations")} className="mt-3 flex min-h-0 flex-1 flex-col border-t border-border/50 pt-2">
        {/* 0.1.47: no "Conversations" nav entry and no second "+" here. The rows below ARE the way
            back to a conversation (the open one is highlighted), and "New conversation" at the top
            is the one way to start one. */}
        <div className="min-h-0 flex-1 space-y-1 overflow-y-auto">
          {shownProjects.length > 0 && <div data-testid="sidebar-projects" className="mb-2 space-y-0.5">
            <div className="mb-1 px-3 text-xs text-muted-foreground">{t("sidebar.projects")}</div>
            {shownProjects.map(renderProject)}
            {projects.length > shownProjects.length && onOpenProject && <button type="button" onClick={() => onChangeSection("projects")}
              className="px-3 py-1 text-[11px] text-subtle-foreground hover:text-foreground">{t("sidebar.allProjects")} ›</button>}
          </div>}
          <div className="mb-2 px-3 text-xs text-muted-foreground">{t("workspace.recentConversations")}</div>
          {activeThreads.map(thread => renderThread(thread, false))}
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
