import { useEffect, useState, useCallback } from 'react';
import { Zap, KeyRound, Check, RefreshCcw, Plug, FolderOpen, X } from 'lucide-react';
import { getMcpCatalog } from '../api/catalog';
import { listMcpServers, addMcpServer, connectMcpServer } from '../api/mcp';
import type { McpServer, McpConnector, McpPrefill } from '../api/client.types';

/** The arg that identifies a connector's package, so we can tell if it's already been added. */
function pkgId(c: McpConnector): string {
  return (
    c.args.find(a => a.startsWith('@modelcontextprotocol/') || a.startsWith('mcp-server-')) ??
    c.args[c.args.length - 1] ??
    c.key
  );
}

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

type Status = { state: 'idle' | 'connecting' | 'ok' | 'error'; msg?: string };

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
  const [connectors, setConnectors] = useState<McpConnector[]>([]);
  const [servers, setServers] = useState<McpServer[]>([]);
  const [status, setStatus] = useState<Record<string, Status>>({});
  const [paths, setPaths] = useState<Record<string, string>>({});

  useEffect(() => {
    getMcpCatalog().then(setConnectors).catch(() => { /* offline: no presets to show */ });
  }, []);

  const refresh = useCallback(async () => {
    try { setServers(await listMcpServers()); } catch { /* offline: cards still connectable */ }
  }, []);
  useEffect(() => { refresh(); }, [refresh]);

  // A connector is already installed if a server shares its command + package identifier.
  const installed = (c: McpConnector): McpServer | undefined =>
    servers.find(s => s.command === c.command && (s.args || []).join(' ').includes(pkgId(c)));

  const setStat = (key: string, s: Status) => setStatus(prev => ({ ...prev, [key]: s }));

  const connect = async (c: McpConnector) => {
    // requires_path connectors (Filesystem/Git) are credential-free but still need a local
    // path — ported from the old mcpPresets.ts needsPath/pathPlaceholder contract: the typed
    // path is appended to args before add/connect (git's base args already end in
    // "--repository", so appending the path completes that flag; filesystem just takes the
    // bare path as its final arg).
    const path = (paths[c.key] || '').trim();
    if (c.requires_path && !path) {
      setStat(c.key, { state: 'error', msg: 'Enter a path first.' });
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
      const hint = c.runtime === 'python'
        ? ' (needs `uv` — install Python/uv, or connect a node server instead)'
        : ' (needs Node.js/npx on the host)';
      setStat(c.key, { state: 'error', msg: /not found|enoent|spawn/i.test(msg) ? msg + hint : msg });
    }
  };

  const card = (c: McpConnector) => {
    const st = status[c.key] ?? { state: 'idle' as const };
    const already = installed(c);
    return (
      <div key={c.key} className="bg-background border border-border-strong rounded-xl p-3.5 flex flex-col gap-2">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="text-[12px] font-bold text-foreground">{c.label}</span>
              <span className="text-[8.5px] font-mono uppercase tracking-wider bg-surface text-subtle-foreground px-1.5 py-0.5 rounded">
                {c.runtime === 'python' ? 'needs uv' : 'node'}
              </span>
              {c.one_click
                ? <span className="inline-flex items-center gap-0.5 text-[8.5px] font-mono uppercase tracking-wider bg-success/15 text-success px-1.5 py-0.5 rounded"><Zap className="w-2.5 h-2.5" />one-click</span>
                : <span className="inline-flex items-center gap-0.5 text-[8.5px] font-mono uppercase tracking-wider bg-warning/15 text-warning px-1.5 py-0.5 rounded"><KeyRound className="w-2.5 h-2.5" />needs key</span>}
            </div>
            <p className="text-[11px] text-subtle-foreground font-sans mt-1 leading-snug">{c.description}</p>
          </div>
        </div>

        {c.one_click && c.requires_path && !already && (
          <div className="flex items-center gap-1.5">
            <FolderOpen className="w-3.5 h-3.5 text-subtle-foreground shrink-0" />
            <input
              type="text"
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
              <Check className="w-3.5 h-3.5" /> Added — manage below
            </span>
          ) : c.one_click ? (
            <button
              type="button"
              onClick={() => connect(c)}
              disabled={st.state === 'connecting'}
              className="inline-flex items-center gap-1 px-3 py-1.5 bg-primary hover:bg-primary-hover text-primary-foreground text-[10.5px] font-bold font-mono uppercase rounded-lg transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {st.state === 'connecting' ? <RefreshCcw className="w-3.5 h-3.5 animate-spin" /> : <Plug className="w-3.5 h-3.5" />}
              <span>{st.state === 'connecting' ? 'Connecting…' : 'Connect'}</span>
            </button>
          ) : (
            <button
              type="button"
              onClick={() => onPrefillMcp?.(toPrefill(c))}
              className="inline-flex items-center gap-1 px-3 py-1.5 bg-surface hover:bg-foreground/[0.04] border border-border-strong text-muted-foreground hover:text-foreground text-[10.5px] font-bold font-mono uppercase rounded-lg transition-all"
            >
              <KeyRound className="w-3.5 h-3.5" />
              <span>Set up</span>
            </button>
          )}
          {st.state === 'ok' && !already && (
            <span className="inline-flex items-center gap-1 text-[10.5px] text-success font-mono"><Check className="w-3.5 h-3.5" /> Connected</span>
          )}
          {st.state === 'error' && (
            <span className="inline-flex items-center gap-1 text-[10.5px] text-danger font-sans"><X className="w-3.5 h-3.5 shrink-0" /> {st.msg}</span>
          )}
        </div>
      </div>
    );
  };

  const oneClickConnectors = connectors.filter(c => c.one_click);
  const authConnectors = connectors.filter(c => !c.one_click);

  return (
    <div className="space-y-3">
      <div>
        <div className="flex items-center gap-1.5 text-[10px] font-mono text-subtle-foreground uppercase tracking-widest mb-2">
          <Zap className="w-3 h-3 text-success" /> One-click (no credentials)
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-2.5">{oneClickConnectors.map(card)}</div>
      </div>
      <div>
        <div className="flex items-center gap-1.5 text-[10px] font-mono text-subtle-foreground uppercase tracking-widest mb-2">
          <KeyRound className="w-3 h-3 text-warning" /> Needs an API key — set up, then connect
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-2.5">{authConnectors.map(card)}</div>
      </div>
    </div>
  );
}
