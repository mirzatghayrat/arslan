import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { AppSettings } from '../types';
import type { ProviderOption, ProviderConfig } from '../api/client.types';
import type { BackendStatus } from '../hooks/useBackendStatus';
import { api } from '../api/client';
import { toBackendSettings } from '../api/adapters';
import {
  Sliders, Check, Save,
  Info, AlertCircle, WifiOff
} from 'lucide-react';
import ProviderConfigList from './ProviderConfigList';
import AccessTokenSettings from './AccessTokenSettings';
import SettingsShell from './settings/SettingsShell';
import SearchToolsSection from './settings/SearchToolsSection';
import AppearanceSection from './settings/AppearanceSection';
import MemoryDataSection from './settings/MemoryDataSection';
import AdvancedSection from './settings/AdvancedSection';
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
      <MemoryDataSection
        providerConfigs={providerConfigs}
        embeddingConfigId={localSettings.embeddingConfigId ?? ''}
        onEmbeddingConfigIdChange={(v) =>
          setLocalSettings((prev) => ({ ...prev, embeddingConfigId: v }))
        }
        distillOnSessionEnd={localSettings.distillOnSessionEnd ?? true}
        onDistillChange={(v) => setLocalSettings((prev) => ({ ...prev, distillOnSessionEnd: v }))}
        retentionDays={localSettings.runDebugRetentionDays ?? 30}
        onRetentionDaysChange={(v) => setLocalSettings((prev) => ({ ...prev, runDebugRetentionDays: v }))}
      />
    ),

    // Advanced — telemetry + orchestrator shell + confirm policy + spawn mode.
    advanced: (
      <AdvancedSection
        telemetry={localSettings.telemetry}
        onTelemetryChange={(v) => setLocalSettings((prev) => ({ ...prev, telemetry: v }))}
        orchestratorShellEnabled={localSettings.orchestratorShellEnabled ?? false}
        onOrchestratorShellChange={(v) => setLocalSettings((prev) => ({ ...prev, orchestratorShellEnabled: v }))}
        shellConfirmPolicy={localSettings.shellConfirmPolicy}
        onShellConfirmPolicyChange={(v) => setLocalSettings((prev) => ({ ...prev, shellConfirmPolicy: v }))}
        spawnMode={localSettings.spawnMode}
        onSpawnModeChange={(v) => setLocalSettings((prev) => ({ ...prev, spawnMode: v }))}
      />
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
          {t('settings.headerLore')}
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
                <span>{t('settings.footerNote')}</span>
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
