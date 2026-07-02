import React, { useState } from 'react';
import {
  MessageSquare, LayoutGrid, Settings, Cpu, Layers, HardDrive,
  Paintbrush, Plus, HelpCircle, Network, Terminal, Settings2,
  ChevronDown, ChevronUp, Boxes
} from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { useTranslation } from 'react-i18next';
import { Spawn } from '../types';
import { SpawnAvatar } from './SpawnAvatar';
import { BUILD_TAG } from '../buildInfo';
import type { BackendStatus } from '../hooks/useBackendStatus';

interface ArslanThread {
  id: string;
  title: string;
}

interface SidebarProps {
  threads: ArslanThread[];
  activeThreadId: string;
  onSelectThread: (id: string) => void;
  onAddThread: () => void;
  spawns: Spawn[];
  activeSpawnChatId: string;
  onSelectSpawnChat: (id: string) => void;

  // Outer global view states
  activeSection: 'arslan' | 'spawn' | 'ledger' | 'capabilities' | 'settings';
  onChangeSection: (section: 'arslan' | 'spawn' | 'ledger' | 'capabilities' | 'settings') => void;

  /** Called when the user completes (完结) a direct chat with a spawn */
  onCompleteChat: (id: string) => void;

  /** Real backend reachability signal from useBackendStatus */
  backendStatus: BackendStatus;
}

