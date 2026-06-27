import { useEffect, useState } from "react";
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
  setMcpToolHost,
  wireMcpTool,
} from "../api/mcp";

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
  const [servers, setServers] = useState<McpServer[]>([]);
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

  async function toggleHost(id: number, tool: McpTool) {
    setBusy(true);
    setError(null);
    try {
      await setMcpToolHost(tool.key, !tool.host_enabled);
      await refreshTools(id);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
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

  return (
    <div className="bg-surface/60 border border-border rounded-2xl p-6 space-y-6">
      <div className="flex items-center gap-2 pb-4 border-b border-border/50 select-none">
        <Plug className="w-4.5 h-4.5 text-primary" />
        <h3 className="text-xs font-semibold font-mono uppercase tracking-widest text-foreground leading-none">
          MCP Servers
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
          No MCP servers registered. Add one below to discover and wire external tools.
        </p>
      ) : (
        <ul className="space-y-4">
          {servers.map((s) => {
            const exposed = false; // expose state lives in the toolset; toggle reflects intent
            return (
              <li
                key={s.id}
                className="bg-surface/40 border border-border/60 rounded-xl p-4 space-y-3"
              >
                <div className="flex items-center justify-between gap-3">
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
                        {s.status}
                      </span>
                    </div>
                    <p className="text-[10px] text-subtle-foreground font-mono mt-0.5 truncate">
                      {s.transport === "http"
                        ? `http · ${s.url ?? ""}`
                        : `${s.command} ${s.args.join(" ")}`}
                    </p>
                    {s.last_error && (
                      <p className="text-[10px] text-danger font-mono mt-1 break-words">
                        {s.last_error}
                      </p>
                    )}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => connect(s.id)}
                      className="flex items-center gap-1 px-2.5 py-1.5 text-[10px] font-bold font-sans uppercase rounded-lg bg-primary hover:bg-primary-hover text-primary-foreground transition-all disabled:opacity-50"
                    >
                      <Zap className="w-3 h-3" /> Connect
                    </button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => reconnect(s.id)}
                      className="flex items-center gap-1 px-2.5 py-1.5 text-[10px] font-bold font-sans uppercase rounded-lg bg-surface-raised hover:bg-surface text-muted-foreground hover:text-foreground transition-all disabled:opacity-50"
                    >
                      <RefreshCw className="w-3 h-3" /> Reconnect
                    </button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => remove(s.id)}
                      aria-label="delete server"
                      className="p-1.5 rounded-lg text-subtle-foreground hover:text-danger hover:bg-danger/10 transition-all disabled:opacity-50"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>

                {/* Allow-for-spawns (expose) toggle */}
                <label className="flex items-center gap-2 text-[11px] text-muted-foreground font-sans select-none">
                  <input
                    type="checkbox"
                    defaultChecked={exposed}
                    disabled={busy}
                    onChange={(e) => expose(s.id, e.target.checked)}
                    className="w-3.5 h-3.5 accent-primary"
                  />
                  Allow for spawns (expose toolset)
                </label>

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
                          title="Suggested tier (heuristic hint)"
                        >
                          suggest: {t.suggested_tier}
                        </span>
                        <div className="flex items-center gap-2 ml-auto">
                          <select
                            value={t.tier}
                            disabled={busy}
                            onChange={(e) =>
                              wire(s.id, t, e.target.value, t.status === "wired")
                            }
                            aria-label={`tier for ${t.name}`}
                            className="bg-surface border border-border-strong rounded-md px-2 py-1 text-[10px] text-foreground font-mono focus:outline-none focus:border-primary"
                          >
                            <option value="orchestrator">orchestrator</option>
                            <option value="safe">safe</option>
                          </select>
                          <label className="flex items-center gap-1 text-[10px] text-muted-foreground font-mono select-none">
                            <input
                              type="checkbox"
                              checked={t.status === "wired"}
                              disabled={busy}
                              onChange={(e) => wire(s.id, t, t.tier, e.target.checked)}
                              className="w-3.5 h-3.5 accent-primary"
                            />
                            wire
                          </label>
                          <label className="flex items-center gap-1 text-[10px] text-muted-foreground font-mono select-none">
                            <input
                              type="checkbox"
                              checked={t.host_enabled}
                              disabled={busy}
                              onChange={() => toggleHost(s.id, t)}
                              className="w-3.5 h-3.5 accent-primary"
                            />
                            allow Arslan
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

      {/* Add-server form */}
      <div className="space-y-3 pt-4 border-t border-border/50">
        <h4 className="text-[10.5px] font-mono font-medium text-muted-foreground uppercase tracking-wide">
          Register an MCP server
        </h4>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <input
            className={inputCls}
            placeholder="Label (e.g. filesystem)"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            autoComplete="off"
          />
          <select
            className={inputCls}
            value={transport}
            onChange={(e) => setTransport(e.target.value as "stdio" | "http")}
            aria-label="transport"
          >
            <option value="stdio">stdio (local process)</option>
            <option value="http">http (streamable)</option>
          </select>
        </div>
        {transport === "http" ? (
          <input
            className={inputCls}
            placeholder="URL (e.g. https://api.example.com/mcp)"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            autoComplete="off"
          />
        ) : (
          <>
            <input
              className={inputCls}
              placeholder="Command (e.g. npx)"
              value={command}
              onChange={(e) => setCommand(e.target.value)}
              autoComplete="off"
            />
            <input
              className={inputCls}
              placeholder="Args (space-separated, e.g. -y @modelcontextprotocol/server-everything)"
              value={argsText}
              onChange={(e) => setArgsText(e.target.value)}
              autoComplete="off"
            />
          </>
        )}
        <div className="space-y-2">
          <span className="block text-[10px] text-subtle-foreground font-mono uppercase tracking-wide">
            {transport === "http" ? "Headers" : "Environment variables"}
          </span>
          {envRows.map((r, i) => (
            <div key={i} className="flex items-center gap-2">
              <input
                className={inputCls}
                placeholder="KEY"
                value={r.k}
                onChange={(e) => setEnvRow(i, { k: e.target.value })}
                autoComplete="off"
              />
              <input
                className={inputCls}
                placeholder="value"
                type="password"
                value={r.v}
                onChange={(e) => setEnvRow(i, { v: e.target.value })}
                autoComplete="off"
              />
              <button
                type="button"
                aria-label="remove env row"
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
            <Plus className="w-3 h-3" /> {transport === "http" ? "Add header" : "Add env var"}
          </button>
        </div>
        <button
          type="button"
          disabled={busy || !canAdd}
          onClick={addServer}
          className="flex items-center gap-1.5 px-4 py-2 text-xs font-bold font-sans uppercase rounded-lg bg-primary hover:bg-primary-hover text-primary-foreground transition-all disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <Plus className="w-4 h-4" /> Add server
        </button>
      </div>
    </div>
  );
}
