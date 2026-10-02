/**
 * AdvancedSection — the "Advanced" settings section.
 *
 * Self-contained card lifted verbatim out of SettingsScreen's `advanced` slot.
 * Per spec B1 this section groups: the diagnostic-telemetry toggle, the
 * terminal toggle + its ask policy + the commands the user said never to ask
 * about again, workspace, voice input, LAN/SSH reach, background-job budget.
 *
 * Presentational: owns NO persistence. onChange callbacks are value-based so the
 * host keeps the exact save path it had before extraction (Task 6 owns save).
 */

import React from 'react';
import { useTranslation } from 'react-i18next';
import { LANGUAGE_OPTIONS } from '../../lib/languages';
import { VOICE_LOCALE_BY_CODE } from '../../lib/speech';
import { AlertTriangle, Sliders } from 'lucide-react';
import Select from '../Select';
import McpTokenControl from './McpTokenControl';
import SshIdentityPanel from './SshIdentityPanel';
import SshNodesPanel from './SshNodesPanel';
import TerminalRulesPanel from './TerminalRulesPanel';
import BrowserPanel from '../BrowserPanel';
import type { VoiceMode } from '../../types';

export type ShellConfirmPolicy = 'ask_all' | 'ask_risky';
export type BackgroundJobBudget = 'lean' | 'standard' | 'ample';
// Mirrors arslan/execution_budget.JOB_TIERS (the soft limits). A backend test
// pins the same numbers, so the two cannot drift silently.
export const JOB_TIER_NUMBERS: Record<BackgroundJobBudget, { requests: number; tools: number; tokens: string; minutes: number }> = {
  lean: { requests: 60, tools: 40, tokens: '300k', minutes: 15 },
  standard: { requests: 120, tools: 80, tokens: '600k', minutes: 30 },
  ample: { requests: 240, tools: 160, tokens: '1.2M', minutes: 60 },
};

export interface AdvancedSectionProps {
  /** Diagnostic-telemetry opt-in. */
  telemetry: boolean;
  onTelemetryChange: (value: boolean) => void;
  /** Whether Arslan may use the terminal (0.1.48: on by default). */
  orchestratorShellEnabled: boolean;
  onOrchestratorShellChange: (value: boolean) => void;
  /** Confirm policy for shell commands (only meaningful when shell is enabled). */
  shellConfirmPolicy: ShellConfirmPolicy;
  onShellConfirmPolicyChange: (value: ShellConfirmPolicy) => void;
  /** 0.1.51 P3: commands run in the workspace sandbox (on by default). Optional so older hosts still render. */
  terminalSandboxEnabled?: boolean;
  onTerminalSandboxChange?: (value: boolean) => void;
  /** 0.1.43: where a background job wraps up. Optional so older hosts still render. */
  backgroundJobBudget?: BackgroundJobBudget;
  onBackgroundJobBudgetChange?: (value: BackgroundJobBudget) => void;
  /** Directory the file tools may work in. Empty = unset = tools not offered. */
  workspaceDir: string;
  onWorkspaceDirChange: (value: string) => void;
  /** May Arslan look at what is on the local network? Default OFF. */
  lanDiscoveryEnabled: boolean;
  onLanDiscoveryChange: (value: boolean) => void;
  defaultReadEnabled: boolean;
  onDefaultReadChange: (value: boolean) => void;
  voiceInputLocale: string;
  onVoiceInputLocaleChange: (value: string) => void;
  /** How the microphone is used: not at all, held, or always listening. */
  voiceMode: VoiceMode;
  onVoiceModeChange: (value: VoiceMode) => void;
  /** Conversation mode: silence (ms) after speech that ends a sentence. */
  voiceEndpointSilenceMs: number;
  onVoiceEndpointSilenceChange: (value: number) => void;
  /** May Arslan log into another machine over SSH? Default OFF, separately. */
  sshEnabled: boolean;
  onSshChange: (value: boolean) => void;
}

// Moved out of here, deliberately, and the moves are the point of the redesign:
//   mcpServerEnabled  → AccessTokenSettings (beside the token that guards it)