export default function Sidebar({
  threads,
  activeThreadId,
  onSelectThread,
  onAddThread,
  spawns,
  activeSpawnChatId,
  onSelectSpawnChat,
  activeSection,
  onChangeSection,
  onCompleteChat,
  backendStatus,
}: SidebarProps) {
  const { t } = useTranslation();
  const [isMetricsExpanded, setIsMetricsExpanded] = useState(true);
  const [picking, setPicking] = useState(false);
  
  return (
    <aside className="w-64 bg-sidebar/95 border-r border-border flex flex-col justify-between select-none h-full relative z-40">
      {/* Top Portion of the Sidebar */}
      <div className="flex-1 flex flex-col min-h-0">
        
        {/* macOS Style Traffic Lights */}
        <div className="flex items-center gap-1.5 px-5 pt-4 pb-3 flex-shrink-0">
          <div className="w-3 h-3 rounded-full bg-danger border border-black/20 cursor-pointer"></div>
          <div className="w-3 h-3 rounded-full bg-warning border border-black/20 cursor-pointer"></div>
          <div className="w-3 h-3 rounded-full bg-success border border-black/20 cursor-pointer"></div>
          <span className="text-[9.5px] text-subtle-foreground font-mono tracking-wider ml-auto uppercase opacity-60">
            {t('sidebar.node_version')} · build {BUILD_TAG}
          </span>
        </div>

        {/* Brand Header */}
        <div className="px-5 py-3 mb-6 flex items-center gap-3 flex-shrink-0">
          <img src="/arslan-mark.png" alt={t('app.name')} className="w-9 h-9 object-contain flex-shrink-0 select-none arslan-mark" draggable={false} />
          <div>
            <div className="flex items-center gap-1.5">
              <h1 className="font-sans font-bold text-foreground text-sm tracking-tight">
                {t('app.name')} Orchestrator
              </h1>
              <span className="text-[8px] bg-primary/10 text-primary px-1 py-0.2 rounded font-mono font-medium border border-primary/20 uppercase">
                Host
              </span>
            </div>
            <p className="text-[9px] text-subtle-foreground font-mono tracking-tight mt-0.5">
              {t('sidebar.brand_subtitle')}
            </p>
          </div>
        </div>

        {/* Main Content Area — each list scrolls INSIDE its module so ACTIVE CHATS can
            never push ACTIVE SPAWNS out of view (they used to share one outer scroll). */}
        <div className="flex-1 overflow-hidden px-2 pb-4 space-y-6 flex flex-col min-h-0">
          
          {/* MODULE 1: CONTROL DECK (Toolbar, New Chat/Session, Portals) */}
          <div className="space-y-1.5 flex-shrink-0">
            <button
              id="btn-add-arslan-thread-primary"
              onClick={onAddThread}
              className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-sans tracking-wide transition-all text-left text-muted-foreground hover:text-foreground hover:bg-primary/5 border-l-2 border-transparent hover:border-l-2 hover:border-primary/50 group"
            >
              <Plus className="w-3.5 h-3.5 text-subtle-foreground shrink-0 group-hover:text-primary transition-transform group-hover:scale-110" />
              <span className="truncate font-sans font-medium">{t('sidebar.new_session')}</span>
            </button>

            {/* Quick Portal Shortcuts (Listed vertically for consistent list style) */}
            <div className="space-y-1">
              {/* Spawns Ledger */}
              <button
                id="nav-btn-ledger-deck"
                onClick={() => onChangeSection('ledger')}
                className={`w-full flex items-center justify-between px-3 py-2 rounded-lg text-xs font-sans tracking-wide transition-all text-left ${
                  activeSection === 'ledger'
                    ? 'bg-gradient-to-r from-primary/15 to-transparent text-foreground border-l-2 border-primary'
                    : 'text-muted-foreground hover:text-foreground hover:bg-foreground/[0.02] border-l-2 border-transparent'
                }`}
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  <LayoutGrid className={`w-3.5 h-3.5 flex-shrink-0 ${activeSection === 'ledger' ? 'text-primary' : 'text-subtle-foreground'}`} />
                  <span className="truncate font-sans font-medium">{t('sidebar.spawns_ledger')}</span>
                </div>
                <span className="text-[8px] bg-primary/10 text-primary font-mono font-bold px-2 py-0.5 rounded shrink-0">
                  {spawns.length}
                </span>
              </button>

              {/* Capabilities */}
              <button
                id="nav-btn-capabilities-deck"
                onClick={() => onChangeSection('capabilities')}
                className={`w-full flex items-center justify-between px-3 py-2 rounded-lg text-xs font-sans tracking-wide transition-all text-left ${
                  activeSection === 'capabilities'
                    ? 'bg-gradient-to-r from-primary/15 to-transparent text-foreground border-l-2 border-primary'
                    : 'text-muted-foreground hover:text-foreground hover:bg-foreground/[0.02] border-l-2 border-transparent'
                }`}
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  <Boxes className={`w-3.5 h-3.5 flex-shrink-0 ${activeSection === 'capabilities' ? 'text-primary' : 'text-subtle-foreground'}`} />
                  <span className="truncate font-sans font-medium">{t('sidebar.capabilities')}</span>
                </div>
              </button>

            </div>
          </div>

          {/* MODULE 2: AGENT CONVERSATIONS — flexes to fill, its own inner scroll */}
          <div className="border-t border-border/40 pt-4.5 flex flex-col min-h-0 flex-1">
            {/* Header section with counts and spacing */}
            <div className="px-3 mb-2.5 select-none flex items-center justify-between">
              <span className="text-[9.5px] font-mono text-subtle-foreground font-bold uppercase tracking-widest flex items-center gap-1.5">
                {t('sidebar.active_chats')}
              </span>
              <span className="text-[8.5px] text-primary font-mono bg-primary/10 rounded px-2 py-0.5 select-none font-bold">
                {t('sidebar.chats_count', { count: threads.length })}
              </span>
            </div>

            <div className="space-y-1 pr-1 flex-1 min-h-0 overflow-y-auto scrollbar-thin">
              {threads.map((thread) => {
                const isActive = activeSection === 'arslan' && activeThreadId === thread.id;
                return (
                  <button
                    key={thread.id}
                    id={`active-thread-btn-${thread.id}`}
                    onClick={() => {
                      onSelectThread(thread.id);
                      onChangeSection('arslan');
                    }}
                    className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-sans tracking-wide transition-all text-left truncate group ${
                      isActive
                        ? 'bg-gradient-to-r from-primary/15 to-transparent text-foreground border-l-2 border-primary shadow-sm shadow-primary/5'
                        : 'text-muted-foreground hover:text-foreground hover:bg-foreground/[0.02] border-l-2 border-transparent'
                    }`}
                  >
                    <MessageSquare className={`w-3.5 h-3.5 flex-shrink-0 transition-colors ${isActive ? 'text-primary' : 'text-subtle-foreground group-hover:text-muted-foreground'}`} />
                    <span className="truncate flex-1 pr-1 font-sans">{thread.title}</span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* MODULE 3: ACTIVE SPAWNS — pinned below chats, own capped inner scroll */}
          <div className="border-t border-border/40 pt-4.5 flex flex-col min-h-0 flex-shrink-0">
            <div className="px-3 mb-2.5 select-none flex items-center justify-between">
              <span className="text-[9.5px] font-mono text-subtle-foreground font-bold uppercase tracking-widest flex items-center gap-1.5">
                {t('sidebar.active_spawns')}
              </span>
              <div className="flex items-center gap-1">
                <span className="text-[9.5px] text-success font-mono bg-success/10 rounded px-2 py-0.5 select-none font-bold">
                  {t('sidebar.live_count', { count: spawns.filter(s => s.hasActiveChat).length })}
                </span>
                <button
                  title={t('sidebar.new_chat')}
                  onClick={() => setPicking((p) => !p)}
                  className="w-5 h-5 flex items-center justify-center rounded text-subtle-foreground hover:text-primary hover:bg-primary/10 transition-all text-xs font-bold"
                >
                  ＋
                </button>
              </div>
            </div>

            {/* Picker dropdown: all spawns to start a new direct chat */}
            {picking && (
              <div className="mx-2 mb-2 bg-background border border-border rounded-lg shadow-lg overflow-hidden">
                {spawns.map((spawn) => (
                  <button
                    key={spawn.id}
                    onClick={() => {
                      setPicking(false);
                      onSelectSpawnChat(spawn.id);
                      onChangeSection('spawn');
                    }}
                    className="w-full flex items-center gap-2 px-3 py-1.5 text-xs font-sans text-muted-foreground hover:text-foreground hover:bg-foreground/[0.04] transition-all text-left"
                  >
                    <SpawnAvatar seed={spawn.name} size={16} />
                    <span className="truncate">{spawn.name}</span>
                  </button>
                ))}
                {spawns.length === 0 && (
                  <p className="px-3 py-2 text-[10px] text-subtle-foreground italic font-mono">No spawns yet</p>
                )}
              </div>
            )}

            <div className="space-y-1 pr-1 max-h-[32vh] overflow-y-auto scrollbar-thin">
              {spawns.filter(s => s.hasActiveChat).map((spawn) => {
                const isActive = activeSection === 'spawn' && activeSpawnChatId === spawn.id;
                return (
                  <div
                    key={spawn.id}
                    id={`active-spawn-chat-btn-${spawn.id}`}
                    role="button"
                    tabIndex={0}
                    onClick={() => {
                      onSelectSpawnChat(spawn.id);
                      onChangeSection('spawn');
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        onSelectSpawnChat(spawn.id);
                        onChangeSection('spawn');
                      }
                    }}
                    className={`w-full flex items-center justify-between px-3 py-2 rounded-lg text-xs font-sans tracking-wide transition-all cursor-pointer group ${
                      isActive
                        ? 'bg-gradient-to-r from-primary/15 to-transparent text-foreground border-l-2 border-primary'
                        : 'text-muted-foreground hover:text-foreground hover:bg-foreground/[0.02] border-l-2 border-transparent'
                    }`}
                  >
                    <div className="flex items-center gap-2 min-w-0 flex-1">
                      <SpawnAvatar seed={spawn.name} size={22} />
                      <span className="truncate flex-1 font-sans">{spawn.name}</span>
                      <span className="text-[8.5px] font-mono bg-primary/15 text-primary rounded px-2 py-0.5 flex-shrink-0 font-extrabold select-none">
                        L.{Math.max(1, Math.floor(spawn.totalTasks / 10) + 1)}
                      </span>
                    </div>

                    <div className="flex items-center gap-1.5 pl-2">
                      <span className={`w-1.5 h-1.5 rounded-full ${
                        spawn.status === 'working' ? 'bg-warning animate-pulse' : 'bg-success/80'
                      }`} />
                      <button
                        title={t('sidebar.complete_chat')}
                        onClick={(e) => {
                          e.stopPropagation();
                          if (window.confirm(t('sidebar.complete_confirm'))) {
                            onCompleteChat(spawn.id);
                          }
                        }}
                        className="opacity-0 group-hover:opacity-100 text-[9px] font-mono text-subtle-foreground hover:text-warning transition-all px-1 py-0.5 rounded hover:bg-warning/10"
                      >
                        {t('sidebar.complete_chat')}
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

        </div>
      </div>

      {/* System Resource Metrics Footer */}
      <div className="p-4 border-t border-border/60 bg-background select-none space-y-3">
        {/* System Settings Button (Moved to footer) */}
        <button
          id="nav-btn-settings-footer"
          onClick={() => onChangeSection('settings')}
          className={`w-full flex items-center gap-2.5 px-3 py-1.8 rounded-lg text-xs font-sans tracking-wide transition-all text-left group/settings-foot ${
            activeSection === 'settings'
              ? 'bg-gradient-to-r from-primary/15 to-transparent text-foreground border-l-2 border-primary'
              : 'text-muted-foreground hover:text-foreground hover:bg-foreground/[0.02] border-l-2 border-transparent'
          }`}
        >
          <Settings2 className={`w-3.5 h-3.5 flex-shrink-0 transition-colors ${activeSection === 'settings' ? 'text-primary' : 'text-subtle-foreground group-hover/settings-foot:text-muted-foreground'}`} />
          <span className="truncate font-sans font-medium">{t('sidebar.system_settings')}</span>
        </button>

        <div className="border-t border-border/40 pt-3">
          {/* DAEMON CORE — wired to real backend health signal */}
          <div className="flex items-center justify-between text-[10px] font-mono text-subtle-foreground uppercase tracking-widest select-none">
            <span className="flex items-center gap-1.5">
              <span>{t('sidebar.daemon_core')}</span>
            </span>
            {backendStatus === 'checking' && (
              <span className="flex items-center gap-1 text-subtle-foreground">
                <span className="w-1.5 h-1.5 rounded-full bg-subtle-foreground animate-pulse"></span>
                {t('common.connecting')}
              </span>
            )}
            {backendStatus === 'online' && (
              <span className="flex items-center gap-1 text-success">
                <span className="w-1.5 h-1.5 rounded-full bg-success animate-pulse"></span>
                {t('common.online')}
              </span>
            )}
            {backendStatus === 'offline' && (
              <span className="flex items-center gap-1 text-danger">
                <span className="w-1.5 h-1.5 rounded-full bg-danger"></span>
                {t('common.offline')}
              </span>
            )}
          </div>
        </div>
      </div>
    </aside>
  );
}
