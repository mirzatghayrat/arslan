import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import CapabilityFilter from "./CapabilityFilter";
import { matches } from "../lib/capabilitySearch";
import { Plug, Plus, Trash2, X, AlertCircle, Zap, RefreshCw } from "lucide-react";
import type { McpServer, McpTool } from "../api/client.types";
import {
  addMcpServer,
  connectMcpServer,
  deleteMcpServer,
  exposeMcpServer,
  listMcpServers,
  listMcpTools,
  reconnectMcpServer,
  setMcpServerHost,
  wireMcpTool,
  authorizeMcpOauth,
  getMcpOauthStatus,
} from "../api/mcp";
import { openExternal } from "../lib/shell";

interface EnvRow {
  k: string;
  v: string;
}

// One-time seed payload for the add form (from a curated preset). Does NOT auto-submit.
interface McpServersProps {
  prefill?: {
    label: string;
    command: string;
    args: string[];
    transport: string;
    url?: string;
    envKeys?: string[];
  };
}

/**
 * MCP servers panel: register stdio MCP servers, connect to discover their tools,
 * then expose (toolset→safe) + wire (tool→safe+wired) to open the SQL choke point.
 * Tools are locked by default. Renders ONLY plain text — never server-supplied HTML.
 */
export default function McpServers({ prefill }: McpServersProps = {}) {
  const { t: tr } = useTranslation();
  const [servers, setServers] = useState<McpServer[]>([]);
  const [query, setQuery] = useState("");
  const [tools, setTools] = useState<Record<number, McpTool[]>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // add-server form state
  const [transport, setTransport] = useState<"stdio" | "http">("stdio");
  const [label, setLabel] = useState("");
  const [command, setCommand] = useState("");
  const [argsText, setArgsText] = useState("");
  const [url, setUrl] = useState("");
  const [envRows, setEnvRows] = useState<EnvRow[]>([{ k: "", v: "" }]);

  async function loadServers() {
    try {
      setServers(await listMcpServers());
    } catch (e) {
      setError(String(e));
    }
  }

  useEffect(() => {
    loadServers();
  }, []);

  // One-time seed of the add form from a curated preset. Does NOT auto-submit —
  // the user reviews, fills the path/key, and clicks Add (the consent step).
  useEffect(() => {
    if (!prefill) return;
    setLabel(prefill.label);
    setTransport(prefill.transport === "http" ? "http" : "stdio");
    setCommand(prefill.command);
    setArgsText((prefill.args || []).join(" "));
    setUrl(prefill.url ?? "");
    setEnvRows(
      prefill.envKeys && prefill.envKeys.length > 0
        ? prefill.envKeys.map((k) => ({ k, v: "" }))
        : [{ k: "", v: "" }],
    );
  }, [prefill]);

  const canAdd =
    !!label.trim() && (transport === "http" ? !!url.trim() : !!command.trim());

  async function addServer() {
    if (!canAdd) return;
    setBusy(true);
    setError(null);
    try {
      const args = argsText
        .split(/\s+/)
        .map((a) => a.trim())
        .filter(Boolean);
      // env doubles as HTTP headers (key/value rows).
      const env: Record<string, string> = {};
      for (const r of envRows) {
        if (r.k.trim()) env[r.k.trim()] = r.v;
      }
      if (transport === "http") {
        await addMcpServer({ label: label.trim(), args: [], env, transport: "http", url: url.trim() });
      } else {
        await addMcpServer({
          label: label.trim(),
          command: command.trim(),
          args,
          env,
          transport: "stdio",
        });
      }
      setLabel("");
      setCommand("");
      setArgsText("");
      setUrl("");
      setEnvRows([{ k: "", v: "" }]);
      await loadServers();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function reconnect(id: number) {
    setBusy(true);
    setError(null);
    try {
      await reconnectMcpServer(id);
      await loadServers();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function toggleServerHost(id: number, allowed: boolean) {
    setBusy(true);
    setError(null);
    try {
      await setMcpServerHost(id, allowed);
      await loadServers();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  const [oauthError, setOauthError] = useState<string>("");
  async function authorizeOauth(id: number) {
    setOauthError("");
    try {
      const { auth_url } = await authorizeMcpOauth(id);
      // The one legal path for this URL (ruling ③A): backend → this response →
      // the shell doorway. Nothing else may mint or open one.
      await openExternal(auth_url);
      // Poll the background flow, then run a REAL connect so the row's status
      // comes from the normal path rather than a special case.
      for (let i = 0; i < 90; i++) {
        const st = await getMcpOauthStatus(id);
        if (st.state === "done") {
          await connect(id);
          return;
        }
        if (st.state === "error") {
          setOauthError(st.error || tr("connectionsUI.authFailed"));
          return;
        }
        await new Promise((r) => setTimeout(r, 2000));
      }
      setOauthError(tr("connectionsUI.authTimeout"));
    } catch (e) {
      setOauthError(e instanceof Error ? e.message : String(e));
    }
  }

  async function connect(id: number) {
    setBusy(true);
    setError(null);
    try {
      const discovered = await connectMcpServer(id);
      setTools((prev) => ({ ...prev, [id]: discovered }));
      await loadServers();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function refreshTools(id: number) {
    try {
      const fresh = await listMcpTools(id);
      setTools((prev) => ({ ...prev, [id]: fresh }));
    } catch (e) {
      setError(String(e));
    }
  }

  async function expose(id: number, exposed: boolean) {
    setBusy(true);
    setError(null);
    try {
      await exposeMcpServer(id, exposed);
      await loadServers();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function wire(id: number, tool: McpTool, tier: string, wired: boolean) {
    setBusy(true);
    setError(null);
    try {
      await wireMcpTool(tool.key, tier, wired);
      await refreshTools(id);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: number) {
    setBusy(true);
    setError(null);
    try {
      await deleteMcpServer(id);
      setTools((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
      await loadServers();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  const setEnvRow = (i: number, patch: Partial<EnvRow>) =>
    setEnvRows((rows) => rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));

  const inputCls =
    "w-full bg-surface border border-border-strong focus:border-primary focus:ring-1 focus:ring-ring rounded-lg px-3 py-2 text-xs text-foreground placeholder-subtle-foreground focus:outline-none transition-all font-mono";

  // Search across what identifies a server to a person: its label, and how it
  // is reached. `command`/`url` are in the haystack because "the one I pointed
  // at notion" is how people remember these, not by the label they typed once.
  const shownServers = servers.filter((srv) =>
    matches(
      {
        key: srv.label,
        name: srv.label,
        description: [srv.command, ...(srv.args ?? []), srv.url ?? "", srv.transport ?? ""].join(" "),
      },
      query,
    ),
  );

  return (
    <div className="bg-surface/60 border border-border rounded-2xl p-6 space-y-6">
      <div className="flex items-center gap-2 pb-4 border-b border-border/50 select-none">
        <Plug className="w-4.5 h-4.5 text-primary" />
        <h3 className="text-xs font-semibold font-mono uppercase tracking-widest text-foreground leading-none">
          {tr("connectionsUI.servers")}
        </h3>
      </div>

      {error && (
        <div
          className="flex items-start gap-2 bg-danger/20 border border-danger/40 rounded-lg px-3 py-2 text-[11px] text-danger font-mono"
          role="alert"
        >
          <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {/* Server list */}
      {servers.length === 0 ? (
        <p className="text-[11px] text-subtle-foreground font-sans">
          {tr("connectionsUI.none")}
        </p>
      ) : (
        <>
        <CapabilityFilter
          testId="mcp-filter"
          value={query}
          onChange={setQuery}
          shown={shownServers.length}
          total={servers.length}
        />
        {shownServers.length === 0 ? (
          // A distinct message from "none registered": a query that hides
          // everything must not look like an empty library.
          <p className="text-[11px] text-subtle-foreground font-sans"
             data-testid="mcp-filter-empty">
            {tr("capabilities.filter.no_match")}
          </p>
        ) : (
        <ul className="space-y-4">
          {shownServers.map((s) => {
            const exposed = s.exposed ?? false;   // toolset-derived truth from the list
            return (
              <li
                key={s.id}
                className="bg-surface/40 border border-border/60 rounded-xl p-4 space-y-3"
              >
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-bold text-foreground font-sans truncate">
                        {s.label}
                      </span>
                      <span
                        className={`text-[9px] font-mono uppercase tracking-wide px-1.5 py-0.5 rounded ${
                          s.status === "connected"
                            ? "bg-success/20 text-success"
                            : s.status === "error"
                              ? "bg-danger/20 text-danger"
                              : "bg-surface-raised text-subtle-foreground"
                        }`}
                      >
                        {tr(`connectionsUI.${["registered", "connected", "connecting", "error", "disconnected"].includes(s.status) ? s.status : "unknown"}`)}
                      </span>
                    </div>
                    <p className="text-[10px] text-subtle-foreground font-mono mt-0.5 truncate">
                      {s.transport === "http"
                        ? `http · ${s.url ?? ""}`
                        : `${s.command} ${s.args.join(" ")}`}
                    </p>
                    {oauthError && (
                      <p className="text-[10px] text-danger font-mono mt-1 break-words">{oauthError}</p>
                    )}
                    {s.last_error && (
                      <p className="text-[10px] text-danger font-mono mt-1 break-words">
                        {s.last_error}
                      </p>
                    )}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {s.transport === "http" && /authorization/i.test(s.last_error ?? "") && (
                      /* Step 1's classifier decides when this shows: only a
                         failure NAMED as authorization. An unreachable host gets
                         no button — a browser round-trip cannot fix a network
                         path. */
                      <button
                        type="button"
                        data-testid={`mcp-authorize-${s.id}`}
                        disabled={busy}
                        onClick={() => authorizeOauth(s.id)}
                        className="flex items-center gap-1 px-2.5 py-1.5 text-[10px] font-bold font-sans uppercase rounded-lg bg-warning/20 hover:bg-warning/30 text-warning transition-all disabled:opacity-50"
                      >
                        {tr("connectionsUI.authorize")}
                      </button>
                    )}
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => connect(s.id)}
                      className="flex items-center gap-1 px-2.5 py-1.5 text-[10px] font-bold font-sans uppercase rounded-lg bg-primary hover:bg-primary-hover text-primary-foreground transition-all disabled:opacity-50"
                    >
                      <Zap className="w-3 h-3" /> {tr("connectionsUI.connect")}
                    </button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => reconnect(s.id)}
                      className="flex items-center gap-1 px-2.5 py-1.5 text-[10px] font-bold font-sans uppercase rounded-lg bg-surface-raised hover:bg-surface text-muted-foreground hover:text-foreground transition-all disabled:opacity-50"
                    >
                      <RefreshCw className="w-3 h-3" /> {tr("connectionsUI.reconnect")}
                    </button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => remove(s.id)}
                      aria-label={tr("connectionsUI.deleteServer")}
                      className="p-1.5 rounded-lg text-subtle-foreground hover:text-danger hover:bg-danger/10 transition-all disabled:opacity-50"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>

                {/* Server-level equipment (user ruling 2026-08-18): connect = usable
                    by Arslan; both dimensions confirm at SERVER granularity. */}
                <div className="flex items-center gap-4 flex-wrap">
                  <label className="flex items-center gap-2 text-[11px] text-muted-foreground font-sans select-none">
                    <input
                      type="checkbox"
                      data-testid={`mcp-host-${s.id}`}
                      checked={s.host_allowed ?? true}
                      disabled={busy}
                      onChange={(e) => toggleServerHost(s.id, e.target.checked)}
                      className="w-3.5 h-3.5 accent-primary"
                    />
                    {tr("connectionsUI.allowHost")}
                  </label>
                  <label className="flex items-center gap-2 text-[11px] text-muted-foreground font-sans select-none">
                    <input
                      type="checkbox"
                      data-testid={`mcp-expose-${s.id}`}
                      checked={exposed}
                      disabled={busy}
                      onChange={(e) => expose(s.id, e.target.checked)}
                      className="w-3.5 h-3.5 accent-primary"
                    />
                    {tr("connectionsUI.allowExperts")}
                  </label>
                </div>

                {/* Discovered tools */}
                {tools[s.id] && tools[s.id].length > 0 && (
                  <ul className="space-y-1.5 pt-1">
                    {tools[s.id].map((t) => (
                      <li
                        key={t.key}
                        className="flex items-center gap-2 flex-wrap bg-surface/50 border border-border/40 rounded-lg px-3 py-2"
                      >
                        <span className="text-[11px] font-mono text-foreground truncate max-w-[12rem]">
                          {t.name}
                        </span>
                        <span
                          className={`text-[9px] font-mono uppercase px-1.5 py-0.5 rounded ${
                            t.suggested_tier === "safe"
                              ? "bg-success/15 text-success"
                              : "bg-surface-raised text-subtle-foreground"
                          }`}
                          title={tr("connectionsUI.suggestTitle")}
                        >
                          {tr("connectionsUI.suggest", { tier: tr(`connectionsUI.${t.suggested_tier === "safe" ? "safe" : "orchestrator"}`) })}
                        </span>
                        <div className="flex items-center gap-2 ml-auto">
                          <select
                            value={t.tier}
                            disabled={busy}
                            onChange={(e) =>
                              wire(s.id, t, e.target.value, t.status === "wired")
                            }
                            aria-label={tr("connectionsUI.tierFor", { name: t.name })}
                            className="bg-surface border border-border-strong rounded-md px-2 py-1 text-[10px] text-foreground font-mono focus:outline-none focus:border-primary"
                          >
                            <option value="orchestrator">{tr("connectionsUI.orchestrator")}</option>
                            <option value="safe">{tr("connectionsUI.safe")}</option>
                          </select>
                          <label className="flex items-center gap-1 text-[10px] text-muted-foreground font-mono select-none">
                            <input
                              type="checkbox"
                              checked={t.status === "wired"}
                              disabled={busy}
                              onChange={(e) => wire(s.id, t, t.tier, e.target.checked)}
                              className="w-3.5 h-3.5 accent-primary"
                            />
                            {tr("connectionsUI.wire")}
                          </label>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
        )}
        </>
      )}

      {/* Add-server form */}
      <div className="space-y-3 pt-4 border-t border-border/50">
        <h4 className="text-[10.5px] font-mono font-medium text-muted-foreground uppercase tracking-wide">
          {tr("connectionsUI.register")}
        </h4>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <input
            className={inputCls}
            placeholder={tr("connectionsUI.label")} aria-label={tr("connectionsUI.label")}
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            autoComplete="off"
          />
          <select
            className={inputCls}
            value={transport}
            onChange={(e) => setTransport(e.target.value as "stdio" | "http")}
            aria-label={tr("connectionsUI.transport")}
          >
            <option value="stdio">{tr("connectionsUI.stdio")}</option>
            <option value="http">{tr("connectionsUI.http")}</option>
          </select>
        </div>
        {transport === "http" ? (
          <input
            className={inputCls}
            placeholder={tr("connectionsUI.url")} aria-label={tr("connectionsUI.url")}
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            autoComplete="off"
          />
        ) : (
          <>
            <input
              className={inputCls}
              placeholder={tr("connectionsUI.command")} aria-label={tr("connectionsUI.command")}
              value={command}
              onChange={(e) => setCommand(e.target.value)}
              autoComplete="off"
            />
            <input
              className={inputCls}
              placeholder={tr("connectionsUI.args")} aria-label={tr("connectionsUI.args")}
              value={argsText}
              onChange={(e) => setArgsText(e.target.value)}
              autoComplete="off"
            />
          </>
        )}
        <div className="space-y-2">
          <span className="block text-[10px] text-subtle-foreground font-mono uppercase tracking-wide">
            {tr(transport === "http" ? "connectionsUI.headers" : "connectionsUI.environment")}
          </span>
          {envRows.map((r, i) => (
            <div key={i} className="flex items-center gap-2">
              <input
                className={inputCls}
                placeholder={tr("connectionsUI.key")} aria-label={tr("connectionsUI.key")}
                value={r.k}
                onChange={(e) => setEnvRow(i, { k: e.target.value })}
                autoComplete="off"
              />
              <input
                className={inputCls}
                placeholder={tr("connectionsUI.value")} aria-label={tr("connectionsUI.value")}
                type="password"
                value={r.v}
                onChange={(e) => setEnvRow(i, { v: e.target.value })}
                autoComplete="off"
              />
              <button
                type="button"
                aria-label={tr("connectionsUI.removeRow")}
                onClick={() =>
                  setEnvRows((rows) => (rows.length > 1 ? rows.filter((_, idx) => idx !== i) : rows))
                }
                className="p-1.5 rounded-lg text-subtle-foreground hover:text-danger transition-all"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
          <button
            type="button"
            onClick={() => setEnvRows((rows) => [...rows, { k: "", v: "" }])}
            className="flex items-center gap-1 text-[10px] text-primary hover:text-primary-hover font-mono transition-colors"
          >
            <Plus className="w-3 h-3" /> {tr(transport === "http" ? "connectionsUI.addHeader" : "connectionsUI.addEnvironment")}
          </button>
        </div>
        <button
          type="button"
          disabled={busy || !canAdd}
          onClick={addServer}
          className="flex items-center gap-1.5 px-4 py-2 text-xs font-bold font-sans uppercase rounded-lg bg-primary hover:bg-primary-hover text-primary-foreground transition-all disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <Plus className="w-4 h-4" /> {tr("connectionsUI.addServer")}
        </button>
      </div>
    </div>
  );
}
