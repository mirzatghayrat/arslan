import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { ProviderOption, ProviderConfig } from '../api/client.types';
import {
  addProviderConfig,
  updateProviderConfig,
  setPrimaryProviderConfig,
  deleteProviderConfig,
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
    </div>
  );
}
