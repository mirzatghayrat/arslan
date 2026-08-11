/**
 * SearchToolsSection — the "Search & Tools" settings section.
 *
 * Self-contained card lifted verbatim out of SettingsScreen's `search` slot.
 * Per spec B1 this section groups the search provider + search key AND the
 * GitHub token (the token belongs here — its earlier mis-labeling, not
 * mis-placement, was spec problem 3). The eye-toggle state for the two secret
 * fields is now local to this component.
 *
 * Presentational: owns NO persistence. onChange callbacks are value-based so the
 * host keeps the exact save path it had before extraction (Task 6 converts these
 * to blur-save without touching this component's surface).
 */

import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Search, Eye, EyeOff } from 'lucide-react';
import { testSearchInstance, type SearchProbeResult } from '../../api/client';
import Select from '../Select';
import CryptoHealthNotice from './CryptoHealthNotice';
import type { CryptoHealth } from '../../lib/cryptoHealth';

export interface SearchToolsSectionProps {
  /** Why stored secrets cannot be read, or null when unknown/healthy. */
  cryptoHealth?: CryptoHealth | null;
  /** Current search provider key (e.g. "tavily"). */
  searchProvider: string;
  /** Available search provider keys for the Select options. */
  searchProviders: string[];
  onSearchProviderChange: (value: string) => void;
  /** Search API key (masked). */
  searchKey: string;
  onSearchKeyChange: (value: string) => void;
  /**
   * Blur-save for the search key (key-type field persists on blur only, never
   * per-keystroke — the user's constraint). Optional so presentational tests can
   * omit it; the host wires it to flushField.
   */
  onSearchKeyBlur?: (value: string) => void;
  /** GitHub token (masked, optional). */
  githubToken: string;
  onGithubTokenChange: (value: string) => void;
  /** Blur-save for the GitHub token (key-type field — blur only). */
  onGithubTokenBlur?: (value: string) => void;
  /** Address of a self-hosted SearXNG instance. Plain text, not a secret. */
  searchBaseUrl?: string;
  onSearchBaseUrlChange?: (value: string) => void;
  onSearchBaseUrlBlur?: (value: string) => void;
}

