/**
 * MemoryDataSection — the "Memory & Data" settings section.
 *
 * Self-contained card lifted verbatim out of SettingsScreen's `memory` slot.
 * Per spec B1 this section groups: the semantic-retrieval embedding config
 * (<EmbeddingSettings/>, rendered as-is), the session-end distillation toggle,
 * and the run-debug detail retention-days input.
 *
 * Copy fix (spec B3): the retention label + hint were hardcoded Chinese inline;
 * they now come from the i18n keys settings.retentionLabel / settings.retentionHint
 * (×6 locales). The below-minimum clamp (Math.max(1, …)) is preserved so the
 * retention behavior is unchanged by the extraction.
 *
 * Presentational: owns NO persistence. onChange callbacks are value-based so the
 * host keeps the exact save path it had before extraction (Task 6 owns save).
 */

import React from 'react';
import { useTranslation } from 'react-i18next';
import { Database } from 'lucide-react';
import type { ProviderConfig } from '../../api/client.types';
import EmbeddingSettings from '../EmbeddingSettings';

export interface MemoryDataSectionProps {
  /** Multi-model provider configurations (for the embedding-provider picker). */
  providerConfigs: ProviderConfig[];
  /** Currently selected embedding config id (empty string = built-in local). */
  embeddingConfigId: string;
  onEmbeddingConfigIdChange: (value: string) => void;
  /** Whether to distill per-spawn preferences at session end. */
  distillOnSessionEnd: boolean;
  onDistillChange: (value: boolean) => void;
  /** Days before the boot sweep redacts sensitive/bulky run fields. */
  retentionDays: number;
  onRetentionDaysChange: (value: number) => void;
}

export default function MemoryDataSection({
  providerConfigs,
  embeddingConfigId,
  onEmbeddingConfigIdChange,
  distillOnSessionEnd,
  onDistillChange,
  retentionDays,
  onRetentionDaysChange,
}: MemoryDataSectionProps) {
  const { t } = useTranslation();

  return (
    <div className="bg-surface/60 border border-border rounded-2xl p-6 space-y-6">
      <div className="flex items-center gap-2 pb-4 border-b border-border/50 select-none">
        <Database className="w-4.5 h-4.5 text-primary" />
        <h3 className="text-xs font-semibold font-mono uppercase tracking-widest text-foreground leading-none">{t('settings.navMemory')}</h3>
      </div>

      <EmbeddingSettings
        providerConfigs={providerConfigs}
        embeddingConfigId={embeddingConfigId}
        onEmbeddingConfigIdChange={onEmbeddingConfigIdChange}
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
          checked={distillOnSessionEnd}
          onChange={(e) => onDistillChange(e.target.checked)}
          className="w-4 h-4 text-primary bg-background border-border rounded focus:ring-0 select-none cursor-pointer"
        />
      </div>

      {/* Separation divider */}
      <div className="h-[1px] bg-border/40"></div>

      {/* Run debug detail retention — days before boot sweep redacts sensitive/bulky run fields */}
      <div className="flex items-center justify-between">
        <div>
          <h4 className="text-xs font-bold text-foreground font-sans">{t('settings.retentionLabel')}</h4>
          <p className="text-[11px] text-muted-foreground font-sans mt-0.5 max-w-xl">
            {t('settings.retentionHint')}
          </p>
        </div>
        <input
          id="settings-run-debug-retention-days"
          type="number"
          min={1}
          value={retentionDays}
          onChange={(e) => onRetentionDaysChange(Math.max(1, Number(e.target.value) || 1))}
          className="w-24 bg-surface border border-border-strong focus:border-primary focus:ring-1 focus:ring-ring rounded-xl px-3 py-2 text-xs text-foreground focus:outline-none transition-all font-mono"
        />
      </div>
    </div>
  );
}
