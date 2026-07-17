/**
 * McpTokenControl — generate + show-once reveal/copy for the dedicated inbound
 * MCP-server token (Task 10, modeled on AccessTokenSettings).
 *
 * Self-contained and self-fetching: it only calls api.generateMcpToken() on an
 * explicit click. The freshly minted token is kept in LOCAL component state
 * only — it is NOT written to the auth store, since it is not the app's own
 * bearer token (that's AccessTokenSettings' concern). A page refresh forgets
 * it, matching the backend's show-once semantics (GET /settings/mcp-token
 * never returns the plaintext).
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { RefreshCw, Eye, EyeOff, Copy, Check } from "lucide-react";
import { api } from "../../api/client";

export default function McpTokenControl() {
  const { t } = useTranslation();
  const [token, setToken] = useState<string | null>(null);
  const [reveal, setReveal] = useState(false);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);

  const generate = async () => {
    setBusy(true);
    setError(false);
    try {
      const res = await api.generateMcpToken();
      setToken(res.token);
      setReveal(true);
    } catch {
      setError(true); // localhost-gated: a remote caller / offline gets an error
    } finally {
      setBusy(false);
    }
  };

  const copy = async () => {
    if (!token) return;
    try {
      await navigator.clipboard.writeText(token);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked — no-op */
    }
  };

  return (
    <div className="space-y-2">
      <button
        type="button"
        data-testid="mcp-token-generate"
        onClick={generate}
        disabled={busy}
        className="flex items-center gap-1.5 px-3 py-2 text-[11px] font-mono font-bold text-muted-foreground hover:text-primary border border-border hover:border-primary/50 rounded-lg transition-colors disabled:opacity-50"
      >
        <RefreshCw className={`w-3.5 h-3.5 ${busy ? "animate-spin" : ""}`} />
        {busy ? t("settings.mcpToken.generating") : t("settings.mcpToken.generate")}
      </button>
      {token && (
        <div className="relative">
          <input
            data-testid="mcp-token-value"
            type={reveal ? "text" : "password"}
            readOnly
            value={token}
            className="w-full bg-surface border border-border-strong rounded-xl px-4 py-3 text-xs text-foreground focus:outline-none pr-20 font-mono select-all"
          />
          <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
            <button
              type="button"
              onClick={() => setReveal((r) => !r)}
              className="p-1.5 text-subtle-foreground hover:text-foreground transition-colors"
              title={reveal ? t("settings.accessToken.hide") : t("settings.accessToken.reveal")}
            >
              {reveal ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
            <button
              type="button"
              data-testid="mcp-token-copy"
              onClick={copy}
              className="flex items-center gap-1 px-2 py-1 text-[10px] font-mono font-bold text-primary hover:bg-primary/10 rounded-md transition-colors"
            >
              {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
            </button>
          </div>
        </div>
      )}
      {error && <span className="text-[11px] text-danger">{t("settings.mcpToken.generateError")}</span>}
    </div>
  );
}
