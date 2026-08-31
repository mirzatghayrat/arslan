/**
 * The model chip in the composer: which model is about to answer, and a way to
 * change it without leaving the conversation.
 *
 * It used to render `settings.llm_provider · settings.llm_model` — two fields
 * that api/adapters.ts has not mapped since the multi-config list became the
 * source of truth. They are always empty, so the chip always rendered a bare
 * "·". It was not a chip missing a dropdown; it was a chip displaying two dead
 * fields. Reading the primary ProviderConfig fixes the display, and once it is
 * reading the real rows it can also carry their status and switch between them.
 */

import React, { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Cpu, ChevronDown, Check } from 'lucide-react';
import type { ProviderConfig, ProviderOption } from '../api/client.types';
import { providerStatus, type ProviderStatus } from '../lib/providerStatus';

const DOT: Record<ProviderStatus, string> = {
  ok: 'bg-success',
  failed: 'bg-danger',
  untested: 'bg-subtle-foreground/50',
  testing: 'bg-subtle-foreground/50 animate-pulse',
};

export interface ModelSwitcherProps {
  configs: ProviderConfig[];
  llmProviders: ProviderOption[];
  /** Ids whose launch-time test is still in flight. */
  testingIds?: Set<number>;
  onSelect: (id: number) => void;
  onManage?: () => void;
}

export default function ModelSwitcher({
  configs,
  llmProviders,
  testingIds,
  onSelect,
  onManage,
}: ModelSwitcherProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', away);
    document.addEventListener('keydown', esc);
    return () => {
      document.removeEventListener('mousedown', away);
      document.removeEventListener('keydown', esc);
    };
  }, [open]);

  const labelFor = (c: ProviderConfig) =>
    llmProviders.find((p) => p.key === c.provider)?.label ?? c.label ?? c.provider;

  const statusFor = (c: ProviderConfig) =>
    providerStatus(c, testingIds?.has(c.id) ? { state: 'testing' } : undefined);

  const active = configs.find((c) => c.is_primary) ?? configs[0] ?? null;

  if (!active) {
    return (
      <button
        type="button"
        data-testid="model-switcher-empty"
        onClick={onManage}
        className="flex items-center gap-1.5 bg-background/40 px-2.5 py-1 rounded-full border border-border text-[10px] font-mono text-subtle-foreground hover:border-primary/40 transition-colors"
      >
        <Cpu className="w-3 h-3 flex-shrink-0" />
        {t('settings.modelSwitcherNone')}
      </button>
    );
  }

  return (
    <div className="relative" ref={boxRef}>
      <button
        type="button"
        data-testid="model-switcher"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 bg-background/40 px-2.5 py-1 rounded-full border border-border hover:border-primary/40 text-[10px] font-mono text-muted-foreground max-w-[220px] transition-colors"
      >
        <span
          data-testid="model-switcher-dot"
          data-status={statusFor(active).status}
          className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${DOT[statusFor(active).status]}`}
        />
        <span className="truncate">
          {labelFor(active)} · {active.model}
        </span>
        <ChevronDown className="w-2.5 h-2.5 flex-shrink-0 opacity-60" />
      </button>

      {open && (
        <div
          data-testid="model-switcher-menu"
          role="listbox"
          className="absolute bottom-full left-0 mb-2 w-[290px] bg-surface border border-border-strong rounded-xl p-1 shadow-lg z-50"
        >
          {configs.map((c) => {
            const view = statusFor(c);
            return (
              <button
                key={c.id}
                type="button"
                role="option"
                aria-selected={c.is_primary}
                data-testid={`model-switcher-option-${c.id}`}
                onClick={() => {
                  onSelect(c.id);
                  setOpen(false);
                }}
                className={`w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-left transition-colors ${
                  c.is_primary ? 'bg-primary/5' : 'hover:bg-surface-raised'
                }`}
              >
                <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${DOT[view.status]}`} />
                <span className="flex-1 min-w-0">
                  <span className="block text-[11px] font-mono text-foreground truncate">
                    {labelFor(c)}
                  </span>
                  {/* A broken model says WHY right here. Picking one only to have
                      the next message fail is the loop this whole change exists
                      to close. */}
                  <span className="block text-[9.5px] font-mono text-subtle-foreground truncate mt-0.5">
                    {view.status === 'failed' && view.reason ? view.reason : c.model}
                  </span>
                </span>
                {c.is_primary && <Check className="w-3 h-3 text-primary flex-shrink-0" />}
              </button>
            );
          })}

          {onManage && (
            <button
              type="button"
              data-testid="model-switcher-manage"
              onClick={() => {
                onManage();
                setOpen(false);
              }}
              className="w-full mt-1 pt-2 border-t border-border px-2.5 pb-1.5 text-left text-[11px] font-mono text-muted-foreground hover:text-primary transition-colors"
            >
              {t('settings.modelSwitcherManage')}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
