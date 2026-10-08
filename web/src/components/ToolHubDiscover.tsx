import { useState } from 'react';
import { Cpu, Search, Globe, RefreshCcw, X, Check } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { evaluateRepo, saveCandidate, type EvalResult } from '../api/discovery';
import { capabilitiesApi, type CapabilitySearch } from '../api/capabilities';
import RepoDossier from './RepoDossier';
import DiscoverResults from './capabilities/DiscoverResults';
import CandidateDossier from './capabilities/CandidateDossier';
import type { CapabilityCandidate } from '../api/capabilities';
import type { McpPrefill } from '../api/client.types';

// Re-export McpPrefill so existing importers (SavedCandidates) keep their path.
export type { McpPrefill };

// Tool-Hub hero — the Google-style centered entry point of the Capability Library.
// One big input: a GitHub link / owner/repo → backend /discovery/evaluate → project
// dossier card; anything else → 0.1.57 capability search (official MCP Registry + GitHub +
// skill libraries) → DiscoverResults with Look / Save per candidate.
// Read-only discovery; all "add" actions live on the dossier and reuse locked paths.

const REPO_REF = /^(?:https?:\/\/(?:www\.)?github\.com\/)?[\w.-]+\/[\w.-]+\/?$/;
const looksLikeRepoRef = (s: string): boolean =>
  REPO_REF.test(s.trim()) || /github\.com\//i.test(s);

export default function ToolHubDiscover({ onMcpAdded }: { onMcpAdded?: () => void } = {}) {
  const { t } = useTranslation();

  const [query, setQuery] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<EvalResult | null>(null);
  const [found, setFound] = useState<CapabilitySearch | null>(null);
  const [dossier, setDossier] = useState<CapabilityCandidate | null>(null);
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
        setFound(null);
        setResult(await evaluateRepo(q));
      } else {
        setResult(null);
        setFound(await capabilitiesApi.search(q));
      }
    } catch (e) {
      setResult(null);
      setFound(null);
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  };

  const evaluateItem = async (fullName: string, busyKey: string = fullName) => {
    setRowBusy(busyKey);
    setError(null);
    try {
      setResult(await evaluateRepo(fullName));
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setRowBusy(null);
    }
  };

  const saveItem = async (fullName: string, busyKey: string = fullName) => {
    setCatalogNotice(null);
    setCatalogError(null);
    setRowBusy(busyKey);
    try {
      const snapshot = result?.repo.full_name === fullName ? result : await evaluateRepo(fullName);
      await saveCandidate(snapshot);
      setCatalogNotice(`Saved ${fullName} to catalog.`);
    } catch (e) {
      setCatalogError(String(e instanceof Error ? e.message : e));
    } finally {
      setRowBusy(null);
    }
  };

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
            aria-busy={busy}
            className="px-6 py-3 bg-primary hover:bg-primary-hover text-primary-foreground text-xs font-bold font-mono uppercase rounded-2xl flex items-center gap-1.5 shrink-0 transition-colors disabled:cursor-not-allowed disabled:bg-primary/70"
          >
            {busy ? <RefreshCcw className="w-4 h-4 animate-spin" /> : <Cpu className="w-4 h-4" />}
            <span>{busy ? t('capabilities.hero.researching') : t('capabilities.hero.research')}</span>
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
        <div className="max-w-3xl mx-auto mt-6 animate-fade-in">
          <RepoDossier key={result.repo.full_name} result={result} onMcpAdded={onMcpAdded} />
        </div>
      )}

      {/* Search results (free-text queries): 0.1.57 — registry + GitHub + skill libraries */}
      {dossier && <CandidateDossier candidate={dossier} onClose={() => setDossier(null)}
        onInstalled={(r) => { if (r.state === 'on') onMcpAdded?.(); }} />}
      {found && (
        <DiscoverResults result={found} busyId={rowBusy}
          onLook={(c) => setDossier(c)}
          onSave={(c) => { if (c.repo) void saveItem(c.repo, c.id); }} />
      )}
    </div>
  );
}
