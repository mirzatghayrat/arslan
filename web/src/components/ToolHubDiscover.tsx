import { useState } from 'react';
import {
  ArrowUpRight, Shield, Cpu, ChevronDown, ChevronUp, Search, Globe,
  RefreshCcw, Plus, Database, X, Check, BookOpen,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import {
  evaluateRepo, searchRepos, saveCandidate,
  generateSkill, createSkill,
  type EvalResult, type SearchItem, type SkillDraft,
} from '../api/discovery';
import { addMcpServer } from '../api/mcp';
import RecommendedMcp from './RecommendedMcp';
import SkillImportPanel from './SkillImportPanel';
import type { McpPrefill } from '../data/mcpPresets';

// The type + isOneClick now live in the data module (breaks the RecommendedMcp import cycle);
// re-export McpPrefill so existing importers (Capabilities, SavedCandidates) keep their path.
export type { McpPrefill };

// Global Integration Discovery & Repository Engine (Tool-Hub) — LIVE.
// Read-only discovery: paste a GitHub repo → backend evaluates trust + classifies MCP.
// "Add" promotes the candidate into the live MCP registry via the existing P2b addMcpServer (locked).
export default function ToolHubDiscover({ onPrefillMcp, onMcpConnected }: {
  onPrefillMcp?: (d: McpPrefill) => void;
  onMcpConnected?: () => void;
} = {}) {
  const { t } = useTranslation();

  const [showSandboxSearch, setShowSandboxSearch] = useState(true);
  const [integrationQuery, setIntegrationQuery] = useState('');
  const [isEvaluating, setIsEvaluating] = useState(false);
  const [evaluationResult, setEvaluationResult] = useState<EvalResult | null>(null);
  const [evalError, setEvalError] = useState<string | null>(null);
  // Editable suggested-command draft (pre-filled from the LLM suggestion so the user can review/edit).
  const [draft, setDraft] = useState<{ transport: string; command: string; args: string; url: string }>({
    transport: 'stdio', command: '', args: '', url: '',
  });
  const [isAdding, setIsAdding] = useState(false);
  const [addNotice, setAddNotice] = useState<string | null>(null);
  const [addError, setAddError] = useState<string | null>(null);

  // GitHub search results + persistent Saved Candidates catalog.
  const [searchItems, setSearchItems] = useState<SearchItem[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [catalogNotice, setCatalogNotice] = useState<string | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);

  // "Add as Skill" — distill a repo into a SkillPack. generate (read-only) → editable draft
  // (the human-review/consent step — body is editable before Create) → create (safe/registered).
  // One draft panel at a time. The body is shown ONLY in a <textarea> (plain text, never HTML).
  const [skillBusyRef, setSkillBusyRef] = useState<string | null>(null);
  const [skillDraft, setSkillDraft] = useState<
    { full_name: string } & SkillDraft | null
  >(null);
  const [skillCreating, setSkillCreating] = useState(false);
  const [skillNotice, setSkillNotice] = useState<string | null>(null);
  const [skillError, setSkillError] = useState<string | null>(null);

  const handleGenerateSkill = async (fullName: string) => {
    setSkillBusyRef(fullName);
    setSkillDraft(null);
    setSkillNotice(null);
    setSkillError(null);
    try {
      const result = await generateSkill(fullName);
      if (!result.skill) {
        setSkillNotice(`Couldn't distill a skill from ${result.repo.full_name}.`);
        return;
      }
      setSkillDraft({ full_name: result.repo.full_name, ...result.skill });
    } catch (e) {
      setSkillError(String(e instanceof Error ? e.message : e));
    } finally {
      setSkillBusyRef(null);
    }
  };

  const handleCreateSkill = async () => {
    if (!skillDraft) return;
    setSkillCreating(true);
    setSkillNotice(null);
    setSkillError(null);
    try {
      await createSkill({
        full_name: skillDraft.full_name,
        name: skillDraft.name,
        category: skillDraft.category,
        description: skillDraft.description,
        body: skillDraft.body,
      });
      setSkillNotice('Added to Skills library (safe) — equip it from a spawn\'s skill menu.');
      setSkillDraft(null);
    } catch (e) {
      setSkillError(String(e instanceof Error ? e.message : e));
    } finally {
      setSkillCreating(false);
    }
  };

  const handleSearch = async (q: string) => {
    const trimmed = (q ?? '').trim();
    if (!trimmed) return;
    setIsSearching(true);
    setSearchError(null);
    try {
      setSearchItems(await searchRepos(trimmed));
    } catch (e) {
      setSearchItems([]);
      setSearchError(String(e instanceof Error ? e.message : e));
    } finally {
      setIsSearching(false);
    }
  };

  const handleSaveSnapshot = async (snapshot: EvalResult) => {
    setCatalogNotice(null);
    setCatalogError(null);
    try {
      await saveCandidate(snapshot);
      setCatalogNotice(`Saved ${snapshot.repo.full_name} to catalog.`);
    } catch (e) {
      setCatalogError(String(e instanceof Error ? e.message : e));
    }
  };

  const handleSaveSearchItem = async (item: SearchItem) => {
    setCatalogNotice(null);
    setCatalogError(null);
    try {
      const snapshot =
        evaluationResult?.repo.full_name === item.full_name
          ? evaluationResult
          : await evaluateRepo(item.full_name);
      await saveCandidate(snapshot);
      setCatalogNotice(`Saved ${item.full_name} to catalog.`);
    } catch (e) {
      setCatalogError(String(e instanceof Error ? e.message : e));
    }
  };

  // Trust tier → semantic token classes (shared by search rows).
  const trustBadgeCls = (tier: 'high' | 'medium' | 'low') =>
    tier === 'high'
      ? 'bg-success/15 text-success border-success/30'
      : tier === 'medium'
      ? 'bg-warning/15 text-warning border-warning/30'
      : 'bg-danger/15 text-danger border-danger/30';

  const handleEvaluateRepository = async (ref: string) => {
    const trimmed = (ref ?? '').trim();
    if (!trimmed) return;
    setIsEvaluating(true);
    setEvalError(null);
    setAddNotice(null);
    setAddError(null);
    try {
      const res = await evaluateRepo(trimmed);
      setEvaluationResult(res);
      const s = res.suggestion;
      setDraft({
        transport: s.transport ?? 'stdio',
        command: s.command ?? '',
        args: (s.args || []).join(' '),
        url: s.url ?? '',
      });
    } catch (e) {
      setEvaluationResult(null);
      setEvalError(String(e instanceof Error ? e.message : e));
    } finally {
      setIsEvaluating(false);
    }
  };

  const handleAddToMCP = async () => {
    if (!evaluationResult) return;
    const repo = evaluationResult.repo;
    setIsAdding(true);
    setAddNotice(null);
    setAddError(null);
    try {
      await addMcpServer({
        label: repo.full_name.split('/').pop()!,
        transport: draft.transport,
        command: draft.command,
        args: draft.args.split(/\s+/).filter(Boolean),
        url: draft.url || undefined,
        env: {},
      });
      setAddNotice('Added to MCP panel (locked) — open System Settings → MCP Servers to connect it.');
    } catch (e) {
      setAddError(String(e instanceof Error ? e.message : e));
    } finally {
      setIsAdding(false);
    }
  };

  const canAdd = Boolean(
    evaluationResult?.suggestion.is_mcp &&
    (draft.transport === 'http' ? draft.url.trim() : draft.command.trim())
  );

  return (
    <div className="bg-surface/40 border border-border-strong rounded-2xl p-6 mb-8 transition-all z-10 select-text">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-primary/10 border border-primary/30 flex items-center justify-center text-sm transition-colors shadow-inner shadow-black/40">
            <Globe className="w-5 h-5 text-primary" />
          </div>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="font-sans font-bold text-sm text-foreground tracking-wide">
                {t('ledger.tool_hub_title')} <span className="text-subtle-foreground font-normal text-xs ml-1">(Tool-Hub)</span>
              </h3>
            </div>
            <p className="text-[11.5px] text-subtle-foreground font-sans mt-0.5">
              {t('ledger.tool_hub_subtitle')}
            </p>
          </div>
        </div>

        <button
          onClick={() => setShowSandboxSearch(!showSandboxSearch)}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-surface/90 hover:bg-border text-muted-foreground rounded-lg border border-border-strong transition-all cursor-pointer text-xs font-medium font-sans"
        >
          <span>{showSandboxSearch ? t('common.collapse') : t('common.expand')}</span>
          {showSandboxSearch ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </button>
      </div>

      {showSandboxSearch && (
        <div className="mt-5 space-y-4 border-t border-border/40 pt-4">
          <div className="flex gap-2">
            <div className="relative flex-1">
              <Search className="absolute left-3.5 top-3 w-4 h-4 text-subtle-foreground" />
              <input
                type="text"
                placeholder={t('ledger.tool_hub_search_placeholder')}
                value={integrationQuery}
                onChange={(e) => setIntegrationQuery(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && !isEvaluating) handleEvaluateRepository(integrationQuery); }}
                className="w-full bg-background border border-border/60 focus:border-primary focus:ring-1 focus:ring-ring rounded-xl pl-10 pr-4 py-2.5 text-xs text-foreground placeholder-subtle-foreground focus:outline-none transition-all font-sans"
              />
            </div>
            <button
              onClick={() => handleSearch(integrationQuery)}
              disabled={isSearching || !integrationQuery.trim()}
              className="px-5 py-2.5 bg-surface/90 hover:bg-border text-foreground border border-border-strong text-xs font-bold font-mono uppercase rounded-xl flex items-center gap-1 shrink-0 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isSearching ? <RefreshCcw className="w-3.5 h-3.5 animate-spin" /> : <Search className="w-3.5 h-3.5" />}
              <span>Search</span>
            </button>
            <button
              onClick={() => handleEvaluateRepository(integrationQuery)}
              disabled={isEvaluating || !integrationQuery.trim()}
              className="px-5 py-2.5 bg-primary hover:bg-primary-hover text-primary-foreground text-xs font-bold font-mono uppercase rounded-xl flex items-center gap-1 shrink-0 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isEvaluating ? <RefreshCcw className="w-3.5 h-3.5 animate-spin" /> : <Cpu className="w-3.5 h-3.5" />}
              <span>{t('ledger.tool_hub_evaluate')}</span>
            </button>
          </div>

          {/* Recommended MCP servers — credential-free ones connect in one click; keyed ones
              prefill the add form. Replaces the old prefill-only preset chips. */}
          <div className="space-y-2">
            <span className="text-[10.5px] font-mono text-subtle-foreground select-none">{t('ledger.tool_hub_presets_label')}</span>
            <RecommendedMcp onPrefillMcp={onPrefillMcp} onChanged={onMcpConnected} />
          </div>

          {/* P3: faithful SKILL.md importer — verbatim, license-gated, scripts → sandbox */}
          <div className="border-t border-border/40 pt-4">
            <SkillImportPanel />
          </div>

          {evalError && (
            <div className="flex items-start gap-2 bg-danger/15 border border-danger/40 rounded-xl px-4 py-3 text-[11px] text-danger font-sans">
              <X className="w-3.5 h-3.5 shrink-0 mt-0.5" />
              <span>{evalError}</span>
            </div>
          )}

          {searchError && (
            <div className="flex items-start gap-2 bg-danger/15 border border-danger/40 rounded-xl px-4 py-3 text-[11px] text-danger font-sans">
              <X className="w-3.5 h-3.5 shrink-0 mt-0.5" />
              <span>{searchError}</span>
            </div>
          )}

          {/* Search results list */}
          {searchItems.length > 0 && (
            <div className="space-y-2">
              <span className="text-[9.5px] font-mono text-subtle-foreground uppercase tracking-widest block">Search results</span>
              {searchItems.map((item) => (
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
                      ⭐{item.stars} · {item.forks} forks · {item.license ?? 'no license'} · pushed {item.pushed_days ?? '?'}d ago
                    </p>
                    {item.description && (
                      <p className="text-[11px] text-muted-foreground font-sans mt-1 line-clamp-2">{item.description}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <button
                      type="button"
                      onClick={() => handleEvaluateRepository(item.full_name)}
                      className="px-3 py-1.5 bg-surface hover:bg-foreground/[0.04] border border-border hover:border-border-strong text-muted-foreground hover:text-foreground text-[10px] font-mono uppercase rounded-lg transition-all flex items-center gap-1"
                    >
                      <Cpu className="w-3 h-3" />
                      <span>Evaluate</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => handleSaveSearchItem(item)}
                      className="px-3 py-1.5 bg-primary/10 hover:bg-primary/20 border border-primary/30 text-primary text-[10px] font-mono uppercase rounded-lg transition-all flex items-center gap-1"
                    >
                      <Database className="w-3 h-3" />
                      <span>Save</span>
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Evaluation card */}
          {evaluationResult && (
            <div className="bg-background border border-border-strong rounded-xl p-5 space-y-4">
              {/* Repo header + trust badge */}
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div className="min-w-0">
                  <a
                    href={evaluationResult.repo.html_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sm font-bold text-foreground hover:text-primary transition-colors inline-flex items-center gap-1"
                  >
                    {evaluationResult.repo.full_name}
                    <ArrowUpRight className="w-3.5 h-3.5" />
                  </a>
                  <p className="text-[11px] text-subtle-foreground font-mono mt-1">
                    ⭐{evaluationResult.repo.stars} · {evaluationResult.repo.forks} forks · {evaluationResult.repo.license ?? 'no license'} · pushed {evaluationResult.repo.pushed_days ?? '?'}d ago
                  </p>
                </div>
                <div className="shrink-0">
                  {(() => {
                    const tier = evaluationResult.trust.tier;
                    const cls = tier === 'high'
                      ? 'bg-success/15 text-success border-success/30'
                      : tier === 'medium'
                      ? 'bg-warning/15 text-warning border-warning/30'
                      : 'bg-danger/15 text-danger border-danger/30';
                    return (
                      <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-bold font-mono uppercase tracking-wider border ${cls}`}>
                        <Shield className="w-3 h-3" />
                        {tier} trust
                      </span>
                    );
                  })()}
                </div>
              </div>

              {evaluationResult.repo.description && (
                <p className="text-[11.5px] text-muted-foreground font-sans leading-relaxed">
                  {evaluationResult.repo.description}
                </p>
              )}

              <p className="text-[10.5px] text-subtle-foreground font-mono">{evaluationResult.trust.license_note}</p>

              {/* Classification line */}
              <div className="flex items-start gap-2 text-[11.5px] font-sans border-t border-border/40 pt-3">
                <span className={`font-bold shrink-0 ${evaluationResult.suggestion.is_mcp ? 'text-success' : 'text-danger'}`}>
                  {evaluationResult.suggestion.is_mcp ? 'MCP server ✓' : 'Not an MCP server ✗'}
                </span>
                {evaluationResult.suggestion.reason && (
                  <span className="text-muted-foreground">— {evaluationResult.suggestion.reason}</span>
                )}
              </div>

              {/* Editable suggested-command fields */}
              {evaluationResult.suggestion.is_mcp && (
                <div className="space-y-3 border-t border-border/40 pt-3">
                  <span className="text-[9.5px] font-mono text-subtle-foreground uppercase tracking-widest block">Suggested launch command (review &amp; edit)</span>
                  <div className="grid grid-cols-1 sm:grid-cols-4 gap-2">
                    <div className="sm:col-span-1">
                      <select
                        value={draft.transport}
                        onChange={(e) => setDraft(prev => ({ ...prev, transport: e.target.value }))}
                        className="w-full bg-surface border border-border-strong focus:border-primary focus:outline-none rounded-lg px-3 py-2 text-[11px] text-foreground font-mono"
                      >
                        <option value="stdio">stdio</option>
                        <option value="http">http</option>
                      </select>
                    </div>
                    {draft.transport === 'http' ? (
                      <input
                        type="text"
                        value={draft.url}
                        onChange={(e) => setDraft(prev => ({ ...prev, url: e.target.value }))}
                        placeholder="https://…/mcp"
                        className="sm:col-span-3 w-full bg-surface border border-border-strong focus:border-primary focus:outline-none rounded-lg px-3 py-2 text-[11px] text-foreground font-mono placeholder-subtle-foreground"
                      />
                    ) : (
                      <>
                        <input
                          type="text"
                          value={draft.command}
                          onChange={(e) => setDraft(prev => ({ ...prev, command: e.target.value }))}
                          placeholder="npx"
                          className="sm:col-span-1 w-full bg-surface border border-border-strong focus:border-primary focus:outline-none rounded-lg px-3 py-2 text-[11px] text-foreground font-mono placeholder-subtle-foreground"
                        />
                        <input
                          type="text"
                          value={draft.args}
                          onChange={(e) => setDraft(prev => ({ ...prev, args: e.target.value }))}
                          placeholder="-y @scope/server"
                          className="sm:col-span-2 w-full bg-surface border border-border-strong focus:border-primary focus:outline-none rounded-lg px-3 py-2 text-[11px] text-foreground font-mono placeholder-subtle-foreground"
                        />
                      </>
                    )}
                  </div>

                  <div className="flex flex-col sm:flex-row sm:items-center gap-3 pt-1">
                    <button
                      type="button"
                      onClick={handleAddToMCP}
                      disabled={!canAdd || isAdding}
                      className="px-4 py-2 bg-primary hover:bg-primary-hover text-primary-foreground text-[11px] font-bold font-mono uppercase rounded-lg flex items-center gap-1.5 transition-all disabled:opacity-50 disabled:cursor-not-allowed shrink-0"
                    >
                      {isAdding ? <RefreshCcw className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
                      <span>Add as MCP server</span>
                    </button>
                    {addNotice && (
                      <span className="text-[11px] text-success font-sans inline-flex items-center gap-1.5">
                        <Check className="w-3.5 h-3.5 shrink-0" />
                        {addNotice}
                      </span>
                    )}
                    {addError && (
                      <span className="text-[11px] text-danger font-sans inline-flex items-center gap-1.5">
                        <X className="w-3.5 h-3.5 shrink-0" />
                        {addError}
                      </span>
                    )}
                  </div>
                </div>
              )}

              {/* Save snapshot to the persistent catalog + Add as Skill */}
              <div className="flex flex-col sm:flex-row sm:items-center gap-3 border-t border-border/40 pt-3">
                <button
                  type="button"
                  onClick={() => handleSaveSnapshot(evaluationResult)}
                  className="px-4 py-2 bg-primary/10 hover:bg-primary/20 border border-primary/30 text-primary text-[11px] font-bold font-mono uppercase rounded-lg flex items-center gap-1.5 transition-all shrink-0"
                >
                  <Database className="w-3.5 h-3.5" />
                  <span>Save to catalog</span>
                </button>
                <button
                  type="button"
                  onClick={() => handleGenerateSkill(evaluationResult.repo.full_name)}
                  disabled={skillBusyRef === evaluationResult.repo.full_name}
                  className="px-4 py-2 bg-warning/10 hover:bg-warning/20 border border-warning/30 text-warning text-[11px] font-bold font-mono uppercase rounded-lg flex items-center gap-1.5 transition-all shrink-0 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {skillBusyRef === evaluationResult.repo.full_name
                    ? <RefreshCcw className="w-3.5 h-3.5 animate-spin" />
                    : <BookOpen className="w-3.5 h-3.5" />}
                  <span>Add as Skill</span>
                </button>
                {catalogNotice && (
                  <span className="text-[11px] text-success font-sans inline-flex items-center gap-1.5">
                    <Check className="w-3.5 h-3.5 shrink-0" />
                    {catalogNotice}
                  </span>
                )}
                {catalogError && (
                  <span className="text-[11px] text-danger font-sans inline-flex items-center gap-1.5">
                    <X className="w-3.5 h-3.5 shrink-0" />
                    {catalogError}
                  </span>
                )}
              </div>
            </div>
          )}

          {/* Add-as-Skill notice / error (when no draft panel is open) */}
          {!skillDraft && (skillNotice || skillError) && (
            skillError ? (
              <div className="flex items-start gap-2 bg-danger/15 border border-danger/40 rounded-xl px-4 py-3 text-[11px] text-danger font-sans">
                <X className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                <span>{skillError}</span>
              </div>
            ) : (
              <div className="flex items-start gap-2 bg-success/15 border border-success/40 rounded-xl px-4 py-3 text-[11px] text-success font-sans">
                <Check className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                <span>{skillNotice}</span>
              </div>
            )
          )}

          {/* Editable Skill draft panel — review & edit before Create (consent step).
              🔒 body is shown ONLY in a <textarea> (plain text), never rendered as HTML. */}
          {skillDraft && (
            <div className="bg-background border border-warning/40 rounded-xl p-5 space-y-3">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[9.5px] font-mono text-subtle-foreground uppercase tracking-widest block">
                  Distilled skill from <span className="text-foreground font-bold">{skillDraft.full_name}</span> (review &amp; edit)
                </span>
                <button
                  type="button"
                  onClick={() => { setSkillDraft(null); setSkillError(null); setSkillNotice(null); }}
                  className="p-1 text-subtle-foreground hover:text-foreground transition-colors"
                  aria-label="Cancel"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                <input
                  type="text"
                  value={skillDraft.name}
                  onChange={(e) => setSkillDraft(prev => prev && ({ ...prev, name: e.target.value }))}
                  placeholder="Skill name"
                  className="sm:col-span-1 w-full bg-surface border border-border-strong focus:border-primary focus:outline-none rounded-lg px-3 py-2 text-[11px] text-foreground font-sans placeholder-subtle-foreground"
                />
                <input
                  type="text"
                  value={skillDraft.category}
                  onChange={(e) => setSkillDraft(prev => prev && ({ ...prev, category: e.target.value }))}
                  placeholder="category"
                  className="sm:col-span-1 w-full bg-surface border border-border-strong focus:border-primary focus:outline-none rounded-lg px-3 py-2 text-[11px] text-foreground font-mono placeholder-subtle-foreground"
                />
                <input
                  type="text"
                  value={skillDraft.description}
                  onChange={(e) => setSkillDraft(prev => prev && ({ ...prev, description: e.target.value }))}
                  placeholder="one-line description"
                  className="sm:col-span-1 w-full bg-surface border border-border-strong focus:border-primary focus:outline-none rounded-lg px-3 py-2 text-[11px] text-foreground font-sans placeholder-subtle-foreground"
                />
              </div>

              <div>
                <span className="text-[9.5px] font-mono text-subtle-foreground uppercase tracking-widest block mb-1">
                  SKILL.md body (must contain ## Trigger and ## 决策规则)
                </span>
                <textarea
                  value={skillDraft.body}
                  onChange={(e) => setSkillDraft(prev => prev && ({ ...prev, body: e.target.value }))}
                  rows={12}
                  spellCheck={false}
                  className="w-full bg-surface border border-border-strong focus:border-primary focus:outline-none rounded-lg px-3 py-2 text-[11px] text-foreground font-mono placeholder-subtle-foreground resize-y"
                />
              </div>

              <div className="flex flex-col sm:flex-row sm:items-center gap-3 pt-1">
                <button
                  type="button"
                  onClick={handleCreateSkill}
                  disabled={skillCreating || !skillDraft.name.trim() || !skillDraft.body.trim()}
                  className="px-4 py-2 bg-warning hover:opacity-90 text-background text-[11px] font-bold font-mono uppercase rounded-lg flex items-center gap-1.5 transition-all disabled:opacity-50 disabled:cursor-not-allowed shrink-0"
                >
                  {skillCreating ? <RefreshCcw className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
                  <span>Create skill</span>
                </button>
                <button
                  type="button"
                  onClick={() => { setSkillDraft(null); setSkillError(null); setSkillNotice(null); }}
                  className="px-4 py-2 bg-surface hover:bg-foreground/[0.04] border border-border hover:border-border-strong text-muted-foreground hover:text-foreground text-[11px] font-mono uppercase rounded-lg transition-all shrink-0"
                >
                  Cancel
                </button>
                {skillError && (
                  <span className="text-[11px] text-danger font-sans inline-flex items-center gap-1.5">
                    <X className="w-3.5 h-3.5 shrink-0" />
                    {skillError}
                  </span>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
