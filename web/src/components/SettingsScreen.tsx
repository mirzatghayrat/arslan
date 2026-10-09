import React, { useState, useEffect } from 'react';

import type { CryptoHealth } from '../lib/cryptoHealth';
import { useTranslation } from 'react-i18next';
import { AppSettings } from '../types';
import { api } from '../api/client';
import type { ProviderOption, ProviderConfig } from '../api/client.types';
import type { BackendStatus } from '../hooks/useBackendStatus';
import {
  Check, Loader2,
  Info, AlertCircle, WifiOff
} from 'lucide-react';
import ProviderConfigList from './ProviderConfigList';
import AccessTokenSettings from './AccessTokenSettings';
import SettingsShell from './settings/SettingsShell';
import SearchToolsSection from './settings/SearchToolsSection';
import ModelRolesSection from './settings/ModelRolesSection';
import AppearanceSection from './settings/AppearanceSection';
import MemoryDataSection from './settings/MemoryDataSection';
import AdvancedSection from './settings/AdvancedSection';
import { SETTINGS_SECTIONS, resolveSection, type SettingsSectionId } from './settings/sectionRegistry';
import { SettingsGroup, SectionIntro } from './settings/SettingsGroup';
import AboutSection from './settings/AboutSection';
import type { AdvancedBlock } from './settings/AdvancedSection';
import type { MemoryBlock } from './settings/MemoryDataSection';
import { useDebouncedSettingsSave } from '../hooks/useDebouncedSettingsSave';
import AutomationSection from './settings/AutomationSection';
import DesktopSection from './settings/DesktopSection';
import HandsSection from './settings/HandsSection';
import PhoneSection from './settings/PhoneSection';
import ProactiveSection from './settings/ProactiveSection';
import { normalizeLanguage } from '../lib/languages';

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
  /** Deep-link: which section opens first (defaults to 'models'). */
  /** A section id — including one from before 0.1.55 (mapped to its new home). */
  initialSection?: SettingsSectionId | string;
  /** Automation points at Diagnostics for scheduled tasks and usage — the two
   *  placeholder nav entries it replaced did the same, but as dead tabs. */
  onOpenActivity?: () => void;
  onBack?: () => void;
}

