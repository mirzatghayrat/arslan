import BrandMark from './BrandMark';
import React, { useState } from "react";
import type { Section } from "../lib/sections";
import { MessageSquare, Settings2, Plus, ChevronDown, ChevronUp, Boxes, Network, Archive, FolderOpen, Inbox, Activity } from "lucide-react";
import { useTranslation } from "react-i18next";
import ThreadRowMenu from "./ThreadRowMenu";
import type { BackendStatus } from "../hooks/useBackendStatus";
import BackgroundJobs from "./companion/BackgroundJobs";
import { threadDisplayTitle } from "../lib/threadTitles";
import ConversationGlyph from "./ConversationGlyph";
import { remoteFirst, type ConversationMeta } from "../lib/conversationMeta";
import { Smartphone } from "lucide-react";

interface ArslanThread { id: string; title: string; archived?: boolean; temporary?: boolean; defaultTitle?: boolean }
interface SidebarProps {
  threads: ArslanThread[]; activeThreadId: string; onSelectThread: (id: string) => void; onAddThread: () => void;
  activeSection: Section; onChangeSection: (section: Section) => void;
  onDistillThread: (id: string) => void; onArchiveThread: (id: string) => void;
  onUnarchiveThread: (id: string) => void; onDeleteThread: (id: string) => void;
  backendStatus: BackendStatus;
  onOpenConversation?: (conversationId: string) => void;
  /** Inbox badge: items not yet looked at, and how many of those need a look. */
  inboxUnread?: number; inboxHigh?: number;
  /** Each conversation's kind and state (GET /conversations), for the glyphs and the Remote trace. */
  meta?: Record<string, ConversationMeta>;
}
export default function Sidebar(props: SidebarProps) {
  const { threads, activeThreadId, onSelectThread, onAddThread,
    activeSection, onChangeSection, onDistillThread, onArchiveThread, onUnarchiveThread,
    onDeleteThread, backendStatus, onOpenConversation, inboxUnread = 0, inboxHigh = 0, meta = {} } = props;
  const { t } = useTranslation();
  const [archivedOpen, setArchivedOpen] = useState(false);
  const activeThreads = remoteFirst(threads.filter(thread => !thread.archived), meta);
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
        onDistill={onDistillThread} onArchive={onArchiveThread} onUnarchive={onUnarchiveThread} onDelete={onDeleteThread} />}
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
          <Boxes size={15} /><span>{t("sidebar.capabilities")}</span></button>
      </nav>
      <section aria-label={t("workspace.recentConversations")} className="mt-3 flex min-h-0 flex-1 flex-col border-t border-border/50 pt-2">
        {/* 0.1.47: no "Conversations" nav entry and no second "+" here. The rows below ARE the way
            back to a conversation (the open one is highlighted), and "New conversation" at the top
            is the one way to start one. */}
        <div className="mb-2 px-3 text-xs text-muted-foreground">{t("workspace.recentConversations")}</div>
        <div className="min-h-0 flex-1 space-y-1 overflow-y-auto">
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