export default function AdvancedSection({
  telemetry,
  onTelemetryChange,
  orchestratorShellEnabled,
  onOrchestratorShellChange,
  shellConfirmPolicy,
  onShellConfirmPolicyChange,
  terminalSandboxEnabled = true,
  onTerminalSandboxChange,
  backgroundJobBudget = 'standard',
  onBackgroundJobBudgetChange,
  workspaceDir,
  onWorkspaceDirChange,
  lanDiscoveryEnabled,
  onLanDiscoveryChange,
  defaultReadEnabled,
  onDefaultReadChange,
  voiceInputLocale,
  onVoiceInputLocaleChange,
  voiceMode,
  onVoiceModeChange,
  voiceEndpointSilenceMs,
  onVoiceEndpointSilenceChange,
  sshEnabled,
  onSshChange,
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

        {/* Where Arslan saves its work. Empty = Arslan's own folder (~/Arslan). */}
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

        {/* The language you SPEAK. Separate from the interface language on
            purpose: reading replies aloud followed the interface language and
            handed an English voice Chinese sentences, and reading an English
            UI while speaking Chinese is the ordinary case, not the edge one. */}
        <div className="flex items-start justify-between gap-4">
          <div>
            <h4 className="text-xs font-bold text-foreground font-sans">
              {t('settings.labelVoiceInputLocale')}
            </h4>
            <p className="text-[11px] text-muted-foreground font-sans mt-0.5 max-w-xl">
              {t('settings.voiceInputLocaleDesc')}
            </p>
          </div>
          <select
            data-testid="voice-input-locale"
            value={voiceInputLocale}
            onChange={(e) => onVoiceInputLocaleChange(e.target.value)}
            className="text-[11px] font-mono bg-background border border-border rounded-lg px-2 py-1.5 shrink-0"
          >
            <option value="">{t('settings.labelLanguage')}</option>
            {LANGUAGE_OPTIONS.map((o) => (
              <option key={o.code} value={VOICE_LOCALE_BY_CODE[o.code] ?? o.code}>
                {o.label}
              </option>
            ))}
          </select>
        </div>

        {/* How the microphone is used. Conversation mode is opt-in: an app that
            listens all the time is a choice the user makes, never a default. */}
        <div className="flex items-start justify-between gap-4">
          <div>
            <h4 className="text-xs font-bold text-foreground font-sans">{t('settings.labelVoiceMode')}</h4>
            <p className="text-[11px] text-muted-foreground font-sans mt-0.5 max-w-xl">{t('settings.voiceModeDesc')}</p>
          </div>
          <select
            data-testid="voice-mode"
            value={voiceMode}
            onChange={(e) => onVoiceModeChange(e.target.value as VoiceMode)}
            className="text-[11px] font-mono bg-background border border-border rounded-lg px-2 py-1.5 shrink-0"
          >
            <option value="off">{t('settings.voiceModeOff')}</option>
            <option value="push_to_talk">{t('settings.voiceModePushToTalk')}</option>
            <option value="conversation">{t('settings.voiceModeConversation')}</option>
          </select>
        </div>

        {/* The one tunable of the endpointer (spec §3.1). Clamped: below 300 ms
            every breath ends a sentence, above 3 s the app feels deaf. */}
        <div className="flex items-start justify-between gap-4">
          <div>
            <h4 className="text-xs font-bold text-foreground font-sans">{t('settings.labelVoiceEndpointSilence')}</h4>
            <p className="text-[11px] text-muted-foreground font-sans mt-0.5 max-w-xl">{t('settings.voiceEndpointSilenceDesc')}</p>
          </div>
          <input
            data-testid="voice-endpoint-silence"
            type="number"
            min={300}
            max={3000}
            step={100}
            value={voiceEndpointSilenceMs}
            onChange={(e) => {
              const n = Number.parseInt(e.target.value, 10);
              onVoiceEndpointSilenceChange(Math.min(3000, Math.max(300, Number.isNaN(n) ? 900 : n)));
            }}
            className="w-24 text-[11px] font-mono bg-background border border-border rounded-lg px-2 py-1.5 shrink-0"
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

        {/* Terminal (0.1.48): on by default; the policy decides what asks first. */}
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
        {orchestratorShellEnabled && (
          <div className="flex items-start justify-between gap-4 pl-4 border-l-2 border-primary/20">
            <div>
              <h4 className="text-xs font-bold text-foreground font-sans">{t('settings.labelTerminalSandbox')}</h4>
              <p className="text-[11px] text-muted-foreground font-sans mt-0.5 max-w-xl">
                {t('settings.terminalSandboxDesc')}
              </p>
            </div>
            <input
              id="settings-terminal-sandbox-toggle"
              data-testid="settings-terminal-sandbox-toggle"
              type="checkbox"
              checked={terminalSandboxEnabled}
              onChange={(e) => onTerminalSandboxChange?.(e.target.checked)}
              className="w-4 h-4 mt-1 shrink-0 text-primary bg-background border-border rounded focus:ring-0 select-none cursor-pointer"
            />
          </div>
        )}
        {orchestratorShellEnabled && <TerminalRulesPanel />}

        {/* Separation divider */}
        <div className="h-[1px] bg-border/40"></div>

        {/* 0.1.43: where a background job stops gathering and writes up its result. */}
        {onBackgroundJobBudgetChange && <>
        <div className="h-[1px] bg-border/40"></div>
        <div className="flex items-center justify-between gap-4">
          <div>
            <h4 className="text-xs font-bold text-foreground font-sans">{t('jobs.budgetLabel')}</h4>
            <p className="text-[11px] text-muted-foreground font-sans mt-0.5 max-w-xl" data-testid="job-budget-desc">
              {t('jobs.budgetDesc', JOB_TIER_NUMBERS[backgroundJobBudget])}
            </p>
          </div>
          <Select
            id="settings-background-job-budget"
            value={backgroundJobBudget}
            onChange={(v) => onBackgroundJobBudgetChange(v as BackgroundJobBudget)}
            options={(['lean', 'standard', 'ample'] as const).map(value => ({ value, label: t(`jobs.budgetTier.${value}`) }))}
            className="w-40"
            ariaLabel={t('jobs.budgetLabel')}
          />
        </div>
        </>}

        {/* 0.1.42: moved here from the work panel's footer — this is the one
            place that sets up the browser runtime and runs a static preview. */}
        <div className="h-[1px] bg-border/40"></div>
        <BrowserSetupRow />

      </div>
    </div>
  );
}

function BrowserSetupRow() {
  const { t } = useTranslation();
  const [open, setOpen] = React.useState(false);
  return (
    <div className="flex items-center justify-between">
      <h4 className="text-xs font-bold text-foreground font-sans">{t('dock.staticPreview')}</h4>
      <button type="button" data-testid="settings-browser-setup" onClick={() => setOpen(true)}
        className="rounded-lg border border-border px-3 py-1.5 text-xs hover:bg-foreground/5">{t('ui.open')}</button>
      <BrowserPanel open={open} onClose={() => setOpen(false)} />
    </div>
  );
}