export default function SettingsScreen({ settings, setSettings, llmProviders, searchProviders, backendStatus, providerConfigs = [], onProviderConfigsChange, initialSection, onOpenActivity, onBack }: SettingsScreenProps) {
  const { t, i18n } = useTranslation();
  const [localSettings, setLocalSettings] = useState<AppSettings>({ ...settings });
  const [activeSection, setActiveSection] = useState<SettingsSectionId>(resolveSection(initialSection) ?? 'general');
  // A failed save rolls localSettings back. Keep the visible language aligned
  // with that rollback rather than caching an unsaved language until reload.
  useEffect(() => {
    const language = normalizeLanguage(localSettings.language);
    if (i18n?.language && normalizeLanguage(i18n.language) !== language) {
      void i18n.changeLanguage(language);
    }
  }, [localSettings.language, i18n]);
  // The crypto diagnosis. Starts null and STAYS null on failure: a notice is only
  // shown when the backend actually said something is wrong. Guessing while the
  // request is in flight would put a data-loss warning on every cold start.
  const [cryptoHealth, setCryptoHealth] = useState<CryptoHealth | null>(null);

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
    let live = true;
    // Optional-chained and caught: this endpoint is BEST EFFORT. A frontend newer
    // than its backend gets a 404 here, and Settings must still render — a missing
    // diagnosis shows no notice, which is exactly right, whereas a screen that
    // cannot open without it turns a nice-to-have into a hard dependency.
    void api.getCryptoHealth?.()
      .then((h) => { if (live) setCryptoHealth(h); })
      .catch(() => { /* stay null — no diagnosis is better than a guessed one */ });
    return () => { live = false; };
  }, []);

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
  // 0.1.55 §11: eleven sections → seven. The controls, handlers, ids and save paths are
  // unchanged — only where each one lives. Groups inside a section give it a shape.
  const intro = (id: SettingsSectionId) => {
    const meta = SETTINGS_SECTIONS.find((s) => s.id === id)!;
    return <SectionIntro title={t(meta.labelKey)} hint={t(meta.hintKey ?? '')} />;
  };
  const advanced = (only: AdvancedBlock[]) => <AdvancedSection
        telemetry={localSettings.telemetry}
        onTelemetryChange={(v) => saveField({ telemetry: v })}
        orchestratorShellEnabled={localSettings.orchestratorShellEnabled ?? true}
        onOrchestratorShellChange={(v) => saveField({ orchestratorShellEnabled: v })}
        shellConfirmPolicy={localSettings.shellConfirmPolicy}
        onShellConfirmPolicyChange={(v) => saveField({ shellConfirmPolicy: v })}
        terminalSandboxEnabled={localSettings.terminalSandboxEnabled ?? true}
        onTerminalSandboxChange={(v) => saveField({ terminalSandboxEnabled: v })}
        backgroundJobBudget={localSettings.backgroundJobBudget ?? 'standard'}
        onBackgroundJobBudgetChange={(v) => saveField({ backgroundJobBudget: v })}
        workspaceDir={localSettings.workspaceDir ?? ''}
        onWorkspaceDirChange={(v) => saveField({ workspaceDir: v })}
        lanDiscoveryEnabled={localSettings.lanDiscoveryEnabled ?? false}
        onLanDiscoveryChange={(v) => saveField({ lanDiscoveryEnabled: v })}
        defaultReadEnabled={localSettings.defaultReadEnabled ?? true}
        onDefaultReadChange={(v) => saveField({ defaultReadEnabled: v })}
        voiceInputLocale={localSettings.voiceInputLocale ?? ''}
        onVoiceInputLocaleChange={(v) => saveField({ voiceInputLocale: v })}
        voiceMode={localSettings.voiceMode ?? 'push_to_talk'}
        onVoiceModeChange={(v) => saveField({ voiceMode: v })}
        voiceEndpointSilenceMs={localSettings.voiceEndpointSilenceMs ?? 900}
        onVoiceEndpointSilenceChange={(v) => saveField({ voiceEndpointSilenceMs: v })}
        sshEnabled={localSettings.sshEnabled ?? false}
        onSshChange={(v) => saveField({ sshEnabled: v })}
        bare only={only}
      />;
  const desktop = (only: ('keepAwake' | 'notifications' | 'island')[]) => <DesktopSection
          keepAwakeEnabled={localSettings.keepAwakeEnabled ?? true}
          onKeepAwakeChange={(v) => saveField({ keepAwakeEnabled: v })}
          notificationsEnabled={localSettings.desktopNotificationsEnabled ?? true}
          onNotificationsChange={(v) => saveField({ desktopNotificationsEnabled: v })}
          islandEnabled={localSettings.islandEnabled ?? true}
          onIslandChange={(v) => saveField({ islandEnabled: v })}
        bare only={only}
      />;
  const memoryData = (only: MemoryBlock[]) => <MemoryDataSection
        providerConfigs={providerConfigs}
        embeddingConfigId={localSettings.embeddingConfigId ?? ''}
        onEmbeddingConfigIdChange={(v) => saveField({ embeddingConfigId: v })}
        distillOnSessionEnd={localSettings.distillOnSessionEnd ?? true}
        onDistillChange={(v) => saveField({ distillOnSessionEnd: v })}
        retentionDays={localSettings.runDebugRetentionDays ?? 30}
        onRetentionDaysChange={(v) => saveField({ runDebugRetentionDays: v })}
        memoryInConversations={localSettings.memoryInConversations ?? true}
        onMemoryInConversationsChange={(v) => saveField({ memoryInConversations: v })}
        learnedPracticesTakeEffect={localSettings.learnedPracticesTakeEffect ?? true}
        onLearnedPracticesChange={(v) => saveField({ learnedPracticesTakeEffect: v })}
        bare only={only}
      />;
  const sections: Partial<Record<SettingsSectionId, React.ReactNode>> = {
    general: (
      <div className="space-y-6" data-testid="settings-general">
        {intro('general')}
      <AppearanceSection
        language={localSettings.language}
        onLanguageChange={(code) => {
          // Language must persist before a quick Back navigation unmounts this
          // screen and cancels its debounce timer. Only this non-secret patch
          // is flushed; unblurred keys remain excluded by the save hook.
          i18n.changeLanguage(code);
          flushField({ language: code });
        }}
        ocrLanguages={localSettings.ocrLanguages ?? ''}
        onOcrLanguagesChange={(next) => saveField({ ocrLanguages: next })}
      />
        <SettingsGroup title={t('settings.grpNotifications')}>
          {desktop(['notifications'])}
          <div className="mt-5"><ProactiveSection bare only={['notify']} /></div>
        </SettingsGroup>
        <SettingsGroup title={t('settings.grpOnMac')}>{desktop(['island', 'keepAwake'])}</SettingsGroup>
        {/* 0.1.58 §1: raw tool data under a reply's steps — off for everyone who does not ask. */}
        <SettingsGroup title={t('process.convGroup')}>
          <div className="flex items-start justify-between gap-4">
            <div>
              <h4 className="text-[13px] font-medium text-foreground">{t('process.techTitle')}</h4>
              <p className="text-[12px] leading-snug text-muted-foreground mt-0.5 max-w-xl">{t('process.techBody')}</p>
            </div>
            <input id="settings-technical-details" data-testid="settings-technical-details" type="checkbox"
              checked={localSettings.showTechnicalDetails ?? false}
              onChange={(e) => saveField({ showTechnicalDetails: e.target.checked })} className="kit-switch mt-0.5" />
          </div>
        </SettingsGroup>
        <SettingsGroup title={t('settings.grpVoice')}>{advanced(['voice'])}</SettingsGroup>
      </div>
    ),
    models: (
      <div className="space-y-6">
        {/* No intro here: the provider list carries the page title beside its Add button. */}
      <section className="space-y-5" aria-labelledby="settings-models-title">
        <ProviderConfigList
          startCollapsed
          llmProviders={llmProviders}
          providerConfigs={providerConfigs}
          onConfigsChange={(updated) => onProviderConfigsChange?.(updated)}
          strategy={localSettings.llmStrategy}
          onStrategyChange={(s) =>
            saveField({ llmStrategy: s as AppSettings['llmStrategy'] })
          }
        />
      </section>
      <ModelRolesSection
        values={{
          synthesisConfigId: localSettings.synthesisConfigId ?? '',
          compactionConfigId: localSettings.compactionConfigId ?? '',
          titleConfigId: localSettings.titleConfigId ?? '',
          routerConfigId: localSettings.routerConfigId ?? '',
          visionConfigId: localSettings.visionConfigId ?? '',
        }}
        onChange={(key, v) => saveField({ [key]: v } as Partial<AppSettings>)}
        providerConfigs={providerConfigs ?? []}
        strategy={localSettings.llmStrategy ?? 'single'}
        // Without this the "no models configured yet" line is a dead end: it
        // names the problem and offers nothing to do about it.
        onGoToProviders={() => setActiveSection('models')}
      />
        <SettingsGroup>{memoryData(['embedding'])}</SettingsGroup>
      </div>
    ),
    abilities: (
      <div className="space-y-6" data-testid="settings-abilities">
        {intro('abilities')}
        <SettingsGroup title={t('settings.grpFiles')}>{advanced(['defaultRead', 'workspace'])}</SettingsGroup>
        <SettingsGroup title={t('settings.grpTerminal')}>{advanced(['terminal'])}</SettingsGroup>
        <SettingsGroup title={t('settings.grpApps')}>
          <HandsSection />
          <div className="mt-5">{advanced(['browser'])}</div>
        </SettingsGroup>
        <SettingsGroup title={t('settings.grpOtherComputers')}>{advanced(['lan', 'ssh'])}</SettingsGroup>
      </div>
    ),
    background: (
      <div className="space-y-6" data-testid="settings-background">
        {intro('background')}
        <SettingsGroup title={t('settings.grpLookingOut')} note={t('settings.watchesInInbox')}>
          <ProactiveSection bare only={['looking', 'brief']} />
        </SettingsGroup>
        <SettingsGroup title={t('settings.grpSpends')}>
      <AutomationSection
        curationEnabled={localSettings.curationEnabled ?? false}
        onCurationEnabledChange={(v) => saveField({ curationEnabled: v })}
        researchReviewEnabled={localSettings.researchReviewEnabled ?? false}
        onResearchReviewEnabledChange={(v) => saveField({ researchReviewEnabled: v })}
        heartbeatEnabled={localSettings.heartbeatEnabled ?? false}
        onHeartbeatEnabledChange={(v) => saveField({ heartbeatEnabled: v })}
        heartbeatChecklist={localSettings.heartbeatChecklist ?? ''}
        onHeartbeatChecklistChange={(v) => saveField({ heartbeatChecklist: v })}
        onOpenActivity={onOpenActivity}
      />
        </SettingsGroup>
        <SettingsGroup title={t('settings.grpJobs')}>{advanced(['budget'])}</SettingsGroup>
        <SettingsGroup title={t('projectsUI.settingsGroup')}>
          <label className="flex items-start justify-between gap-4" data-testid="settings-projects-auto">
            <span>
              <span className="block text-[13px] font-medium text-foreground">{t('projectsUI.settingsAuto')}</span>
              <span className="mt-0.5 block max-w-xl text-[12px] leading-snug text-muted-foreground">{t('projectsUI.settingsAutoDesc')}</span>
            </span>
            <input type="checkbox" className="kit-switch mt-0.5" data-testid="projects-auto-toggle"
              checked={localSettings.projectsAutoAdvance ?? false}
              onChange={(e) => saveField({ projectsAutoAdvance: e.target.checked })} />
          </label>
        </SettingsGroup>
      </div>
    ),
    memory: (
      <div className="space-y-6">
        {intro('memory')}
        <SettingsGroup title={t('settings.grpRemember')}>{memoryData(['remember', 'practices', 'distill'])}</SettingsGroup>
        <SettingsGroup title={t('settings.grpData')}>
          {memoryData(['data', 'retention'])}
          <div className="mt-5">{advanced(['telemetry'])}</div>
        </SettingsGroup>
      </div>
    ),
    connections: (
      <div className="space-y-6" data-testid="settings-connections">
        {intro('connections')}
        <SettingsGroup title={t('settings.grpPhone')}><PhoneSection enabled={localSettings.phoneBridgeEnabled ?? false}
      onEnabledChange={(v) => saveField({ phoneBridgeEnabled: v })} /></SettingsGroup>
        <SettingsGroup title={t('settings.grpSearch')}>
      <SearchToolsSection
        cryptoHealth={cryptoHealth}
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
        searchBaseUrl={localSettings.searchBaseUrl}
        onSearchBaseUrlChange={(v) => saveField({ searchBaseUrl: v })}
      />
        </SettingsGroup>
        <SettingsGroup title={t('settings.grpAccess')}>
      <AccessTokenSettings
        backendStatus={backendStatus}
        mcpServerEnabled={localSettings.mcpServerEnabled ?? false}
        onMcpServerChange={(v) => saveField({ mcpServerEnabled: v })}
      />
        </SettingsGroup>
      </div>
    ),
    about: (
      <div className="space-y-6">
        {intro('about')}
        <AboutSection onOpenActivity={onOpenActivity} />
      </div>
    ),
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-background select-none relative">
      {/* Header bar */}
      <div className="sr-only">
        {/* Was a hardcoded English string naming the Diagnostics screen — wrong
            twice over: untranslatable, and describing a different page than the
            one it sat on. The old wording is deliberately not quoted here: the
            guard for this greps the source, and unlike the backend's AST guard
            it cannot tell a comment from a rendered string. A strict guard that
            costs one reworded comment is the better trade. */}
        <h1 className="sr-only">{t('settings.pageTitle')}</h1>
        <p className="text-xs text-muted-foreground font-sans mt-1.5 leading-relaxed">
          {t('settings.headerLore')}
        </p>
      </div>

      {/* Backend-down honest banner — shown when health check fails */}
      {backendStatus === 'offline' && (
        <div className="mx-4 mt-3 shrink-0 max-w-6xl flex items-start gap-3 bg-danger/30 border border-danger/50 rounded-xl px-5 py-3">
          <WifiOff className="w-4 h-4 text-danger shrink-0 mt-0.5" />
          <div>
            <p className="text-xs font-bold text-danger font-mono uppercase tracking-wide">
              {t('ledger.empty_backend_offline')}
            </p>
            <p className="text-[11px] text-danger/80 font-sans mt-1 leading-relaxed">
              {t('settings.offlineBody')}
            </p>
          </div>
        </div>
      )}

      <div className="flex min-h-0 flex-1 flex-col">
        <SettingsShell activeSection={activeSection} onSectionChange={setActiveSection} onBack={onBack}>
          {sections}
        </SettingsShell>

        {/* Footer status bar — the global auto-save indicator (no Save button:
            settings persist instantly per field). */}
        <div className="flex shrink-0 select-none items-center gap-1.5 px-3 py-2 border-t border-border/60 text-[10.5px] font-sans text-subtle-foreground">
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
