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
import { Loader2, FlaskConical, ChevronDown, Plus } from 'lucide-react';
import type { SelectOption } from './Select';
import ProviderCard from './settings/ProviderCard';
import ProviderDetailPane, { type DraftConfig } from './settings/ProviderDetailPane';
import RoutingStrategyCard from './settings/RoutingStrategyCard';
import { purgeCapabilityOverrides } from './settings/CapabilityBadges';
import { formatRelativeTime } from './settings/relativeTime';
import { providerStatus, type LiveTest } from '../lib/providerStatus';

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

/** P3: quick-pick base_url templates for the custom OpenAI-compatible
 *  provider. Labels are product names (not translated) except the Ollama
 *  remote chip, whose "(remote)" qualifier is localized via labelKey. */
const CUSTOM_BASE_URL_TEMPLATES: { label?: string; labelKey?: string; url: string }[] = [
  { label: 'LM Studio', url: 'http://localhost:1234/v1' },
  { label: 'vLLM', url: 'http://localhost:8000/v1' },
  { label: 'llama.cpp', url: 'http://localhost:8080/v1' },
  { label: 'LiteLLM', url: 'http://localhost:4000' },
  { labelKey: 'settings.customChipOllamaRemote', url: 'http://<host>:11434/v1' },
];

/** Test status per saved config id. `latency` carries the level-2 (deep chat
 *  test) round-trip time so the ConnectionTester can show it (parity with the
 *  level-1 probe). */
type TestStatusMap = Record<
  number,
  { state: 'idle' | 'testing' | 'ok' | 'failed'; error?: string; latency?: number }
>;

