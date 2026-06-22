import React, { useState } from 'react';
import { Spawn } from '../types';
import { TOOLS, SKILLS } from '../data';
import {
  Sliders, Wrench, BookOpen, Clock, Activity, ArrowUpRight, Shield, Cpu,
  ChevronDown, ChevronUp, Terminal, MessageSquare, Search, Globe, RefreshCcw, Sparkles, Plus, Database, X, WifiOff
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { getIcon } from './iconMap';
import { motion, AnimatePresence } from 'motion/react';
import { SpawnAvatar } from './SpawnAvatar';
import type { BackendStatus } from '../hooks/useBackendStatus';

interface SpawnsDashboardProps {
  spawns: Spawn[];
  selectedSpawnId: string | null;
  setSelectedSpawnId: (id: string | null) => void;
  cardStyle: 'isometric' | 'blueprint' | 'compact';
  setCardStyle: (style: 'isometric' | 'blueprint' | 'compact') => void;
  onEditEquipment: (spawnId: string) => void;
  onDeleteSpawn?: (spawnId: string) => void;
  onCreateSpawnClick: () => void;
  onOpenDirectChat?: (spawnId: string) => void;
  setSpawns?: React.Dispatch<React.SetStateAction<Spawn[]>>;
  setThreads?: React.Dispatch<React.SetStateAction<any[]>>;
  activeThreadId?: string;
  setSpawnChats?: React.Dispatch<React.SetStateAction<Record<string, any[]>>>;
  backendStatus?: BackendStatus;
}

export default function SpawnsDashboard({
  spawns,
  selectedSpawnId,
  setSelectedSpawnId,
  cardStyle,
  setCardStyle,
  onEditEquipment,
  onCreateSpawnClick,
  onOpenDirectChat,
  setSpawns,
  setThreads,
  activeThreadId,
  setSpawnChats,
  backendStatus,
}: SpawnsDashboardProps) {
  const { t } = useTranslation();

  // Global Integration Discovery & Repository Engine States
  // NOTE: This Tool-Hub (MCP/discovery backend) does not exist yet — kept as visual shell, actions disabled.
  const [showSandboxSearch, setShowSandboxSearch] = useState(true);
  const [integrationQuery, setIntegrationQuery] = useState('');
  const isEvaluating = false; // evaluation backend not yet available — do not enable
  const [mcpRegistry] = useState<{name: string, url: string, description: string, tags: string[]}[]>([]); // no real MCP servers yet
  const [skillRegistry] = useState<{name: string, repo: string, capabilities: string[]}[]>([]); // no real skill registry yet
  const evaluationResult = null; // evaluation results disabled

  // Tool-Hub evaluation handlers are disabled — no MCP/discovery backend exists yet.
  // Keeping stubs to avoid removing prop references from the render tree.
  const handleEvaluateRepository = (_urlOrQuery: string) => {
    // No-op: evaluation backend not yet available (即将推出)
  };
  const handleAddToMCP = () => { /* coming soon */ };
  const handleAddToSkill = () => { /* coming soon */ };
  const handleSynthesizeSpawn = () => { /* coming soon */ };

  return (
    <div className="flex-1 overflow-y-auto bg-background p-8 select-none relative">
      {/* Decorative Top Lights */}
      {cardStyle === 'isometric' && (
        <div className="absolute top-0 right-1/4 w-[35rem] h-[35rem] bg-primary/[0.02] blur-[120px] rounded-full pointer-events-none"></div>
      )}

      {/* Header bar */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-8">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold text-foreground tracking-tight font-sans">{t('ledger.title')}</h1>
            <span className="text-[10px] bg-primary/10 text-primary font-mono font-semibold px-2 py-0.5 rounded-full uppercase">
              {spawns.length} Spawns
            </span>
          </div>
          <p className="text-xs text-subtle-foreground font-sans mt-1">
            {t('ledger.subtitle')}
          </p>
        </div>

        {/* Buttons right: Spawn Creator & Card Style Variator */}
        <div className="flex items-center gap-3 shrink-0 flex-wrap">
          {/* Card Style Switcher */}
          <div className="flex items-center border border-border p-0.5 rounded-lg bg-surface">
            <span className="text-[9px] font-mono text-subtle-foreground uppercase px-2">{t('ledger.card_layout_label')}</span>
            <button
              id="card-iso-btn"
              onClick={() => setCardStyle('isometric')}
              className={`px-2 py-1 rounded text-[10px] font-mono transition-all font-medium ${
                cardStyle === 'isometric'
                  ? 'bg-primary/10 text-primary border border-primary/30'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              {t('ledger.style_glass')}
            </button>
            <button
              id="card-blue-btn"
              onClick={() => setCardStyle('blueprint')}
              className={`px-2 py-1 rounded text-[10px] font-mono transition-all font-medium ${
                cardStyle === 'blueprint'
                  ? 'bg-primary text-primary-foreground font-bold border border-primary'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              {t('ledger.style_blueprint')}
            </button>
            <button
              id="card-comp-btn"
              onClick={() => setCardStyle('compact')}
              className={`px-2 py-1 rounded text-[10px] font-mono transition-all font-medium ${
                cardStyle === 'compact'
                  ? 'bg-surface-raised text-foreground border border-border-strong'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              {t('ledger.style_compact')}
            </button>
          </div>

          {/* Create spawn handler */}
          <button
            id="create-spawn-trigger"
            onClick={onCreateSpawnClick}
            className="px-3 py-1.5 bg-primary hover:bg-primary-hover text-primary-foreground text-xs font-bold font-sans uppercase rounded-lg transition-all flex items-center gap-1 shadow-lg shadow-[var(--color-primary)]/15"
          >
            <span>+</span> {t('ledger.synthesize_spawn')}
          </button>
        </div>
      </div>

      {/* Global Integration Discovery & Repository Engine (Tool-Hub) */}
      {/* NOTE: MCP/discovery backend does not exist yet — kept as visual shell, actions disabled */}
      <div className="bg-surface/40 border border-border-strong rounded-2xl p-6 mb-8 transition-all z-10 select-text opacity-70">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-primary/10 border border-primary/30 flex items-center justify-center text-sm transition-colors shadow-inner shadow-black/40">
              <Globe className="w-5 h-5 text-primary" />
            </div>
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <h3 className="font-sans font-bold text-sm text-foreground tracking-wide">
                  {t('ledger.tool_hub_title')} <span className="text-subtle-foreground font-normal text-xs ml-1">(Tool-Hub)</span>
                </h3>
                <span className="text-[8px] font-mono bg-surface-raised text-muted-foreground px-1.5 py-0.5 rounded uppercase tracking-wider shrink-0">{t('ledger.tool_hub_coming_soon')}</span>
              </div>
              <p className="text-[11.5px] text-subtle-foreground font-sans mt-0.5">
                {t('ledger.tool_hub_subtitle')}
              </p>
            </div>
          </div>

          <button
            onClick={() => setShowSandboxSearch(!showSandboxSearch)}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-surface/90 hover:bg-border text-muted-foreground rounded-lg border border-border-strong transition-all cursor-pointer text-xs font-medium font-sans"
          >
            <span>{showSandboxSearch ? t('common.collapse') : t('common.expand')}</span>
            {showSandboxSearch ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>
        </div>

        {showSandboxSearch && (
          <div className="mt-5 space-y-4 border-t border-border/40 pt-4">
            <div className="flex gap-2">
              <div className="relative flex-1">
                <Search className="absolute left-3.5 top-3 w-4 h-4 text-subtle-foreground" />
                <input
                  type="text"
                  placeholder={t('ledger.tool_hub_search_placeholder')}
                  value={integrationQuery}
                  onChange={(e) => setIntegrationQuery(e.target.value)}
                  disabled
                  className="w-full bg-background border border-border/60 rounded-xl pl-10 pr-4 py-2.5 text-xs text-subtle-foreground placeholder-subtle-foreground cursor-not-allowed transition-all font-sans"
                />
              </div>
              <button
                disabled
                title={t('ledger.tool_hub_coming_soon')}
                className="px-5 py-2.5 bg-surface/60 border border-border/40 text-subtle-foreground text-xs font-bold font-mono uppercase rounded-xl flex items-center gap-1 shrink-0 cursor-not-allowed opacity-50"
              >
                <Cpu className="w-3.5 h-3.5" />
                <span>{t('ledger.tool_hub_evaluate')}</span>
              </button>
            </div>

            {/* Quick Presets — disabled */}
            <div className="flex flex-wrap items-center gap-2 text-[10.5px] font-mono text-subtle-foreground select-none opacity-50">
              <span>{t('ledger.tool_hub_presets_label')}</span>
              {['Brave-MCP', 'GDrive-Workspace', 'PostgreSQL-Analyzer', 'Milvus-RAG'].map(label => (
                <span key={label} className="px-2 py-0.5 rounded bg-foreground/[0.05] text-subtle-foreground cursor-not-allowed">{label}</span>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Spawns Grid Render */}
      {spawns.length === 0 ? (
        backendStatus === 'offline' ? (
          <div className="h-64 border border-dashed border-danger/40 rounded-2xl flex flex-col items-center justify-center text-center p-6 bg-danger/10">
            <WifiOff className="w-8 h-8 text-danger/60 mb-2" />
            <h3 className="text-sm font-sans font-medium text-danger">{t('ledger.empty_backend_offline')}</h3>
            <p className="text-xs text-danger/70 max-w-sm mt-1">
              {t('ledger.empty_backend_offline_desc')}
            </p>
          </div>
        ) : (
          <div className="h-64 border border-dashed border-border rounded-2xl flex flex-col items-center justify-center text-center p-6 bg-background">
            <Cpu className="w-8 h-8 text-subtle-foreground mb-2 animate-bounce" />
            <h3 className="text-sm font-sans font-medium text-foreground">{t('ledger.empty_no_spawns')}</h3>
            <p className="text-xs text-subtle-foreground max-w-sm mt-1">
              {t('ledger.empty_no_spawns_desc')}
            </p>
          </div>
        )
      ) : (
        <div className={`grid gap-6 ${cardStyle === 'compact' ? 'grid-cols-1' : 'grid-cols-1 md:grid-cols-2 lg:grid-cols-3'}`}>
          {spawns.map(spawn => {

            // 1. ISOMETRIC GLASS GLOW CARD STYLE
            if (cardStyle === 'isometric') {
              const spawnLevel = Math.max(1, Math.floor(spawn.totalTasks / 10) + 1);
              return (
                <div
                  key={spawn.id}
                  onClick={() => setSelectedSpawnId(spawn.id)}
                  className={`bg-gradient-to-b from-surface/90 to-background/95 border border-border-strong hover:border-primary/40 rounded-2xl p-5 shadow-xl transition-all duration-300 hover:-translate-y-1 relative group cursor-pointer overflow-hidden`}
                >
                  {/* Neon pulsing glow outline */}
                  <div className="absolute top-0 right-0 w-32 h-32 bg-gradient-to-br from-primary/5 to-transparent blur-xl pointer-events-none group-hover:opacity-100 opacity-60 transition-opacity"></div>

                  {/* Title Info Row */}
                  <div className="flex items-start justify-between mb-4">
                    <div className="flex items-center gap-3.5">
                      <SpawnAvatar seed={spawn.name} size={48} />
                      <div>
                        <div className="flex items-center gap-1.5">
                          <h3 className="text-xs font-bold text-foreground font-sans tracking-wide group-hover:text-primary transition-colors">
                            {spawn.name}
                          </h3>
                        </div>
                        <p className="text-[10px] text-muted-foreground font-mono uppercase tracking-wider mt-0.5">
                          {spawn.domain}
                        </p>
                      </div>
                    </div>

                    {/* Status Badge */}
                    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[9px] font-bold tracking-wider uppercase font-mono ${
                      spawn.status === 'working'
                        ? 'bg-success/20 text-success animate-pulse'
                        : spawn.status === 'escalated'
                        ? 'bg-danger/20 text-danger'
                        : 'bg-info/20 text-info'
                    }`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${
                        spawn.status === 'working'
                          ? 'bg-success'
                          : spawn.status === 'escalated'
                          ? 'bg-danger'
                          : 'bg-info'
                      }`} />
                      {spawn.status}
                    </span>
                  </div>

                  {/* Spawn Description */}
                  <p className="text-xs text-muted-foreground leading-relaxed font-sans mb-3 h-10 overflow-hidden line-clamp-2">
                    {spawn.description}
                  </p>



                  {/* Equipment Panel Indicator */}
                  <div className="space-y-3 pt-4 border-t border-border/50">
                    <div className="flex justify-between items-center text-[10px] font-mono text-subtle-foreground uppercase tracking-widest">
                      <span>{t('ledger.equipped_systems')}</span>
                      <span className="text-muted-foreground font-bold">
                        {t('ledger.items_count', { count: spawn.tools.length + spawn.skills.length })}
                      </span>
                    </div>

                    <div className="flex flex-wrap gap-1.5">
                      {spawn.tools.slice(0, 2).map(id => {
                        const meta = TOOLS.find(t => t.id === id);
                        return (
                          <span key={id} className="inline-flex items-center gap-1 text-[10px] font-mono bg-surface text-muted-foreground px-2 py-0.5 rounded-md">
                            {getIcon(id, 'w-3 h-3')} {meta?.name || id}
                          </span>
                        );
                      })}
                      {spawn.skills.slice(0, 2).map(id => {
                        const meta = SKILLS.find(s => s.id === id);
                        return (
                          <span key={id} className="inline-flex items-center gap-1 text-[10px] font-mono bg-warning/10 text-warning px-2 py-0.5 rounded-md">
                            {getIcon(id, 'w-3 h-3')} {meta?.name || id}
                          </span>
                        );
                      })}
                      {spawn.tools.length + spawn.skills.length > 4 && (
                        <span className="text-[10px] text-subtle-foreground font-mono px-1">
                          +{spawn.tools.length + spawn.skills.length - 4} more
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Card Bottom Panel / Hover actions */}
                  <div className="mt-5 flex items-center justify-between text-subtle-foreground group-hover:text-muted-foreground transition-colors select-none">
                    <div className="flex items-center gap-3 text-[10px] font-mono">
                      <span className="flex items-center gap-1">
                        <Activity className="w-3.5 h-3.5 text-primary" />
                        {t('ledger.jobs_compiled', { count: spawn.totalTasks })}
                      </span>
                    </div>

                    <button
                      id={`edit-equip-${spawn.id}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        onEditEquipment(spawn.id);
                      }}
                      className="text-[10px] text-primary hover:text-primary-foreground font-mono bg-primary/10 hover:bg-primary px-2.5 py-1 rounded transition-all border border-primary/20 uppercase font-semibold flex items-center gap-1"
                    >
                      <Sliders className="w-3 h-3" />
                      {t('ledger.configure')}
                    </button>
                  </div>
                </div>
              );
            }

            // 2. TECH BLUEPRINT GRID CARD STYLE (Monospace labels, high contrast, wireframe layout)
            if (cardStyle === 'blueprint') {
              const spawnLevel = Math.max(1, Math.floor(spawn.totalTasks / 10) + 1);
              return (
                <div
                  key={spawn.id}
                  onClick={() => setSelectedSpawnId(spawn.id)}
                  className="border-2 border-primary/60 p-4 font-mono text-[11px] bg-background shadow-[3px_3px_0px_var(--color-primary)] hover:shadow-[5px_5px_0px_var(--color-primary)] transition-all relative cursor-pointer"
                >
                  <div className="absolute top-1 right-2 text-[9px] font-mono tracking-widest text-subtle-foreground uppercase">
                    Spawn-Ref: {spawn.id.slice(6, 11).toUpperCase()}
                  </div>

                  {/* Header info */}
                  <div className="pb-2 border-b border-dashed border-border mb-3 flex items-start gap-3">
                    <SpawnAvatar seed={spawn.name} size={26} />
                    <div className="flex-1">
                      <div className="font-bold text-foreground text-[12px] hover:text-primary flex items-center justify-between">
                        <span>{spawn.name.toUpperCase()}</span>
                      </div>
                      <div className="text-[9px] text-primary font-mono mt-0.5">
                        DOMAIN // {spawn.domain.toUpperCase()}
                      </div>
                    </div>
                  </div>

                  <p className="text-muted-foreground leading-relaxed mb-3 text-[11px] h-8 overflow-hidden">
                    {spawn.description.toUpperCase()}
                  </p>



                  {/* Equipment checklist items */}
                  <div className="space-y-1.5 mb-4">
                    <div className="text-[10px] text-subtle-foreground font-bold uppercase tracking-wider">
                      ≫ HARDWARE EQUIPMENT CHANCELLOR:
                    </div>
                    <div className="grid grid-cols-2 gap-1.5">
                      {spawn.tools.map(id => (
                        <div key={id} className="text-[10px] border border-border bg-background p-1 text-muted-foreground flex items-center gap-1">
                          {getIcon(id, 'w-3 h-3')} {id.toUpperCase()}
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="flex items-center justify-between pt-3 border-t border-border text-[10px]">
                    <span className="bg-primary text-primary-foreground px-1.5 font-bold">STATE: {spawn.status.toUpperCase()}</span>

                    <button
                      id={`edit-equip-bp-${spawn.id}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        onEditEquipment(spawn.id);
                      }}
                      className="text-foreground hover:text-primary border-l border-border pl-2 font-bold uppercase"
                    >
                      [ EDIT CHIPS ]
                    </button>
                  </div>
                </div>
              );
            }

            // 3. PILL COMPACT CARD STYLE (Ultra streamlined, expandable list view)
            if (cardStyle === 'compact') {
              const isSelected = selectedSpawnId === spawn.id;
              const spawnLevel = Math.max(1, Math.floor(spawn.totalTasks / 10) + 1);
              const progressPercent = (spawn.totalTasks % 10) * 10;
              const tasksToNextLevel = 10 - (spawn.totalTasks % 10);

              return (
                <div key={spawn.id} className="flex flex-col mb-2.5 select-none">
                  <div
                    onClick={() => setSelectedSpawnId(isSelected ? null : spawn.id)}
                    className={`bg-surface hover:bg-surface-raised border ${
                      isSelected ? 'border-primary bg-surface-raised' : 'border-border/60 hover:border-border-strong'
                    } rounded-xl p-3 px-4 flex flex-col sm:flex-row items-center justify-between gap-4 transition-all cursor-pointer`}
                  >
                    <div className="flex items-center gap-3 w-full sm:w-auto flex-1 min-w-0">
                      <SpawnAvatar seed={spawn.name} size={30} />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-bold text-foreground text-xs">{spawn.name}</span>
                          <span className="text-[9px] font-mono text-primary bg-primary/10 rounded px-2 py-0.5 select-none uppercase font-bold tracking-wider">{spawn.domain}</span>
                        </div>
                        <p className="text-xs text-muted-foreground mt-0.5 max-w-sm truncate">
                          {spawn.description}
                        </p>
                      </div>
                    </div>



                    {/* Equipment tags and action button */}
                    <div className="flex items-center gap-3.5 w-full sm:w-auto shrink-0 justify-end">
                      <div className="hidden md:flex flex-wrap items-center gap-2 text-[10px] text-subtle-foreground font-mono">
                        <span className="flex items-center gap-1"><Wrench className="w-3 h-3" /> {spawn.tools.length} tools</span>
                        <span>•</span>
                        <span className="flex items-center gap-1"><BookOpen className="w-3 h-3" /> {spawn.skills.length} skills</span>
                        <span>•</span>
                        <span className="text-success font-bold uppercase tracking-wider select-none">● active</span>
                      </div>

                      <div className="text-muted-foreground hover:text-foreground transition-colors">
                        {isSelected ? <ChevronUp className="w-4.5 h-4.5 text-primary" /> : <ChevronDown className="w-4.5 h-4.5" />}
                      </div>
                    </div>
                  </div>

                  {/* Expand-down panel content with glass animation */}
                  <AnimatePresence>
                    {isSelected && (
                      <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ duration: 0.25, ease: 'easeInOut' }}
                        className="overflow-hidden"
                      >
                        <div className="mt-1.5 bg-gradient-to-r from-surface/90 to-background/95 border border-border-strong/90 rounded-xl p-5 shadow-2xl relative">
                          <div className="absolute inset-0 bg-[linear-gradient(to_right,var(--color-primary)_1px,transparent_1px)] bg-[size:16rem_16rem] opacity-[0.012] pointer-events-none rounded-xl" />

                          <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 relative z-10">

                            {/* Summary profile */}
                            <div className="lg:col-span-4 space-y-4 border-b lg:border-b-0 lg:border-r border-border/60 pb-4 lg:pb-0 lg:pr-5 flex flex-col justify-between">
                              <div className="space-y-3">
                                <div>
                                  <span className="text-[9.5px] font-mono text-subtle-foreground uppercase tracking-widest block mb-1">Assigned Domain Profile</span>
                                  <span className="text-xs text-foreground font-bold block capitalize">{spawn.domain} Specialist</span>
                                </div>

                                <div>
                                  <div className="flex items-center justify-between mb-1">
                                    <span className="text-[9.5px] font-mono text-subtle-foreground uppercase tracking-widest block">Task Directive Scope</span>
                                  </div>
                                  <p className="text-xs text-muted-foreground leading-relaxed font-sans">{spawn.description}</p>
                                </div>
                              </div>

                              {/* Telemetry Jobs stats */}
                              <div className="bg-background border border-border/80 rounded-lg p-3 flex items-center justify-between mt-2">
                                <div className="space-y-0.5">
                                  <span className="text-[9px] font-mono text-subtle-foreground uppercase">Compiled Jobs Clocked</span>
                                  <div className="text-xs text-muted-foreground font-mono flex items-center gap-1 mt-0.5">
                                    <Clock className="w-3" />
                                    <span>Latency: 14ms average</span>
                                  </div>
                                </div>
                                <div className="text-right">
                                  <div className="text-lg font-mono font-bold text-primary animate-pulse">
                                    {spawn.totalTasks} jobs
                                  </div>
                                  <span className="text-[8px] font-mono text-success block uppercase font-bold">100% HEALTHY</span>
                                </div>
                              </div>
                            </div>

                            {/* Equipped Tools details */}
                            <div className="lg:col-span-4 space-y-3 border-b lg:border-b-0 lg:border-r border-border/60 pb-4 lg:pb-0 lg:pr-5">
                              <span className="text-[9.5px] font-mono text-subtle-foreground uppercase tracking-widest block font-bold">Equipped Standard Tools</span>

                              <div className="space-y-1.5 max-h-48 overflow-y-auto">
                                {spawn.tools.length === 0 ? (
                                  <div className="text-center py-4 bg-background border border-dashed border-border rounded">
                                    <span className="text-[10px] text-subtle-foreground font-mono">NO ACTIVE TOOLS LOADED</span>
                                  </div>
                                ) : (
                                  spawn.tools.map(tId => {
                                    const tool = TOOLS.find(t => t.id === tId) || { name: tId, description: 'Raw custom tool instruction.' };
                                    return (
                                      <div key={tId} className="flex items-start gap-2.5 p-2 bg-background border border-border rounded-lg">
                                        <span className="p-1 bg-foreground/5 border border-border rounded-md flex items-center justify-center">
                                          {getIcon(tId, 'w-3.5 h-3.5 text-muted-foreground')}
                                        </span>
                                        <div>
                                          <h4 className="text-[10.5px] font-bold text-foreground">{tool.name}</h4>
                                          <p className="text-[9.5px] text-muted-foreground font-sans mt-0.5 leading-relaxed">{tool.description}</p>
                                        </div>
                                      </div>
                                    );
                                  })
                                )}
                              </div>
                            </div>

                            {/* Skills details */}
                            <div className="lg:col-span-4 space-y-3 flex flex-col justify-between">
                              <div className="space-y-3">
                                <span className="text-[9.5px] font-mono text-subtle-foreground uppercase tracking-widest block font-bold">Cognitive Soft Skills</span>
                                <div className="space-y-1.5 max-h-40 overflow-y-auto">
                                  {spawn.skills.length === 0 ? (
                                    <div className="text-center py-4 bg-background border border-dashed border-border rounded">
                                      <span className="text-[10px] text-subtle-foreground font-mono font-medium">NO ACTIVE COGNITIVE SCHEMAS</span>
                                    </div>
                                  ) : (
                                    spawn.skills.map(sId => {
                                      const skill = SKILLS.find(s => s.id === sId) || { name: sId, description: 'Raw custom skill instruction context.' };
                                      return (
                                        <div key={sId} className="flex items-start gap-2.5 p-2 bg-background border border-border rounded-lg">
                                          <span className="p-1 bg-warning/5 border border-warning/10 text-warning rounded-md flex items-center justify-center">
                                            {getIcon(sId, 'w-3.5 h-3.5 text-warning')}
                                          </span>
                                          <div>
                                            <h4 className="text-[10.5px] font-bold text-warning">{skill.name}</h4>
                                            <p className="text-[9.5px] text-muted-foreground font-sans mt-0.5 leading-relaxed">{skill.description}</p>
                                          </div>
                                        </div>
                                      );
                                    })
                                  )}
                                </div>
                              </div>

                              {/* Action buttons inside interactive tray */}
                              <div className="pt-3 border-t border-border/50 flex items-center justify-between gap-3">
                                <button
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    onOpenDirectChat?.(spawn.id);
                                  }}
                                  className="flex-1 py-1.5 px-3 bg-primary hover:bg-primary-hover text-primary-foreground text-[10px] font-bold font-sans uppercase rounded-lg transition-all flex items-center justify-center gap-1.5 shadow-lg shadow-primary/10 cursor-pointer"
                                >
                                  <MessageSquare className="w-3.5 h-3.5" />
                                  <span>{t('ledger.open_channel')}</span>
                                </button>

                                <button
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    onEditEquipment(spawn.id);
                                  }}
                                  className="py-1.5 px-3 bg-surface hover:bg-foreground/[0.04] border border-border hover:border-border-strong text-muted-foreground hover:text-foreground text-[10px] font-mono uppercase rounded-lg transition-all flex items-center justify-center gap-1 cursor-pointer"
                                >
                                  <Sliders className="w-3.5 h-3.5" />
                                  <span>{t('ledger.calibrate')}</span>
                                </button>
                              </div>
                            </div>

                          </div>
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              );
            }

            return null;
          })}
        </div>
      )}
    </div>
  );
}
