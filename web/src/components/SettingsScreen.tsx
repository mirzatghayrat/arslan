import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { AppSettings } from '../types';
import type { ProviderOption, ProviderConfig } from '../api/client.types';
import type { BackendStatus } from '../hooks/useBackendStatus';
import { api } from '../api/client';
import { toBackendSettings } from '../api/adapters';
import {
  Sliders, Check, Save,
  Info, AlertCircle, WifiOff, Database
} from 'lucide-react';
import ProviderConfigList from './ProviderConfigList';
import AccessTokenSettings from './AccessTokenSettings';
import EmbeddingSettings from './EmbeddingSettings';
import Select from './Select';
import SettingsShell from './settings/SettingsShell';
import SearchToolsSection from './settings/SearchToolsSection';
import AppearanceSection from './settings/AppearanceSection';
import type { SettingsSectionId } from './settings/sectionRegistry';

interface SettingsScreenProps {
  settings: AppSettings;
  setSettings: React.Dispatch<React.SetStateAction<AppSettings>>;
  llmProviders: ProviderOption[];
  searchProviders: string[];
  backendStatus: BackendStatus;
  /** Multi-model provider configurations loaded from backend. */
  providerConfigs?: ProviderConfig[];
  /** Called when the configs list changes (add/update/delete/set-primary). */
  onProviderConfigsChange?: (configs: ProviderConfig[]) => void;
  /** Deep-link: which section opens first (defaults to 'providers'). */
  initialSection?: SettingsSectionId;
}

