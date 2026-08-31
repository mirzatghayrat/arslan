/**
 * One saved model, as one full-width card: a summary row that is always visible,
 * and the editable fields inline underneath when it is the selected one.
 *
 * This replaces a left list + right detail pane. That split cost the fields half
 * the width for no benefit — there was never more than one detail pane, so the
 * right column was empty space whenever nothing was selected, and cramped
 * whenever something was. Inline expansion keeps the whole list in view AND
 * gives the fields the full width.
 *
 * The card owns no state: selection, status and every handler live in the
 * container, so the "what does this dot mean" logic stays in one place.
 */

import React from 'react';
import { useTranslation } from 'react-i18next';
import { Cpu, ChevronRight } from 'lucide-react';
import type { ProviderConfig, ProviderOption } from '../../api/client.types';
import type { StatusView } from '../../lib/providerStatus';
import ProviderStatusPill from './ProviderStatusPill';
import { formatRelativeTime } from './relativeTime';

export interface ProviderCardProps {
  config: ProviderConfig;
  index: number;
  llmProviders: ProviderOption[];
  selected: boolean;
  onSelect: (id: number) => void;
  status: StatusView;
  /** The editable fields, rendered inline when this card is the selected one. */
  children?: React.ReactNode;
}

export default function ProviderCard({
  config,
  index,
  llmProviders,
  selected,
  onSelect,
  status,
  children,
}: ProviderCardProps) {
  const { t } = useTranslation();
  const label =
    llmProviders.find((p) => p.key === config.provider)?.label ?? config.label ?? config.provider;

  return (
    <div
      data-testid={`provider-card-${index}`}
      data-selected={selected ? 'true' : 'false'}
      className={[
        'bg-surface border rounded-xl overflow-hidden transition-colors',
        selected ? 'border-primary/50 ring-1 ring-primary/15' : 'border-border hover:border-primary/30',
      ].join(' ')}
    >
      <button
        type="button"
        data-testid={`provider-card-row-${index}`}
        data-selected={selected ? 'true' : 'false'}
        aria-expanded={selected}
        onClick={() => onSelect(config.id)}
        className="w-full flex items-center gap-3 px-4 py-3.5 text-left cursor-pointer"
      >
        <Cpu className="w-4 h-4 text-subtle-foreground flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <span className="text-[13px] font-mono font-semibold text-foreground truncate">
              {label}
            </span>
            {config.is_primary && (
              <span className="text-primary text-[11px] flex-shrink-0" title={t('settings.primary')}>
                ★
              </span>
            )}
          </div>
          <span className="block text-[11px] font-mono text-subtle-foreground truncate mt-0.5">
            {config.model}
          </span>
        </div>

        <ProviderStatusPill status={status.status} testId={`provider-status-${index}`} />
        {status.at && (
          <span className="text-[9px] font-mono text-subtle-foreground hidden sm:inline">
            {formatRelativeTime(status.at, t)}
          </span>
        )}
        <ChevronRight
          className={`w-3.5 h-3.5 text-subtle-foreground flex-shrink-0 transition-transform ${
            selected ? 'rotate-90' : ''
          }`}
        />
      </button>

      {/* The reason lives on the collapsed row too. Someone scanning the list to
          find out why nothing works should not have to open each card to learn
          it — that was the old "click the dot to find out" problem in a new shape. */}
      {status.status === 'failed' && status.reason && (
        <p
          data-testid={`provider-reason-${index}`}
          className="mx-4 mb-3 -mt-1 px-3 py-2 rounded-lg bg-danger/5 border border-danger/20 text-[11px] leading-relaxed text-danger font-sans"
        >
          {status.reason}
        </p>
      )}

      {selected && children && (
        <div className="border-t border-border bg-background/40 px-4 py-4">{children}</div>
      )}
    </div>
  );
}
