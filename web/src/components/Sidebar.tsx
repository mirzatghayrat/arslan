import React, { useState } from 'react';
import {
  MessageSquare, LayoutGrid, Settings, Cpu, Layers, HardDrive,
  Paintbrush, Plus, HelpCircle, Network, Terminal, Settings2,
  ChevronDown, ChevronUp
} from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { useTranslation } from 'react-i18next';
import { Spawn } from '../types';
import SFSymbol from './SFSymbol';
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
  activeSection: 'arslan' | 'spawn' | 'ledger' | 'settings';
  onChangeSection: (section: 'arslan' | 'spawn' | 'ledger' | 'settings') => void;

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
  backendStatus,
}: SidebarProps) {
  const { t } = useTranslation();
  const [isMetricsExpanded, setIsMetricsExpanded] = useState(true);
  
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
            {t('sidebar.node_version')}
          </span>
        </div>

        {/* Brand Header */}
        <div className="px-5 py-3 mb-6 flex items-center gap-3 flex-shrink-0">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-primary via-primary/90 to-primary-hover flex items-center justify-center shadow-lg shadow-primary/20 border border-primary/50 relative overflow-hidden group">
            <div className="absolute inset-0 bg-white/10 opacity-0 group-hover:opacity-100 transition-opacity duration-300"></div>
            <svg
              className="w-5.5 h-5.5 text-white drop-shadow-md"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M12 21a9 9 0 010-18 2 2 0 012 2l-2 3M8 12c-1.5 0-2.5-1-3-2.5a3.5 3.5 0 014.5-4C10 6 11 8.5 12 10" />
              <path d="M12 10c1-1.5 2-4 2-5.5a3.5 3.5 0 015.5 1.5c.3.9 0 2.5-1.5 3" />
              <circle cx="12" cy="10" r="1.5" fill="currentColor" />
              <circle cx="12" cy="15" r="1.5" fill="currentColor" />
              <path d="M12 10l-4 4M12 10l4 4" />
              <circle cx="8" cy="14" r="1" fill="currentColor" />
              <circle cx="16" cy="14" r="1" fill="currentColor" />
            </svg>
          </div>
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

        {/* Main Content Area (Unified scroll region with spacious, clean ratios) */}
        <div className="flex-1 overflow-y-auto px-2 pb-6 space-y-6 flex flex-col min-h-0 scrollbar-thin">
          
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


            </div>
          </div>

          {/* MODULE 2: AGENT CONVERSATIONS (Scrollable active session threads list with spacing) */}
          <div className="border-t border-border/40 pt-4.5 flex flex-col min-h-0">
            {/* Header section with counts and spacing */}
            <div className="px-3 mb-2.5 select-none flex items-center justify-between">
              <span className="text-[9.5px] font-mono text-subtle-foreground font-bold uppercase tracking-widest flex items-center gap-1.5">
                {t('sidebar.active_chats')}
              </span>
              <span className="text-[8.5px] text-primary font-mono bg-primary/10 rounded px-2 py-0.5 select-none font-bold">
                {t('sidebar.chats_count', { count: threads.length })}
              </span>
            </div>

            <div className="space-y-1 pr-1">
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

          {/* MODULE 3: ACTIVE SPAWNS (Direct spawn portals/channels with spacing & border) */}
          <div className="border-t border-border/40 pt-4.5 flex flex-col min-h-0">
            <div className="px-3 mb-2.5 select-none flex items-center justify-between">
              <span className="text-[9.5px] font-mono text-subtle-foreground font-bold uppercase tracking-widest flex items-center gap-1.5">
                {t('sidebar.active_spawns')}
              </span>
              <span className="text-[9.5px] text-success font-mono bg-success/10 rounded px-2 py-0.5 select-none font-bold">
                {t('sidebar.live_count', { count: spawns.length })}
              </span>
            </div>

            <div className="space-y-1 pr-1">
              {spawns.map((spawn) => {
                const isActive = activeSection === 'spawn' && activeSpawnChatId === spawn.id;
                return (
                  <button
                    key={spawn.id}
                    id={`active-spawn-chat-btn-${spawn.id}`}
                    onClick={() => {
                      onSelectSpawnChat(spawn.id);
                      onChangeSection('spawn');
                    }}
                    className={`w-full flex items-center justify-between px-3 py-2 rounded-lg text-xs font-sans tracking-wide transition-all group ${
                      isActive
                        ? 'bg-gradient-to-r from-primary/15 to-transparent text-foreground border-l-2 border-primary'
                        : 'text-muted-foreground hover:text-foreground hover:bg-foreground/[0.02] border-l-2 border-transparent'
                    }`}
                  >
                    <div className="flex items-center gap-2 min-w-0 flex-1">
                      <SFSymbol nameOrEmoji={spawn.avatarEmoji} className="w-3.5 h-3.5 flex-shrink-0" />
                      <span className="truncate flex-1 font-sans">{spawn.name}</span>
                      <span className="text-[8.5px] font-mono bg-primary/15 text-primary rounded px-1.5 py-0.5 scale-90 flex-shrink-0 font-extrabold select-none">
                        L.{Math.max(1, Math.floor(spawn.totalTasks / 10) + 1)}
                      </span>
                    </div>

                    <div className="flex items-center gap-1.5 pl-2">
                      <span className={`w-1.5 h-1.5 rounded-full ${
                        spawn.status === 'working' ? 'bg-warning animate-pulse' : 'bg-success/80'
                      }`} />
                    </div>
                  </button>
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