export default function SettingsScreen({ settings, setSettings, llmProviders, searchProviders, backendStatus, providerConfigs = [], onProviderConfigsChange, initialSection }: SettingsScreenProps) {
  const { t, i18n } = useTranslation();
  const [localSettings, setLocalSettings] = useState<AppSettings>({ ...settings });
  const [isSaved, setIsSaved] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [activeSection, setActiveSection] = useState<SettingsSectionId>(initialSection ?? 'providers');

  // Sync local form when parent settings update (e.g. after initial backend fetch)
  useEffect(() => {
    setLocalSettings((prev) => ({ ...prev, ...settings }));
  }, [settings]);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaveError(null);
    try {
      const backendBody = toBackendSettings(localSettings);
      await api.updateSettings(backendBody);
      setSettings(localSettings);
      setIsSaved(true);
      setTimeout(() => setIsSaved(false), 2000);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Save failed');
    }
  };

  // ── Section slots ─────────────────────────────────────────────────────────
  // Pure relocation of the existing cards into the shell's section slots. The
  // controls, handlers, ids and state setters are unchanged — only their host
  // section differs. (Task 1: no internal edits, no save-logic change.)
  const sections: Partial<Record<SettingsSectionId, React.ReactNode>> = {
    // Providers — the multi-model LLM provider list (embedding moved to memory).
    providers: (
      <div className="bg-surface/60 border border-border rounded-2xl p-6 space-y-6">
        <div className="flex items-center gap-2 pb-4 border-b border-border/50 select-none">
          <Sliders className="w-4.5 h-4.5 text-primary" />
          <h3 className="text-xs font-semibold font-mono uppercase tracking-widest text-foreground leading-none">{t('settings.sectionLlmConfig')}</h3>
        </div>
        <ProviderConfigList
          llmProviders={llmProviders}
          providerConfigs={providerConfigs}
          onConfigsChange={(updated) => onProviderConfigsChange?.(updated)}
          strategy={localSettings.llmStrategy}
          onStrategyChange={(s) =>
            setLocalSettings((prev) => ({
              ...prev,
              llmStrategy: s as AppSettings['llmStrategy'],
            }))
          }
        />
      </div>
    ),

    // Search & Tools — search provider + search key + GitHub token.
    search: (
      <SearchToolsSection
        searchProvider={localSettings.searchProvider}
        searchProviders={searchProviders}
        onSearchProviderChange={(v) => setLocalSettings(prev => ({ ...prev, searchProvider: v }))}
        searchKey={localSettings.apiKeySearch}
        onSearchKeyChange={(v) => setLocalSettings(prev => ({ ...prev, apiKeySearch: v }))}
        githubToken={localSettings.githubToken}
        onGithubTokenChange={(v) => setLocalSettings(prev => ({ ...prev, githubToken: v }))}
      />
    ),

    // Appearance & Language — display name + language + palette/mode.
    appearance: (
      <AppearanceSection
        language={localSettings.language}
        onLanguageChange={(code) => {
          setLocalSettings(prev => ({ ...prev, language: code }));
          i18n.changeLanguage(code);
        }}
      />
    ),

    // Access token card — token-entry / copy / reset (packaged builds).
    access: (
      <AccessTokenSettings backendStatus={backendStatus} />
    ),

    // Memory & Data — embedding config + distillation + run-debug retention.
    memory: (
      <div className="bg-surface/60 border border-border rounded-2xl p-6 space-y-6">
        <div className="flex items-center gap-2 pb-4 border-b border-border/50 select-none">
          <Database className="w-4.5 h-4.5 text-primary" />
          <h3 className="text-xs font-semibold font-mono uppercase tracking-widest text-foreground leading-none">{t('settings.navMemory')}</h3>
        </div>

        <EmbeddingSettings
          providerConfigs={providerConfigs}
          embeddingConfigId={localSettings.embeddingConfigId ?? ''}
          onEmbeddingConfigIdChange={(v) =>
            setLocalSettings((prev) => ({ ...prev, embeddingConfigId: v }))
          }
        />

        {/* Separation divider */}
        <div className="h-[1px] bg-border/40"></div>

        {/* Toggle session-end distillation */}
        <div className="flex items-center justify-between">
          <div>
            <h4 className="text-xs font-bold text-foreground font-sans">{t('settings.distill_on_session_end')}</h4>
            <p className="text-[11px] text-muted-foreground font-sans mt-0.5 max-w-xl">
              {t('settings.distill_hint')}
            </p>
          </div>
          <input
            id="settings-distill-toggle"
            type="checkbox"
            checked={localSettings.distillOnSessionEnd ?? true}
            onChange={(e) => setLocalSettings(prev => ({ ...prev, distillOnSessionEnd: e.target.checked }))}
            className="w-4 h-4 text-primary bg-background border-border rounded focus:ring-0 select-none cursor-pointer"
          />
        </div>

        {/* Separation divider */}
        <div className="h-[1px] bg-border/40"></div>

        {/* Run debug detail retention — days before boot sweep redacts sensitive/bulky run fields */}
        <div className="flex items-center justify-between">
          <div>
            <h4 className="text-xs font-bold text-foreground font-sans">运行调试详情保留天数</h4>
            <p className="text-[11px] text-muted-foreground font-sans mt-0.5 max-w-xl">
              超过此天数的 run，实际系统提示 / 注入知识 / 工具完整入参与原始返回会被自动清除（分数与耗时不受影响）。
            </p>
          </div>
          <input
            id="settings-run-debug-retention-days"
            type="number"
            min={1}
            value={localSettings.runDebugRetentionDays ?? 30}
            onChange={(e) =>
              setLocalSettings((prev) => ({
                ...prev,
                runDebugRetentionDays: Math.max(1, Number(e.target.value) || 1),
              }))
            }
            className="w-24 bg-surface border border-border-strong focus:border-primary focus:ring-1 focus:ring-ring rounded-xl px-3 py-2 text-xs text-foreground focus:outline-none transition-all font-mono"
          />
        </div>
      </div>
    ),

    // Advanced — telemetry + orchestrator shell + confirm policy + spawn mode.
    advanced: (
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
              checked={localSettings.telemetry}
              onChange={(e) => setLocalSettings(prev => ({ ...prev, telemetry: e.target.checked }))}
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
              checked={localSettings.orchestratorShellEnabled ?? false}
              onChange={(e) => setLocalSettings(prev => ({ ...prev, orchestratorShellEnabled: e.target.checked }))}
              className="w-4 h-4 text-primary bg-background border-border rounded focus:ring-0 select-none cursor-pointer"
            />
          </div>

          {/* Confirm-policy select — only meaningful when shell is enabled */}
          {localSettings.orchestratorShellEnabled && (
            <div className="flex items-center justify-between pl-4 border-l-2 border-primary/20">
              <div>
                <h4 className="text-xs font-bold text-foreground font-sans">{t('settings.labelShellConfirmPolicy')}</h4>
              </div>
              <Select
                id="settings-shell-policy"
                value={localSettings.shellConfirmPolicy}
                onChange={(v) => setLocalSettings(prev => ({ ...prev, shellConfirmPolicy: v as AppSettings['shellConfirmPolicy'] }))}
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
                Choose how sub-agents are created. Auto: instant delegation without checks. Interactive: asks user approval on the fly before spinning up new spawns.
              </p>
            </div>
            <Select
              id="settings-spawn-mode"
              value={localSettings.spawnMode}
              onChange={(v) => setLocalSettings(prev => ({ ...prev, spawnMode: v as AppSettings['spawnMode'] }))}
              options={[
                { value: 'auto', label: 'Autonomous Synthesis' },
                { value: 'interactive', label: 'Interactive Sandbox Auth' },
                { value: 'strict', label: 'Strict Static Lock' },
              ]}
              className="w-40"
              ariaLabel="Spawn synthesis mode"
            />
          </div>
        </div>
      </div>
    ),
  };

  return (
    <div className="flex-1 overflow-y-auto bg-background p-8 select-none relative">
      {/* Decorative Blur Ambient Lights */}
      <div className="absolute bottom-0 left-1/4 w-[30rem] h-[30rem] bg-primary/[0.01] blur-[120px] rounded-full pointer-events-none"></div>

      {/* Header bar */}
      <div className="mb-8">
        <h1 className="text-xl font-bold text-foreground tracking-tight font-sans">System Diagnostics & Configuration</h1>
        <p className="text-xs text-subtle-foreground font-sans mt-1">
          Calibrate the neural orchestrator core, assign LLM credential keys, and configure telemetry parameters.
        </p>
      </div>

      {/* Backend-down honest banner — shown when health check fails */}
      {backendStatus === 'offline' && (
        <div className="max-w-6xl mb-6 flex items-start gap-3 bg-danger/30 border border-danger/50 rounded-xl px-5 py-4">
          <WifiOff className="w-4 h-4 text-danger shrink-0 mt-0.5" />
          <div>
            <p className="text-xs font-bold text-danger font-mono uppercase tracking-wide">
              后端未连接 / Backend not connected
            </p>
            <p className="text-[11px] text-danger/80 font-sans mt-1 leading-relaxed">
              Settings could not be loaded from the server. Displaying defaults — do not treat these values as real configuration. Save is disabled until the backend is reachable.
            </p>
          </div>
        </div>
      )}

      <form onSubmit={handleSave} className="max-w-6xl space-y-8">
        <SettingsShell activeSection={activeSection} onSectionChange={setActiveSection}>
          {sections}
        </SettingsShell>

        {/* Footer actions bar */}
        <div className="flex select-none items-center justify-between pt-4 border-t border-border/60 text-[10.5px] font-mono text-subtle-foreground">
          <div className="flex items-center gap-1.5 matches">
            {saveError ? (
              <>
                <AlertCircle className="w-4 h-4 text-danger" />
                <span className="text-danger">{saveError}</span>
              </>
            ) : (
              <>
                <Info className="w-4 h-4 text-subtle-foreground" />
                <span>Diagnostics confirm hardware configurations match system boundaries.</span>
              </>
            )}
          </div>

          <button
            id="settings-save-button"
            type="submit"
            disabled={backendStatus === 'offline'}
            className={`px-4 py-2 text-xs font-bold font-sans uppercase rounded-lg transition-all flex items-center gap-1.5 ${
              backendStatus === 'offline'
                ? 'bg-surface-raised text-subtle-foreground cursor-not-allowed opacity-50'
                : isSaved
                  ? 'bg-success text-white'
                  : 'bg-primary hover:bg-primary-hover text-primary-foreground shadow-lg shadow-primary/10'
            }`}
          >
            {isSaved ? <Check className="w-4 h-4 text-white" /> : <Save className="w-4 h-4" />}
            {isSaved ? t('settings.btnSaving') : t('settings.btnSave')}
          </button>
        </div>

      </form>
    </div>
  );
}
