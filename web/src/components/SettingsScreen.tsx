import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { AppSettings } from '../types';
import type { ProviderOption, ProviderConfig } from '../api/client.types';
import type { BackendStatus } from '../hooks/useBackendStatus';
import {
  Sliders, Check, Loader2,
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
import { useDebouncedSettingsSave } from '../hooks/useDebouncedSettingsSave';

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
  const [activeSection, setActiveSection] = useState<SettingsSectionId>(initialSection ?? 'providers');

  // ── Persistence (Task 6) ───────────────────────────────────────────────────
  // Instant auto-save replaces the old top Save button + <form onSubmit>.
  // Non-key fields debounce through saveField; the two key-type fields (search
  // key / GitHub token) persist on BLUR only via flushField (user's constraint).
  // While offline the change is buffered and flushed on reconnect; the optimistic
  // display still updates so controls stay live.
  const { saveField, editKeyField, flushField, getEditingKeyFields, status: saveStatus, error: saveError } =
    useDebouncedSettingsSave({
      settings: localSettings,
      setLocalSettings,
      // Merge only the fields the hook actually persisted (a patch) so a masked
      // key never round-trips back through the parent onto a field the user is
      // still editing.
      onPersisted: (patch) => setSettings((prev) => ({ ...prev, ...patch })),
      enabled: backendStatus !== 'offline',
    });

  // Sync local form when parent settings update (e.g. after initial backend fetch),
  // but never clobber a key field the user is actively editing — that would revert
  // an in-progress secret back to its mask when a background save resolves.
  useEffect(() => {
    setLocalSettings((prev) => {
      const next: AppSettings = { ...prev, ...settings };
      const mutableNext = next as unknown as Record<string, unknown>;
      const prevRec = prev as unknown as Record<string, unknown>;
      for (const f of getEditingKeyFields()) {
        mutableNext[f as string] = prevRec[f as string];
      }
      return next;
    });
  }, [settings, getEditingKeyFields]);

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
            saveField({ llmStrategy: s as AppSettings['llmStrategy'] })
          }
        />
      </div>
    ),

    // Search & Tools — search provider + search key + GitHub token.
    search: (
      <SearchToolsSection
        searchProvider={localSettings.searchProvider}
        searchProviders={searchProviders}
        onSearchProviderChange={(v) => saveField({ searchProvider: v })}
        searchKey={localSettings.apiKeySearch}
        // Key-type field: onChange updates the display value only + marks dirty
        // (no save); the value persists on blur via flushField, and ONLY if the
        // user actually edited it (an unedited tab-through blur is a no-op).
        onSearchKeyChange={(v) => editKeyField('apiKeySearch', v)}
        onSearchKeyBlur={(v) => flushField({ apiKeySearch: v })}
        githubToken={localSettings.githubToken}
        onGithubTokenChange={(v) => editKeyField('githubToken', v)}
        onGithubTokenBlur={(v) => flushField({ githubToken: v })}
      />
    ),

    // Appearance & Language — display name + language + palette/mode.
    appearance: (
      <AppearanceSection
        language={localSettings.language}
        onLanguageChange={(code) => {
          // i18n switches immediately; the PERSIST is debounced through the hook.
          i18n.changeLanguage(code);
          saveField({ language: code });
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
        onEmbeddingConfigIdChange={(v) => saveField({ embeddingConfigId: v })}
        distillOnSessionEnd={localSettings.distillOnSessionEnd ?? true}
        onDistillChange={(v) => saveField({ distillOnSessionEnd: v })}
        retentionDays={localSettings.runDebugRetentionDays ?? 30}
        onRetentionDaysChange={(v) => saveField({ runDebugRetentionDays: v })}
      />
    ),

    // Advanced — telemetry + orchestrator shell + confirm policy + spawn mode.
    advanced: (
      <AdvancedSection
        telemetry={localSettings.telemetry}
        onTelemetryChange={(v) => saveField({ telemetry: v })}
        orchestratorShellEnabled={localSettings.orchestratorShellEnabled ?? false}
        onOrchestratorShellChange={(v) => saveField({ orchestratorShellEnabled: v })}
        shellConfirmPolicy={localSettings.shellConfirmPolicy}
        onShellConfirmPolicyChange={(v) => saveField({ shellConfirmPolicy: v })}
        spawnMode={localSettings.spawnMode}
        onSpawnModeChange={(v) => saveField({ spawnMode: v })}
        mcpServerEnabled={localSettings.mcpServerEnabled ?? false}
        onMcpServerChange={(v) => saveField({ mcpServerEnabled: v })}
        evolutionAuto={localSettings.evolutionAuto ?? false}
        onEvolutionAutoChange={(v) => saveField({ evolutionAuto: v })}
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

      <div className="max-w-6xl space-y-8">
        <SettingsShell activeSection={activeSection} onSectionChange={setActiveSection}>
          {sections}
        </SettingsShell>

        {/* Footer status bar — the global auto-save indicator (no Save button:
            settings persist instantly per field). */}
        <div className="flex select-none items-center gap-1.5 pt-4 border-t border-border/60 text-[10.5px] font-mono text-subtle-foreground">
          {saveStatus === 'error' ? (
            <>
              <AlertCircle className="w-4 h-4 text-danger" />
              <span className="text-danger">{saveError ?? t('settings.saveFailed')}</span>
            </>
          ) : saveStatus === 'saving' ? (
            <>
              <Loader2 className="w-4 h-4 text-subtle-foreground animate-spin" />
              <span>{t('settings.savingLabel')}</span>
            </>
          ) : saveStatus === 'saved' ? (
            <span id="settings-saved-tick" className="flex items-center gap-1.5 text-success">
              <Check className="w-4 h-4" />
              {t('settings.savedTick')}
            </span>
          ) : (
            <>
              <Info className="w-4 h-4 text-subtle-foreground" />
              <span>{t('settings.footerNote')}</span>
            </>
          )}
        </div>

      </div>
    </div>
  );
}
