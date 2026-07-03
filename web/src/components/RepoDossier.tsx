import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ArrowUpRight, Shield, BookOpen, Plug, FileDown, Database, RefreshCcw,
  Check, X, Plus, NotebookPen,
} from 'lucide-react';
import {
  saveCandidate, scanSkills, importSkill, generateSkill, createSkill,
  type EvalResult, type SkillScanResult,
} from '../api/discovery';
import { addMcpServer } from '../api/mcp';
import { api } from '../api/client';
import type { SpawnSummary } from '../api/client.types';

// ── Project dossier for one evaluated GitHub repo ────────────────────────────
// Everything rendered here comes from the real /discovery/evaluate response
// (repo metadata straight from GitHub + the backend's trust / MCP analysis).
// Nothing is fabricated; loading and errors are shown honestly.

/** Permissive-license allowlist (SPDX ids, lowercased). Green = usable; red = learning only. */
const PERMISSIVE_LICENSES = new Set([
  'mit', 'apache-2.0', 'bsd-2-clause', 'bsd-3-clause', 'bsd-3-clause-clear',
  'isc', 'mpl-2.0', 'unlicense', 'cc0-1.0', '0bsd', 'zlib',
]);

export const isLicensePermissive = (license: string | null): boolean =>
  license != null && PERMISSIVE_LICENSES.has(license.toLowerCase());

export type RepoKind = 'mcp' | 'skill' | 'agent' | 'other';

/** Classify the repo from real eval fields (backend is_mcp verdict, then name/desc/topics). */
export function detectRepoKind(result: EvalResult): RepoKind {
  if (result.suggestion.is_mcp) return 'mcp';
  const hay = [
    result.repo.full_name,
    result.repo.description ?? '',
    ...(result.repo.topics ?? []),
  ].join(' ').toLowerCase();
  if (/skill/.test(hay)) return 'skill';
  if (/agent/.test(hay)) return 'agent';
  return 'other';
}

/** Grounded fallback note: markdown composed ONLY from real eval-response fields. */
function evalSummaryMarkdown(result: EvalResult): string {
  const r = result.repo;
  const lines = [
    `# ${r.full_name}`,
    '',
    `- Stars: ${r.stars} · Forks: ${r.forks}`,
    `- License: ${r.license ?? 'none'}`,
    `- Last push: ${r.pushed_days ?? '?'}d ago`,
    `- URL: ${r.html_url}`,
  ];
  if ((r.topics ?? []).length > 0) lines.push(`- Topics: ${r.topics.join(', ')}`);
  if (r.description) lines.push('', '## Description', '', r.description);
  if (result.suggestion.reason) lines.push('', '## Assessment', '', result.suggestion.reason);
  if (result.trust.license_note) lines.push('', result.trust.license_note);
  return lines.join('\n');
}

type Panel = 'none' | 'scan' | 'mcp' | 'note';
type Notice = { kind: 'ok' | 'err'; text: string } | null;

type NoteDraft = {
  name: string; category: string; description: string; body: string;
  /** true when the body came from the LLM distill endpoint (registerable as a skill). */
  llm: boolean;
};

