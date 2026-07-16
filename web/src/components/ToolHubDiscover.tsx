import { useState } from 'react';
import { ArrowUpRight, Shield, Cpu, Search, Globe, RefreshCcw, Database, X, Check } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import {
  evaluateRepo, searchRepos, saveCandidate,
  type EvalResult, type SearchItem,
} from '../api/discovery';
import RepoDossier from './RepoDossier';
import type { McpPrefill } from '../api/client.types';

// Re-export McpPrefill so existing importers (SavedCandidates) keep their path.
export type { McpPrefill };

// Tool-Hub hero — the Google-style centered entry point of the Capability Library.
// One big input: a GitHub link / owner/repo → backend /discovery/evaluate → project
// dossier card; anything else → GitHub search → result rows with per-row Evaluate.
// Read-only discovery; all "add" actions live on the dossier and reuse locked paths.

const REPO_REF = /^(?:https?:\/\/(?:www\.)?github\.com\/)?[\w.-]+\/[\w.-]+\/?$/;
const looksLikeRepoRef = (s: string): boolean =>
  REPO_REF.test(s.trim()) || /github\.com\//i.test(s);

export default function ToolHubDiscover({ onMcpAdded }: { onMcpAdded?: () => void } = {}) {
  const { t } = useTranslation();

  const [query, setQuery] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<EvalResult | null>(null);
  const [items, setItems] = useState<SearchItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [rowBusy, setRowBusy] = useState<string | null>(null);
  const [catalogNotice, setCatalogNotice] = useState<string | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);

  const research = async () => {
    const q = query.trim();
    if (!q || busy) return;
    setBusy(true);
    setError(null);
    setCatalogNotice(null);
    setCatalogError(null);
    try {
      if (looksLikeRepoRef(q)) {
        setItems([]);
        setResult(await evaluateRepo(q));
      } else {
        setResult(null);
        setItems(await searchRepos(q));
      }
    } catch (e) {
      setResult(null);
      setItems([]);
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  };

  const evaluateItem = async (fullName: string) => {
    setRowBusy(fullName);
    setError(null);
    try {
      setResult(await evaluateRepo(fullName));
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setRowBusy(null);
    }
  };

  const saveItem = async (item: SearchItem) => {
    setCatalogNotice(null);
    setCatalogError(null);
    try {
      const snapshot =
        result?.repo.full_name === item.full_name ? result : await evaluateRepo(item.full_name);
      await saveCandidate(snapshot);
      setCatalogNotice(`Saved ${item.full_name} to catalog.`);
    } catch (e) {
      setCatalogError(String(e instanceof Error ? e.message : e));
    }
  };

  const trustBadgeCls = (tier: 'high' | 'medium' | 'low') =>
    tier === 'high'
      ? 'bg-success/15 text-success border-success/30'
      : tier === 'medium'
      ? 'bg-warning/15 text-warning border-warning/30'
      : 'bg-danger/15 text-danger border-danger/30';

  return (
    <div className="mb-10 select-text">
      {/* Centered hero */}
      <div className="max-w-3xl mx-auto text-center pt-8 pb-2">
        <div className="w-12 h-12 rounded-2xl bg-primary/10 border border-primary/30 flex items-center justify-center mx-auto mb-4 shadow-inner shadow-black/20">
          <Globe className="w-6 h-6 text-primary" />
        </div>
        <h2 className="text-xl font-bold font-sans text-foreground tracking-wide">
          {t('capabilities.title')}
        </h2>
        <p className="text-[12px] text-subtle-foreground font-sans mt-1 mb-6">
          {t('capabilities.subtitle')}
        </p>

        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-4 top-3.5 w-4.5 h-4.5 text-subtle-foreground" />
            <input
              type="text"
              placeholder={t('capabilities.hero.placeholder')}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') research(); }}
              className="w-full bg-background border border-border-strong focus:border-primary focus:ring-1 focus:ring-ring rounded-2xl pl-11 pr-4 py-3 text-sm text-foreground placeholder-subtle-foreground focus:outline-none transition-all font-sans"
            />
          </div>
          <button
            onClick={research}
            disabled={busy || !query.trim()}
            className="px-6 py-3 bg-primary hover:bg-primary-hover text-primary-foreground text-xs font-bold font-mono uppercase rounded-2xl flex items-center gap-1.5 shrink-0 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {busy ? <RefreshCcw className="w-4 h-4 animate-spin" /> : <Cpu className="w-4 h-4" />}
            <span>{t('capabilities.hero.research')}</span>
          </button>
        </div>
        <p className="text-[10.5px] text-subtle-foreground font-sans mt-2">{t('capabilities.hero.hint')}</p>

        {error && (
          <div className="flex items-start gap-2 bg-danger/15 border border-danger/40 rounded-xl px-4 py-3 text-[11px] text-danger font-sans mt-4 text-left">
            <X className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}
        {catalogNotice && (
          <div className="flex items-start gap-2 bg-success/15 border border-success/40 rounded-xl px-4 py-3 text-[11px] text-success font-sans mt-4 text-left">
            <Check className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            <span>{catalogNotice}</span>
          </div>
        )}
        {catalogError && (
          <div className="flex items-start gap-2 bg-danger/15 border border-danger/40 rounded-xl px-4 py-3 text-[11px] text-danger font-sans mt-4 text-left">
            <X className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            <span>{catalogError}</span>
          </div>
        )}
      </div>

      {/* Project dossier — grounded in the /discovery/evaluate response */}
      {result && (
        <div className="max-w-3xl mx-auto mt-6">
          <RepoDossier key={result.repo.full_name} result={result} onMcpAdded={onMcpAdded} />
        </div>
      )}

      {/* Search results (free-text queries) */}
      {items.length > 0 && (
        <div className="max-w-3xl mx-auto mt-6 space-y-2 text-left">
          <span className="text-[9.5px] font-mono text-subtle-foreground uppercase tracking-widest block">
            {t('capabilities.hero.results')}
          </span>
          {items.map((item) => (
            <div
              key={item.full_name}
              className="bg-background border border-border-strong rounded-xl px-4 py-3 flex flex-col sm:flex-row sm:items-center justify-between gap-3"
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <a
                    href={item.html_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[12px] font-bold text-foreground hover:text-primary transition-colors inline-flex items-center gap-1"
                  >
                    {item.full_name}
                    <ArrowUpRight className="w-3 h-3" />
                  </a>
                  <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[9px] font-bold font-mono uppercase tracking-wider border ${trustBadgeCls(item.trust.tier)}`}>
                    <Shield className="w-2.5 h-2.5" />
                    {item.trust.tier}
                  </span>
                </div>
                <p className="text-[10.5px] text-subtle-foreground font-mono mt-1">
                  ⭐{item.stars} · ⑂{item.forks} · {item.license ?? t('capabilities.dossier.no_license')} · {item.pushed_days ?? '?'}d
                </p>
                {item.description && (
                  <p className="text-[11px] text-muted-foreground font-sans mt-1 line-clamp-2">{item.description}</p>
                )}
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <button
                  type="button"
                  onClick={() => evaluateItem(item.full_name)}
                  disabled={rowBusy === item.full_name}
                  className="px-3 py-1.5 bg-surface hover:bg-foreground/[0.04] border border-border hover:border-border-strong text-muted-foreground hover:text-foreground text-[10px] font-mono uppercase rounded-lg transition-all flex items-center gap-1 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {rowBusy === item.full_name ? <RefreshCcw className="w-3 h-3 animate-spin" /> : <Cpu className="w-3 h-3" />}
                  <span>{t('capabilities.hero.evaluate')}</span>
                </button>
                <button
                  type="button"
                  onClick={() => saveItem(item)}
                  className="px-3 py-1.5 bg-primary/10 hover:bg-primary/20 border border-primary/30 text-primary text-[10px] font-mono uppercase rounded-lg transition-all flex items-center gap-1"
                >
                  <Database className="w-3 h-3" />
                  <span>{t('capabilities.hero.save')}</span>
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
