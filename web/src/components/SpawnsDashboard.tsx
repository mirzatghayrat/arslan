import React, { useState } from 'react';
import { Spawn } from '../types';
import { useCapabilityLabel } from '../stores/registryStore';
import SpawnDetail from './SpawnDetail';
import {
  Sliders, Activity, Cpu, WifiOff, Plus } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { getIcon } from './iconMap';
import { SpawnAvatar } from './SpawnAvatar';
import type { BackendStatus } from '../hooks/useBackendStatus';
import EmptyState, { EmptyStateAction } from "./EmptyState";

interface SpawnsDashboardProps {
  spawns: Spawn[];
  selectedSpawnId: string | null;
  setSelectedSpawnId: (id: string | null) => void;
  onEditEquipment: (spawnId: string) => void;
  onDeleteSpawn?: (spawnId: string) => void;
  onCreateSpawnClick: () => void;
  onOpenDirectChat?: (spawnId: string) => void;
  setSpawns?: React.Dispatch<React.SetStateAction<Spawn[]>>;
  setThreads?: React.Dispatch<React.SetStateAction<any[]>>;
  activeThreadId?: string;
  backendStatus?: BackendStatus;
}

export default function SpawnsDashboard({
  spawns,
  selectedSpawnId,
  setSelectedSpawnId,
  onEditEquipment,
  onCreateSpawnClick,
  onOpenDirectChat,
  setSpawns,
  setThreads,
  activeThreadId,
  backendStatus,
}: SpawnsDashboardProps) {
  const { t } = useTranslation();
  const capabilityLabel = useCapabilityLabel();
  const [detailSpawnId, setDetailSpawnId] = useState<string | null>(null);
  return (
    <div className="flex-1 overflow-y-auto bg-background p-8 select-none relative">
      {/* Decorative Top Lights */}
      <div className="absolute top-0 right-1/4 w-[35rem] h-[35rem] bg-primary/[0.02] blur-[120px] rounded-full pointer-events-none"></div>

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

      {/* Spawns Grid Render */}
      {spawns.length === 0 ? (
        backendStatus === 'offline' ? (
          <EmptyState icon={WifiOff} tone="danger" testId="empty-spawn-ledger-offline"
            title={t('ledger.empty_backend_offline')} body={t('ledger.empty_backend_offline_desc')} />
        ) : (
          <EmptyState
            icon={Cpu}
            title={t('ledger.empty_no_spawns')}
            body={t('ledger.empty_no_spawns_desc')}
            testId="empty-spawn-ledger"
            action={
              <EmptyStateAction onClick={onCreateSpawnClick}>
                <Plus className="w-3 h-3" />
                {t('ledger.empty_no_spawns_action')}
              </EmptyStateAction>
            }
          />
        )
      ) : (
        <div className="grid gap-6 grid-cols-1 md:grid-cols-2 lg:grid-cols-3">
          {spawns.map(spawn => {
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
                      {spawn.tools.slice(0, 2).map(id => (
                          <span key={id} className="inline-flex items-center gap-1 text-[10px] font-mono bg-surface text-muted-foreground px-2 py-0.5 rounded-md">
                            {getIcon(id, 'w-3 h-3')} {capabilityLabel(id)}
                          </span>
                      ))}
                      {spawn.skills.slice(0, 2).map(id => (
                          <span key={id} className="inline-flex items-center gap-1 text-[10px] font-mono bg-warning/10 text-warning px-2 py-0.5 rounded-md">
                            {getIcon(id, 'w-3 h-3')} {capabilityLabel(id)}
                          </span>
                      ))}
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
          })}
        </div>
      )}

      {detailSpawnId != null && (
        <div className="run-replay-overlay" onClick={() => setDetailSpawnId(null)}>
          <div className="run-replay-overlay__panel" onClick={(e) => e.stopPropagation()}>
            <SpawnDetail
              spawnId={Number(detailSpawnId)}
              spawnName={spawns.find((s) => s.id === detailSpawnId)?.name ?? ""}
              onClose={() => setDetailSpawnId(null)}
            />
          </div>
        </div>
      )}
    </div>
  );
}