export default function RepoDossier({ result, onMcpAdded }: {
  result: EvalResult;
  onMcpAdded?: () => void;
}) {
  const { t } = useTranslation();
  const repo = result.repo;
  const suggestion = result.suggestion;
  const permissive = isLicensePermissive(repo.license);
  const kind = detectRepoKind(result);

  const [panel, setPanel] = useState<Panel>('none');
  const [saveNotice, setSaveNotice] = useState<Notice>(null);
  const [saving, setSaving] = useState(false);

  // ── Register as Skill (verbatim SKILL.md scan → import; license gate server-side) ──
  const [scan, setScan] = useState<SkillScanResult | null>(null);
  const [scanning, setScanning] = useState(false);
  const [scanError, setScanError] = useState<string | null>(null);
  const [importBusy, setImportBusy] = useState<string | null>(null);
  const [imported, setImported] = useState<Record<string, boolean>>({});
  const [importErr, setImportErr] = useState<Record<string, string>>({});

  // ── Add as MCP (editable suggested launch command → existing addMcpServer) ──
  const [draft, setDraft] = useState({
    transport: suggestion.transport ?? 'stdio',
    command: suggestion.command ?? '',
    args: (suggestion.args || []).join(' '),
    url: suggestion.url ?? '',
  });
  const [adding, setAdding] = useState(false);
  const [mcpNotice, setMcpNotice] = useState<Notice>(null);

  // ── Distill to reference note (LLM distill → editable md → skill or knowledge ingest) ──
  const [note, setNote] = useState<NoteDraft | null>(null);
  const [noteBusy, setNoteBusy] = useState(false);
  const [noteNotice, setNoteNotice] = useState<Notice>(null);
  const [spawns, setSpawns] = useState<SpawnSummary[]>([]);
  const [spawnId, setSpawnId] = useState('');
  const [ingesting, setIngesting] = useState(false);
  const [creatingSkill, setCreatingSkill] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    setSaveNotice(null);
    try {
      await saveCandidate(result);
      setSaveNotice({ kind: 'ok', text: t('capabilities.dossier.saved_ok') });
    } catch (e) {
      setSaveNotice({ kind: 'err', text: String(e instanceof Error ? e.message : e) });
    } finally {
      setSaving(false);
    }
  };

  const openScan = async () => {
    setPanel('scan');
    if (scan || scanning) return;
    setScanning(true);
    setScanError(null);
    try {
      setScan(await scanSkills(repo.full_name));
    } catch (e) {
      setScanError(String(e instanceof Error ? e.message : e));
    } finally {
      setScanning(false);
    }
  };

  const doImport = async (path: string) => {
    setImportBusy(path);
    setImportErr((prev) => ({ ...prev, [path]: '' }));
    try {
      await importSkill(repo.full_name, path);
      setImported((prev) => ({ ...prev, [path]: true }));
    } catch (e) {
      setImportErr((prev) => ({ ...prev, [path]: String(e instanceof Error ? e.message : e) }));
    } finally {
      setImportBusy(null);
    }
  };

  const handleAddMcp = async () => {
    setAdding(true);
    setMcpNotice(null);
    try {
      await addMcpServer({
        label: repo.full_name.split('/').pop()!,
        transport: draft.transport,
        command: draft.command,
        args: draft.args.split(/\s+/).filter(Boolean),
        url: draft.url || undefined,
        env: {},
      });
      setMcpNotice({ kind: 'ok', text: t('capabilities.dossier.mcp.added') });
      onMcpAdded?.();
    } catch (e) {
      setMcpNotice({ kind: 'err', text: String(e instanceof Error ? e.message : e) });
    } finally {
      setAdding(false);
    }
  };

  const openNote = async () => {
    setPanel('note');
    if (note || noteBusy) return;
    setNoteBusy(true);
    setNoteNotice(null);
    api.listSpawns().then(setSpawns).catch(() => setSpawns([]));
    const fallback = (): NoteDraft => ({
      name: repo.full_name,
      category: 'reference',
      description: repo.description ?? '',
      body: evalSummaryMarkdown(result),
      llm: false,
    });
    try {
      const gen = await generateSkill(repo.full_name);
      if (gen.skill) {
        setNote({ ...gen.skill, llm: true });
      } else {
        setNote(fallback());
        setNoteNotice({ kind: 'err', text: t('capabilities.dossier.note.fallback') });
      }
    } catch {
      setNote(fallback());
      setNoteNotice({ kind: 'err', text: t('capabilities.dossier.note.fallback') });
    } finally {
      setNoteBusy(false);
    }
  };

  const handleIngest = async () => {
    if (!note || !spawnId) return;
    setIngesting(true);
    setNoteNotice(null);
    try {
      await api.ingestKnowledgeText(Number(spawnId), `repo:${repo.full_name}`, note.body);
      const sp = spawns.find((s) => String(s.id) === spawnId);
      setNoteNotice({
        kind: 'ok',
        text: t('capabilities.dossier.note.ingest_ok', { name: sp?.name ?? spawnId }),
      });
    } catch (e) {
      setNoteNotice({ kind: 'err', text: String(e instanceof Error ? e.message : e) });
    } finally {
      setIngesting(false);
    }
  };

  const handleCreateSkill = async () => {
    if (!note) return;
    setCreatingSkill(true);
    setNoteNotice(null);
    try {
      await createSkill({
        full_name: repo.full_name,
        name: note.name,
        category: note.category || 'reference',
        description: note.description,
        body: note.body,
      });
      setNoteNotice({ kind: 'ok', text: t('capabilities.dossier.note.create_ok') });
    } catch (e) {
      setNoteNotice({ kind: 'err', text: String(e instanceof Error ? e.message : e) });
    } finally {
      setCreatingSkill(false);
    }
  };

  const canAddMcp = Boolean(
    suggestion.is_mcp &&
    (draft.transport === 'http' ? draft.url.trim() : draft.command.trim())
  );

  const actionBtn = 'px-4 py-2 text-[11px] font-bold font-mono uppercase rounded-lg flex items-center gap-1.5 transition-all disabled:opacity-50 disabled:cursor-not-allowed shrink-0';
  const inputCls = 'w-full bg-surface border border-border-strong focus:border-primary focus:outline-none rounded-lg px-3 py-2 text-[11px] text-foreground font-mono placeholder-subtle-foreground';
  const sectionLabel = 'text-[9.5px] font-mono text-subtle-foreground uppercase tracking-widest block';

  const noticeRow = (n: Notice) => n && (
    <span className={`text-[11px] font-sans inline-flex items-center gap-1.5 ${n.kind === 'ok' ? 'text-success' : 'text-danger'}`}>
      {n.kind === 'ok' ? <Check className="w-3.5 h-3.5 shrink-0" /> : <X className="w-3.5 h-3.5 shrink-0" />}
      {n.text}
    </span>
  );

  return (
    <div className="bg-surface/40 border border-border-strong rounded-2xl p-6 space-y-4 text-left select-text" data-testid="repo-dossier">
      {/* Header: repo name + license verdict + detected type */}
      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
        <div className="min-w-0">
          <a
            href={repo.html_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-base font-bold text-foreground hover:text-primary transition-colors inline-flex items-center gap-1"
          >
            {repo.full_name}
            <ArrowUpRight className="w-4 h-4" />
          </a>
          <p className="text-[11px] text-subtle-foreground font-mono mt-1">
            ⭐{repo.stars} · ⑂{repo.forks} · {repo.license ?? t('capabilities.dossier.no_license')} · {repo.pushed_days ?? '?'}d
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap shrink-0">
          <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-bold font-mono uppercase tracking-wider border ${
            permissive
              ? 'bg-success/15 text-success border-success/30'
              : 'bg-danger/15 text-danger border-danger/30'
          }`}>
            <Shield className="w-3 h-3" />
            {permissive ? t('capabilities.dossier.license_ok') : t('capabilities.dossier.license_learn')}
          </span>
          <span className="inline-flex items-center px-2.5 py-1 rounded-full text-[10px] font-bold font-mono uppercase tracking-wider border bg-primary/10 text-primary border-primary/30">
            {t(`capabilities.dossier.type.${kind}`)}
          </span>
        </div>
      </div>

      {repo.description && (
        <p className="text-[12px] text-muted-foreground font-sans leading-relaxed">{repo.description}</p>
      )}

      {(repo.topics ?? []).length > 0 && (
        <div className="flex items-center gap-1.5 flex-wrap">
          {repo.topics.map((topic) => (
            <span key={topic} className="text-[9.5px] font-mono bg-surface text-subtle-foreground border border-border/60 px-2 py-0.5 rounded-full">
              {topic}
            </span>
          ))}
        </div>
      )}

      {/* Value assessment — backend analysis (suggestion.reason) + license note, verbatim */}
      {(suggestion.reason || result.trust.license_note) && (
        <div className="border-t border-border/40 pt-3 space-y-1">
          <span className={sectionLabel}>{t('capabilities.dossier.value_label')}</span>
          {suggestion.reason && (
            <p className="text-[11.5px] text-muted-foreground font-sans leading-relaxed">{suggestion.reason}</p>
          )}
          {result.trust.license_note && (
            <p className="text-[10.5px] text-subtle-foreground font-mono">{result.trust.license_note}</p>
          )}
        </div>
      )}

      {/* Contextual actions by license verdict */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-2 flex-wrap border-t border-border/40 pt-3">
        {permissive && (
          <button
            type="button"
            onClick={openScan}
            className={`${actionBtn} bg-primary/10 hover:bg-primary/20 border border-primary/30 text-primary`}
          >
            {scanning ? <RefreshCcw className="w-3.5 h-3.5 animate-spin" /> : <FileDown className="w-3.5 h-3.5" />}
            <span>{t('capabilities.dossier.actions.register_skill')}</span>
          </button>
        )}
        {permissive && suggestion.is_mcp && (
          <button
            type="button"
            onClick={() => setPanel('mcp')}
            className={`${actionBtn} bg-primary hover:bg-primary-hover text-primary-foreground`}
          >
            <Plug className="w-3.5 h-3.5" />
            <span>{t('capabilities.dossier.actions.add_mcp')}</span>
          </button>
        )}
        <button
          type="button"
          onClick={openNote}
          className={`${actionBtn} bg-warning/10 hover:bg-warning/20 border border-warning/30 text-warning`}
        >
          {noteBusy ? <RefreshCcw className="w-3.5 h-3.5 animate-spin" /> : <NotebookPen className="w-3.5 h-3.5" />}
          <span>{t('capabilities.dossier.actions.distill')}</span>
        </button>
        <button
          type="button"
          onClick={handleSave}
          disabled={saving}
          className={`${actionBtn} bg-surface hover:bg-foreground/[0.04] border border-border-strong text-muted-foreground hover:text-foreground`}
        >
          {saving ? <RefreshCcw className="w-3.5 h-3.5 animate-spin" /> : <Database className="w-3.5 h-3.5" />}
          <span>{t('capabilities.dossier.actions.save')}</span>
        </button>
        {noticeRow(saveNotice)}
      </div>

      {/* ── Panel: Register as Skill (scan → verbatim import) ───────────────── */}
      {panel === 'scan' && (
        <div className="border-t border-border/40 pt-3 space-y-2">
          <span className={sectionLabel}>{t('capabilities.dossier.scan.title')}</span>
          {scanning && (
            <div className="flex items-center gap-2 text-[11px] text-subtle-foreground font-sans">
              <RefreshCcw className="w-3.5 h-3.5 animate-spin" />
            </div>
          )}
          {scanError && (
            <div className="flex items-start gap-2 bg-danger/15 border border-danger/40 rounded-lg px-3 py-2 text-[11px] text-danger font-sans">
              <X className="w-3.5 h-3.5 shrink-0 mt-0.5" /> <span>{scanError}</span>
            </div>
          )}
          {scan && !scan.license_ok && scan.license_note && (
            <p className="text-[11px] text-danger font-sans">{scan.license_note}</p>
          )}
          {scan && scan.skills.length === 0 && (
            <p className="text-[11px] text-subtle-foreground font-sans">{t('capabilities.dossier.scan.none')}</p>
          )}
          {scan?.skills.map((s) => (
            <div key={s.path} className="bg-background border border-border/60 rounded-lg px-3 py-2 flex items-center gap-2 flex-wrap">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-[11.5px] font-bold text-foreground">{s.name ?? s.path}</span>
                  {s.scripts.length > 0 && (
                    <span className="text-[9px] font-mono bg-primary/10 text-primary px-1.5 py-0.5 rounded">
                      {s.scripts.length} script{s.scripts.length > 1 ? 's' : ''}
                    </span>
                  )}
                </div>
                {s.description && (
                  <p className="text-[10.5px] text-subtle-foreground font-sans mt-0.5 line-clamp-1">{s.description}</p>
                )}
                {(importErr[s.path] || (!s.importable && s.reason)) && (
                  <p className="text-[10px] text-danger font-sans mt-0.5">{importErr[s.path] || s.reason}</p>
                )}
              </div>
              {imported[s.path] ? (
                <span className="inline-flex items-center gap-1 text-[10.5px] text-success font-mono shrink-0">
                  <Check className="w-3.5 h-3.5" /> {t('capabilities.dossier.scan.imported')}
                </span>
              ) : (
                <button
                  type="button"
                  onClick={() => doImport(s.path)}
                  disabled={!s.importable || importBusy === s.path}
                  className="px-3 py-1 bg-primary/10 hover:bg-primary/20 border border-primary/30 text-primary text-[10px] font-mono uppercase rounded-lg transition-all disabled:opacity-40 disabled:cursor-not-allowed shrink-0 flex items-center gap-1"
                >
                  {importBusy === s.path ? <RefreshCcw className="w-3 h-3 animate-spin" /> : <FileDown className="w-3 h-3" />}
                  <span>{t('capabilities.dossier.scan.import')}</span>
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {/* ── Panel: Add as MCP (editable launch command → locked registry entry) ─ */}
      {panel === 'mcp' && suggestion.is_mcp && (
        <div className="border-t border-border/40 pt-3 space-y-3">
          <span className={sectionLabel}>{t('capabilities.dossier.mcp.title')}</span>
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-2">
            <select
              value={draft.transport}
              onChange={(e) => setDraft((prev) => ({ ...prev, transport: e.target.value as 'http' | 'stdio' }))}
              className={`sm:col-span-1 ${inputCls}`}
            >
              <option value="stdio">stdio</option>
              <option value="http">http</option>
            </select>
            {draft.transport === 'http' ? (
              <input
                type="text"
                value={draft.url}
                onChange={(e) => setDraft((prev) => ({ ...prev, url: e.target.value }))}
                placeholder="https://…/mcp"
                className={`sm:col-span-3 ${inputCls}`}
              />
            ) : (
              <>
                <input
                  type="text"
                  value={draft.command}
                  onChange={(e) => setDraft((prev) => ({ ...prev, command: e.target.value }))}
                  placeholder="npx"
                  className={`sm:col-span-1 ${inputCls}`}
                />
                <input
                  type="text"
                  value={draft.args}
                  onChange={(e) => setDraft((prev) => ({ ...prev, args: e.target.value }))}
                  placeholder="-y @scope/server"
                  className={`sm:col-span-2 ${inputCls}`}
                />
              </>
            )}
          </div>
          <div className="flex flex-col sm:flex-row sm:items-center gap-3">
            <button
              type="button"
              onClick={handleAddMcp}
              disabled={!canAddMcp || adding}
              className={`${actionBtn} bg-primary hover:bg-primary-hover text-primary-foreground`}
            >
              {adding ? <RefreshCcw className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
              <span>{t('capabilities.dossier.mcp.add')}</span>
            </button>
            {noticeRow(mcpNotice)}
          </div>
        </div>
      )}

      {/* ── Panel: Distill to reference note (editable md → skill / spawn knowledge) ─
          🔒 note body is shown ONLY in a <textarea> (plain text), never rendered as HTML. */}
      {panel === 'note' && (
        <div className="border-t border-border/40 pt-3 space-y-3">
          <span className={sectionLabel}>{t('capabilities.dossier.note.title')}</span>
          {noteBusy && (
            <div className="flex items-center gap-2 text-[11px] text-subtle-foreground font-sans">
              <RefreshCcw className="w-3.5 h-3.5 animate-spin" />
            </div>
          )}
          {note && (
            <>
              {note.llm && (
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                  <input
                    type="text"
                    value={note.name}
                    onChange={(e) => setNote((prev) => prev && ({ ...prev, name: e.target.value }))}
                    placeholder="name"
                    className={`sm:col-span-1 ${inputCls}`}
                  />
                  <input
                    type="text"
                    value={note.category}
                    onChange={(e) => setNote((prev) => prev && ({ ...prev, category: e.target.value }))}
                    placeholder="category"
                    className={`sm:col-span-1 ${inputCls}`}
                  />
                  <input
                    type="text"
                    value={note.description}
                    onChange={(e) => setNote((prev) => prev && ({ ...prev, description: e.target.value }))}
                    placeholder="description"
                    className={`sm:col-span-1 ${inputCls}`}
                  />
                </div>
              )}
              <textarea
                value={note.body}
                onChange={(e) => setNote((prev) => prev && ({ ...prev, body: e.target.value }))}
                rows={10}
                spellCheck={false}
                aria-label={t('capabilities.dossier.note.title')}
                className={`${inputCls} resize-y`}
              />
              <div className="flex flex-col sm:flex-row sm:items-center gap-2 flex-wrap">
                {note.llm && permissive && (
                  <button
                    type="button"
                    onClick={handleCreateSkill}
                    disabled={creatingSkill || !note.name.trim() || !note.body.trim()}
                    className={`${actionBtn} bg-warning hover:opacity-90 text-background`}
                  >
                    {creatingSkill ? <RefreshCcw className="w-3.5 h-3.5 animate-spin" /> : <BookOpen className="w-3.5 h-3.5" />}
                    <span>{t('capabilities.dossier.note.create_skill')}</span>
                  </button>
                )}
                <select
                  value={spawnId}
                  onChange={(e) => setSpawnId(e.target.value)}
                  aria-label={t('capabilities.dossier.note.pick_spawn')}
                  className="bg-surface border border-border-strong focus:border-primary focus:outline-none rounded-lg px-2 py-2 text-[10.5px] text-foreground font-mono max-w-[180px]"
                >
                  <option value="">{t('capabilities.dossier.note.pick_spawn')}</option>
                  {spawns.map((s) => (
                    <option key={s.id} value={s.id}>{s.name}</option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={handleIngest}
                  disabled={ingesting || !spawnId || !note.body.trim()}
                  className={`${actionBtn} bg-primary/10 hover:bg-primary/20 border border-primary/30 text-primary`}
                >
                  {ingesting ? <RefreshCcw className="w-3.5 h-3.5 animate-spin" /> : <Database className="w-3.5 h-3.5" />}
                  <span>{t('capabilities.dossier.note.ingest')}</span>
                </button>
              </div>
            </>
          )}
          {noticeRow(noteNotice)}
        </div>
      )}
    </div>
  );
}
