import React, { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { CatalogEntry, ModelInfo, ModelListResult, ProviderOption, ProviderConfig, SuggestPrimaryResult } from '../api/client.types';
import {
  addProviderConfig,
  updateProviderConfig,
  setPrimaryProviderConfig,
  deleteProviderConfig,
  suggestPrimary,
  getCatalog,
  fetchProviderModels,
  testLlm,
  testProviderConfig,
} from '../api/client';
import type { TestLlmResult } from '../api/client';
import { Plus, Star, Trash2, Loader2, FlaskConical, ChevronDown } from 'lucide-react';
import Select from './Select';
import type { SelectOption } from './Select';
import ModelCombobox from './ModelCombobox';

interface ProviderConfigListProps {
  llmProviders: ProviderOption[];
  providerConfigs: ProviderConfig[];
  /** Called after any mutation so the parent can refresh the list. */
  onConfigsChange: (updated: ProviderConfig[]) => void;
  /** Current routing strategy (default "single"). */
  strategy?: string;
  /** Called when the user picks a different strategy. */
  onStrategyChange?: (strategy: string) => void;
}

const INPUT_CLS =
  'w-full bg-background border border-border focus:border-primary/50 focus:ring-1 focus:ring-primary/20 rounded-xl px-3 py-2 text-xs text-foreground placeholder-subtle-foreground focus:outline-none transition-all font-mono';

/** Draft state for the add-new flow */
interface DraftConfig {
  provider: string;
  model: string;
  base_url: string;
  api_key: string;
  testState: 'idle' | 'testing' | 'ok' | 'failed';
  testError?: string;
}

/** Test status per saved config id */
type TestStatusMap = Record<
  number,
  { state: 'idle' | 'testing' | 'ok' | 'failed'; error?: string }
>;

/** Dynamic model list state per saved config id (lazy, fetched on first focus). */
type RowModelsMap = Record<number, { loading: boolean; result: ModelListResult | null }>;

/** Tiny relative-time helper (minutes/hours/days). `iso` is naive-UTC without
 *  a timezone suffix — append "Z" before parsing so it isn't read as local. */
function formatRelativeTime(
  iso: string,
  t: (key: string, opts?: Record<string, unknown>) => string,
): string {
  const hasTz = iso.endsWith('Z') || /[+-]\d{2}:?\d{2}$/.test(iso);
  const then = new Date(hasTz ? iso : `${iso}Z`).getTime();
  if (Number.isNaN(then)) return iso;
  const mins = Math.floor((Date.now() - then) / 60_000);
  if (mins < 1) return t('settings.timeJustNow');
  if (mins < 60) return t('settings.timeMinutesAgo', { n: mins });
  const hours = Math.floor(mins / 60);
  if (hours < 24) return t('settings.timeHoursAgo', { n: hours });
  return t('settings.timeDaysAgo', { n: Math.floor(hours / 24) });
}

export default function ProviderConfigList({
  llmProviders,
  providerConfigs,
  onConfigsChange,
  strategy = 'single',
  onStrategyChange,
}: ProviderConfigListProps) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState<number | null>(null);
  const [suggestion, setSuggestion] = useState<SuggestPrimaryResult | null>(null);
  const [suggestBusy, setSuggestBusy] = useState(false);
  const [catalog, setCatalog] = useState<CatalogEntry[]>([]);
  const [catalogOpen, setCatalogOpen] = useState(false);
  const [testStatus, setTestStatus] = useState<TestStatusMap>({});
  const [draft, setDraft] = useState<DraftConfig | null>(null);
  const [testAllBusy, setTestAllBusy] = useState(false);
  const [rowModels, setRowModels] = useState<RowModelsMap>({});
  // Rows whose dynamic model list was already requested (fetch once per row).
  const modelsFetchedRef = useRef<Set<number>>(new Set());
  // Rows with base_url edits pending a blur-save.
  const baseUrlDirtyRef = useRef<Set<number>>(new Set());

  useEffect(() => {
    getCatalog().then(setCatalog).catch(() => setCatalog([]));
  }, []);

  // --- helpers ---

  const modelsFor = (providerKey: string): string[] =>
    llmProviders.find((p) => p.key === providerKey)?.models ?? [];

  const defaultModelFor = (providerKey: string): string =>
    llmProviders.find((p) => p.key === providerKey)?.default_model ?? '';

  const baseUrlFor = (providerKey: string): string =>
    llmProviders.find((p) => p.key === providerKey)?.base_url ?? '';

  const isNative = (providerKey: string): boolean =>
    llmProviders.find((p) => p.key === providerKey)?.native ?? false;

  /** Static seed models (from the provider preset) shaped as ModelInfo. */
  const staticModelInfos = (providerKey: string): ModelInfo[] =>
    modelsFor(providerKey).map((m) => ({
      id: m,
      display_name: null,
      context_window: null,
      capabilities: [],
      source: 'static',
    }));

  // --- dynamic model lists (lazy per row) ---

  const loadModels = async (id: number, refresh = false) => {
    setRowModels((prev) => ({
      ...prev,
      [id]: { loading: true, result: prev[id]?.result ?? null },
    }));
    try {
      const result = await fetchProviderModels(id, refresh);
      setRowModels((prev) => ({ ...prev, [id]: { loading: false, result } }));
    } catch {
      setRowModels((prev) => ({
        ...prev,
        [id]: { loading: false, result: prev[id]?.result ?? null },
      }));
    }
  };

  /** Fetch a row's dynamic model list the first time its combobox is focused. */
  const ensureModelsLoaded = (id: number) => {
    if (modelsFetchedRef.current.has(id)) return;
    modelsFetchedRef.current.add(id);
    void loadModels(id, false);
  };

  /** Combobox options for a saved row: dynamic list when non-empty, else seed. */
  const optionsForRow = (config: ProviderConfig): ModelInfo[] => {
    const result = rowModels[config.id]?.result;
    if (result && result.models.length > 0) return result.models;
    return staticModelInfos(config.provider);
  };

  /** Inline hint under the model field when the served list is stale. */
  const staleHintFor = (config: ProviderConfig): string | undefined => {
    const result = rowModels[config.id]?.result;
    if (!result || !result.stale) return undefined;
    if (result.fetched_at) {
      const rel = formatRelativeTime(result.fetched_at, t);
      const updated = t('settings.modelLastUpdated', { time: rel });
      return result.error ? `${updated} · ${t('settings.modelRefreshFailed')}` : updated;
    }
    // Pure static fallback (never fetched successfully).
    return t('settings.modelStaticFallback');
  };

  /** Ollama daemon-down empty state: dynamic list empty + error present. */
  const showOllamaHint = (config: ProviderConfig): boolean => {
    if (config.provider !== 'ollama') return false;
    const result = rowModels[config.id]?.result;
    return !!result && result.models.length === 0 && result.error != null;
  };

  // --- mutations ---

  const handleSetPrimary = async (id: number) => {
    setBusy(id);
    try {
      await setPrimaryProviderConfig(id);
      const updated = providerConfigs.map((c) => ({ ...c, is_primary: c.id === id }));
      onConfigsChange(updated);
    } finally {
      setBusy(null);
    }
  };

  const handleDelete = async (id: number) => {
    setBusy(id);
    try {
      await deleteProviderConfig(id);
      onConfigsChange(providerConfigs.filter((c) => c.id !== id));
      // Clear test status for deleted row
      setTestStatus((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
    } finally {
      setBusy(null);
    }
  };

  const handleFieldChange = async (
    config: ProviderConfig,
    field: 'provider' | 'model' | 'api_key',
    value: string,
  ) => {
    let patch: Partial<ProviderConfig> = { [field]: value };
    if (field === 'provider') {
      patch.model = defaultModelFor(value);
      patch.base_url = baseUrlFor(value);
    }
    const optimistic = providerConfigs.map((c) =>
      c.id === config.id ? { ...c, ...patch } : c,
    );
    onConfigsChange(optimistic);
    // Clear test status since config changed
    setTestStatus((prev) => ({ ...prev, [config.id]: { state: 'idle' } }));
    try {
      await updateProviderConfig(config.id, patch);
    } catch {
      onConfigsChange(providerConfigs);
    }
  };

  /** Local-only (optimistic) edit — no network. Used by blur-saved fields. */
  const handleLocalFieldChange = (
    config: ProviderConfig,
    field: 'base_url',
    value: string,
  ) => {
    baseUrlDirtyRef.current.add(config.id);
    onConfigsChange(
      providerConfigs.map((c) => (c.id === config.id ? { ...c, [field]: value } : c)),
    );
  };

  /** Persist base_url on blur only (never per-keystroke). */
  const handleBaseUrlBlur = async (config: ProviderConfig, value: string) => {
    if (!baseUrlDirtyRef.current.has(config.id)) return;
    baseUrlDirtyRef.current.delete(config.id);
    setTestStatus((prev) => ({ ...prev, [config.id]: { state: 'idle' } }));
    try {
      await updateProviderConfig(config.id, { base_url: value });
    } catch {
      // Keep the optimistic value; the next successful save will reconcile.
    }
  };

  const handleTestSaved = async (id: number) => {
    setTestStatus((prev) => ({ ...prev, [id]: { state: 'testing' } }));
    try {
      const result: TestLlmResult = await testProviderConfig(id);
      if (result.ok) {
        setTestStatus((prev) => ({ ...prev, [id]: { state: 'ok' } }));
      } else {
        setTestStatus((prev) => ({
          ...prev,
          [id]: { state: 'failed', error: result.error ?? 'Test failed' },
        }));
      }
    } catch (err) {
      setTestStatus((prev) => ({
        ...prev,
        [id]: { state: 'failed', error: err instanceof Error ? err.message : 'Test failed' },
      }));
    }
  };

  const handleTestAll = async () => {
    if (providerConfigs.length === 0) return;
    setTestAllBusy(true);
    // Set all to 'testing' first
    setTestStatus((prev) => {
      const next = { ...prev };
      for (const c of providerConfigs) {
        next[c.id] = { state: 'testing' };
      }
      return next;
    });
    await Promise.all(
      providerConfigs.map(async (c) => {
        try {
          const result: TestLlmResult = await testProviderConfig(c.id);
          if (result.ok) {
            setTestStatus((prev) => ({ ...prev, [c.id]: { state: 'ok' } }));
          } else {
            setTestStatus((prev) => ({
              ...prev,
              [c.id]: { state: 'failed', error: result.error ?? 'Test failed' },
            }));
          }
        } catch (err) {
          setTestStatus((prev) => ({
            ...prev,
            [c.id]: { state: 'failed', error: err instanceof Error ? err.message : 'Test failed' },
          }));
        }
      }),
    );
    setTestAllBusy(false);
  };

  const handleSuggest = async () => {
    setSuggestBusy(true);
    try {
      const result = await suggestPrimary();
      setSuggestion(result);
    } finally {
      setSuggestBusy(false);
    }
  };

  const handleUseThis = async () => {
    if (!suggestion) return;
    setBusy(suggestion.id);
    try {
      await setPrimaryProviderConfig(suggestion.id);
      const updated = providerConfigs.map((c) => ({ ...c, is_primary: c.id === suggestion.id }));
      onConfigsChange(updated);
      setSuggestion(null);
    } finally {
      setBusy(null);
    }
  };

  // --- Draft (add-new) flow ---

  const openDraft = () => {
    const firstProvider = llmProviders[0];
    if (!firstProvider) return;
    setDraft({
      provider: firstProvider.key,
      model: firstProvider.default_model,
      base_url: firstProvider.base_url,
      api_key: '',
      testState: 'idle',
    });
  };

  const handleDraftProviderChange = (providerKey: string) => {
    setDraft((prev) =>
      prev
        ? {
            ...prev,
            provider: providerKey,
            model: defaultModelFor(providerKey),
            base_url: baseUrlFor(providerKey),
            testState: 'idle',
            testError: undefined,
          }
        : prev,
    );
  };

  const handleDraftTest = async () => {
    if (!draft) return;
    setDraft((prev) => prev ? { ...prev, testState: 'testing', testError: undefined } : prev);
    try {
      const result: TestLlmResult = await testLlm({
        provider: draft.provider,
        model: draft.model,
        base_url: draft.base_url || undefined,
        api_key: draft.api_key || undefined,
      });
      if (result.ok) {
        setDraft((prev) => prev ? { ...prev, testState: 'ok' } : prev);
      } else {
        setDraft((prev) =>
          prev
            ? { ...prev, testState: 'failed', testError: result.error ?? 'Test failed' }
            : prev,
        );
      }
    } catch (err) {
      setDraft((prev) =>
        prev
          ? {
              ...prev,
              testState: 'failed',
              testError: err instanceof Error ? err.message : 'Test failed',
            }
          : prev,
      );
    }
  };

  const handleDraftConfirm = async () => {
    if (!draft || !draft.provider || !draft.model || !draft.api_key) return;
    const providerInfo = llmProviders.find((p) => p.key === draft.provider);
    setBusy(-1);
    try {
      const newConfig = await addProviderConfig({
        label: providerInfo?.label ?? draft.provider,
        provider: draft.provider,
        model: draft.model,
        base_url: draft.base_url,
        api_key: draft.api_key,
      });
      onConfigsChange([...providerConfigs, newConfig]);
      setDraft(null);
      // Key just saved — fetch the live model list once (doubles as key check).
      modelsFetchedRef.current.add(newConfig.id);
      void loadModels(newConfig.id, true);
    } finally {
      setBusy(null);
    }
  };

  const handleDraftCancel = () => setDraft(null);

  // --- Strategy options with gating ---
  const canUseMultiStrategy = providerConfigs.length >= 2;
  const strategyOptions: SelectOption[] = [
    { value: 'single', label: t('settings.strategyOptions.single') },
    {
      value: 'cost',
      label: t('settings.strategyOptions.cost'),
      disabled: !canUseMultiStrategy,
    },
    {
      value: 'balanced',
      label: t('settings.strategyOptions.balanced'),
      disabled: !canUseMultiStrategy,
    },
    {
      value: 'performance',
      label: t('settings.strategyOptions.performance'),
      disabled: !canUseMultiStrategy,
    },
  ];

  const providerSelectOptions: SelectOption[] = llmProviders.map((p) => ({
    value: p.key,
    label: `${p.label}${p.native ? ' (Native)' : ''}`,
  }));

  return (
    <div className="space-y-4">
      {/* Config rows */}
      <div className="space-y-3">
        {providerConfigs.map((config, idx) => {
          const ts = testStatus[config.id];
          const native = isNative(config.provider);

          return (
            <div
              key={config.id}
              className="flex flex-wrap items-start gap-2 bg-surface border border-border rounded-xl px-4 py-3"
            >
              {/* Primary indicator */}
              <div className="w-5 flex-shrink-0 flex items-center justify-center pt-2">
                {config.is_primary ? (
                  <span className="text-primary text-sm" title="Primary">★</span>
                ) : null}
              </div>

              {/* Provider select */}
              <div className="flex-1 min-w-[120px]">
                <Select
                  data-testid={`provider-config-provider-${idx}`}
                  id={`provider-config-provider-${idx}`}
                  value={config.provider}
                  onChange={(v) => handleFieldChange(config, 'provider', v)}
                  options={providerSelectOptions}
                  ariaLabel="Provider"
                />
              </div>

              {/* Model combobox (dynamic catalog, lazy-fetched on first focus) */}
              <div
                className="flex-1 min-w-[160px]"
                onFocus={() => ensureModelsLoaded(config.id)}
              >
                <ModelCombobox
                  data-testid={`provider-config-model-${idx}`}
                  value={config.model}
                  onChange={(v) => handleFieldChange(config, 'model', v)}
                  options={optionsForRow(config)}
                  staleHint={staleHintFor(config)}
                  onRefresh={() => void loadModels(config.id, true)}
                  ariaLabel="Model"
                />
                {showOllamaHint(config) && (
                  <p
                    data-testid={`provider-config-ollama-hint-${idx}`}
                    className="mt-1 text-[10px] font-mono text-subtle-foreground"
                  >
                    {t('settings.ollamaNotDetected')}{' '}
                    <a
                      href="https://ollama.com/download"
                      target="_blank"
                      rel="noreferrer"
                      className="underline text-primary hover:text-primary/80"
                    >
                      {t('settings.ollamaDownload')}
                    </a>
                  </p>
                )}
              </div>

              {/* Base URL (non-native providers only) — saved on blur */}
              {!native && (
                <div className="flex-1 min-w-[120px]">
                  <input
                    type="text"
                    data-testid={`provider-config-baseurl-${idx}`}
                    value={config.base_url}
                    onChange={(e) => handleLocalFieldChange(config, 'base_url', e.target.value)}
                    onBlur={(e) => handleBaseUrlBlur(config, e.target.value)}
                    placeholder={baseUrlFor(config.provider) || t('settings.labelBaseUrl')}
                    aria-label={t('settings.labelBaseUrl')}
                    className={INPUT_CLS}
                  />
                </div>
              )}

              {/* API key */}
              <div className="flex-1 min-w-[100px]">
                <input
                  type="password"
                  data-testid={`provider-config-key-${idx}`}
                  value={config.api_key}
                  onChange={(e) => handleFieldChange(config, 'api_key', e.target.value)}
                  placeholder={t('settings.labelConfigApiKey')}
                  className={INPUT_CLS}
                />
              </div>

              {/* Per-row test result indicator (populated by Test all) */}
              <div className="flex items-center gap-2 flex-shrink-0">
                {ts?.state === 'testing' && (
                  <Loader2 className="w-3 h-3 animate-spin text-muted-foreground" />
                )}
                {ts?.state === 'ok' && (
                  <span className="text-[10px] font-mono text-success">{t('settings.testOk')}</span>
                )}
                {ts?.state === 'failed' && (
                  <span className="text-[10px] font-mono text-danger">✗ {ts.error}</span>
                )}
              </div>

              {/* Set primary button (only for non-primary rows) */}
              {!config.is_primary && (
                <button
                  type="button"
                  onClick={() => handleSetPrimary(config.id)}
                  disabled={busy === config.id}
                  className="flex items-center gap-1 px-2 py-1.5 text-[10px] font-mono font-medium text-muted-foreground hover:text-primary border border-border hover:border-primary/50 rounded-lg transition-colors disabled:opacity-50"
                  title={t('settings.btnSetPrimary')}
                >
                  <Star className="w-3 h-3" />
                  {t('settings.btnSetPrimary')}
                </button>
              )}

              {/* Delete button */}
              <button
                type="button"
                onClick={() => handleDelete(config.id)}
                disabled={busy === config.id || config.is_primary}
                className="flex items-center gap-1 px-2 py-1.5 text-[10px] font-mono font-medium text-subtle-foreground hover:text-danger border border-border hover:border-danger/50 rounded-lg transition-colors disabled:opacity-30"
                title={t('settings.btnDelete')}
              >
                <Trash2 className="w-3 h-3" />
              </button>
            </div>
          );
        })}
      </div>

      {/* Test all button + Suggest primary button + rationale panel */}
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          {providerConfigs.length > 0 && (
            <button
              type="button"
              data-testid="provider-test-all"
              onClick={handleTestAll}
              disabled={testAllBusy}
              className="flex items-center gap-1.5 px-3 py-2 text-xs font-mono font-medium text-muted-foreground hover:text-primary border border-border hover:border-primary/50 rounded-xl transition-colors disabled:opacity-50"
            >
              {testAllBusy ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <FlaskConical className="w-3.5 h-3.5" />
              )}
              {t('settings.btnTestAll')}
            </button>
          )}
          <button
            type="button"
            onClick={handleSuggest}
            disabled={suggestBusy}
            className="flex items-center gap-1.5 px-3 py-2 text-xs font-mono font-medium text-muted-foreground hover:text-primary border border-border hover:border-primary/50 rounded-xl transition-colors disabled:opacity-50"
          >
            {t('settings.btnSuggestPrimary')}
          </button>
        </div>
        {suggestion && (
          <div className="flex items-start gap-3 bg-surface/80 border border-primary/20 rounded-xl px-4 py-3">
            <p className="flex-1 text-xs text-foreground font-mono">{suggestion.rationale}</p>
            <button
              type="button"
              onClick={handleUseThis}
              disabled={busy === suggestion.id}
              className="flex-shrink-0 px-2 py-1 text-[10px] font-mono font-medium text-primary border border-primary/40 hover:border-primary/80 rounded-lg transition-colors disabled:opacity-50"
            >
              {t('settings.btnUseThis')}
            </button>
          </div>
        )}
      </div>

      {/* Add model button OR draft form */}
      {draft === null ? (
        <button
          type="button"
          onClick={openDraft}
          disabled={llmProviders.length === 0}
          className="flex items-center gap-1.5 px-3 py-2 text-xs font-mono font-medium text-primary border border-primary/30 hover:border-primary/60 rounded-xl transition-colors disabled:opacity-50"
        >
          <Plus className="w-3.5 h-3.5" />
          {t('settings.btnAddModel')}
        </button>
      ) : (
        /* Draft / new config form */
        <div className="flex flex-wrap items-start gap-2 bg-surface border border-primary/30 rounded-xl px-4 py-3">
          {/* Provider select */}
          <div className="flex-1 min-w-[120px]">
            <Select
              value={draft.provider}
              onChange={handleDraftProviderChange}
              options={providerSelectOptions}
              ariaLabel="Provider"
            />
          </div>

          {/* Model combobox (static seed options until the config is saved) */}
          <div className="flex-1 min-w-[160px]">
            <ModelCombobox
              data-testid="provider-draft-model"
              value={draft.model}
              onChange={(v) =>
                setDraft((prev) => prev ? { ...prev, model: v, testState: 'idle', testError: undefined } : prev)
              }
              options={staticModelInfos(draft.provider)}
              ariaLabel="Model"
            />
          </div>

          {/* Base URL (non-native providers only) — part of the draft payload */}
          {!isNative(draft.provider) && (
            <div className="flex-1 min-w-[120px]">
              <input
                type="text"
                data-testid="provider-draft-baseurl"
                value={draft.base_url}
                onChange={(e) =>
                  setDraft((prev) =>
                    prev ? { ...prev, base_url: e.target.value, testState: 'idle', testError: undefined } : prev,
                  )
                }
                placeholder={baseUrlFor(draft.provider) || t('settings.labelBaseUrl')}
                aria-label={t('settings.labelBaseUrl')}
                className={INPUT_CLS}
              />
            </div>
          )}

          {/* API key */}
          <div className="flex-1 min-w-[100px]">
            <input
              type="password"
              value={draft.api_key}
              onChange={(e) =>
                setDraft((prev) =>
                  prev ? { ...prev, api_key: e.target.value, testState: 'idle', testError: undefined } : prev,
                )
              }
              placeholder={t('settings.labelConfigApiKey')}
              className={INPUT_CLS}
            />
          </div>

          {/* Confirm / Cancel */}
          <div className="flex items-center gap-2 flex-shrink-0">
            <button
              type="button"
              data-testid="provider-draft-confirm"
              onClick={handleDraftConfirm}
              disabled={!draft.provider || !draft.model || !draft.api_key || busy === -1}
              className="flex items-center gap-1 px-2 py-1.5 text-[10px] font-mono font-medium text-primary border border-primary/40 hover:border-primary/80 rounded-lg transition-colors disabled:opacity-30"
            >
              {t('settings.btnAddConfirm')}
            </button>
            <button
              type="button"
              onClick={handleDraftCancel}
              className="flex items-center gap-1 px-2 py-1.5 text-[10px] font-mono font-medium text-subtle-foreground hover:text-foreground border border-border hover:border-border-strong rounded-lg transition-colors"
            >
              {t('common.cancel')}
            </button>
          </div>
        </div>
      )}

      {/* ── Strategy selector (C: below the config rows) ── */}
      <div className="space-y-1.5 pt-2 border-t border-border/40">
        <label className="block text-[10.5px] font-mono font-medium text-muted-foreground uppercase tracking-wide">
          {t('settings.labelStrategy')}
        </label>
        <Select
          data-testid="provider-strategy-select"
          id="provider-strategy-select"
          value={canUseMultiStrategy ? strategy : 'single'}
          onChange={(v) => onStrategyChange?.(v)}
          options={strategyOptions}
          ariaLabel={t('settings.labelStrategy')}
        />
        {!canUseMultiStrategy && (
          <p className="text-[10px] text-subtle-foreground font-mono">
            {t('settings.strategyHint')}
          </p>
        )}
      </div>

      {/* ── Provider capability comparison table ── */}
      {catalog.length > 0 && (
        <div className="pt-2 border-t border-border/40">
          <button
            type="button"
            data-testid="capability-table-toggle"
            onClick={() => setCatalogOpen((o) => !o)}
            className="flex items-center gap-2 w-full cursor-pointer group"
          >
            <ChevronDown
              className={`w-3.5 h-3.5 text-subtle-foreground group-hover:text-foreground transition-transform duration-200 ${catalogOpen ? 'rotate-0' : '-rotate-90'}`}
            />
            <span className="text-[10.5px] font-mono font-medium text-subtle-foreground group-hover:text-foreground uppercase tracking-wide transition-colors">
              {t('settings.capabilityTable')}
              {' '}
              <span className="normal-case text-[10px] font-normal opacity-70">
                · {t('settings.capabilityTableCount', { count: catalog.length })}
              </span>
            </span>
          </button>
          {catalogOpen && (
            <div className="mt-2 overflow-x-auto">
              <table className="w-full text-[10px] font-mono border-collapse">
                <thead>
                  <tr className="border-b border-border">
                    <th className="text-left py-1.5 pr-3 text-subtle-foreground font-medium">{t('settings.capColProvider')}</th>
                    <th className="text-center py-1.5 px-2 text-subtle-foreground font-medium">{t('settings.capColCost')}</th>
                    <th className="text-center py-1.5 px-2 text-subtle-foreground font-medium">{t('settings.capColSpeed')}</th>
                    <th className="text-center py-1.5 px-2 text-subtle-foreground font-medium">{t('settings.capColTools')}</th>
                    <th className="text-center py-1.5 px-2 text-subtle-foreground font-medium">{t('settings.capColReasoning')}</th>
                    <th className="text-center py-1.5 px-2 text-subtle-foreground font-medium">{t('settings.capColContext')}</th>
                  </tr>
                </thead>
                <tbody>
                  {catalog.map((entry) => (
                    <tr key={entry.provider} className="border-b border-border/50 hover:bg-surface">
                      <td className="py-1.5 pr-3 text-foreground">{entry.provider}</td>
                      <td className="py-1.5 px-2 text-center text-muted-foreground">{entry.capabilities.cost}</td>
                      <td className="py-1.5 px-2 text-center text-muted-foreground">{entry.capabilities.speed}</td>
                      <td className="py-1.5 px-2 text-center text-muted-foreground">{entry.capabilities.tool_calling}</td>
                      <td className="py-1.5 px-2 text-center text-muted-foreground">{entry.capabilities.reasoning}</td>
                      <td className="py-1.5 px-2 text-center text-muted-foreground">{entry.capabilities.long_context}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

    </div>
  );
}
