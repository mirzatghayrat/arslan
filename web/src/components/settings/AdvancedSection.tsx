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
import SshIdentityPanel from './SshIdentityPanel';
import SshNodesPanel from './SshNodesPanel';

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
  /** Directory the file tools may work in. Empty = unset = tools not offered. */
  workspaceDir: string;
  onWorkspaceDirChange: (value: string) => void;
  /** May Arslan look at what is on the local network? Default OFF. */
  lanDiscoveryEnabled: boolean;
  onLanDiscoveryChange: (value: boolean) => void;
  defaultReadEnabled: boolean;
  onDefaultReadChange: (value: boolean) => void;
  voiceOutputEnabled: boolean;
  onVoiceOutputChange: (value: boolean) => void;
  /** May Arslan log into another machine over SSH? Default OFF, separately. */
  sshEnabled: boolean;
  onSshChange: (value: boolean) => void;
  /** How sub-agents are created. */
  spawnMode: SpawnMode;
  onSpawnModeChange: (value: SpawnMode) => void;
}

// Moved out of here, deliberately, and the moves are the point of the redesign:
//   mcpServerEnabled  → AccessTokenSettings (beside the token that guards it)
//   evolutionAuto     → AutomationSection   (beside the other things that spend)
//   evolutionMaxDispatches → AutomationSection (beside what it caps)

export default function AdvancedSection({
  telemetry,
  onTelemetryChange,
  orchestratorShellEnabled,
  onOrchestratorShellChange,
  shellConfirmPolicy,
  onShellConfirmPolicyChange,
  workspaceDir,
  onWorkspaceDirChange,
  lanDiscoveryEnabled,
  onLanDiscoveryChange,
  defaultReadEnabled,
  onDefaultReadChange,
  voiceOutputEnabled,
  onVoiceOutputChange,
  sshEnabled,
  onSshChange,
  spawnMode,
  onSpawnModeChange,
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

        {/* Workspace for the file tools (P1). Empty by design: with no directory
            picked the tools are not offered at all. */}
        <div className="space-y-1.5">
          <label htmlFor="workspace-dir" className="text-[11px] font-mono text-muted-foreground">
            {t('settings.labelWorkspaceDir')}
          </label>
          <input
            id="workspace-dir"
            type="text"
            data-testid="settings-workspace-dir"
            value={workspaceDir}
            onChange={(e) => onWorkspaceDirChange(e.target.value)}
            placeholder={t('settings.workspaceDirPlaceholder')}
            className="w-full bg-surface border border-border-strong focus:border-primary focus:outline-none rounded-lg px-3 py-2 text-[12px] text-foreground font-mono"
          />
          <p className="text-[10.5px] text-subtle-foreground font-sans">
            {t('settings.workspaceDirHint')}
          </p>
        </div>

        {/* Default read (spec 2026-08-24). ON by default — the one switch here
            that ships enabled, because reading is the low-risk half and it is
            what makes a fresh install useful. Turning it off reverts to
            "workspace only". */}
        <div className="flex items-start justify-between gap-4">
          <div>
            <h4 className="text-xs font-bold text-foreground font-sans">
              {t('settings.labelDefaultRead')}
            </h4>
            <p className="text-[11px] text-muted-foreground font-sans mt-0.5 max-w-xl">
              {t('settings.defaultReadDesc')}
            </p>
          </div>
          <input
            id="settings-default-read"
            data-testid="default-read-toggle"
            type="checkbox"
            checked={defaultReadEnabled}
            onChange={(e) => onDefaultReadChange(e.target.checked)}
            className="w-4 h-4 mt-1 shrink-0 text-primary bg-background border-border rounded focus:ring-0 select-none cursor-pointer"
          />
        </div>

        {/* Voice output (V1). Reads replies aloud via the webview's speech
            synthesizer — off by default, since a talking machine is a choice. */}
        <div className="flex items-start justify-between gap-4">
          <div>
            <h4 className="text-xs font-bold text-foreground font-sans">
              {t('settings.labelVoiceOutput')}
            </h4>
            <p className="text-[11px] text-muted-foreground font-sans mt-0.5 max-w-xl">
              {t('settings.voiceOutputDesc')}
            </p>
          </div>
          <input
            id="settings-voice-output"
            data-testid="voice-output-toggle"
            type="checkbox"
            checked={voiceOutputEnabled}
            onChange={(e) => onVoiceOutputChange(e.target.checked)}
            className="w-4 h-4 mt-1 shrink-0 text-primary bg-background border-border rounded focus:ring-0 select-none cursor-pointer"
          />
        </div>

        {/* Local network discovery (P3a). Read-only, and off until chosen. */}
        <div className="flex items-start justify-between gap-4">
          <div>
            <h4 className="text-xs font-bold text-foreground font-sans">
              {t('settings.labelLanDiscovery')}
            </h4>
            <p className="text-[11px] text-muted-foreground font-sans mt-0.5 max-w-xl">
              {t('settings.lanDiscoveryDesc')}
            </p>
          </div>
          <input
            id="settings-lan-discovery"
            data-testid="lan-discovery-toggle"
            type="checkbox"
            checked={lanDiscoveryEnabled}
            onChange={(e) => onLanDiscoveryChange(e.target.checked)}
            className="w-4 h-4 mt-1 shrink-0 text-primary bg-background border-border rounded focus:ring-0 select-none cursor-pointer"
          />
        </div>

        {/* Reaching another machine (P3b). A separate consent from discovery:
            seeing a machine and logging into it are different decisions. */}
        <div className="flex items-start justify-between gap-4">
          <div>
            <h4 className="text-xs font-bold text-foreground font-sans">
              {t('settings.labelSsh')}
            </h4>
            <p className="text-[11px] text-muted-foreground font-sans mt-0.5 max-w-xl">
              {t('settings.sshDesc')}
            </p>
          </div>
          <input
            id="settings-ssh"
            data-testid="ssh-toggle"
            type="checkbox"
            checked={sshEnabled}
            onChange={(e) => onSshChange(e.target.checked)}
            className="w-4 h-4 mt-1 shrink-0 text-primary bg-background border-border rounded focus:ring-0 select-none cursor-pointer"
          />
        </div>
        {sshEnabled ? <SshIdentityPanel /> : null}
        {sshEnabled ? <SshNodesPanel /> : null}

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

      </div>
    </div>
  );
}
