import { useState } from 'react';
import { Plug, FolderOpen, X, Check, ExternalLink, Loader2 } from 'lucide-react';
import { addMcpServer, connectMcpServer, exposeMcpServer, wireMcpTool } from '../api/mcp';
import type { McpConnectorEnvVar, McpTool } from '../api/client.types';

/** Input to the apply chain: everything addMcpServer needs, PLUS the credential
 *  VALUES the user typed into this card's password fields (never sent over WS). */
export interface ConnectMcpAdd {
  label: string;
  transport: string;
  command: string;
  args: string[];
  url: string | null;
  env: Record<string, string>;
}

export interface ApplyConnectMcpResult {
  ok: boolean;
  /** Present only on failure — the stage where the chain stopped. */
  stage?: 'add' | 'connect' | 'expose';
  serverId?: number;
  /** Human-readable outcome: on failure, names the stopped state + where to fix it
   *  (never a bare "failed"); on success, unset (the card renders its own copy from
   *  the counts below). */
  message?: string;
  toolCount?: number;
  safeCount?: number;
  restrictedCount?: number;
  /** False when NO tool was wired "safe" — connected but nothing is usable by a
   *  spawn until a human reviews tiers in Settings → MCP. */
  assignable?: boolean;
}

/**
 * Pure apply chain for a confirmed ConnectMcpCard: add → connect → expose → wire.
 *
 * 🔒 SECURITY-LOAD-BEARING (the whole point of this card):
 *   1. Each discovered tool is wired at its OWN `suggested_tier` from
 *      `connectMcpServer`'s response — NEVER a blanket "safe". A write tool
 *      (suggested_tier === "orchestrator", e.g. delete_repo) must come out of chat
 *      still locked to "orchestrator" — chat can never grant a wider default than
 *      Settings → MCP would.
 *   2. Secrets (`add.env` values) flow ONLY into `addMcpServer`'s REST body. This
 *      function never touches a WS frame and never logs/echoes a value.
 *   3. Any failure returns the STOPPED stage + an actionable message naming where to
 *      finish in Settings → MCP — never a bare "failed".
 *   4. `assignable` is false whenever no tool was wired "safe", so the caller can
 *      show "connected but needs review" instead of implying it's ready to use.
 */
export async function applyConnectMcp(add: ConnectMcpAdd): Promise<ApplyConnectMcpResult> {
  let serverId: number;
  try {
    const srv = await addMcpServer(add);
    serverId = srv.id;
  } catch {
    return {
      ok: false,
      stage: 'add',
      message: "Couldn't add the server — check the details, or add it in Settings → MCP.",
    };
  }

  let tools: McpTool[];
  try {
    tools = await connectMcpServer(serverId);
  } catch {
    return {
      ok: false,
      stage: 'connect',
      serverId,
      message:
        "Added but couldn't connect (check the token / that the command is installed) — retry in Settings → MCP.",
    };
  }

  try {
    await exposeMcpServer(serverId, true);
  } catch {
    return {
      ok: false,
      stage: 'expose',
      serverId,
      message: "Connected but couldn't expose its tools — finish in Settings → MCP.",
    };
  }

  let safe = 0;
  let restricted = 0;
  for (const t of tools) {
    // NEVER blanket "safe" — wire each tool at its own suggested_tier.
    const tier = t.suggested_tier === 'safe' ? 'safe' : 'orchestrator';
    await wireMcpTool(t.key, tier, true);
    if (tier === 'safe') safe++;
    else restricted++;
  }

  return {
    ok: true,
    serverId,
    toolCount: tools.length,
    safeCount: safe,
    restrictedCount: restricted,
    assignable: safe >= 1,
  };
}

export interface ConnectMcpCardProps {
  callId: string;
  label: string;
  transport: string;
  command: string;
  /** Raw argv from the propose_connect_mcp frame — NEVER mutated in place. */
  args: string[];
  url: string | null;
  envKeys: McpConnectorEnvVar[];
  prerequisites?: string;
  requiresPath?: boolean;
  pathPlaceholder?: string | null;
  /** Fired once the apply chain settles (success or failure) so the parent can
   *  send the secret-free confirm_connect_mcp frame on success. */
  onApplied: (result: ApplyConnectMcpResult) => void;
  onCancel: (callId: string) => void;
}

/**
 * In-chat confirm card for a `propose_connect_mcp` frame. Discloses prerequisites
 * (per required env: name/description/get-it link/paid flag) and collects
 * credential VALUES in password fields (reused McpServers.tsx markup) — those
 * values are read locally and go straight into `applyConnectMcp`'s REST calls,
 * never onto the WebSocket. A `requires_path` connector (Filesystem/Git) instead
 * shows a plain text path field and gates Connect until it's filled; the typed
 * path is appended to a NEW args array before applying.
 */
