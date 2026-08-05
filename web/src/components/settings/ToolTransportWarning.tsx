/**
 * The notice shown in Settings when the selected provider cannot call tools.
 *
 * This exists because the failure it describes has no symptom. Pick Anthropic
 * or Gemini, equip a toolset, connect an MCP server, and everything reads as
 * installed — then the agent simply never uses any of it. There is no error, no
 * log the user sees, nothing to search for. The project's own rule is that a
 * degradation must be visible; this is the visible part, and it ships ahead of
 * the fix (G1) rather than waiting for it.
 *
 * Text lives in the locale files, not in the backend's REASONS strings, so it
 * exists in all six languages — the backend's display-text whitelist is
 * registry.py alone.
 */
import { useTranslation } from "react-i18next";

import { toolTransportState } from "../../lib/toolTransport";

export default function ToolTransportWarning({ provider }: { provider: string | null | undefined }) {
  const { t } = useTranslation();
  const state = toolTransportState(provider);

  if (state === "supported") return null;

  const unsupported = state === "unsupported";

  return (
    <div
      // role="status", not "alert": this describes a standing property of the
      // selected provider, not an event. An alert would interrupt a screen
      // reader mid-sentence every time the select changes.
      role="status"
      data-testid="tool-transport-warning"
      data-state={state}
      className={
        "sm:col-span-2 min-w-0 rounded-lg border px-3 py-2.5 text-xs leading-relaxed " +
        // The house warning tokens (--color-warning), not raw Tailwind amber:
        // they are the pair the theme system keeps legible in both light and
        // dark, and `bg-surface-muted` — my first guess — is not a token at all
        // and would have rendered as no background whatsoever.
        (unsupported
          ? "border-warning/40 bg-warning/10 text-warning"
          : "border-border bg-surface-raised text-muted-foreground")
      }
    >
      {unsupported && (
        <div className="font-medium mb-0.5 text-warning">
          {t("settings.tool_transport_title")}
        </div>
      )}
      <div>
        {t(unsupported ? "settings.tool_transport_unsupported" : "settings.tool_transport_unverified")}
      </div>
    </div>
  );
}
