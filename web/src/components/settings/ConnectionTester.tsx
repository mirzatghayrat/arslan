/**
 * ConnectionTester — two-level connection testing for the provider detail pane
 * (spec B2). Presentational: owns NO state/refs; every handler lives in the
 * container (ProviderConfigList).
 *
 * Level 1 "Test connection" = the fast /health probe (onProbeHealth). It renders
 * the PERSISTENT tri-state result (config.last_health / last_health_at, or the
 * live `health`/`lastHealthAt` overlay when the container passes one) + a
 * relative time, and the reachable_no_list caveat ("connected but no model list
 * — doesn't mean unusable; chat may still work").
 *
 * Level 2 "Deep test" = the existing real-chat round-trip (onDeepTest). It shows
 * that test's TRANSIENT ok / latency / error result. The two levels are visually
 * distinct: level 1 = connectivity, level 2 = usability.
 */

import React from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, PlugZap, FlaskConical } from 'lucide-react';
import type { ProviderConfig } from '../../api/client.types';
import { formatRelativeTime } from './relativeTime';

/** Transient level-2 (deep chat test) status for the selected config. */
export interface DeepTestStatus {
  state: 'idle' | 'testing' | 'ok' | 'failed';
  error?: string;
  latency?: number;
}

export interface ConnectionTesterProps {
  config: ProviderConfig;
  /** Live tri-state overlay from the container; falls back to config.last_health. */
  health?: string | null;
  /** Live probe timestamp from the container; falls back to config.last_health_at. */
  lastHealthAt?: string | null;
  onProbeHealth: (config: ProviderConfig) => void;
  onDeepTest: (config: ProviderConfig) => void;
  deepTestStatus?: DeepTestStatus;
}

/** Tri-state → dot color class (matches the master-list health dot). */
function dotClass(state: string | null): string {
  switch (state) {
    case 'reachable_models':
      return 'text-success';
    case 'reachable_no_list':
      return 'text-warning';
    case 'unreachable':
      return 'text-danger';
    default:
      return 'text-subtle-foreground';
  }
}

/** Tri-state → i18n tooltip key (matches the master-list health dot). */
function dotTitleKey(state: string | null): string {
  switch (state) {
    case 'reachable_models':
      return 'settings.healthDotModels';
    case 'reachable_no_list':
      return 'settings.healthDotNoList';
    case 'unreachable':
      return 'settings.healthDotUnreachable';
    default:
      return 'settings.healthDotUnknown';
  }
}

export default function ConnectionTester({
  config,
  health,
  lastHealthAt,
  onProbeHealth,
  onDeepTest,
  deepTestStatus,
}: ConnectionTesterProps) {
  const { t } = useTranslation();

  // Effective persistent state: the live overlay wins, else the config columns.
  const state = health ?? config.last_health ?? null;
  const at = lastHealthAt ?? config.last_health_at ?? null;
  const deep = deepTestStatus?.state ?? 'idle';

  return (
    <div
      data-testid="connection-tester"
      className="w-full flex flex-col gap-2 pt-2 mt-1 border-t border-border/40"
    >
      {/* ── Level 1: connectivity (fast /health probe) ── */}
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          data-testid="connection-test-level1"
          onClick={() => onProbeHealth(config)}
          className="flex items-center gap-1.5 px-2.5 py-1.5 text-[10px] font-mono font-medium text-muted-foreground hover:text-primary border border-border hover:border-primary/50 rounded-lg transition-colors"
        >
          <PlugZap className="w-3 h-3" />
          {t('settings.testConnection')}
        </button>
        <span
          data-testid="connection-health-dot"
          data-health-state={state ?? 'unknown'}
          title={t(dotTitleKey(state))}
          aria-label={t(dotTitleKey(state))}
          className={`text-[11px] leading-none ${dotClass(state)}`}
        >
          {state ? '●' : '○'}
        </span>
        {at && (
          <span className="text-[9px] font-mono text-subtle-foreground">
            {formatRelativeTime(at, t)}
          </span>
        )}
      </div>
      {state === 'reachable_no_list' && (
        <p
          data-testid="connection-reachable-no-list-note"
          className="text-[10px] font-mono text-warning/90"
        >
          {t('settings.reachableNoListNote')}
        </p>
      )}

      {/* ── Level 2: usability (real chat round-trip) ── */}
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          data-testid="connection-test-level2"
          onClick={() => onDeepTest(config)}
          disabled={deep === 'testing'}
          className="flex items-center gap-1.5 px-2.5 py-1.5 text-[10px] font-mono font-medium text-muted-foreground hover:text-primary border border-border hover:border-primary/50 rounded-lg transition-colors disabled:opacity-50"
        >
          {deep === 'testing' ? (
            <Loader2 className="w-3 h-3 animate-spin" />
          ) : (
            <FlaskConical className="w-3 h-3" />
          )}
          {t('settings.deepTest')}
        </button>
        {deep === 'ok' && (
          <span className="text-[10px] font-mono text-success">
            {t('settings.deepTestOk')}
            {deepTestStatus?.latency != null && ` · ${deepTestStatus.latency}ms`}
          </span>
        )}
        {deep === 'failed' && (
          <span className="text-[10px] font-mono text-danger truncate max-w-[220px]">
            ✗ {deepTestStatus?.error}
          </span>
        )}
      </div>
    </div>
  );
}