export default function ConnectMcpCard({
  callId,
  label,
  transport,
  command,
  args,
  url,
  envKeys,
  prerequisites,
  requiresPath,
  pathPlaceholder,
  onApplied,
  onCancel,
}: ConnectMcpCardProps) {
  const [envValues, setEnvValues] = useState<Record<string, string>>({});
  const [path, setPath] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ApplyConnectMcpResult | null>(null);
  const [pathError, setPathError] = useState<string | null>(null);

  const pathMissing = !!requiresPath && !path.trim();

  async function handleConnect() {
    if (busy) return;
    if (pathMissing) {
      setPathError('Enter a path first.');
      return;
    }
    setPathError(null);
    setBusy(true);
    setResult(null);
    // NEVER mutate the frame's args in place — build a new array.
    const finalArgs = requiresPath ? [...args, path.trim()] : args;
    const env: Record<string, string> = {};
    for (const e of envKeys) {
      const v = (envValues[e.name] ?? '').trim();
      if (v) env[e.name] = v;
    }
    const res = await applyConnectMcp({ label, transport, command, args: finalArgs, url, env });
    setBusy(false);
    setResult(res);
    onApplied(res);
  }

  return (
    <div
      className="bg-surface border border-border-strong rounded-2xl p-5 space-y-4"
      data-testid="connect-mcp-card"
    >
      <div className="flex items-center gap-2">
        <Plug className="w-4 h-4 text-primary" />
        <h3 className="text-sm font-bold text-foreground">{label}</h3>
      </div>
      <p className="text-[11px] text-subtle-foreground font-mono truncate">
        {transport === 'http' ? `http · ${url ?? ''}` : `${command} ${args.join(' ')}`}
      </p>
      {prerequisites ? <p className="text-[11px] text-muted-foreground">{prerequisites}</p> : null}

      {envKeys.length > 0 && (
        <div className="space-y-3">
          {envKeys.map((e) => (
            <div key={e.name} className="space-y-1">
              <label
                htmlFor={`mcp-env-${e.name}`}
                className="block text-[10px] font-mono uppercase tracking-wide text-subtle-foreground"
              >
                {e.name}
              </label>
              <p className="text-[11px] text-muted-foreground">
                {e.description}
                {e.get_it_url ? (
                  <>
                    {' '}
                    <a
                      href={e.get_it_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-primary underline inline-flex items-center gap-0.5"
                    >
                      Get one <ExternalLink className="w-3 h-3" />
                    </a>
                  </>
                ) : null}
              </p>
              {e.paid ? (
                <span className="inline-block text-[9px] font-mono uppercase tracking-wide text-warning">
                  Requires a paid account
                </span>
              ) : null}
              {/* Secret-via-REST: this value is collected locally and only ever
                  leaves the browser inside addMcpServer's POST body. */}
              <input
                id={`mcp-env-${e.name}`}
                type="password"
                autoComplete="off"
                aria-label={e.name}
                value={envValues[e.name] ?? ''}
                onChange={(ev) => setEnvValues((prev) => ({ ...prev, [e.name]: ev.target.value }))}
                className="w-full bg-surface border border-border-strong focus:border-primary focus:ring-1 focus:ring-ring rounded-lg px-3 py-2 text-xs text-foreground placeholder-subtle-foreground focus:outline-none transition-all font-mono"
              />
            </div>
          ))}
        </div>
      )}

      {requiresPath && (
        <div className="space-y-1">
          <div className="flex items-center gap-1.5">
            <FolderOpen className="w-3.5 h-3.5 text-subtle-foreground shrink-0" />
            <input
              type="text"
              aria-label="local path"
              value={path}
              onChange={(e) => {
                setPath(e.target.value);
                if (pathError) setPathError(null);
              }}
              placeholder={pathPlaceholder ?? undefined}
              className="flex-1 bg-surface border border-border-strong focus:border-primary focus:outline-none rounded-md px-2 py-1 text-[10.5px] text-foreground font-mono placeholder-subtle-foreground"
            />
          </div>
          {pathError ? <p className="text-[10.5px] text-danger">{pathError}</p> : null}
        </div>
      )}

      {result && !result.ok && (
        <div
          role="alert"
          className="flex items-start gap-2 bg-danger/10 border border-danger/30 rounded-lg px-3 py-2 text-[11px] text-danger"
        >
          <X className="w-3.5 h-3.5 shrink-0 mt-0.5" />
          <span>{result.message}</span>
        </div>
      )}
      {result && result.ok && (
        <div className="flex items-start gap-2 bg-success/10 border border-success/30 rounded-lg px-3 py-2 text-[11px] text-success">
          <Check className="w-3.5 h-3.5 shrink-0 mt-0.5" />
          <span>
            {result.assignable
              ? `Connected — ${result.safeCount} ready, ${result.restrictedCount} restricted.`
              : 'Connected but needs review in Settings → MCP before any spawn can use it.'}
          </span>
        </div>
      )}

      <div className="flex items-center gap-2">
        <button
          type="button"
          disabled={busy || (result?.ok ?? false)}
          onClick={handleConnect}
          data-testid="connect-mcp-connect"
          className="flex items-center gap-1.5 px-4 py-2 text-xs font-bold font-sans uppercase rounded-lg bg-primary hover:bg-primary-hover text-primary-foreground transition-all disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plug className="w-3.5 h-3.5" />}
          {busy ? 'Connecting…' : 'Connect'}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => onCancel(callId)}
          data-testid="connect-mcp-cancel"
          className="px-4 py-2 text-xs font-bold font-sans uppercase rounded-lg bg-surface-raised hover:bg-surface text-muted-foreground hover:text-foreground transition-all disabled:opacity-50"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
