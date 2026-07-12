/**
 * ProviderMasterList — presentational left column of the provider master-detail
 * layout (spec B2). One row per saved config: connectivity dot + provider icon
 * + label + model id (small) + primary ★, plus a compact test-status indicator
 * (populated by "Test all"). A bottom "+ add provider" button opens the draft;
 * an active draft shows as a pending row.
 *
 * Owns NO state — selection, health overlay, and test status all live in the
 * container. The health dot is rendered via a container-supplied render prop so
 * the tri-state color/probe logic (and all its invariants) stays in one place.
 */

import React from 'react';
import { useTranslation } from 'react-i18next';
import { Plus, Cpu, Loader2 } from 'lucide-react';
import type { ProviderConfig, ProviderOption } from '../../api/client.types';

interface TestStatusEntry {
  state: 'idle' | 'testing' | 'ok' | 'failed';
  error?: string;
}

export interface ProviderMasterListProps {
  configs: ProviderConfig[];
  llmProviders: ProviderOption[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  onAddDraft: () => void;
  draftActive: boolean;
  draftLabel?: string;
  testStatus: Record<number, TestStatusEntry>;
  /** Container-supplied per-row connectivity dot (keeps health logic centralized). */
  renderHealthDot: (config: ProviderConfig, idx: number) => React.ReactNode;
}

export default function ProviderMasterList({
  configs,
  llmProviders,
  selectedId,
  onSelect,
  onAddDraft,
  draftActive,
  draftLabel,
  testStatus,
  renderHealthDot,
}: ProviderMasterListProps) {
  const { t } = useTranslation();

  const labelFor = (c: ProviderConfig): string =>
    llmProviders.find((p) => p.key === c.provider)?.label ?? c.label ?? c.provider;

  return (
    <div
      data-testid="provider-master-list"
      className="flex flex-col gap-2 md:w-72 md:flex-shrink-0"
    >
      <div className="flex flex-col gap-2">
        {configs.map((config, idx) => {
          const selected = !draftActive && config.id === selectedId;
          const ts = testStatus[config.id];
          // Non-interactive layout container: the health-dot <button> and the
          // row-select <button> are SIBLINGS here (never nested) so both stay
          // independently mouse- and keyboard-activatable (no axe
          // nested-interactive, no keydown swallowing the dot's activation).
          return (
            <div
              key={config.id}
              className={[
                'w-full flex items-center gap-2 bg-surface border rounded-xl pl-3 pr-2 py-2.5 transition-colors',
                selected
                  ? 'border-primary/60 ring-1 ring-primary/20'
                  : 'border-border hover:border-primary/40',
              ].join(' ')}
            >
              {renderHealthDot(config, idx)}
              <button
                type="button"
                data-testid={`provider-master-row-${idx}`}
                data-selected={selected ? 'true' : 'false'}
                onClick={() => onSelect(config.id)}
                className="flex-1 min-w-0 flex items-center gap-2 text-left cursor-pointer"
              >
                <Cpu className="w-3.5 h-3.5 text-subtle-foreground flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs font-mono font-medium text-foreground truncate">
                      {labelFor(config)}
                    </span>
                    {config.is_primary && (
                      <span className="text-primary text-xs flex-shrink-0" title="Primary">
                        ★
                      </span>
                    )}
                  </div>
                  <span className="block text-[10px] font-mono text-subtle-foreground truncate">
                    {config.model}
                  </span>
                </div>
                {ts?.state === 'testing' && (
                  <Loader2 className="w-3 h-3 animate-spin text-muted-foreground flex-shrink-0" />
                )}
                {ts?.state === 'ok' && (
                  <span className="text-[10px] font-mono text-success flex-shrink-0">
                    {t('settings.testOk')}
                  </span>
                )}
                {ts?.state === 'failed' && (
                  <span className="text-[10px] font-mono text-danger flex-shrink-0 truncate max-w-[96px]">
                    ✗ {ts.error}
                  </span>
                )}
              </button>
            </div>
          );
        })}

        {draftActive && (
          <div
            data-testid="provider-master-draft-row"
            className="w-full flex items-center gap-2 bg-surface border border-dashed border-primary/40 rounded-xl px-3 py-2.5"
          >
            <Cpu className="w-3.5 h-3.5 text-subtle-foreground flex-shrink-0" />
            <span className="text-xs font-mono text-muted-foreground truncate">
              {draftLabel ?? t('settings.btnAddModel')}
            </span>
          </div>
        )}
      </div>

      <button
        type="button"
        onClick={onAddDraft}
        disabled={draftActive || llmProviders.length === 0}
        className="flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-mono font-medium text-primary border border-primary/30 hover:border-primary/60 rounded-xl transition-colors disabled:opacity-50"
      >
        <Plus className="w-3.5 h-3.5" />
        {t('settings.btnAddModel')}
      </button>
    </div>
  );
}
