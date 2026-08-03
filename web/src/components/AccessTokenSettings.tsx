/**
 * AccessTokenSettings — the "Access token" section of the Settings screen.
 *
 * On mount it asks the backend (GET /settings/access-token) whether a bearer
 * token is required and, when the caller is localhost, what the bootstrapped
 * token is. Three states:
 *   - token NOT required (dev + localhost) → a subtle, non-nagging note.
 *   - token required + we have it (localhost bootstrap, or already stored) →
 *     show it (masked, copyable) + a Reset button that rotates it.
 *   - token required + we don't have it (remote, unauthenticated) → a field to
 *     paste the token, which is written into the auth store for API/WS auth.
 *
 * Degrades gracefully: any failed call just leaves the section quiet.
 */

import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { KeyRound, ShieldCheck, Copy, Check, RefreshCw, Eye, EyeOff } from "lucide-react";
import { api } from "../api/client";
import { useAuthStore } from "../stores/authStore";
import type { BackendStatus } from "../hooks/useBackendStatus";
import McpTokenControl from './settings/McpTokenControl';

interface AccessTokenSettingsProps {
  /** Inbound MCP server — moved here from Advanced. It belongs beside the
   *  token that guards it: the toggle opens a door and the token is its key,
   *  and having them on different screens meant you could turn one on without
   *  ever meeting the other. */
  mcpServerEnabled?: boolean;
  onMcpServerChange?: (v: boolean) => void;
  backendStatus: BackendStatus;
}

