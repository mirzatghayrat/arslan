import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FolderOpen, ExternalLink, KeyRound, Plug } from 'lucide-react';
import { AskCard, CodeBox, Notice, type AskQueuePosition } from './kit';
import { lineIcon } from './kit/askParts';
import { addMcpServer, connectMcpServer, exposeMcpServer, wireMcpTool } from '../api/mcp';
import type { McpConnectorEnvVar, McpTool } from '../api/client.types';
import { catalogText } from '../lib/catalogDisplay';

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
  stage?: 'add' | 'connect' | 'expose' | 'wire';
  serverId?: number;
  /** Human-readable outcome: on failure, names the stopped state + where to fix it
   *  (never a bare "failed"); on success, unset (the card renders its own copy from
   *  the counts below). */
  message?: string;
  toolCount?: number;
  safeCount?: number;
  restrictedCount?: number;
  /** False when NO tool was wired "safe" — connected but nothing is usable by a
   *  spawn until a human reviews tiers in Connections & permissions. */
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
 *      Connections & permissions would.
 *   2. Secrets (`add.env` values) flow ONLY into `addMcpServer`'s REST body. This
 *      function never touches a WS frame and never logs/echoes a value.
 *   3. Any failure returns the STOPPED stage + an actionable message naming where to
 *      finish in Connections & permissions — never a bare "failed".
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
      message: "Couldn't add the server — check the details, or add it in Connections & permissions.",
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
        "Added but couldn't connect (check the token / that the command is installed) — retry in Connections & permissions.",
    };
  }

  try {
    await exposeMcpServer(serverId, true);
  } catch {
    return {
      ok: false,
      stage: 'expose',
      serverId,
      message: "Connected but couldn't expose its tools — finish in Connections & permissions.",
    };
  }

  let safe = 0;
  let restricted = 0;
  try {
    for (const t of tools) {
      // NEVER blanket "safe" — wire each tool at its own suggested_tier.
      const tier = t.suggested_tier === 'safe' ? 'safe' : 'orchestrator';
      await wireMcpTool(t.key, tier, true);
      if (tier === 'safe') safe++;
      else restricted++;
    }
  } catch {
    return {
      ok: false,
      stage: 'wire',
      serverId,
      message: "Connected but couldn't finish wiring its tools — finish in Connections & permissions.",
    };
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
  labelKey?: string;
  transport: string;
  command: string;
  /** Raw argv from the propose_connect_mcp frame — NEVER mutated in place. */
  args: string[];
  url: string | null;
  envKeys: McpConnectorEnvVar[];
  prerequisites?: string;
  requiresPath?: boolean;
  pathPlaceholder?: string | null;
  expiresAt?: number | null;
  queue?: AskQueuePosition;
  /** Fired once the apply chain settles (success or failure) so the parent can
   *  send the secret-free confirm_connect_mcp frame on success. */
  onApplied: (result: ApplyConnectMcpResult) => void;
  onCancel: (callId: string) => void;
}

/**
 * In-chat confirm card for a `propose_connect_mcp` frame, in the 0.1.55 AskCard.
 * Discloses prerequisites (per required env: name / description / get-it link /
 * paid flag) and collects credential VALUES in password fields — read locally and
 * sent only through `applyConnectMcp`'s REST calls, never onto the WebSocket. A
 * `requires_path` connector (Filesystem / Git) shows a path field and gates Connect
 * until it is filled; the typed path is appended to a NEW args array.
 */
export default function ConnectMcpCard({
  callId, label, labelKey, transport, command, args, url, envKeys, prerequisites, requiresPath,
  pathPlaceholder, expiresAt, queue, onApplied, onCancel,
}: ConnectMcpCardProps) {
  const { t } = useTranslation();
  const [envValues, setEnvValues] = useState<Record<string, string>>({});
  const [path, setPath] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ApplyConnectMcpResult | null>(null);
  const [pathError, setPathError] = useState<string | null>(null);

  const pathMissing = !!requiresPath && !path.trim();

  async function handleConnect() {
    if (busy || result?.ok) return;
    if (pathMissing) {
      setPathError('path_required');
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

  const field = 'w-full rounded-[10px] border border-border bg-surface-raised px-3 py-2 font-mono text-[12px] text-foreground placeholder:text-subtle-foreground focus:outline-none focus:ring-2 focus:ring-foreground/20';
  const needs = prerequisites
    ? (envKeys.length > 0 && prerequisites === `Needs: ${envKeys.map(e => e.name).join(', ')}`
        ? `${t('connectionsUI.needsKey')}: ${envKeys.map(e => e.name).join(', ')}` : prerequisites)
    : null;
  const form = (
    <div className="flex flex-col gap-3">
      <CodeBox code={transport === 'http' ? `http · ${url ?? ''}` : `${command} ${args.join(' ')}`} numbered={false} />
      {envKeys.map((e) => (
        <div key={e.name} className="flex flex-col gap-1">
          <label htmlFor={`mcp-env-${e.name}`} className="font-mono text-[12px] text-foreground">{e.name}
            {e.paid ? <span className="ml-2 font-sans text-[11px] text-ask">{t('connectionsUI.paid')}</span> : null}</label>
          <p className="text-[12px] text-muted-foreground">
            {catalogText(t, e.description_key, e.description)}
            {e.get_it_url ? (<>{' '}<a href={e.get_it_url} target="_blank" rel="noreferrer"
              className="inline-flex items-center gap-0.5 underline underline-offset-2 hover:text-foreground">
              {t('connectionsUI.getKey')} <ExternalLink className="h-3 w-3" /></a></>) : null}
          </p>
          {/* Secret-via-REST: only ever leaves the browser inside addMcpServer's POST body. */}
          <input id={`mcp-env-${e.name}`} type="password" autoComplete="off" aria-label={e.name}
            value={envValues[e.name] ?? ''} className={field}
            onChange={(ev) => setEnvValues((prev) => ({ ...prev, [e.name]: ev.target.value }))} />
        </div>
      ))}
      {requiresPath && (
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <FolderOpen className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
            <input type="text" aria-label={t('connectionsUI.localPath')} value={path} className={field}
              placeholder={pathPlaceholder ?? undefined}
              onChange={(e) => { setPath(e.target.value); if (pathError) setPathError(null); }} />
          </div>
          {pathError ? <p className="text-[12px] text-danger-strong">{t('connectionsUI.pathFirst')}</p> : null}
        </div>
      )}
    </div>
  );
  return (
    <AskCard testId="connect-mcp-card" who={t('kit.whoArslan')}
      title={<span className="inline-flex items-center gap-2">{lineIcon(Plug)}<span>{catalogText(t, labelKey, label)}</span></span>}
      detail={form}
      context={needs ? [{ icon: lineIcon(KeyRound), text: needs }] : []}
      extra={result ? (result.ok
        ? <Notice tone="info" title={result.assignable
            ? t('connectionsUI.ready', { safe: result.safeCount, restricted: result.restrictedCount })
            : t('connectionsUI.needsReview')} />
        : <Notice tone="error">{result.stage ? t(`connectionsUI.failed_${result.stage}`) : t('connectionsUI.error')}</Notice>)
        : null}
      expiresAt={expiresAt} queue={queue} busy={busy}
      allowLabel={t(busy ? 'connectionsUI.connecting' : 'connectionsUI.connect')} declineLabel={t('common.cancel')}
      allowTestId="connect-mcp-connect" declineTestId="connect-mcp-cancel"
      onAllow={() => void handleConnect()} onDecline={() => onCancel(callId)} />
  );
}
