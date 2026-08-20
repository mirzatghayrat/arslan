import React from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, ArrowUpRight, Bot } from 'lucide-react';

/**
 * Automation — everything that runs on its own and calls the model provider.
 *
 * The reason this section exists is not tidiness. Auto-evolution lived in
 * Advanced next to telemetry and shell policy, and background curation lived
 * NOWHERE: `curation_enabled` has shipped in `SettingsIn`/`SettingsOut` since
 * the curation round, `server/schemas.py:20` documents it as opt-in "because it
 * spends", and the app rendered no control for it at all. A user could not see
 * it, could not turn it off, and had no reason to suspect it existed.
 *
 * Putting them together is what makes the honest copy possible: the lede states
 * once, for all of them, that these cost money and are off by default. Split
 * across sections, someone turns on the second one having never read the
 * first one's warning.
 *
 * The two placeholder nav entries (Scheduled, Usage) are replaced by the link
 * at the bottom. A nav entry whose only job is to say "not here, go to
 * Diagnostics" is worse than a sentence saying so beside the related settings.
 */
export default function AutomationSection({
  evolutionAuto,
  onEvolutionAutoChange,
  evolutionMaxDispatches,
  onEvolutionMaxDispatchesChange,
  curationEnabled,
  onCurationEnabledChange,
  heartbeatEnabled,
  onHeartbeatEnabledChange,
  heartbeatChecklist,
  onHeartbeatChecklistChange,
  onOpenDiagnostics,
}: {
  evolutionAuto: boolean;
  onEvolutionAutoChange?: (v: boolean) => void;
  evolutionMaxDispatches: number | null;
  onEvolutionMaxDispatchesChange?: (v: number | null) => void;
  curationEnabled: boolean;
  onCurationEnabledChange?: (v: boolean) => void;
  heartbeatEnabled: boolean;
  onHeartbeatEnabledChange?: (v: boolean) => void;
  heartbeatChecklist: string;
  onHeartbeatChecklistChange?: (v: string) => void;
  onOpenDiagnostics?: () => void;
}) {
  const { t } = useTranslation();

  return (
    <div className="bg-surface border border-border rounded-2xl p-6" data-testid="settings-automation">
      <div className="flex items-center gap-2 mb-1">
        <Bot className="w-3.5 h-3.5 text-subtle-foreground" aria-hidden />
        <h3 className="text-xs font-semibold font-mono uppercase tracking-widest text-foreground leading-none">
          {t('settings.navAutomation')}
        </h3>
      </div>
      <p className="text-[11px] text-muted-foreground font-sans max-w-2xl mb-5">
        {t('settings.automationLede')}
      </p>

      <div className="space-y-5">
        {/* ── auto-evolution ─────────────────────────────────────────────── */}
        <div className="flex items-start justify-between gap-4">
          <div>
            <h4 className="text-xs font-bold text-foreground font-sans">
              {t('settings.labelEvolutionAuto')}
            </h4>
            <p className="text-[11px] text-muted-foreground font-sans mt-0.5 max-w-xl">
              {t('settings.evolutionAutoDesc')}
            </p>
            <p className="mt-1 flex items-start gap-1.5 text-[11px] text-warning font-sans max-w-xl"
               data-testid="evolution-auto-warning">
              <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-[1px]" aria-hidden />
              {/* 🔴 Conditional on purpose, and carried over verbatim from Advanced.
                  Saying "the cap counts dispatches" while no cap is set would describe
                  a guard that is not there. Only once a value exists does the other
                  sentence become true. */}
              <span>
                {evolutionMaxDispatches == null
                  ? t('settings.evolutionAutoSpendWarning')
                  : t('settings.evolutionAutoSpendWarningCapped', { cap: evolutionMaxDispatches })}
              </span>
            </p>
          </div>
          <input
            id="settings-evolution-auto-toggle"
            type="checkbox"
            checked={evolutionAuto}
            onChange={(e) => onEvolutionAutoChange?.(e.target.checked)}
            className="w-4 h-4 mt-1 shrink-0 text-primary bg-background border-border rounded focus:ring-0 select-none cursor-pointer"
          />
        </div>

        {/* ── dispatch cap (belongs beside the thing it caps) ─────────────── */}
        <div className="flex items-center justify-between">
          <div>
            <h4 className="text-xs font-bold text-foreground font-sans">
              {t('settings.labelEvolutionMaxDispatches')}
            </h4>
            <p className="text-[11px] text-muted-foreground font-sans mt-0.5 max-w-xl">
              {t('settings.evolutionMaxDispatchesDesc')}
            </p>
          </div>
          <input
            id="settings-evolution-max-dispatches"
            type="number"
            min={1}
            value={evolutionMaxDispatches ?? ''}
            placeholder={t('settings.evolutionMaxDispatchesUnset')}
            onChange={(e) => {
              const raw = e.target.value.trim();
              onEvolutionMaxDispatchesChange?.(raw === '' ? null : Number(raw));
            }}
            className="w-28 px-2 py-1 text-[11px] font-mono rounded bg-background border border-border focus:ring-0"
          />
        </div>

        <div className="h-[1px] bg-border/40" />

        {/* ── background curation — API-only until this round ─────────────── */}
        <div className="flex items-start justify-between gap-4">
          <div>
            <h4 className="text-xs font-bold text-foreground font-sans">
              {t('settings.labelCuration')}
            </h4>
            <p className="text-[11px] text-muted-foreground font-sans mt-0.5 max-w-xl">
              {t('settings.curationDesc')}
            </p>
            {/* 🔴 Unconditional, unlike the evolution warning above, and that
                asymmetry is the honest part: evolution HAS a dispatch cap the
                user can set, so its warning changes once they set one. This
                loop has no cap of its own, so there is no state in which a
                softer sentence would be true. */}
            <p className="mt-1 flex items-start gap-1.5 text-[11px] text-warning font-sans max-w-xl"
               data-testid="curation-spend-note">
              <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-[1px]" aria-hidden />
              <span>{t('settings.curationSpendNote')}</span>
            </p>
          </div>
          <input
            id="settings-curation-toggle"
            type="checkbox"
            checked={curationEnabled}
            onChange={(e) => onCurationEnabledChange?.(e.target.checked)}
            className="w-4 h-4 mt-1 shrink-0 text-primary bg-background border-border rounded focus:ring-0 select-none cursor-pointer"
          />
        </div>

        <div className="h-[1px] bg-border/40" />

        {/* ── heartbeat: a checklist Arslan re-reads on a cadence (P2 §1.3) ─ */}
        <div className="space-y-2" data-testid="settings-heartbeat">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h4 className="text-xs font-bold text-foreground font-sans">
                {t('settings.labelHeartbeat')}
              </h4>
              <p className="text-[11px] text-muted-foreground font-sans mt-0.5 max-w-xl">
                {t('settings.heartbeatDesc')}
              </p>
              <p className="mt-1 flex items-start gap-1.5 text-[11px] text-warning font-sans max-w-xl"
                 data-testid="heartbeat-spend-note">
                <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-[1px]" aria-hidden />
                <span>{t('settings.heartbeatSpendNote')}</span>
              </p>
            </div>
            <input
              id="settings-heartbeat-toggle"
              data-testid="heartbeat-toggle"
              type="checkbox"
              checked={heartbeatEnabled}
              onChange={(e) => onHeartbeatEnabledChange?.(e.target.checked)}
              className="w-4 h-4 mt-1 shrink-0 text-primary bg-background border-border rounded focus:ring-0 select-none cursor-pointer"
            />
          </div>
          {heartbeatEnabled && (
            <textarea
              id="settings-heartbeat-checklist"
              data-testid="heartbeat-checklist"
              rows={5}
              value={heartbeatChecklist}
              onChange={(e) => onHeartbeatChecklistChange?.(e.target.value)}
              placeholder={t('settings.heartbeatPlaceholder')}
              className="w-full bg-background border border-border rounded-lg px-3 py-2 text-[11px] text-foreground font-sans focus:border-primary focus:outline-none"
            />
          )}
        </div>

        <div className="h-[1px] bg-border/40" />

        {/* ── what the deleted placeholders used to point at ──────────────── */}
        <div className="flex items-center justify-between gap-4">
          <p className="text-[11px] text-muted-foreground font-sans max-w-xl">
            {t('settings.automationElsewhere')}
          </p>
          {onOpenDiagnostics && (
            <button
              type="button"
              data-testid="automation-open-diagnostics"
              onClick={onOpenDiagnostics}
              className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-mono text-muted-foreground hover:text-foreground hover:bg-foreground/[0.04] border border-border transition-colors whitespace-nowrap"
            >
              {t('settings.automationOpenDiagnostics')}
              <ArrowUpRight className="w-3 h-3" aria-hidden />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