export default function AccessTokenSettings({
  backendStatus, mcpServerEnabled = false, onMcpServerChange,
}: AccessTokenSettingsProps) {
  const { t } = useTranslation();
  const storedToken = useAuthStore((s) => s.token);
  const setToken = useAuthStore((s) => s.setToken);

  const [loaded, setLoaded] = useState(false);
  const [required, setRequired] = useState(false);
  // The token the server handed back to a localhost caller (null otherwise).
  const [serverToken, setServerToken] = useState<string | null>(null);
  const [pasteValue, setPasteValue] = useState("");
  const [reveal, setReveal] = useState(false);
  const [copied, setCopied] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [resetError, setResetError] = useState(false);

  useEffect(() => {
    let active = true;
    api
      .getAccessToken()
      .then((info) => {
        if (!active) return;
        setRequired(info.token_required);
        setServerToken(info.token);
        // localhost bootstrap: hydrate the store so auth "just works" if empty.
        if (info.token && !useAuthStore.getState().token) setToken(info.token);
        setLoaded(true);
      })
      .catch(() => {
        if (active) setLoaded(true);
      });
    return () => {
      active = false;
    };
  }, [setToken]);

  // Prefer the localhost-returned token; fall back to whatever is stored.
  const shownToken = serverToken ?? storedToken;
  const offline = backendStatus === "offline";

  const handleCopy = async () => {
    if (!shownToken) return;
    try {
      await navigator.clipboard.writeText(shownToken);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked — no-op */
    }
  };

  const handleReset = async () => {
    setResetting(true);
    setResetError(false);
    try {
      const res = await api.resetAccessToken();
      setServerToken(res.token);
      setToken(res.token);
    } catch {
      // Reset is localhost-gated; a remote caller (or offline) gets an error.
      setResetError(true);
    } finally {
      setResetting(false);
    }
  };

  const handleSavePaste = () => {
    const v = pasteValue.trim();
    if (!v) return;
    setToken(v);
    setPasteValue("");
  };

  const cardHeader = (
    <div className="flex items-center gap-2 pb-4 border-b border-border/50 select-none">
      <KeyRound className="w-4.5 h-4.5 text-primary" />
      <h3 className="text-xs font-semibold font-mono uppercase tracking-widest text-foreground leading-none">
        {t("settings.accessToken.section")}
      </h3>
    </div>
  );

  return (
    <div className="bg-surface/60 border border-border rounded-2xl p-6 space-y-5" data-testid="access-token-section">
      {cardHeader}

      {!loaded ? (
        <p className="text-[11px] text-subtle-foreground font-mono">{t("settings.accessToken.checking")}</p>
      ) : !required ? (
        // Dev + localhost: no token needed. A quiet reassurance, not a nag.
        <div className="flex items-center gap-2.5 text-[11px] font-mono text-muted-foreground">
          <ShieldCheck className="w-4 h-4 text-success shrink-0" />
          <span>{t("settings.accessToken.notRequired")}</span>
        </div>
      ) : shownToken ? (
        // We have a token to show (localhost bootstrap or already stored).
        <div className="space-y-3">
          <label className="block text-[10.5px] font-mono font-medium text-muted-foreground uppercase tracking-wide">
            {t("settings.accessToken.yourToken")}
          </label>
          <div className="relative">
            <input
              data-testid="access-token-value"
              type={reveal ? "text" : "password"}
              readOnly
              value={shownToken}
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
                data-testid="access-token-copy"
                onClick={handleCopy}
                className="flex items-center gap-1 px-2 py-1 text-[10px] font-mono font-bold text-primary hover:bg-primary/10 rounded-md transition-colors"
              >
                {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
                {copied ? t("settings.accessToken.copied") : t("settings.accessToken.copy")}
              </button>
            </div>
          </div>
          <p className="text-[10px] text-subtle-foreground font-sans leading-relaxed">
            {t("settings.accessToken.shownHint")}
          </p>
          <div className="flex items-center gap-3">
            <button
              type="button"
              data-testid="access-token-reset"
              onClick={handleReset}
              disabled={resetting || offline}
              className="flex items-center gap-1.5 px-3 py-2 text-[11px] font-mono font-bold text-muted-foreground hover:text-primary border border-border hover:border-primary/50 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${resetting ? "animate-spin" : ""}`} />
              {resetting ? t("settings.accessToken.resetting") : t("settings.accessToken.reset")}
            </button>
            {resetError && (
              <span className="text-[10px] font-mono text-danger">{t("settings.accessToken.resetError")}</span>
            )}
          </div>
        </div>
      ) : (
        // Required but we have nothing — prompt the operator to paste it.
        <div className="space-y-3">
          <label
            htmlFor="access-token-paste"
            className="block text-[10.5px] font-mono font-medium text-muted-foreground uppercase tracking-wide"
          >
            {t("settings.accessToken.pasteLabel")}
          </label>
          <div className="flex items-center gap-2">
            <input
              id="access-token-paste"
              data-testid="access-token-paste"
              type="password"
              value={pasteValue}
              onChange={(e) => setPasteValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  handleSavePaste();
                }
              }}
              placeholder={t("settings.accessToken.placeholder")}
              className="flex-1 bg-surface border border-border-strong focus:border-primary focus:ring-1 focus:ring-ring rounded-xl px-4 py-3 text-xs text-foreground placeholder-subtle-foreground focus:outline-none transition-all font-mono"
            />
            <button
              type="button"
              data-testid="access-token-save"
              onClick={handleSavePaste}
              disabled={!pasteValue.trim()}
              className="shrink-0 px-4 py-3 bg-primary hover:bg-primary-hover text-primary-foreground text-xs font-bold font-sans uppercase rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-primary/10"
            >
              {t("settings.accessToken.save")}
            </button>
          </div>
          <p className="text-[10px] text-subtle-foreground font-sans leading-relaxed">
            {t("settings.accessToken.requiredHint")}
          </p>
        </div>
      )}

      {/* ── Inbound MCP server (relocated from Advanced) ─────────────────── */}
      <div className="mt-6 pt-6 border-t border-border/40 flex items-center justify-between gap-4">
        <div>
          <h4 className="text-xs font-bold text-foreground font-sans">{t('settings.labelMcpServer')}</h4>
          <p className="text-[11px] text-muted-foreground font-sans mt-0.5 max-w-xl">
            {t('settings.mcpServerDesc')}
          </p>
        </div>
        <input
          id="settings-mcp-server-toggle"
          type="checkbox"
          checked={mcpServerEnabled}
          onChange={(e) => onMcpServerChange?.(e.target.checked)}
          className="w-4 h-4 shrink-0 text-primary bg-background border-border rounded focus:ring-0 select-none cursor-pointer"
        />
      </div>
      {/* Only when the inbound server is ON. The token exists to guard THAT
          endpoint, so offering to mint one while the endpoint is off asks the
          user to make a decision about something that is not running. */}
      {mcpServerEnabled && <div className="mt-4"><McpTokenControl /></div>}
    </div>
  );
}
