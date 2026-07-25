/**
 * AdvancedSection — the "Advanced" settings section.
 *
 * Self-contained card lifted verbatim out of SettingsScreen's `advanced` slot.
 * Per spec B1 this section groups: the diagnostic-telemetry toggle, the
 * orchestrator-shell toggle + its confirm-policy Select (shown only when the
 * shell is enabled), and the spawn synthesis-mode Select.
 *
 * Copy fix (spec B3): the spawn-mode desc paragraph and its three option labels
 * were hardcoded English inline; they now come from the i18n keys
 * settings.spawnModeDesc / spawnModeAuto / spawnModeInteractive / spawnModeStrict
 * (×6 locales). The option VALUES ('auto'/'interactive'/'strict') and the
 * settings.labelSpawnMode label are unchanged.
 *
 * Presentational: owns NO persistence. onChange callbacks are value-based so the
 * host keeps the exact save path it had before extraction (Task 6 owns save).
 */

import React from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Sliders } from 'lucide-react';
import Select from '../Select';
import McpTokenControl from './McpTokenControl';

export type ShellConfirmPolicy = 'ask_all' | 'ask_risky';
export type SpawnMode = 'auto' | 'interactive' | 'strict';

export interface AdvancedSectionProps {
  /** Diagnostic-telemetry opt-in. */
  telemetry: boolean;
  onTelemetryChange: (value: boolean) => void;
  /** Whether Arslan may run whitelisted shell commands. */
  orchestratorShellEnabled: boolean;
  onOrchestratorShellChange: (value: boolean) => void;
  /** Confirm policy for shell commands (only meaningful when shell is enabled). */
  shellConfirmPolicy: ShellConfirmPolicy;
  onShellConfirmPolicyChange: (value: ShellConfirmPolicy) => void;
  /** How sub-agents are created. */
  spawnMode: SpawnMode;
  onSpawnModeChange: (value: SpawnMode) => void;
  /** Inbound MCP server — expose read-only tools to external MCP clients. */
  mcpServerEnabled: boolean;
  onMcpServerChange: (value: boolean) => void;
  /** Background auto-evolution. Optional so existing prop literals stay valid; absent
   * reads as OFF, which is also the backend default. */
  evolutionAuto?: boolean;
  onEvolutionAutoChange?: (value: boolean) => void;
  /** null = no cap in effect, which changes what the warning is allowed to claim. */
  evolutionMaxDispatches?: number | null;
  onEvolutionMaxDispatchesChange?: (value: number | null) => void;
}

