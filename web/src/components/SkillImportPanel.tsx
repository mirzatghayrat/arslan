import { useState } from 'react';
import { FileDown, RefreshCcw, Check, X, Shield, FileCode2 } from 'lucide-react';
import { scanSkills, importSkill, type SkillScanResult } from '../api/discovery';

/**
 * SkillImportPanel (P3) — faithful SKILL.md importer. Scan a repo for standard
 * Agent-Skills SKILL.md files and import them VERBATIM (no LLM rewrite), incl. bundled
 * scripts/*.py for the sandbox. The license gate is enforced server-side; this panel
 * only mirrors the verdict (importable / reason).
 */
export default function SkillImportPanel() {
  const [ref, setRef] = useState('');
  const [subpath, setSubpath] = useState('');
  const [scanning, setScanning] = useState(false);
  const [result, setResult] = useState<SkillScanResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyPath, setBusyPath] = useState<string | null>(null);
  const [imported, setImported] = useState<Record<string, boolean>>({});
  const [importErr, setImportErr] = useState<Record<string, string>>({});

  const scan = async () => {
    if (!ref.trim()) return;
    setScanning(true);
    setError(null);
    setResult(null);
    setImported({});
    setImportErr({});
    try {
      setResult(await scanSkills(ref.trim(), subpath.trim()));
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setScanning(false);
    }
  };

  const doImport = async (path: string) => {
    setBusyPath(path);
    setImportErr((prev) => ({ ...prev, [path]: '' }));
    try {
      await importSkill(ref.trim(), path);
      setImported((prev) => ({ ...prev, [path]: true }));
    } catch (e) {
      setImportErr((prev) => ({ ...prev, [path]: String(e instanceof Error ? e.message : e) }));
    } finally {
      setBusyPath(null);
    }
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1.5 text-[10.5px] font-mono text-subtle-foreground select-none">
        <FileDown className="w-3 h-3" />
        <span>Import skills (standard SKILL.md, verbatim — license-gated)</span>
      </div>
      <div className="flex gap-2">
        <input
          type="text"
          value={ref}
          onChange={(e) => setRef(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !scanning) scan(); }}
          placeholder="owner/repo"
          className="flex-1 bg-background border border-border/60 focus:border-primary focus:outline-none rounded-lg px-3 py-1.5 text-[11px] text-foreground font-mono placeholder-subtle-foreground"
        />
        <input
          type="text"
          value={subpath}
          onChange={(e) => setSubpath(e.target.value)}
          placeholder="subpath (optional)"
          className="w-40 bg-background border border-border/60 focus:border-primary focus:outline-none rounded-lg px-3 py-1.5 text-[11px] text-foreground font-mono placeholder-subtle-foreground"
        />
        <button
          type="button"
          onClick={scan}
          disabled={scanning || !ref.trim()}
          className="px-4 py-1.5 bg-surface/90 hover:bg-border border border-border-strong text-foreground text-[10.5px] font-bold font-mono uppercase rounded-lg flex items-center gap-1 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {scanning ? <RefreshCcw className="w-3 h-3 animate-spin" /> : <FileCode2 className="w-3 h-3" />}
          <span>Scan</span>
        </button>
      </div>

      {error && (
        <div className="flex items-start gap-2 bg-danger/15 border border-danger/40 rounded-lg px-3 py-2 text-[11px] text-danger font-sans">
          <X className="w-3.5 h-3.5 shrink-0 mt-0.5" /> <span>{error}</span>
        </div>
      )}

      {result && (
        <div className="space-y-1.5">
          <div className="flex items-center gap-2 text-[10.5px] font-mono">
            <span className="text-foreground font-bold">{result.repo.full_name}</span>
            <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded ${
              result.license_ok ? 'bg-success/15 text-success' : 'bg-danger/15 text-danger'}`}>
              <Shield className="w-2.5 h-2.5" />
              {result.repo.license ?? 'NO LICENSE'}
            </span>
            {!result.license_ok && (
              <span className="text-danger">{result.license_note}</span>
            )}
          </div>
          {result.skills.length === 0 && (
            <p className="text-[11px] text-subtle-foreground font-sans">No SKILL.md files found.</p>
          )}
          {result.skills.map((s) => (
            <div key={s.path}
              className="bg-background border border-border/60 rounded-lg px-3 py-2 flex items-center gap-2 flex-wrap">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-[11.5px] font-bold text-foreground">{s.name ?? s.path}</span>
                  {typeof s.body_bytes === 'number' && (
                    <span className="text-[9px] font-mono text-subtle-foreground">{Math.round(s.body_bytes / 100) / 10}KB</span>
                  )}
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
                  <Check className="w-3.5 h-3.5" /> Imported
                </span>
              ) : (
                <button
                  type="button"
                  onClick={() => doImport(s.path)}
                  disabled={!s.importable || busyPath === s.path}
                  className="px-3 py-1 bg-primary/10 hover:bg-primary/20 border border-primary/30 text-primary text-[10px] font-mono uppercase rounded-lg transition-all disabled:opacity-40 disabled:cursor-not-allowed shrink-0 flex items-center gap-1"
                >
                  {busyPath === s.path ? <RefreshCcw className="w-3 h-3 animate-spin" /> : <FileDown className="w-3 h-3" />}
                  <span>Import</span>
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
