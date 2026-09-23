import BrandMark from './BrandMark';
import React, { useState } from "react";
import type { Section } from "../lib/sections";
import { MessageSquare, Settings2, Plus, ChevronDown, ChevronUp, Boxes, Network, Archive, FolderOpen, Plug, Activity } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { Spawn } from "../types";
import { SpawnAvatar } from "./SpawnAvatar";
import ThreadRowMenu from "./ThreadRowMenu";
import type { BackendStatus } from "../hooks/useBackendStatus";
import type { TaskSummary } from "../api/tasks";
import OngoingTasks from "./companion/OngoingTasks";
import EmptyState from "./EmptyState";
import { useDismissable } from "../hooks/useDismissable";
import { threadDisplayTitle } from "../lib/threadTitles";

interface ArslanThread { id: string; title: string; archived?: boolean; temporary?: boolean; defaultTitle?: boolean }
interface SidebarProps {
  threads: ArslanThread[]; activeThreadId: string; onSelectThread: (id: string) => void; onAddThread: () => void;
  spawns: Spawn[]; activeSpawnChatId: string; onSelectSpawnChat: (id: string) => void;
  activeSection: Section; onChangeSection: (section: Section) => void;
  onCompleteChat: (id: string) => void;
  onDistillThread: (id: string) => void; onArchiveThread: (id: string) => void;
  onUnarchiveThread: (id: string) => void; onDeleteThread: (id: string) => void;
  backendStatus: BackendStatus; dispatchedSpawnIds: Set<number>;
  onOpenTask?: (task: TaskSummary) => void;
  expertChatIds?: string[];
}
export default function Sidebar(props: SidebarProps) {
  const { threads, activeThreadId, onSelectThread, onAddThread, spawns, activeSpawnChatId, onSelectSpawnChat,
    activeSection, onChangeSection, onCompleteChat, onDistillThread, onArchiveThread, onUnarchiveThread,
    onDeleteThread, backendStatus, dispatchedSpawnIds, onOpenTask, expertChatIds } = props;
  const { t } = useTranslation();
  const [archivedOpen, setArchivedOpen] = useState(false);
  const [picking, setPicking] = useState(false);
  const { anchorRef, floatingRef } = useDismissable<HTMLButtonElement, HTMLDivElement>(picking, () => setPicking(false));
  const activeThreads = threads.filter(thread => !thread.archived);
  const archivedThreads = threads.filter(thread => thread.archived);
  // User-opened expert chats are peers of normal conversations. Temporary task
  // workers are not added here; their existing task-owned panel remains the home.
  const directChats = expertChatIds ? expertChatIds.flatMap(id => spawns.filter(spawn => spawn.id === id)) : spawns.filter(spawn => spawn.hasActiveChat);
  const directIds = new Set(directChats.map(spawn => spawn.id));
  // Keep legacy work discoverable during migration, including work in another
  // conversation. Do not mistake "once dispatched" for "currently running".
  const legacyWork = spawns.filter(spawn => !directIds.has(spawn.id) &&
    (spawn.hasActiveChat || spawn.status === "working" || dispatchedSpawnIds.has(Number(spawn.id))));
  const navClass = (active: boolean) => `w-full flex items-center gap-2.5 rounded-lg border-l-2 px-3 py-2 text-left text-xs transition-colors ${active
    ? "border-primary bg-primary/10 text-foreground" : "border-transparent text-muted-foreground hover:bg-foreground/[0.03] hover:text-foreground"}`;
  const rowClass = (active: boolean) => `relative w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs text-left cursor-pointer group border-l-2 border-transparent ${active
    ? "bg-gradient-to-r from-primary/15 to-transparent text-foreground" : "text-muted-foreground hover:text-foreground hover:bg-foreground/[0.02]"}`;
  const marker = <span aria-hidden className="absolute left-0 top-1/2 -translate-y-1/2 h-4 w-[2px] bg-primary" />;
  function openThread(id: string) { onSelectThread(id); onChangeSection("arslan"); }
  function openExpert(id: string) { onSelectSpawnChat(id); onChangeSection("spawn"); }
  function renderThread(thread: ArslanThread, archived: boolean) {
    const active = activeSection === "arslan" && activeThreadId === thread.id;
    return <div key={thread.id} id={`active-thread-btn-${thread.id}`} role="button" tabIndex={0}
      onClick={() => openThread(thread.id)} onKeyDown={event => {
        if (event.target !== event.currentTarget) return;
        if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openThread(thread.id); }
      }} className={rowClass(active)}>
      {active && marker}<MessageSquare size={14} className="shrink-0" />
      <span className="min-w-0 flex-1 truncate">{threadDisplayTitle(thread, t)}</span>
      {!thread.temporary && <ThreadRowMenu threadId={thread.id} archived={archived}
        onDistill={onDistillThread} onArchive={onArchiveThread} onUnarchive={onUnarchiveThread} onDelete={onDeleteThread} />}
    </div>;
  }
  function renderExpert(spawn: Spawn, direct: boolean) {
    const active = activeSection === "spawn" && activeSpawnChatId === spawn.id;
    return <div key={spawn.id} id={`active-spawn-chat-btn-${spawn.id}`} role="button" tabIndex={0}
      onClick={() => openExpert(spawn.id)} onKeyDown={event => {
        if (event.target !== event.currentTarget) return;
        if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openExpert(spawn.id); }
      }} className={rowClass(active)}>
      {active && marker}<SpawnAvatar seed={spawn.name} size={20} />
      <span className="min-w-0 flex-1 truncate">{spawn.name}</span>
      {spawn.status === "working" && <Activity size={13} className="shrink-0 text-warning" aria-label={t("tasks.running")} />}
      {direct && <button aria-label={t("sidebar.complete_chat")} title={t("sidebar.complete_chat")}
        onClick={event => { event.stopPropagation(); if (window.confirm(t("sidebar.complete_confirm"))) onCompleteChat(spawn.id); }}
        className="rounded px-1 text-[10px] text-muted-foreground opacity-0 group-hover:opacity-100 focus:opacity-100">
        {t("sidebar.complete_chat")}</button>}
    </div>;
  }
  return <aside className="relative z-40 flex h-full w-52 shrink-0 select-none flex-col border-r border-border bg-sidebar/95 lg:w-60">
    <div data-testid="window-chrome-strip" data-tauri-drag-region="deep" className="h-[41px] shrink-0" />
    <div data-tauri-drag-region="deep" className="flex shrink-0 items-center gap-3 px-5 pb-3">
      <BrandMark alt="Arslan" className="h-9 w-9 object-contain" draggable={false} />
      <div><h1 className="text-sm font-semibold">Arslan</h1><p className="mt-0.5 text-[11px] leading-snug text-muted-foreground">{t("sidebar.brand_subtitle")}</p></div>
    </div>
    <div className="flex min-h-0 flex-1 flex-col px-2">
      <button id="btn-add-arslan-thread-primary" onClick={onAddThread} className={navClass(false)}>
        <Plus size={15} /><span>{t("workspace.newConversation")}</span>
      </button>
      <nav aria-label={t("workspace.navigation")} className="mt-2 shrink-0 space-y-1">
        <button id="nav-btn-conversations-deck" onClick={() => onChangeSection("arslan")} className={navClass(activeSection === "arslan" || activeSection === "spawn")}>
          <MessageSquare size={15} /><span>{t("workspace.conversations")}</span></button>
        <button id="nav-btn-projects-deck" onClick={() => onChangeSection("projects")} className={navClass(activeSection === "projects")}>
          <FolderOpen size={15} /><span>{t("companion.projects")}</span></button>
        <button id="nav-btn-brain-deck" onClick={() => onChangeSection("brain")} className={navClass(activeSection === "brain")}>
          <Network size={15} /><span>{t("companion.memory")}</span></button>
        <button id="nav-btn-capabilities-deck" onClick={() => onChangeSection("capabilities")} className={navClass(activeSection === "capabilities" || activeSection === "ledger")}>
          <Boxes size={15} /><span>{t("sidebar.capabilities")}</span></button>
      </nav>
      <section aria-label={t("workspace.recentConversations")} className="mt-3 flex min-h-0 flex-1 flex-col border-t border-border/50 pt-2">
        <div className="mb-2 flex items-center justify-between px-3 text-xs text-muted-foreground">
          <span>{t("workspace.recentConversations")}</span>
          <button ref={anchorRef} title={t("sidebar.new_chat")} aria-label={t("sidebar.new_chat")} aria-expanded={picking} onClick={() => setPicking(value => !value)}><Plus size={14} /></button>
        </div>
        {picking && <div ref={floatingRef} className="mb-2 max-h-32 overflow-y-auto rounded-lg border border-border p-1">
          {spawns.map(spawn => <button key={spawn.id} onClick={() => { setPicking(false); openExpert(spawn.id); }}
            className="block w-full truncate rounded px-3 py-2 text-left text-xs hover:bg-primary/5">{spawn.name}</button>)}
          {!spawns.length && <EmptyState size="inline" testId="empty-sidebar-spawns"
            title={t('sidebar.no_spawns')} body={t('sidebar.no_spawns_desc')} />}
        </div>}
        <div className="min-h-0 flex-1 space-y-1 overflow-y-auto">
          {activeThreads.map(thread => renderThread(thread, false))}
          {directChats.map(spawn => renderExpert(spawn, true))}
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
      {onOpenTask && <div className="shrink-0 border-t border-border/50"><OngoingTasks onOpen={onOpenTask} /></div>}
      {legacyWork.length > 0 && <details className="mb-2 shrink-0 border-t border-border/50 pt-2">
        <summary className="cursor-pointer px-3 text-xs text-muted-foreground">{t("workspace.legacyWork")} ({legacyWork.length})</summary>
        <div className="mt-2 max-h-32 overflow-y-auto">{legacyWork.map(spawn => renderExpert(spawn, false))}</div>
      </details>}
    </div>
    <footer className="shrink-0 space-y-1 border-t border-border/60 p-3">
      <button id="nav-btn-connections-footer" onClick={() => onChangeSection("connections")} className={navClass(activeSection === "connections")}>
        <Plug size={15} /><span>{t("workspace.connections")}</span></button>
      <button id="nav-btn-settings-footer" onClick={() => onChangeSection("settings")} className={navClass(activeSection === "settings" || activeSection === "diagnosis")}>
        <Settings2 size={15} /><span>{t("nav.settings")}</span></button>
      <div className="flex items-center justify-between px-3 pt-2 text-[10px] text-muted-foreground">
        <span>{t("workspace.service")}</span><span className={backendStatus === "online" ? "text-success" : backendStatus === "offline" ? "text-danger" : ""}>
          {t(backendStatus === "checking" ? "common.connecting" : backendStatus === "online" ? "common.online" : "common.offline")}
        </span>
      </div>
    </footer>
  </aside>;
}
