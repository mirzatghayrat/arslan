import { useEffect, useState, useCallback } from 'react';
import { Zap, KeyRound, Check, RefreshCcw, Plug, FolderOpen, X } from 'lucide-react';
import { MCP_PRESETS } from '../data/mcpPresets';
import { isOneClick, type McpPrefill } from '../data/mcpPresets';
import { listMcpServers, addMcpServer, connectMcpServer } from '../api/mcp';
import type { McpServer } from '../api/client.types';

/** The arg that identifies a preset's package, so we can tell if it's already been added. */
function pkgId(p: McpPrefill): string {
  return (
    p.args.find(a => a.startsWith('@modelcontextprotocol/') || a.startsWith('mcp-server-')) ??
    p.args[p.args.length - 1] ??
    p.label
  );
}

type Status = { state: 'idle' | 'connecting' | 'ok' | 'error'; msg?: string };

/**
 * RecommendedMcp — a curated list of MCP servers. Credential-free ones connect in one action
 * (add → connect); credentialed ones prefill the add form (the user supplies the key). Nothing
 * is installed until the user clicks. Path servers (filesystem/git) take a local path inline.
 */
export default function RecommendedMcp({
  onChanged,
  onPrefillMcp,
}: {
  onChanged?: () => void;
  onPrefillMcp?: (d: McpPrefill) => void;
}) {
  const [servers, setServers] = useState<McpServer[]>([]);
  const [status, setStatus] = useState<Record<string, Status>>({});
  const [paths, setPaths] = useState<Record<string, string>>({});

  const refresh = useCallback(async () => {
    try { setServers(await listMcpServers()); } catch { /* offline: cards still connectable */ }
  }, []);
  useEffect(() => { refresh(); }, [refresh]);

  // A preset is already installed if a server shares its command + package identifier.
  const installed = (p: McpPrefill): McpServer | undefined =>
    servers.find(s => s.command === p.command && (s.args || []).join(' ').includes(pkgId(p)));

  const setStat = (label: string, s: Status) => setStatus(prev => ({ ...prev, [label]: s }));

  const connect = async (p: McpPrefill) => {
    const args = p.needsPath ? [...p.args, (paths[p.label] || '').trim()] : p.args;
    if (p.needsPath && !(paths[p.label] || '').trim()) {
      setStat(p.label, { state: 'error', msg: 'Enter a path first.' });
      return;
    }
    setStat(p.label, { state: 'connecting' });
    try {
      const srv = await addMcpServer({
        label: p.label, transport: p.transport, command: p.command, args, env: {},
      });
      await connectMcpServer(srv.id);
      setStat(p.label, { state: 'ok' });
      await refresh();
      onChanged?.();
    } catch (e) {
      const msg = String(e instanceof Error ? e.message : e);
      // A missing runtime is the common failure — make it actionable.
      const hint = p.runtime === 'python'
        ? ' (needs `uv` — install Python/uv, or connect a node server instead)'
        : ' (needs Node.js/npx on the host)';
      setStat(p.label, { state: 'error', msg: /not found|enoent|spawn/i.test(msg) ? msg + hint : msg });
    }
  };

  const card = (p: McpPrefill) => {
    const oneClick = isOneClick(p);
    const st = status[p.label] ?? { state: 'idle' as const };
    const already = installed(p);
    return (
      <div key={p.label} className="bg-background border border-border-strong rounded-xl p-3.5 flex flex-col gap-2">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="text-[12px] font-bold text-foreground">{p.label}</span>
              {p.test && <span className="text-[8.5px] font-mono uppercase tracking-wider bg-surface text-subtle-foreground px-1.5 py-0.5 rounded">test</span>}
              <span className="text-[8.5px] font-mono uppercase tracking-wider bg-surface text-subtle-foreground px-1.5 py-0.5 rounded">
                {p.runtime === 'python' ? 'needs uv' : 'node'}
              </span>
              {oneClick
                ? <span className="inline-flex items-center gap-0.5 text-[8.5px] font-mono uppercase tracking-wider bg-success/15 text-success px-1.5 py-0.5 rounded"><Zap className="w-2.5 h-2.5" />one-click</span>
                : <span className="inline-flex items-center gap-0.5 text-[8.5px] font-mono uppercase tracking-wider bg-warning/15 text-warning px-1.5 py-0.5 rounded"><KeyRound className="w-2.5 h-2.5" />needs key</span>}
            </div>
            <p className="text-[11px] text-subtle-foreground font-sans mt-1 leading-snug">{p.description}</p>
          </div>
        </div>

        {oneClick && p.needsPath && !already && (
          <div className="flex items-center gap-1.5">
            <FolderOpen className="w-3.5 h-3.5 text-subtle-foreground shrink-0" />
            <input
              type="text"
              value={paths[p.label] ?? ''}
              onChange={e => setPaths(prev => ({ ...prev, [p.label]: e.target.value }))}
              placeholder={p.pathPlaceholder}
              className="flex-1 bg-surface border border-border-strong focus:border-primary focus:outline-none rounded-md px-2 py-1 text-[10.5px] text-foreground font-mono placeholder-subtle-foreground"
            />
          </div>
        )}

        <div className="flex items-center gap-2 min-h-[24px]">
          {already ? (
            <span className="inline-flex items-center gap-1 text-[10.5px] text-success font-mono">
              <Check className="w-3.5 h-3.5" /> Added — manage below
            </span>
          ) : oneClick ? (
            <button
              type="button"
              onClick={() => connect(p)}
              disabled={st.state === 'connecting'}
              className="inline-flex items-center gap-1 px-3 py-1.5 bg-primary hover:bg-primary-hover text-primary-foreground text-[10.5px] font-bold font-mono uppercase rounded-lg transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {st.state === 'connecting' ? <RefreshCcw className="w-3.5 h-3.5 animate-spin" /> : <Plug className="w-3.5 h-3.5" />}
              <span>{st.state === 'connecting' ? 'Connecting…' : 'Connect'}</span>
            </button>
          ) : (
            <button
              type="button"
              onClick={() => onPrefillMcp?.(p)}
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

  const oneClickPresets = MCP_PRESETS.filter(isOneClick);
  const authPresets = MCP_PRESETS.filter(p => !isOneClick(p));

  return (
    <div className="space-y-3">
      <div>
        <div className="flex items-center gap-1.5 text-[10px] font-mono text-subtle-foreground uppercase tracking-widest mb-2">
          <Zap className="w-3 h-3 text-success" /> One-click (no credentials)
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-2.5">{oneClickPresets.map(card)}</div>
      </div>
      <div>
        <div className="flex items-center gap-1.5 text-[10px] font-mono text-subtle-foreground uppercase tracking-widest mb-2">
          <KeyRound className="w-3 h-3 text-warning" /> Needs an API key — set up, then connect
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-2.5">{authPresets.map(card)}</div>
      </div>
    </div>
  );
}
