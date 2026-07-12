/**
 * CapabilityBadges — per-model capability badges with a Cherry-style override
 * (spec B2). Net-new for Settings Task 3.
 *
 * Renders tools / vision / reasoning badges for the selected model. A badge is
 * "active" when the API-derived `capabilities` include it. The user can click a
 * badge to override it ON/OFF; the override persists in localStorage keyed by
 * `${configId}:${model}:${cap}` and is MERGED over the API caps at RENDER time
 * (effective = override ?? apiHas) so a manual override is NOT clobbered when
 * the model list refreshes.
 *
 * Presentational + localStorage-only: it holds no server state. localStorage is
 * read at every render (via a force-render tick on toggle) so the effective
 * state always reflects the current configId/model, and survives a
 * `capabilities` prop change.
 */

import React, { useReducer } from 'react';
import { useTranslation } from 'react-i18next';
import { Wrench, Eye, Brain } from 'lucide-react';

/** The three capabilities we surface as togglable badges (spec B2). */
const CAPS = ['tools', 'vision', 'reasoning'] as const;
type Cap = (typeof CAPS)[number];

const CAP_ICON: Record<Cap, typeof Wrench> = {
  tools: Wrench,
  vision: Eye,
  reasoning: Brain,
};

/** i18n label/tooltip key per capability (explicit map — greppable). */
const CAP_LABEL_KEY: Record<Cap, string> = {
  tools: 'settings.modelCapTools',
  vision: 'settings.modelCapVision',
  reasoning: 'settings.modelCapReasoning',
};

const OVERRIDE_PREFIX = 'arslan.capOverride';

/** localStorage key for a per-config, per-model capability override. */
export function capabilityOverrideKey(
  configId: number,
  model: string,
  cap: string,
): string {
  return `${OVERRIDE_PREFIX}:${configId}:${model}:${cap}`;
}

/** Read the stored override: true / false when set, undefined when absent. */
function readOverride(
  configId: number,
  model: string,
  cap: string,
): boolean | undefined {
  try {
    const v = localStorage.getItem(capabilityOverrideKey(configId, model, cap));
    return v === 'on' ? true : v === 'off' ? false : undefined;
  } catch {
    return undefined;
  }
}

export interface CapabilityBadgesProps {
  configId: number;
  model: string;
  /** API-derived capabilities for `model` (subset of tools/vision/reasoning). */
  capabilities: string[];
  /** Notified after a toggle with the capability and its new effective value. */
  onOverride?: (cap: string, value: boolean) => void;
}

export default function CapabilityBadges({
  configId,
  model,
  capabilities,
  onOverride,
}: CapabilityBadgesProps) {
  const { t } = useTranslation();
  // localStorage is the source of truth; bump a tick to re-render on toggle.
  const [, forceRender] = useReducer((x: number) => x + 1, 0);

  const effective = (cap: Cap): boolean => {
    const override = readOverride(configId, model, cap);
    return override !== undefined ? override : capabilities.includes(cap);
  };

  const toggle = (cap: Cap) => {
    const next = !effective(cap);
    try {
      localStorage.setItem(
        capabilityOverrideKey(configId, model, cap),
        next ? 'on' : 'off',
      );
    } catch {
      /* localStorage unavailable — the override just won't persist */
    }
    forceRender();
    onOverride?.(cap, next);
  };

  return (
    <div
      data-testid="capability-badges"
      className="mt-1.5 flex flex-wrap items-center gap-1.5"
    >
      <span className="text-[9px] font-mono uppercase tracking-wide text-subtle-foreground">
        {t('settings.capabilitiesLabel')}
      </span>
      {CAPS.map((cap) => {
        const Icon = CAP_ICON[cap];
        const active = effective(cap);
        return (
          <button
            key={cap}
            type="button"
            data-testid={`cap-badge-${cap}`}
            data-active={active ? 'true' : 'false'}
            onClick={() => toggle(cap)}
            title={t(CAP_LABEL_KEY[cap])}
            aria-label={t(CAP_LABEL_KEY[cap])}
            aria-pressed={active}
            className={[
              'flex items-center gap-1 px-1.5 py-0.5 text-[9px] font-mono rounded-md border transition-colors',
              active
                ? 'text-primary border-primary/50 bg-primary/10'
                : 'text-subtle-foreground border-border hover:border-primary/40 hover:text-muted-foreground',
            ].join(' ')}
          >
            <Icon className="w-2.5 h-2.5" />
            {t(CAP_LABEL_KEY[cap])}
          </button>
        );
      })}
    </div>
  );
}
