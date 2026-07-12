/**
 * RoutingStrategyCard — the routing strategy Select + "Suggest primary", lifted
 * out of ProviderConfigList into its own card at the TOP of the providers
 * section (above the master-detail). Presentational: owns NO state; the
 * container keeps the suggestion state + all handlers and passes them down.
 *
 * Behavior is UNCHANGED from the inline version: single/cost/balanced/
 * performance options with ≥2-config gating (non-single options disabled +
 * hint shown below 2 configs), and the Suggest-primary button + rationale panel
 * with "Use this".
 */

import React from 'react';
import { useTranslation } from 'react-i18next';
import type { SuggestPrimaryResult } from '../../api/client.types';
import Select from '../Select';
import type { SelectOption } from '../Select';

export interface RoutingStrategyCardProps {
  strategy: string;
  onStrategyChange?: (strategy: string) => void;
  /** Number of saved configs — gates the multi-provider strategies (≥2). */
  configCount: number;
  onSuggestPrimary?: () => void;
  suggestBusy?: boolean;
  suggestion?: SuggestPrimaryResult | null;
  onUseThis?: () => void;
  useThisBusy?: boolean;
}

export default function RoutingStrategyCard({
  strategy,
  onStrategyChange,
  configCount,
  onSuggestPrimary,
  suggestBusy = false,
  suggestion,
  onUseThis,
  useThisBusy = false,
}: RoutingStrategyCardProps) {
  const { t } = useTranslation();

  const canUseMultiStrategy = configCount >= 2;
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

  return (
    <div
      data-testid="routing-strategy-card"
      className="flex flex-col gap-3 bg-surface/60 border border-border/60 rounded-xl px-4 py-3"
    >
      {/* ── Strategy selector ── */}
      <div className="space-y-1.5">
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

      {/* ── Suggest primary + rationale ── */}
      <div className="space-y-2">
        <button
          type="button"
          onClick={onSuggestPrimary}
          disabled={suggestBusy}
          className="flex items-center gap-1.5 px-3 py-2 text-xs font-mono font-medium text-muted-foreground hover:text-primary border border-border hover:border-primary/50 rounded-xl transition-colors disabled:opacity-50"
        >
          {t('settings.btnSuggestPrimary')}
        </button>
        {suggestion && (
          <div className="flex items-start gap-3 bg-surface/80 border border-primary/20 rounded-xl px-4 py-3">
            <p className="flex-1 text-xs text-foreground font-mono">{suggestion.rationale}</p>
            <button
              type="button"
              onClick={onUseThis}
              disabled={useThisBusy}
              className="flex-shrink-0 px-2 py-1 text-[10px] font-mono font-medium text-primary border border-primary/40 hover:border-primary/80 rounded-lg transition-colors disabled:opacity-50"
            >
              {t('settings.btnUseThis')}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
