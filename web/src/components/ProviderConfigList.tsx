import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { CatalogEntry, ProviderOption, ProviderConfig, SuggestPrimaryResult } from '../api/client.types';
import {
  addProviderConfig,
  updateProviderConfig,
  setPrimaryProviderConfig,
  deleteProviderConfig,
  suggestPrimary,
  getCatalog,
} from '../api/client';
import { Plus, Star, Trash2 } from 'lucide-react';

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
  'w-full bg-[#0a0c11] border border-[#23293e] focus:border-[#FF8E24]/50 focus:ring-1 focus:ring-[#FF8E24]/20 rounded-xl px-3 py-2 text-xs text-white placeholder-gray-600 focus:outline-none transition-all font-mono';
const SELECT_CLS =
  'w-full bg-[#0a0c11] border border-[#23293e] focus:border-[#FF8E24]/50 focus:ring-1 focus:ring-[#FF8E24]/20 rounded-xl px-3 py-2 text-xs text-white focus:outline-none transition-all font-sans';

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

  useEffect(() => {
    getCatalog().then(setCatalog).catch(() => setCatalog([]));
  }, []);

  // --- helpers ---

  const modelsFor = (providerKey: string): string[] =>
    llmProviders.find((p) => p.key === providerKey)?.models ?? [];

  const defaultModelFor = (providerKey: string): string =>
    llmProviders.find((p) => p.key === providerKey)?.default_model ?? '';

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
    // When provider changes auto-set model to the provider's default
    if (field === 'provider') {
      patch.model = defaultModelFor(value);
    }
    const optimistic = providerConfigs.map((c) =>
      c.id === config.id ? { ...c, ...patch } : c,
    );
    onConfigsChange(optimistic);
    try {
      await updateProviderConfig(config.id, patch);
    } catch {
      // Revert on failure
      onConfigsChange(providerConfigs);
    }
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

  const handleAddModel = async () => {
    const firstProvider = llmProviders[0];
    if (!firstProvider) return;
    setBusy(-1);
    try {
      const newConfig = await addProviderConfig({
        label: firstProvider.label,
        provider: firstProvider.key,
        model: firstProvider.default_model,
        base_url: firstProvider.base_url,
        api_key: '',
      });
      onConfigsChange([...providerConfigs, newConfig]);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-4">
      {/* Strategy selector */}
      <div className="space-y-2">
        <label className="block text-[10.5px] font-mono font-medium text-gray-400 uppercase tracking-wide">
          {t('settings.labelStrategy')}
        </label>
        <select
          data-testid="provider-strategy-select"
          value={strategy}
          onChange={(e) => onStrategyChange?.(e.target.value)}
          className={SELECT_CLS}
        >
          <option value="single">{t('settings.strategyOptions.single')}</option>
          <option value="cost">{t('settings.strategyOptions.cost')}</option>
          <option value="balanced">{t('settings.strategyOptions.balanced')}</option>
          <option value="performance">{t('settings.strategyOptions.performance')}</option>
        </select>
      </div>

      {/* Config rows */}
      <div className="space-y-3">
        {providerConfigs.map((config, idx) => {
          const models = modelsFor(config.provider);
          return (
            <div
              key={config.id}
              className="flex flex-wrap items-center gap-2 bg-[#0d0f15] border border-[#1e2330] rounded-xl px-4 py-3"
            >
              {/* Primary indicator */}
              <div className="w-5 flex-shrink-0 flex items-center justify-center">
                {config.is_primary ? (
                  <span className="text-[#FF8E24] text-sm" title="Primary">★</span>
                ) : null}
              </div>

              {/* Provider select */}
              <div className="flex-1 min-w-[120px]">
                <select
                  data-testid={`provider-config-provider-${idx}`}
                  value={config.provider}
                  onChange={(e) => handleFieldChange(config, 'provider', e.target.value)}
                  className={SELECT_CLS}
                >
                  {llmProviders.map((p) => (
                    <option key={p.key} value={p.key}>
                      {p.label}{p.native ? ' (Native)' : ''}
                    </option>
                  ))}
                </select>
              </div>

              {/* Model select */}
              <div className="flex-1 min-w-[120px]">
                <select
                  data-testid={`provider-config-model-${idx}`}
                  value={config.model}
                  onChange={(e) => handleFieldChange(config, 'model', e.target.value)}
                  className={SELECT_CLS}
                >
                  {models.map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                  {/* Fallback if model not in list */}
                  {models.length === 0 && (
                    <option value={config.model}>{config.model}</option>
                  )}
                </select>
              </div>

              {/* API key (masked input) */}
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

              {/* Set primary button (only for non-primary rows) */}
              {!config.is_primary && (
                <button
                  type="button"
                  onClick={() => handleSetPrimary(config.id)}
                  disabled={busy === config.id}
                  className="flex items-center gap-1 px-2 py-1.5 text-[10px] font-mono font-medium text-gray-400 hover:text-[#FF8E24] border border-[#23293e] hover:border-[#FF8E24]/50 rounded-lg transition-colors disabled:opacity-50"
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
                className="flex items-center gap-1 px-2 py-1.5 text-[10px] font-mono font-medium text-gray-500 hover:text-red-400 border border-[#23293e] hover:border-red-500/50 rounded-lg transition-colors disabled:opacity-30"
                title={t('settings.btnDelete')}
              >
                <Trash2 className="w-3 h-3" />
              </button>
            </div>
          );
        })}
      </div>

      {/* Suggest primary button + rationale panel */}
      <div className="space-y-2">
        <button
          type="button"
          onClick={handleSuggest}
          disabled={suggestBusy}
          className="flex items-center gap-1.5 px-3 py-2 text-xs font-mono font-medium text-gray-400 hover:text-[#FF8E24] border border-[#23293e] hover:border-[#FF8E24]/50 rounded-xl transition-colors disabled:opacity-50"
        >
          {t('settings.btnSuggestPrimary')}
        </button>
        {suggestion && (
          <div className="flex items-start gap-3 bg-[#0d1017] border border-[#FF8E24]/20 rounded-xl px-4 py-3">
            <p className="flex-1 text-xs text-gray-300 font-mono">{suggestion.rationale}</p>
            <button
              type="button"
              onClick={handleUseThis}
              disabled={busy === suggestion.id}
              className="flex-shrink-0 px-2 py-1 text-[10px] font-mono font-medium text-[#FF8E24] border border-[#FF8E24]/40 hover:border-[#FF8E24]/80 rounded-lg transition-colors disabled:opacity-50"
            >
              {t('settings.btnUseThis')}
            </button>
          </div>
        )}
      </div>

      {/* Add model button */}
      <button
        type="button"
        onClick={handleAddModel}
        disabled={busy === -1 || llmProviders.length === 0}
        className="flex items-center gap-1.5 px-3 py-2 text-xs font-mono font-medium text-[#FF8E24] border border-[#FF8E24]/30 hover:border-[#FF8E24]/60 rounded-xl transition-colors disabled:opacity-50"
      >
        <Plus className="w-3.5 h-3.5" />
        {t('settings.btnAddModel')}
      </button>

      {/* Read-only capability table */}
      {catalog.length > 0 && (
        <details className="group">
          <summary className="cursor-pointer list-none text-[10.5px] font-mono font-medium text-gray-500 hover:text-gray-300 uppercase tracking-wide transition-colors">
            {t('settings.capabilityTable')}
          </summary>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-[10px] font-mono border-collapse">
              <thead>
                <tr className="border-b border-[#1e2330]">
                  <th className="text-left py-1.5 pr-3 text-gray-500 font-medium">{t('settings.capColProvider')}</th>
                  <th className="text-center py-1.5 px-2 text-gray-500 font-medium">{t('settings.capColCost')}</th>
                  <th className="text-center py-1.5 px-2 text-gray-500 font-medium">{t('settings.capColSpeed')}</th>
                  <th className="text-center py-1.5 px-2 text-gray-500 font-medium">{t('settings.capColTools')}</th>
                  <th className="text-center py-1.5 px-2 text-gray-500 font-medium">{t('settings.capColReasoning')}</th>
                  <th className="text-center py-1.5 px-2 text-gray-500 font-medium">{t('settings.capColContext')}</th>
                </tr>
              </thead>
              <tbody>
                {catalog.map((entry) => (
                  <tr key={entry.provider} className="border-b border-[#1a1e2b] hover:bg-[#0d0f15]">
                    <td className="py-1.5 pr-3 text-gray-300">{entry.provider}</td>
                    <td className="py-1.5 px-2 text-center text-gray-400">{entry.capabilities.cost}</td>
                    <td className="py-1.5 px-2 text-center text-gray-400">{entry.capabilities.speed}</td>
                    <td className="py-1.5 px-2 text-center text-gray-400">{entry.capabilities.tool_calling}</td>
                    <td className="py-1.5 px-2 text-center text-gray-400">{entry.capabilities.reasoning}</td>
                    <td className="py-1.5 px-2 text-center text-gray-400">{entry.capabilities.long_context}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  );
}
