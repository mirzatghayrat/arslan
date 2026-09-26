import { useEffect, useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Zap, KeyRound, Check, RefreshCcw, Plug, FolderOpen, X } from 'lucide-react';
import { getMcpCatalog } from '../api/catalog';
import { listMcpServers, addMcpServer, connectMcpServer } from '../api/mcp';
import type { McpServer, McpConnector, McpPrefill } from '../api/client.types';
import { catalogText } from '../lib/catalogDisplay';

/** Build the MCP add-form prefill payload from a catalog connector (credentialed cards only). */
function toPrefill(c: McpConnector): McpPrefill {
  return {
    label: c.label,
    command: c.command,
    args: c.args,
    transport: c.transport,
    url: c.url ?? undefined,
    envKeys: c.env.map(e => e.name),
  };
}

type Status = { state: 'idle' | 'connecting' | 'ok' | 'error'; msg?: string; code?: 'pathFirst'; missingRuntime?: boolean };

/**
 * RecommendedMcp — a curated list of MCP servers, fetched from the backend's single-source
 * catalog (GET /mcp/catalog). Credential-free connectors connect in one action (add →
 * connect); credentialed ones prefill the add form (the user supplies the key). Nothing is
 * installed until the user clicks.
 */
export default function RecommendedMcp({
  onChanged,
  onPrefillMcp,
}: {
  onChanged?: () => void;
  onPrefillMcp?: (d: McpPrefill) => void;
}) {
  const { t } = useTranslation();
  const [connectors, setConnectors] = useState<McpConnector[]>([]);
  const [servers, setServers] = useState<McpServer[]>([]);
  const [status, setStatus] = useState<Record<string, Status>>({});
  const [paths, setPaths] = useState<Record<string, string>>({});
  const [catalogState, setCatalogState] = useState<'loading' | 'ready' | 'error'>('loading');

  const loadCatalog = useCallback(async () => {
    setCatalogState('loading');
    try { setConnectors(await getMcpCatalog()); setCatalogState('ready'); }
    catch { setCatalogState('error'); }
  }, []);
  useEffect(() => { void loadCatalog(); }, [loadCatalog]);

  const refresh = useCallback(async () => {
    try { setServers(await listMcpServers()); } catch { /* offline: cards still connectable */ }
  }, []);
  useEffect(() => { refresh(); }, [refresh]);

  // Require the complete preset prefix, including version and containment flags.
  // A shared trailing flag (e.g. --sandbox) is not a package identity.
  const installed = (c: McpConnector): McpServer | undefined =>
    servers.find(s => s.command === c.command && (s.transport ?? 'stdio') === c.transport
      && c.args.length > 0 && c.args.every((arg, index) => s.args?.[index] === arg));

  const setStat = (key: string, s: Status) => setStatus(prev => ({ ...prev, [key]: s }));

  const connect = async (c: McpConnector) => {
    // requires_path connectors (Filesystem/Git) are credential-free but still need a local
    // path — ported from the old mcpPresets.ts needsPath/pathPlaceholder contract: the typed
    // path is appended to args before add/connect (git's base args already end in
    // "--repository", so appending the path completes that flag; filesystem just takes the
    // bare path as its final arg).
    const path = (paths[c.key] || '').trim();
    if (c.requires_path && !path) {
      setStat(c.key, { state: 'error', code: 'pathFirst' });
      return;
    }
    const args = c.requires_path ? [...c.args, path] : c.args;
    setStat(c.key, { state: 'connecting' });
    try {
      const srv = await addMcpServer({
        label: c.label, transport: c.transport, command: c.command, args, env: {},
      });
      await connectMcpServer(srv.id);
      setStat(c.key, { state: 'ok' });
      await refresh();
      onChanged?.();
    } catch (e) {
      const msg = String(e instanceof Error ? e.message : e);
      // A missing runtime is the common failure — make it actionable.
      setStat(c.key, { state: 'error', msg, missingRuntime: /not found|enoent|spawn/i.test(msg) });
    }
  };

  // The explicit field wins; the derivation stays only as a fallback for a stale
  // backend payload from before the field existed.
  const authOf = (c: McpConnector): 'none' | 'static_key' | 'oauth' =>
    c.auth ?? (c.one_click ? 'none' : 'static_key');

  const card = (c: McpConnector) => {
    const st = status[c.key] ?? { state: 'idle' as const };
    const already = installed(c);
    const auth = authOf(c);

    if (auth === 'oauth') {
      // Honest and inert, deliberately: no Connect (it could only fail), no
      // prefill form (it would collect a key no service will ever issue).
      return (
        <div key={c.key} data-auth="oauth" className="bg-background border border-border-strong rounded-xl p-3.5 flex flex-col gap-2 opacity-80">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-[12px] font-bold text-foreground">{catalogText(t, c.label_key, c.label)}</span>
            <span className="inline-flex items-center gap-0.5 text-[8.5px] font-mono uppercase tracking-wider bg-surface text-subtle-foreground px-1.5 py-0.5 rounded"><KeyRound className="w-2.5 h-2.5" />OAuth</span>
          </div>
          <p className="text-[11px] text-subtle-foreground font-sans leading-snug">{catalogText(t, c.description_key, c.description)}</p>
          <p className="text-[10.5px] text-subtle-foreground font-sans">
            {t('connectionsUI.oauthUnsupported')}
          </p>
        </div>
      );
    }

    return (
      <div key={c.key} data-auth={auth} className="bg-background border border-border-strong rounded-xl p-3.5 flex flex-col gap-2">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="text-[12px] font-bold text-foreground">{catalogText(t, c.label_key, c.label)}</span>
              <span className="text-[8.5px] font-mono uppercase tracking-wider bg-surface text-subtle-foreground px-1.5 py-0.5 rounded">
                {c.runtime === 'python' ? t('connectionsUI.needsUv') : 'node'}
              </span>
              {c.one_click
                ? <span className="inline-flex items-center gap-0.5 text-[8.5px] font-mono uppercase tracking-wider bg-success/15 text-success px-1.5 py-0.5 rounded"><Zap className="w-2.5 h-2.5" />{t('connectionsUI.oneClick')}</span>
                : <span className="inline-flex items-center gap-0.5 text-[8.5px] font-mono uppercase tracking-wider bg-warning/15 text-warning px-1.5 py-0.5 rounded"><KeyRound className="w-2.5 h-2.5" />{t('connectionsUI.needsKey')}</span>}
            </div>
            <p className="text-[11px] text-subtle-foreground font-sans mt-1 leading-snug">{catalogText(t, c.description_key, c.description)}</p>
          </div>
        </div>

        {c.one_click && c.requires_path && !already && (
          <div className="flex items-center gap-1.5">
            <FolderOpen className="w-3.5 h-3.5 text-subtle-foreground shrink-0" />
            <input
              type="text"
              aria-label={`${catalogText(t, c.label_key, c.label)} — ${t('connectionsUI.localPath')}`}
              value={paths[c.key] ?? ''}
              onChange={e => setPaths(prev => ({ ...prev, [c.key]: e.target.value }))}
              placeholder={c.path_placeholder ?? undefined}
              className="flex-1 bg-surface border border-border-strong focus:border-primary focus:outline-none rounded-md px-2 py-1 text-[10.5px] text-foreground font-mono placeholder-subtle-foreground"
            />
          </div>
        )}

        <div className="flex items-center gap-2 min-h-[24px]">
          {already ? (
            <span className="inline-flex items-center gap-1 text-[10.5px] text-success font-mono">
              <Check className="w-3.5 h-3.5" /> {t('connectionsUI.added')}
            </span>
          ) : c.one_click ? (
            <button
              type="button"
              onClick={() => connect(c)}
              disabled={st.state === 'connecting'}
              className="inline-flex items-center gap-1 px-3 py-1.5 bg-primary hover:bg-primary-hover text-primary-foreground text-[10.5px] font-bold font-mono uppercase rounded-lg transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {st.state === 'connecting' ? <RefreshCcw className="w-3.5 h-3.5 animate-spin" /> : <Plug className="w-3.5 h-3.5" />}
              <span>{t(st.state === 'connecting' ? 'connectionsUI.connecting' : 'connectionsUI.connect')}</span>
            </button>
          ) : (
            <button
              type="button"
              onClick={() => onPrefillMcp?.(toPrefill(c))}
              className="inline-flex items-center gap-1 px-3 py-1.5 bg-surface hover:bg-foreground/[0.04] border border-border-strong text-muted-foreground hover:text-foreground text-[10.5px] font-bold font-mono uppercase rounded-lg transition-all"
            >
              <KeyRound className="w-3.5 h-3.5" />
              <span>{t('connectionsUI.setup')}</span>
            </button>
          )}
          {st.state === 'ok' && !already && (
            <span className="inline-flex items-center gap-1 text-[10.5px] text-success font-mono"><Check className="w-3.5 h-3.5" /> {t('connectionsUI.connected')}</span>
          )}
          {st.state === 'error' && (
            <span className="inline-flex items-center gap-1 text-[10.5px] text-danger font-sans"><X className="w-3.5 h-3.5 shrink-0" /> {st.code ? t(`connectionsUI.${st.code}`) : st.msg}{st.missingRuntime && t(c.runtime === 'python' ? 'connectionsUI.pythonHint' : 'connectionsUI.nodeHint')}</span>
          )}
        </div>
      </div>
    );
  };

  const oneClickConnectors = connectors.filter(c => authOf(c) === 'none');
  const authConnectors = connectors.filter(c => authOf(c) === 'static_key');
  const oauthConnectors = connectors.filter(c => authOf(c) === 'oauth');

  if (catalogState === 'loading') return <p role="status">{t('create_card.picker.loading')}</p>;
  if (catalogState === 'error') return <div role="alert"><p>{t('create_card.picker.error')}</p>
    <button type="button" onClick={() => void loadCatalog()} className="mt-2 text-sm text-primary underline">{t('connectionsUI.refreshList')}</button></div>;

  return (
    <div className="space-y-3">
      <div>
        <div className="flex items-center gap-1.5 text-[10px] font-mono text-subtle-foreground uppercase tracking-widest mb-2">
          <Zap className="w-3 h-3 text-success" /> {t('connectionsUI.noCredentials')}
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-2.5">{oneClickConnectors.map(card)}</div>
      </div>
      <div>
        <div className="flex items-center gap-1.5 text-[10px] font-mono text-subtle-foreground uppercase tracking-widest mb-2">
          <KeyRound className="w-3 h-3 text-warning" /> {t('connectionsUI.keySection')}
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-2.5">{authConnectors.map(card)}</div>
      </div>
      {/* Rendered only when an oauth entry actually exists: an empty section
          with a heading is a placeholder, and this app deleted its placeholder
          tabs for a reason. Today's catalog has zero such entries — by ruling,
          the mechanism ships before the first real one. */}
      {oauthConnectors.length > 0 && (
        <div data-testid="mcp-oauth-section">
          <div className="flex items-center gap-1.5 text-[10px] font-mono text-subtle-foreground uppercase tracking-widest mb-2">
            <KeyRound className="w-3 h-3" /> {t('connectionsUI.oauthSection')}
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-2.5">{oauthConnectors.map(card)}</div>
        </div>
      )}
    </div>
  );
}
