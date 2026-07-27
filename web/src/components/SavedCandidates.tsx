import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ArrowUpRight, Shield, RefreshCcw, Plus, X, Check, BookOpen,
} from 'lucide-react';
import {
  listCandidates, refreshCandidate, deleteCandidate,
  generateSkill, createSkill,
  type Candidate, type SkillDraft,
} from '../api/discovery';
import type { McpPrefill } from './ToolHubDiscover';

// Saved Candidates — the persistent discovery catalog (its own tab).
// Self-contained: loads its own list on mount; each row can Refresh / Delete /
// Add as MCP server (prefills the MCP add form via onPrefillMcp) / Add as Skill
// (generate → editable draft → create). Read-only browse; "Add" steps reuse the
// existing locked discovery + MCP paths. Plain text only; semantic tokens.
export default function SavedCandidates({ onPrefillMcp }: { onPrefillMcp?: (d: McpPrefill) => void } = {}) {
  const { t } = useTranslation();
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [catalogNotice, setCatalogNotice] = useState<string | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [busyCandidateId, setBusyCandidateId] = useState<number | null>(null);

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

  const reloadCandidates = async () => {
    try {
      setCandidates(await listCandidates());
    } catch (e) {
      setCatalogError(String(e instanceof Error ? e.message : e));
    }
  };

  useEffect(() => {
    void reloadCandidates();
  }, []);

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

  const handleRefreshCandidate = async (id: number) => {
    setBusyCandidateId(id);
    setCatalogNotice(null);
    setCatalogError(null);
    try {
      const updated = await refreshCandidate(id);
      setCandidates(prev => prev.map(c => (c.id === id ? updated : c)));
    } catch (e) {
      setCatalogError(String(e instanceof Error ? e.message : e));
    } finally {
      setBusyCandidateId(null);
    }
  };

  const handleDeleteCandidate = async (id: number) => {
    setBusyCandidateId(id);
    setCatalogNotice(null);
    setCatalogError(null);
    try {
      await deleteCandidate(id);
      await reloadCandidates();
    } catch (e) {
      setCatalogError(String(e instanceof Error ? e.message : e));
    } finally {
      setBusyCandidateId(null);
    }
  };

  const handleAddCandidateToMcp = (cand: Candidate) => {
    const s = cand.snapshot.suggestion;
    onPrefillMcp?.({
      label: cand.full_name.split('/').pop()!,
      command: s.command ?? '',
      args: s.args || [],
      transport: s.transport ?? 'stdio',
      url: s.url ?? undefined,
    });
    setCatalogNotice(`Prefilled MCP add form from ${cand.full_name} — review & connect it in the MCPs tab.`);
  };

  // Trust tier → semantic token classes.
  const trustBadgeCls = (tier: 'high' | 'medium' | 'low') =>
    tier === 'high'
      ? 'bg-success/15 text-success border-success/30'
      : tier === 'medium'
      ? 'bg-warning/15 text-warning border-warning/30'
      : 'bg-danger/15 text-danger border-danger/30';

  return (
    <div className="space-y-3 select-text">
      <div className="flex items-center justify-between">
        <span className="text-[9.5px] font-mono text-subtle-foreground uppercase tracking-widest block">
          Saved Candidates ({candidates.length})
        </span>
        <button
          type="button"
          onClick={() => reloadCandidates()}
          className="px-3 py-1.5 bg-surface hover:bg-foreground/[0.04] border border-border hover:border-border-strong text-muted-foreground hover:text-foreground text-[10px] font-mono uppercase rounded-lg transition-all flex items-center gap-1"
        >
          <RefreshCcw className="w-3 h-3" />
          <span>Refresh list</span>
        </button>
      </div>

      {(catalogNotice || catalogError) && (
        catalogError ? (
          <div className="flex items-start gap-2 bg-danger/15 border border-danger/40 rounded-xl px-4 py-3 text-[11px] text-danger font-sans">
            <X className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            <span>{catalogError}</span>
          </div>
        ) : (
          <div className="flex items-start gap-2 bg-success/15 border border-success/40 rounded-xl px-4 py-3 text-[11px] text-success font-sans">
            <Check className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            <span>{catalogNotice}</span>
          </div>
        )
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
              {t('capabilities.skill_body_label')}
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

      {candidates.length === 0 ? (
        <div className="text-center py-4 bg-background border border-dashed border-border rounded-xl">
          <span className="text-[10px] text-subtle-foreground font-mono">No saved candidates yet — search and save repos to build a catalog.</span>
        </div>
      ) : (
        <div className="space-y-2">
          {candidates.map((cand) => {
            const isMcp = cand.snapshot.suggestion.is_mcp;
            const busy = busyCandidateId === cand.id;
            return (
              <div
                key={cand.id}
                className="bg-background border border-border-strong rounded-xl px-4 py-3 flex flex-col sm:flex-row sm:items-center justify-between gap-3"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <a
                      href={cand.html_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-[12px] font-bold text-foreground hover:text-primary transition-colors inline-flex items-center gap-1"
                    >
                      {cand.full_name}
                      <ArrowUpRight className="w-3 h-3" />
                    </a>
                    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[9px] font-bold font-mono uppercase tracking-wider border ${trustBadgeCls(cand.snapshot.trust.tier)}`}>
                      <Shield className="w-2.5 h-2.5" />
                      {cand.snapshot.trust.tier}
                    </span>
                    <span className={`text-[9.5px] font-mono font-bold ${isMcp ? 'text-success' : 'text-subtle-foreground'}`}>
                      {isMcp ? 'MCP ✓' : 'not MCP'}
                    </span>
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0 flex-wrap">
                  <button
                    type="button"
                    onClick={() => handleRefreshCandidate(cand.id)}
                    disabled={busy}
                    className="px-3 py-1.5 bg-surface hover:bg-foreground/[0.04] border border-border hover:border-border-strong text-muted-foreground hover:text-foreground text-[10px] font-mono uppercase rounded-lg transition-all flex items-center gap-1 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {busy ? <RefreshCcw className="w-3 h-3 animate-spin" /> : <RefreshCcw className="w-3 h-3" />}
                    <span>Refresh</span>
                  </button>
                  {isMcp && (
                    <button
                      type="button"
                      onClick={() => handleAddCandidateToMcp(cand)}
                      disabled={busy}
                      className="px-3 py-1.5 bg-primary/10 hover:bg-primary/20 border border-primary/30 text-primary text-[10px] font-mono uppercase rounded-lg transition-all flex items-center gap-1 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      <Plus className="w-3 h-3" />
                      <span>Add as MCP server</span>
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => handleGenerateSkill(cand.full_name)}
                    disabled={skillBusyRef === cand.full_name}
                    className="px-3 py-1.5 bg-warning/10 hover:bg-warning/20 border border-warning/30 text-warning text-[10px] font-mono uppercase rounded-lg transition-all flex items-center gap-1 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {skillBusyRef === cand.full_name
                      ? <RefreshCcw className="w-3 h-3 animate-spin" />
                      : <BookOpen className="w-3 h-3" />}
                    <span>Add as Skill</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDeleteCandidate(cand.id)}
                    disabled={busy}
                    className="px-3 py-1.5 bg-danger/10 hover:bg-danger/20 border border-danger/30 text-danger text-[10px] font-mono uppercase rounded-lg transition-all flex items-center gap-1 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <X className="w-3 h-3" />
                    <span>Delete</span>
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
