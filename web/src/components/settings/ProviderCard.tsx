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
        'border-b border-border transition-colors',
        selected ? 'bg-surface/40' : 'hover:bg-surface/30',
      ].join(' ')}
    >
      <button
        type="button"
        data-testid={`provider-card-row-${index}`}
        data-selected={selected ? 'true' : 'false'}
        aria-expanded={selected}
        aria-controls={`provider-details-${config.id}`}
        onClick={() => onSelect(config.id)}
        className="w-full flex items-center gap-4 px-3 py-5 text-left cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
      >
        <span className="flex items-center justify-center w-10 h-10 text-primary/80 shrink-0"><Cpu className="w-6 h-6" /></span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <span className="text-sm font-sans font-semibold text-foreground truncate">
              {label}
            </span>
            {config.is_primary && (
              <span className="inline-flex items-center gap-1 text-primary bg-primary/8 rounded-md px-1.5 py-0.5 text-[10px] flex-shrink-0" title={t('settings.primary')}>
                <span>{t('settings.primary')}</span>
              </span>
            )}
          </div>
          <span className="block text-xs font-mono text-muted-foreground truncate mt-1">
            {config.model}
          </span>
        </div>

        <span className="flex flex-col items-end gap-1 shrink-0">
          <ProviderStatusPill status={status.status} testId={`provider-status-${index}`} />
          {status.at && <span className="text-[10px] text-muted-foreground hidden sm:inline">{formatRelativeTime(status.at, t)}</span>}
        </span>
        <span className="hidden sm:inline-flex border border-border rounded-lg px-5 py-1.5 text-xs text-foreground ml-3">{t('settings.editModel')}</span>
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
          className="mx-4 mb-3 -mt-1 pl-3 py-1 border-l-2 border-danger/40 text-xs leading-relaxed text-danger font-sans"
        >
          {status.reason}
        </p>
      )}

      {selected && children && (
        <div id={`provider-details-${config.id}`} className="border-t border-border/70 px-4 pb-4 pt-4">{children}</div>
      )}
    </div>
  );
}