export default function SearchToolsSection({
  searchProvider,
  searchProviders,
  onSearchProviderChange,
  searchKey,
  onSearchKeyChange,
  onSearchKeyBlur,
  githubToken,
  onGithubTokenChange,
  onGithubTokenBlur,
  searchBaseUrl = '',
  onSearchBaseUrlChange,
  onSearchBaseUrlBlur,
  cryptoHealth = null,
}: SearchToolsSectionProps) {
  const { t } = useTranslation();
  const [showSearchKey, setShowSearchKey] = useState(false);
  const [showGithubToken, setShowGithubToken] = useState(false);
  const [probing, setProbing] = useState(false);
  const [probe, setProbe] = useState<SearchProbeResult | null>(null);

  // The address field belongs to exactly one provider. Showing it for the others
  // would put a live-looking control on screen that nothing reads.
  const needsBaseUrl = searchProvider === 'searxng';

  const runProbe = async () => {
    if (!searchBaseUrl.trim()) {
      setProbe({ verdict: 'unreachable' });
      return;
    }
    setProbing(true);
    try {
      setProbe(await testSearchInstance({ base_url: searchBaseUrl.trim() }));
    } catch {
      // A rejected request must still say something. Leaving the box empty is the
      // silent-failure shape this whole feature exists to remove.
      setProbe({ verdict: 'unreachable' });
    } finally {
      setProbing(false);
    }
  };

  const verdictText = (r: SearchProbeResult): string => {
    switch (r.verdict) {
      case 'ok':
        return `${t('settings.searxngVerdictOk')} (${r.result_count ?? 0})`;
      case 'json_disabled':
        return t('settings.searxngVerdictJsonDisabled');
      case 'not_searxng':
        return t('settings.searxngVerdictNotSearxng');
      default:
        return t('settings.searxngVerdictUnreachable');
    }
  };

  return (
    <div className="bg-surface/60 border border-border rounded-2xl p-6 space-y-6">
      <div className="flex items-center gap-2 pb-4 border-b border-border/50 select-none">
        <Search className="w-4.5 h-4.5 text-primary" />
        <h3 className="text-xs font-semibold font-mono uppercase tracking-widest text-foreground leading-none">{t('settings.sectionSearch')}</h3>
      </div>
      <CryptoHealthNotice health={cryptoHealth} />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Search Provider select */}
        <div className="space-y-2">
          <label
            htmlFor="settings-search-provider"
            className="block text-[10.5px] font-mono font-medium text-muted-foreground uppercase tracking-wide"
          >
            {t('settings.labelSearchProvider')}
          </label>
          <Select
            id="settings-search-provider"
            value={searchProvider}
            onChange={(v) => onSearchProviderChange(v)}
            options={
              searchProviders.length > 0
                ? searchProviders.map((k) => ({
                    value: k,
                    label: k.charAt(0).toUpperCase() + k.slice(1),
                  }))
                : [{ value: searchProvider, label: searchProvider || 'Loading…' }]
            }
            ariaLabel={t('settings.labelSearchProvider')}
          />
        </div>

        {/* Search API Key input */}
        <div className="space-y-2">
          <label className="block text-[10.5px] font-mono font-medium text-muted-foreground uppercase tracking-wide">
            {t('settings.labelSearchKey')}
          </label>
          <div className="relative">
            <input
              id="settings-search-key"
              type={showSearchKey ? "text" : "password"}
              value={searchKey}
              onChange={(e) => onSearchKeyChange(e.target.value)}
              onBlur={(e) => onSearchKeyBlur?.(e.target.value)}
              className="w-full bg-surface border border-border-strong focus:border-primary focus:ring-1 focus:ring-ring rounded-xl px-4 py-3 text-xs text-foreground placeholder-subtle-foreground focus:outline-none pr-12 transition-all font-mono"
              placeholder={t('settings.placeholderSearchKey')}
            />
            <button
              id="toggle-show-search-key"
              type="button"
              onClick={() => setShowSearchKey(!showSearchKey)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-subtle-foreground hover:text-foreground transition-colors"
            >
              {showSearchKey ? <EyeOff className="w-4.5 h-4.5" /> : <Eye className="w-4.5 h-4.5" />}
            </button>
          </div>
          <p className="text-[10px] text-subtle-foreground font-sans leading-relaxed">
            {/* This paragraph was hardcoded English AND said the wrong thing. The
                localized hint existed in six languages and nothing rendered it, so
                nobody ever saw "there is a free key" — or, now, "you do not need
                one at all". */}
            {t('settings.search_api_key_hint')}
          </p>
        </div>
      </div>

      {needsBaseUrl && (
        <div className="space-y-2">
          <label
            htmlFor="settings-search-base-url"
            className="block text-[10.5px] font-mono font-medium text-muted-foreground uppercase tracking-wide"
          >
            {t('settings.labelSearchBaseUrl')}
          </label>
          <div className="flex gap-2">
            <input
              id="settings-search-base-url"
              data-testid="searxng-base-url"
              type="text"
              value={searchBaseUrl}
              onChange={(e) => onSearchBaseUrlChange?.(e.target.value)}
              onBlur={(e) => onSearchBaseUrlBlur?.(e.target.value)}
              className="flex-1 bg-surface border border-border-strong focus:border-primary focus:ring-1 focus:ring-ring rounded-xl px-4 py-3 text-xs text-foreground placeholder-subtle-foreground focus:outline-none transition-all font-mono"
              placeholder="http://192.168.1.10:8080"
            />
            <button
              type="button"
              data-testid="searxng-test-button"
              onClick={runProbe}
              disabled={probing}
              className="shrink-0 px-4 py-3 rounded-xl border border-border-strong text-xs font-mono text-foreground hover:border-primary disabled:opacity-50 transition-all"
            >
              {t('settings.searxngTestButton')}
            </button>
          </div>
          {probe && (
            <p
              data-testid="searxng-test-result"
              role="status"
              data-verdict={probe.verdict}
              className="text-[10px] text-subtle-foreground font-sans leading-relaxed"
            >
              {verdictText(probe)}
            </p>
          )}
        </div>
      )}

      {/* GitHub Token input — secret, raises Tool-Hub discovery rate limit */}
      <div className="space-y-2">
        <label className="block text-[10.5px] font-mono font-medium text-muted-foreground uppercase tracking-wide">
          {t('settings.labelGithubToken')}
        </label>
        <div className="relative">
          <input
            id="settings-github-token"
            type={showGithubToken ? "text" : "password"}
            value={githubToken}
            onChange={(e) => onGithubTokenChange(e.target.value)}
            onBlur={(e) => onGithubTokenBlur?.(e.target.value)}
            className="w-full bg-surface border border-border-strong focus:border-primary focus:ring-1 focus:ring-ring rounded-xl px-4 py-3 text-xs text-foreground placeholder-subtle-foreground focus:outline-none pr-12 transition-all font-mono"
            placeholder="ghp_… (optional)"
          />
          <button
            id="toggle-show-github-token"
            type="button"
            onClick={() => setShowGithubToken(!showGithubToken)}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-subtle-foreground hover:text-foreground transition-colors"
          >
            {showGithubToken ? <EyeOff className="w-4.5 h-4.5" /> : <Eye className="w-4.5 h-4.5" />}
          </button>
        </div>
        <p className="text-[10px] text-subtle-foreground font-sans leading-relaxed">
          Used by the Tool-Hub to evaluate GitHub repos. Without a token, GitHub rate-limits anonymous requests.
        </p>
      </div>
    </div>
  );
}