export default function AdvancedSection({
  telemetry,
  onTelemetryChange,
  orchestratorShellEnabled,
  onOrchestratorShellChange,
  shellConfirmPolicy,
  onShellConfirmPolicyChange,
  spawnMode,
  onSpawnModeChange,
  mcpServerEnabled,
  onMcpServerChange,
  evolutionAuto = false,
  onEvolutionAutoChange,
  evolutionMaxDispatches = null,
  onEvolutionMaxDispatchesChange,
}: AdvancedSectionProps) {
  const { t } = useTranslation();

  return (
    <div className="bg-surface/60 border border-border rounded-2xl p-6 space-y-6">
      <div className="flex items-center gap-2 pb-4 border-b border-border/50 select-none">
        <Sliders className="w-4.5 h-4.5 text-primary" />
        <h3 className="text-xs font-semibold font-mono uppercase tracking-widest text-foreground leading-none">{t('settings.navAdvanced')}</h3>
      </div>

      <div className="space-y-4">
        {/* Toggle telemetry */}
        <div className="flex items-center justify-between">
          <div>
            <h4 className="text-xs font-bold text-foreground font-sans">{t('settings.labelTelemetry')}</h4>
            <p className="text-[11px] text-muted-foreground font-sans mt-0.5 max-w-xl">
              {t('settings.telemetryDesc')}
            </p>
          </div>
          <input
            id="settings-telemetry-toggle"
            type="checkbox"
            checked={telemetry}
            onChange={(e) => onTelemetryChange(e.target.checked)}
            className="w-4 h-4 text-primary bg-background border-border rounded focus:ring-0 select-none cursor-pointer"
          />
        </div>

        {/* Separation divider */}
        <div className="h-[1px] bg-border/40"></div>

        {/* Orchestrator shell — Arslan may run whitelisted commands (default off) */}
        <div className="flex items-center justify-between">
          <div>
            <h4 className="text-xs font-bold text-foreground font-sans">{t('settings.labelOrchestratorShell')}</h4>
            <p className="text-[11px] text-muted-foreground font-sans mt-0.5 max-w-xl">
              {t('settings.orchestratorShellDesc')}
            </p>
          </div>
          <input
            id="settings-shell-toggle"
            type="checkbox"
            checked={orchestratorShellEnabled}
            onChange={(e) => onOrchestratorShellChange(e.target.checked)}
            className="w-4 h-4 text-primary bg-background border-border rounded focus:ring-0 select-none cursor-pointer"
          />
        </div>

        {/* Confirm-policy select — only meaningful when shell is enabled */}
        {orchestratorShellEnabled && (
          <div className="flex items-center justify-between pl-4 border-l-2 border-primary/20">
            <div>
              <h4 className="text-xs font-bold text-foreground font-sans">{t('settings.labelShellConfirmPolicy')}</h4>
            </div>
            <Select
              id="settings-shell-policy"
              value={shellConfirmPolicy}
              onChange={(v) => onShellConfirmPolicyChange(v as ShellConfirmPolicy)}
              options={[
                { value: 'ask_all', label: t('settings.shellPolicyAskAll') },
                { value: 'ask_risky', label: t('settings.shellPolicyAskRisky') },
              ]}
              className="w-56"
              ariaLabel={t('settings.labelShellConfirmPolicy')}
            />
          </div>
        )}

        {/* Separation divider */}
        <div className="h-[1px] bg-border/40"></div>

        {/* Spawns synthesis modes */}
        <div className="flex items-center justify-between">
          <div>
            <h4 className="text-xs font-bold text-foreground font-sans">{t('settings.labelSpawnMode')}</h4>
            <p className="text-[11px] text-muted-foreground font-sans mt-0.5 max-w-xl">
              {t('settings.spawnModeDesc')}
            </p>
          </div>
          <Select
            id="settings-spawn-mode"
            value={spawnMode}
            onChange={(v) => onSpawnModeChange(v as SpawnMode)}
            options={[
              { value: 'auto', label: t('settings.spawnModeAuto') },
              { value: 'interactive', label: t('settings.spawnModeInteractive') },
              { value: 'strict', label: t('settings.spawnModeStrict') },
            ]}
            className="w-40"
            ariaLabel={t('settings.labelSpawnMode')}
          />
        </div>

        {/* Separation divider */}
        <div className="h-[1px] bg-border/40"></div>

        {/* Inbound MCP server — expose read-only metadata tools to external MCP clients (default off) */}
        <div className="flex items-center justify-between">
          <div>
            <h4 className="text-xs font-bold text-foreground font-sans">{t('settings.labelMcpServer')}</h4>
            <p className="text-[11px] text-muted-foreground font-sans mt-0.5 max-w-xl">
              {t('settings.mcpServerDesc')}
            </p>
          </div>
          <input
            id="settings-mcp-server-toggle"
            type="checkbox"
            checked={mcpServerEnabled}
            onChange={(e) => onMcpServerChange(e.target.checked)}
            className="w-4 h-4 text-primary bg-background border-border rounded focus:ring-0 select-none cursor-pointer"
          />
        </div>
        <McpTokenControl />

        <div className="h-[1px] bg-border/40"></div>

        {/* Background auto-evolution — default OFF. It spends the user's API credits and
            no working spend cap exists, so the warning below is not decoration: it is the
            information someone needs to decide, and the mitigation is the only real one
            available today. Styling carries the warning, not an emoji in the string —
            emoji render inconsistently across platforms and across six locales. */}
        <div className="flex items-start justify-between gap-4">
          <div>
            <h4 className="text-xs font-bold text-foreground font-sans">
              {t('settings.labelEvolutionAuto')}
            </h4>
            <p className="text-[11px] text-muted-foreground font-sans mt-0.5 max-w-xl">
              {t('settings.evolutionAutoDesc')}
            </p>
            <p className="mt-1 flex items-start gap-1.5 text-[11px] text-warning font-sans max-w-xl"
               data-testid="evolution-auto-warning">
              <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-[1px]" aria-hidden />
              {/* 🔴 Conditional on purpose. Saying "the cap counts dispatches" while no
                  cap is in effect would describe a guard that is not there — the same
                  "looks armed" failure this feature's default was changed to avoid,
                  moved into copy. Only once a value is actually set does the other
                  sentence become true. */}
              <span>
                {evolutionMaxDispatches == null
                  ? t('settings.evolutionAutoSpendWarning')
                  : t('settings.evolutionAutoSpendWarningCapped',
                      { cap: evolutionMaxDispatches })}
              </span>
            </p>
          </div>
          <input
            id="settings-evolution-auto-toggle"
            type="checkbox"
            checked={evolutionAuto}
            onChange={(e) => onEvolutionAutoChange?.(e.target.checked)}
            className="w-4 h-4 mt-1 shrink-0 text-primary bg-background border-border rounded focus:ring-0 select-none cursor-pointer"
          />
        </div>

        <div className="flex items-center justify-between">
          <div>
            <h4 className="text-xs font-bold text-foreground font-sans">
              {t('settings.labelEvolutionMaxDispatches')}
            </h4>
            <p className="text-[11px] text-muted-foreground font-sans mt-0.5 max-w-xl">
              {t('settings.evolutionMaxDispatchesDesc')}
            </p>
          </div>
          <input
            id="settings-evolution-max-dispatches"
            type="number"
            min={1}
            value={evolutionMaxDispatches ?? ''}
            placeholder={t('settings.evolutionMaxDispatchesUnset')}
            onChange={(e) => {
              const raw = e.target.value.trim();
              onEvolutionMaxDispatchesChange?.(raw === '' ? null : Number(raw));
            }}
            className="w-28 px-2 py-1 text-[11px] font-mono rounded bg-background border border-border focus:ring-0"
          />
        </div>
      </div>
    </div>
  );
}