/** Dynamic model list state per saved config id (lazy, fetched on first focus). */
type RowModelsMap = Record<number, { loading: boolean; result: ModelListResult | null }>;

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
  // Fresh-entry API-key drafts per saved config id. The saved-config key input
  // is decoupled from the masked server value (config.api_key): it starts empty
  // and commits the NEW typed value on blur. Keyed by id so switching the
  // selected config never leaks one config's unsaved key onto another.
  const [keyDrafts, setKeyDrafts] = useState<Record<number, string>>({});
  // Master-detail selection: which saved config's detail pane is shown. Default
  // to the primary config, else the first, else null (draft-only / empty).
  const [selectedId, setSelectedId] = useState<number | null>(() => {
    const primary = providerConfigs.find((c) => c.is_primary);
    return primary?.id ?? providerConfigs[0]?.id ?? null;
  });
  const [testAllBusy, setTestAllBusy] = useState(false);
  const [rowModels, setRowModels] = useState<RowModelsMap>({});
  // P4: connectivity dot state (overlay; falls back to the persisted columns).
  // P4: settings-open auto-probe fires ONCE per mount (StrictMode double-invokes
  // effects on the same instance — the ref survives and guards the second pass).
  const healthAutoProbedRef = useRef(false);
  // Rows whose dynamic model list was already requested (fetch once per row).
  const modelsFetchedRef = useRef<Set<number>>(new Set());
  // Rows with base_url edits pending a blur-save.
  const baseUrlDirtyRef = useRef<Set<number>>(new Set());
  // Per-row cache epoch: bumped when the row's provider changes so an
  // in-flight fetch for the OLD provider can't repopulate the cache after
  // invalidation.
  const modelsEpochRef = useRef<Map<number, number>>(new Map());
  // FIX 2: rows switched to "custom" locally but not yet persisted (a PUT
  // with blank base_url would deterministically 422 — a silent dead-end).
  // The base_url blur persists the FULL {provider, model, base_url} patch.
  const pendingCustomSwitchRef = useRef<Set<number>>(new Set());
  // FIX 3: saved-row base_url inputs, so a quick-pick chip can focus the
  // field for review instead of auto-persisting a template value.
  const baseUrlInputRefs = useRef<Map<number, HTMLInputElement | null>>(new Map());

  useEffect(() => {
    getCatalog().then(setCatalog).catch(() => setCatalog([]));
  }, []);

  // Keep the selection valid as the config list changes (e.g. deleting the
  // selected row moves selection to a survivor; an external refresh that drops
  // the selected id re-anchors to the primary/first). The draft owns the pane
  // while active, so leave selection untouched then.
  useEffect(() => {
    if (draft) return;
    if (selectedId != null && providerConfigs.some((c) => c.id === selectedId)) return;
    const primary = providerConfigs.find((c) => c.is_primary);
    setSelectedId(primary?.id ?? providerConfigs[0]?.id ?? null);
  }, [providerConfigs, selectedId, draft]);

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
    const epoch = modelsEpochRef.current.get(id) ?? 0;
    setRowModels((prev) => ({
      ...prev,
      [id]: { loading: true, result: prev[id]?.result ?? null },
    }));
    try {
      const result = await fetchProviderModels(id, refresh);
      // Provider switched while this fetch was in flight — the result
      // belongs to the old provider; drop it.
      if ((modelsEpochRef.current.get(id) ?? 0) !== epoch) return;
      setRowModels((prev) => ({ ...prev, [id]: { loading: false, result } }));
    } catch {
      if ((modelsEpochRef.current.get(id) ?? 0) !== epoch) return;
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

  // --- one status per config: "can this LLM answer a message?" ---

  /** Merge the persisted verdict with any test running in THIS session. The
   *  container owns this so every surface — card, pill, composer chip — reads
   *  the same answer from the same place. */
  const statusFor = (config: ProviderConfig) =>
    providerStatus(config, testStatus[config.id] as LiveTest | undefined);

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
      const remaining = providerConfigs.filter((c) => c.id !== id);
      onConfigsChange(remaining);
      // Re-anchor the master-detail selection in the SAME batched update as the
      // list change so the detail pane never flashes its empty state before
      // landing on a survivor. The sync effect stays as a backstop for external
      // prop changes that drop the selected id.
      if (selectedId === id) {
        const primary = remaining.find((c) => c.is_primary);
        setSelectedId(primary?.id ?? remaining[0]?.id ?? null);
      }
      pendingCustomSwitchRef.current.delete(id);
      baseUrlInputRefs.current.delete(id);
      // Drop any unsaved key draft for the deleted id — SQLite reuses integer
      // PKs, so a future config reclaiming this id must not inherit it.
      setKeyDrafts((prev) => {
        if (!(id in prev)) return prev;
        const next = { ...prev };
        delete next[id];
        return next;
      });
      // SQLite reuses INTEGER PRIMARY KEY values (no AUTOINCREMENT) — purge every
      // per-row cache so a future config reusing this id starts clean instead of
      // inheriting stale models / dirty flags / fetch epoch. This includes the
      // persisted CapabilityBadges overrides (localStorage), which would
      // otherwise leak onto a new config reclaiming this id + model string.
      purgeCapabilityOverrides(id);
      modelsFetchedRef.current.delete(id);
      baseUrlDirtyRef.current.delete(id);
      modelsEpochRef.current.delete(id);
      setRowModels((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
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
    let localOnly = false;
    if (field === 'provider') {
      patch.model = defaultModelFor(value);
      patch.base_url = baseUrlFor(value);
      // The cached dynamic model list (and any stale/ollama hint) belongs to
      // the OLD provider — invalidate it so the next focus refetches, and
      // bump the epoch so an in-flight fetch can't repopulate the cache.
      modelsFetchedRef.current.delete(config.id);
      baseUrlDirtyRef.current.delete(config.id);
      modelsEpochRef.current.set(
        config.id,
        (modelsEpochRef.current.get(config.id) ?? 0) + 1,
      );
      setRowModels((prev) => {
        const next = { ...prev };
        delete next[config.id];
        return next;
      });
      // NB: the stored verdict was about the OLD provider and is now
      // meaningless. It is cleared server-side on any change to
      // provider/model/base_url/key (provider_config_service.update_config), so
      // the card falls back to "not tested" rather than vouching for a
      // configuration nobody has tried.
      // FIX 2: switching to custom leaves base_url blank (no preset) — a PUT
      // would deterministically 422 and the revert would look like a dead
      // click. Apply the switch locally, let the required-base_url hint guide
      // the user, and persist the full patch on the base_url blur.
      if (value === 'custom' && !(patch.base_url ?? '').trim()) {
        pendingCustomSwitchRef.current.add(config.id);
        localOnly = true;
      } else {
        pendingCustomSwitchRef.current.delete(config.id);
      }
    }
    if (field === 'api_key') {
      // Optimistically reflect the honest key state so the placeholder flips to
      // "key saved — type to replace" and any undecryptable warning clears the
      // moment a new key is committed (a failed PUT reverts via the catch below).
      patch.key_status = value.trim() ? 'set' : 'unset';
    }
    // The stored verdict describes the configuration that was tested. Changing
    // what gets called invalidates it — the backend clears it in update_config,
    // and the optimistic row has to agree or the card keeps showing the OLD
    // provider's green until something happens to refetch. (Same reasoning as
    // the server side; the two must not drift.) A label edit is not in this set.
    const invalidates =
      field === 'provider' || field === 'model' || field === 'api_key' || 'base_url' in patch;
    const cleared = invalidates
      ? { last_health: null, last_health_at: null, last_health_detail: null }
      : {};
    const optimistic = providerConfigs.map((c) =>
      c.id === config.id ? { ...c, ...patch, ...cleared } : c,
    );
    onConfigsChange(optimistic);
    // Clear test status since config changed
    setTestStatus((prev) => ({ ...prev, [config.id]: { state: 'idle' } }));
    if (localOnly) return;
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
    const pendingSwitch = pendingCustomSwitchRef.current.has(config.id);
    if (!baseUrlDirtyRef.current.has(config.id) && !pendingSwitch) return;
    // FIX 2: a custom row with a still-blank base_url would 422 — keep the
    // local pending state (the required hint stays) and retry on a later blur.
    if (config.provider === 'custom' && !value.trim()) return;
    baseUrlDirtyRef.current.delete(config.id);
    setTestStatus((prev) => ({ ...prev, [config.id]: { state: 'idle' } }));
    // A pending provider→custom switch persists as ONE complete patch here
    // (provider+model+base_url together, matching the server-side validation).
    const patch: Partial<ProviderConfig> = pendingSwitch
      ? { provider: config.provider, model: config.model, base_url: value }
      : { base_url: value };
    try {
      await updateProviderConfig(config.id, patch);
      pendingCustomSwitchRef.current.delete(config.id);
    } catch {
      // The write failed — mark the row dirty again so the next blur retries
      // instead of silently showing a base_url the server never received.
      // (A pending switch stays pending → the retry re-sends the full patch.)
      baseUrlDirtyRef.current.add(config.id);
    }
  };

  /** Local-only edit of a saved config's fresh-entry key draft (no network). */
  const handleApiKeyDraftChange = (config: ProviderConfig, value: string) => {
    setKeyDrafts((prev) => ({ ...prev, [config.id]: value }));
  };

  /** Commit the key draft on blur. A non-empty draft persists as the NEW key via
   *  the existing api_key field-change path, then clears so the field is ready
   *  for the next replace. An empty/whitespace draft is a no-op — the stored key
   *  (or its honest key_status) is left untouched. */
  const handleApiKeyBlur = (config: ProviderConfig, value: string) => {
    if (!value.trim()) return;
    void handleFieldChange(config, 'api_key', value);
    setKeyDrafts((prev) => {
      const next = { ...prev };
      delete next[config.id];
      return next;
    });
  };

  const handleTestSaved = async (id: number) => {
    setTestStatus((prev) => ({ ...prev, [id]: { state: 'testing' } }));
    try {
      const result: TestLlmResult = await testProviderConfig(id);
      if (result.ok) {
        setTestStatus((prev) => ({ ...prev, [id]: { state: 'ok', latency: result.latency_ms } }));
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
            setTestStatus((prev) => ({ ...prev, [c.id]: { state: 'ok', latency: result.latency_ms } }));
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
    // FIX 1 (spec B3/D3): api_key is deliberately NOT required — keyless
    // configs (ollama, LM Studio, vLLM, …) are legitimate; an empty key just
    // means no Authorization header. The backend accepts empty keys.
    if (!draft || !draft.provider || !draft.model) return;
    // P3: custom has no preset base_url to fall back on — refuse a blank one
    // (mirrors the server-side 422 guard).
    if (draft.provider === 'custom' && !draft.base_url.trim()) return;
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
      // Land the master-detail selection on the freshly added config.
      setSelectedId(newConfig.id);
      // Key just saved — fetch the live model list once (doubles as key check).
      modelsFetchedRef.current.add(newConfig.id);
      void loadModels(newConfig.id, true);
      // The launch-time sweep already ran; a config added mid-session would
      // otherwise sit at "not tested" until someone pressed Test. Test it now,
      // which is also the fastest way to tell the user they typed a bad key.
      void handleTestSaved(newConfig.id);
    } catch (err) {
      // A rejected add MUST surface (never silent) — a validation 422 / network
      // failure otherwise looked like a dead "Add" button. Show the reason on
      // the draft's error channel and keep the draft open for a retry.
      setDraft((prev) =>
        prev
          ? {
              ...prev,
              testState: 'failed',
              testError: err instanceof Error ? err.message : 'Add failed',
            }
          : prev,
      );
    } finally {
      setBusy(null);
    }
  };

  const handleDraftCancel = () => setDraft(null);

  // --- P3: custom provider helpers ---

  /** Chip click on a SAVED row: fill the field (marks dirty) and FOCUS it —
   *  never auto-persist. The user reviews/edits the template (the Ollama
   *  remote chip is a literal placeholder that MUST be edited) and the
   *  natural blur performs the save via the existing dirty/blur machinery. */
  const handleChipFillSaved = (config: ProviderConfig, url: string) => {
    handleLocalFieldChange(config, 'base_url', url);
    baseUrlInputRefs.current.get(config.id)?.focus();
  };

  const handleChipFillDraft = (url: string) => {
    setDraft((prev) =>
      prev ? { ...prev, base_url: url, testState: 'idle', testError: undefined } : prev,
    );
  };

  /** P3 custom-row extras: required-base_url hint + quick-pick chips + static
   *  compatibility note. Rendered full-width under the fields of any custom
   *  row (saved or draft). */
  const renderCustomExtras = (opts: {
    baseUrl: string;
    onChip: (url: string) => void;
    requiredTestId: string;
    noteTestId: string;
  }) => (
    <div className="w-full space-y-1.5">
      {!opts.baseUrl.trim() && (
        <p
          data-testid={opts.requiredTestId}
          className="text-[10px] font-mono text-danger"
        >
          {t('settings.customBaseUrlRequired')}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[10px] font-mono text-subtle-foreground">
          {t('settings.customQuickFill')}
        </span>
        {CUSTOM_BASE_URL_TEMPLATES.map((tpl) => {
          const label = tpl.labelKey ? t(tpl.labelKey) : tpl.label ?? '';
          return (
            <button
              key={tpl.url}
              type="button"
              onClick={() => opts.onChip(tpl.url)}
              className="px-2 py-0.5 text-[10px] font-mono text-muted-foreground hover:text-primary border border-border hover:border-primary/50 rounded-lg transition-colors"
            >
              {label}
            </button>
          );
        })}
      </div>
      <p
        data-testid={opts.noteTestId}
        className="text-[10px] font-mono text-subtle-foreground"
      >
        {t('settings.customCompatNote')}
      </p>
    </div>
  );

  const providerSelectOptions: SelectOption[] = llmProviders.map((p) => ({
    value: p.key,
    label: `${p.label}${p.native ? ' (Native)' : ''}`,
  }));

  // Master-detail: resolve the selected config + its index (for stable testids).
  const selectedConfig =
    (!draft && selectedId != null
      ? providerConfigs.find((c) => c.id === selectedId)
      : undefined) ?? null;
  const selectedIndex = selectedConfig
    ? providerConfigs.findIndex((c) => c.id === selectedConfig.id)
    : -1;

  // B2: API-derived capabilities of the selected model (for CapabilityBadges) —
  // the matching ModelInfo from the row's catalog, or [] when the id is typed
  // free-hand / not in the list.
  const selectedModelCaps = selectedConfig
    ? optionsForRow(selectedConfig).find((m) => m.id === selectedConfig.model)?.capabilities ?? []
    : [];

  return (
    <div className="space-y-4">
      {/* One column of cards; the selected one expands its fields inline. */}
      <div className="flex flex-col gap-2.5">
        {providerConfigs.map((config, idx) => (
          <ProviderCard
            key={config.id}
            config={config}
            index={idx}
            llmProviders={llmProviders}
            selected={!draft && config.id === selectedId}
            onSelect={(id) => setSelectedId(selectedId === id && !draft ? -1 : id)}
            status={statusFor(config)}
          >
            <ProviderDetailPane
              llmProviders={llmProviders}
              providerSelectOptions={providerSelectOptions}
              isNative={isNative}
              baseUrlFor={baseUrlFor}
              staticModelInfos={staticModelInfos}
              draft={null}
              draftBusy={false}
              onDraftProviderChange={handleDraftProviderChange}
              onDraftModelChange={() => {}}
              onDraftBaseUrlChange={() => {}}
              onDraftApiKeyChange={() => {}}
              onDraftConfirm={handleDraftConfirm}
              onDraftCancel={handleDraftCancel}
              draftCustomExtras={null}
              config={config}
              index={idx}
              busy={busy}
              onFieldChange={handleFieldChange}
              onBaseUrlChange={(c, value) => handleLocalFieldChange(c, 'base_url', value)}
              onBaseUrlBlur={handleBaseUrlBlur}
              apiKeyDraft={keyDrafts[config.id] ?? ''}
              onApiKeyDraftChange={handleApiKeyDraftChange}
              onApiKeyDraftBlur={handleApiKeyBlur}
              onSetPrimary={handleSetPrimary}
              onDelete={handleDelete}
              registerBaseUrlRef={(id, el) => {
                baseUrlInputRefs.current.set(id, el);
              }}
              modelOptions={optionsForRow(config)}
              modelStaleHint={staleHintFor(config)}
              onModelFocus={() => ensureModelsLoaded(config.id)}
              onModelChange={(c, v) => handleFieldChange(c, 'model', v)}
              onModelRefresh={() => void loadModels(config.id, true)}
              showOllamaHint={showOllamaHint(config)}
              configCustomExtras={
                config.provider === 'custom'
                  ? renderCustomExtras({
                      baseUrl: config.base_url,
                      onChip: (url) => handleChipFillSaved(config, url),
                      requiredTestId: `provider-config-custom-required-${idx}`,
                      noteTestId: `provider-config-custom-note-${idx}`,
                    })
                  : null
              }
              onTest={(c) => void handleTestSaved(c.id)}
              testStatus={testStatus[config.id]}
              modelCapabilities={
                optionsForRow(config).find((m) => m.id === config.model)?.capabilities ?? []
              }
            />
          </ProviderCard>
        ))}

        {/* Draft (add-new) form as its own card at the end of the list. */}
        {draft && (
          <div data-testid="provider-draft-card" className="bg-surface border border-dashed border-primary/40 rounded-xl px-4 py-4">
            <ProviderDetailPane
              llmProviders={llmProviders}
              providerSelectOptions={providerSelectOptions}
              isNative={isNative}
              baseUrlFor={baseUrlFor}
              staticModelInfos={staticModelInfos}
              draft={draft}
              draftBusy={busy === -1}
              onDraftProviderChange={handleDraftProviderChange}
              onDraftModelChange={(v) =>
                setDraft((prev) =>
                  prev ? { ...prev, model: v, testState: 'idle', testError: undefined } : prev,
                )
              }
              onDraftBaseUrlChange={(v) =>
                setDraft((prev) =>
                  prev ? { ...prev, base_url: v, testState: 'idle', testError: undefined } : prev,
                )
              }
              onDraftApiKeyChange={(v) =>
                setDraft((prev) =>
                  prev ? { ...prev, api_key: v, testState: 'idle', testError: undefined } : prev,
                )
              }
              onDraftConfirm={handleDraftConfirm}
              onDraftCancel={handleDraftCancel}
              draftCustomExtras={
                draft.provider === 'custom'
                  ? renderCustomExtras({
                      baseUrl: draft.base_url,
                      onChip: handleChipFillDraft,
                      requiredTestId: 'provider-draft-custom-required',
                      noteTestId: 'provider-draft-custom-note',
                    })
                  : null
              }
              config={null}
              index={-1}
              busy={busy}
              onFieldChange={handleFieldChange}
              onBaseUrlChange={() => {}}
              onBaseUrlBlur={handleBaseUrlBlur}
              apiKeyDraft=""
              onApiKeyDraftChange={handleApiKeyDraftChange}
              onApiKeyDraftBlur={handleApiKeyBlur}
              onSetPrimary={handleSetPrimary}
              onDelete={handleDelete}
              registerBaseUrlRef={() => {}}
              modelOptions={[]}
              onModelFocus={() => {}}
              onModelChange={() => {}}
              onModelRefresh={() => {}}
              showOllamaHint={false}
              configCustomExtras={null}
              onTest={() => {}}
              modelCapabilities={[]}
            />
          </div>
        )}

        <button
          type="button"
          data-testid="provider-add-model"
          onClick={openDraft}
          disabled={draft !== null || llmProviders.length === 0}
          className="flex items-center justify-center gap-1.5 px-3 py-2.5 text-xs font-mono font-medium text-primary border border-primary/30 hover:border-primary/60 rounded-xl transition-colors disabled:opacity-50"
        >
          <Plus className="w-3.5 h-3.5" />
          {t('settings.btnAddModel')}
        </button>
      </div>

      {/* Test all button (batch level-2 usability test across saved configs) */}
      {providerConfigs.length > 0 && (
        <div className="flex items-center gap-2">
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
        </div>
      )}

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
              {/* These five columns are hand-authored 0-10 ROUTING scores from
                  arslan/llm/catalog.py, used to pick a model for a job. The
                  "Tool aptitude" one collides in wording with a completely
                  different fact shown elsewhere in Settings — whether Arslan
                  transmits tool definitions to the provider at all. A user
                  could otherwise read "9" and "tools will not run" on one
                  screen and reasonably conclude the app contradicts itself. */}
              <p className="mt-2 text-[10px] leading-relaxed text-subtle-foreground">
                {t('settings.capabilityTableNote')}
              </p>
            </div>
          )}
        </div>
      )}

      {/* Routing strategy sits BELOW the model configuration now: it is the
          question you answer AFTER there is more than one model, and having
          it first pushed the thing everyone actually came here for down. */}
      <RoutingStrategyCard
        strategy={strategy}
        onStrategyChange={onStrategyChange}
        configCount={providerConfigs.length}
        onSuggestPrimary={handleSuggest}
        suggestBusy={suggestBusy}
        suggestion={suggestion}
        onUseThis={handleUseThis}
        useThisBusy={suggestion ? busy === suggestion.id : false}
      />

    </div>
  );
}
