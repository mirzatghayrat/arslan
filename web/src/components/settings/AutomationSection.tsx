import React from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, ArrowUpRight, Bot } from 'lucide-react';
import ProactiveDiagnosisCap from './ProactiveDiagnosisCap';

/**
 * Automation — everything that runs on its own and calls the model provider.
 *
 * The reason this section exists is not tidiness. A control that spends and is
 * shown nowhere is one the user cannot see or stop: background curation once
 * shipped that way, API-only. (Curation itself went in C8-3, v0.1.63.)
 *
 * Putting them together is what makes the honest copy possible: the lede states
 * once, for all of them, that these cost money and are off by default. Split
 * across sections, someone turns on the second one having never read the
 * first one's warning.
 *
 * Usage and every run are on the Activity page, and scheduled tasks on their
 * own page (INB3); the line at the bottom says so beside the related settings. (0.1.48: auto-evolution went with the
 * experts it evolved.)
 */
export default function AutomationSection({
  heartbeatEnabled,
  onHeartbeatEnabledChange,
  heartbeatChecklist,
  onHeartbeatChecklistChange,
  onOpenActivity,
}: {
  heartbeatEnabled: boolean;
  onHeartbeatEnabledChange?: (v: boolean) => void;
  heartbeatChecklist: string;
  onHeartbeatChecklistChange?: (v: string) => void;
  onOpenActivity?: () => void;
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
        {/* ── heartbeat: a checklist Arslan re-reads on a cadence (P2 §1.3) ─ */}
        <div className="space-y-2" data-testid="settings-heartbeat">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h4 className="text-[13px] font-medium text-foreground">
                {t('settings.labelHeartbeat')}
              </h4>
              <p className="text-[12px] leading-snug text-muted-foreground mt-0.5 max-w-xl">
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
              className="kit-switch mt-0.5"
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

        {/* ── proactivity's cause guesses (0.1.47): capped per day, off by default ─ */}
        <ProactiveDiagnosisCap />

        <div className="h-[1px] bg-border/40" />

        {/* ── what the deleted placeholders used to point at ──────────────── */}
        <div className="flex items-center justify-between gap-4">
          <p className="text-[11px] text-muted-foreground font-sans max-w-xl">
            {t('settings.automationElsewhere')}
          </p>
          {onOpenActivity && (
            <button
              type="button"
              data-testid="automation-open-activity"
              onClick={onOpenActivity}
              className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-mono text-muted-foreground hover:text-foreground hover:bg-foreground/[0.04] border border-border transition-colors whitespace-nowrap"
            >
              {t('settings.automationOpenActivity')}
              <ArrowUpRight className="w-3 h-3" aria-hidden />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
