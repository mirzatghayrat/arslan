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
import Select from '../Select';

export interface SearchToolsSectionProps {
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
}: SearchToolsSectionProps) {
  const { t } = useTranslation();
  const [showSearchKey, setShowSearchKey] = useState(false);
  const [showGithubToken, setShowGithubToken] = useState(false);

  return (
    <div className="bg-surface/60 border border-border rounded-2xl p-6 space-y-6">
      <div className="flex items-center gap-2 pb-4 border-b border-border/50 select-none">
        <Search className="w-4.5 h-4.5 text-primary" />
        <h3 className="text-xs font-semibold font-mono uppercase tracking-widest text-foreground leading-none">{t('settings.sectionSearch')}</h3>
      </div>

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
            Tavily / Google Search API Private key
          </label>
          <div className="relative">
            <input
              id="settings-search-key"
              type={showSearchKey ? "text" : "password"}
              value={searchKey}
              onChange={(e) => onSearchKeyChange(e.target.value)}
              onBlur={(e) => onSearchKeyBlur?.(e.target.value)}
              className="w-full bg-surface border border-border-strong focus:border-primary focus:ring-1 focus:ring-ring rounded-xl px-4 py-3 text-xs text-foreground placeholder-subtle-foreground focus:outline-none pr-12 transition-all font-mono"
              placeholder="Enter search provider key..."
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
            Allocated to standard spawns carrying "Web Search" capability chips. Ensure live indices limits are sufficient.
          </p>
        </div>
      </div>

      {/* GitHub Token input — secret, raises Tool-Hub discovery rate limit */}
      <div className="space-y-2">
        <label className="block text-[10.5px] font-mono font-medium text-muted-foreground uppercase tracking-wide">
          GitHub Token (optional — raises rate limit)
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
