/**
 * "Model roles" — which task uses which model.
 *
 * A section of its own rather than part of `automation`, deliberately. That section's
 * whole narrative is a spend warning (auto-evolution, dispatch caps, curation, each
 * with honest copy about what the caps do and do not bound), and these slots do not
 * spend on their own — they only change which model handles a call that was going to
 * happen anyway. Mixing them in dilutes the warning, and collecting the spending
 * controls in one place is the entire reason that section exists.
 *
 * The empty-slot sentence is computed by `slotFallback`, not written per slot here:
 * the five slots have three different empty meanings, and duplicating that judgement
 * in the view is how one of them would quietly drift into a false line on screen.
 */
import React from 'react';
import { useTranslation } from 'react-i18next';
import { Cpu } from 'lucide-react';

import Select from '../Select';
import {
  MODEL_SLOTS,
  slotFallback,
  type SlotConfig,
  type SlotFallback,
} from '../../lib/modelSlots';

export interface ModelRolesSectionProps {
  /** settingsKey -> provider config id, "" when the slot is unset. */
  values: Record<string, string>;
  onChange: (settingsKey: string, value: string) => void;
  providerConfigs: SlotConfig[];
  /** AppSettings.llmStrategy — decides whether an unset slot is routed. */
  strategy: string;
  onGoToProviders?: () => void;
}

export default function ModelRolesSection({
  values,
  onChange,
  providerConfigs,
  strategy,
  onGoToProviders,
}: ModelRolesSectionProps) {
  const { t } = useTranslation();

  const fallbackText = (f: SlotFallback): string => {
    switch (f.kind) {
      case 'pinned-primary':
        return t('settings.slotFallbackPinnedPrimary').replace('{model}', f.modelLabel);
      case 'follows-primary':
        return t('settings.slotFallbackFollowsPrimary').replace('{model}', f.modelLabel);
      case 'routed':
        // No parenthetical naming the primary: the strategy may pick something else,
        // and naming it here would re-imply that the primary is doing the work.
        return t('settings.slotFallbackRouted');
      case 'follows-conversation':
        return t('settings.slotFallbackFollowsConversation');
      default:
        return t('settings.slotFallbackNoConfigs');
    }
  };

  const options = [
    { value: '', label: t('settings.slotUnset') },
    ...providerConfigs.map((c) => ({
      value: String(c.id),
      label: c.label?.trim() ? c.label : `${c.provider} (${c.model})`,
    })),
  ];

  return (
    <div className="bg-surface/60 border border-border rounded-2xl p-6 space-y-6">
      <div className="flex items-center gap-2 pb-4 border-b border-border/50 select-none">
        <Cpu className="w-4.5 h-4.5 text-primary" />
        <h3 className="text-xs font-semibold font-mono uppercase tracking-widest text-foreground leading-none">
          {t('settings.navModelRoles')}
        </h3>
      </div>
      <p className="text-[11px] text-muted-foreground font-sans leading-relaxed">
        {t('settings.modelRolesLede')}
      </p>

      {/* One way out, not five. Rendering it per slot stacked five identical
          links — noise, and noise is how a real prompt stops being read. */}
      {providerConfigs.length === 0 && onGoToProviders && (
        <button
          type="button"
          data-testid="slot-goto-providers"
          onClick={onGoToProviders}
          className="text-[11px] underline text-primary hover:text-foreground self-start"
        >
          {t('settings.slotGoToProviders')}
        </button>
      )}

      {MODEL_SLOTS.map((slot) => {
        const f = slotFallback(slot.id, { strategy, configs: providerConfigs });
        return (
          <div key={slot.id} className="space-y-2">
            <label
              htmlFor={`settings-slot-${slot.id}`}
              className="block text-[10.5px] font-mono font-medium text-muted-foreground uppercase tracking-wide"
            >
              {t(slot.labelKey)}
            </label>
            <p
              data-testid={`slot-purpose-${slot.id}`}
              className="text-[10px] text-subtle-foreground font-sans leading-relaxed"
            >
              {t(slot.purposeKey)}
            </p>
            {/* The testid lives on a wrapper rather than on Select: Select has ten
                call sites and does not forward arbitrary props, and widening its
                API for a test hook would be the wrong direction. */}
            <div data-testid={`slot-${slot.id}`}>
              <Select
                id={`settings-slot-${slot.id}`}
                value={values[slot.settingsKey] ?? ''}
                onChange={(v) => onChange(slot.settingsKey, v)}
                options={options}
                className="max-w-sm"
                ariaLabel={t(slot.labelKey)}
              />
            </div>
            <p
              data-testid={`slot-fallback-${slot.id}`}
              data-kind={f.kind}
              className="text-[10px] text-subtle-foreground font-sans leading-relaxed"
            >
              {fallbackText(f)}
            </p>
          </div>
        );
      })}

      <p
        data-testid="embedding-pointer"
        className="text-[10px] text-subtle-foreground font-sans leading-relaxed pt-2 border-t border-border/50"
      >
        {t('settings.modelRolesEmbeddingPointer')}
      </p>
    </div>
  );
}
