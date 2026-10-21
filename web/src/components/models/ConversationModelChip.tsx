import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown, Cpu } from "lucide-react";
import { fetchProviderModels, updateProviderConfig } from "../../api/client";
import { conversationModelApi } from "../../api/conversationModel";
import type { ContextParts, ModelInfo, ProviderConfig, ProviderOption } from "../../api/client.types";
import { useDismissable } from "../../hooks/useDismissable";
import { useArslanStore } from "../../stores/arslanStore";
import { providerStatus, type ProviderStatus } from "../../lib/providerStatus";
import ModelPicker, { type ModelChoice } from "./ModelPicker";

const DOT: Record<ProviderStatus, string> = {
  ok: "bg-success", failed: "bg-danger", untested: "bg-subtle-foreground/50", testing: "bg-subtle-foreground/50 animate-pulse",
};

/** One catalog fetch per provider per window, shared by every chip (for the ring's context size). */
const catalogs = new Map<number, Promise<ModelInfo[]>>();
function catalog(id: number): Promise<ModelInfo[]> {
  let p = catalogs.get(id);
  if (!p) { p = Promise.resolve().then(() => fetchProviderModels(id)).then((r) => r.models).catch(() => []); catalogs.set(id, p); }
  return p;
}
export function _resetChipCatalogs() { catalogs.clear(); }

/** The chip names the provider short — "OpenRouter", not "OpenRouter (Claude, Gemini and more)" —
 *  so the model stays readable (0.1.59). The picker keeps the full label. */
export function shortProvider(label: string): string {
  return label.replace(/\s*[(\uFF08][^()\uFF08\uFF09]*[)\uFF09]\s*$/, "").trim() || label;
}

/** 0.1.63 K4b: the ring's breakdown, in this order, with user-facing labels. */
const RING_PARTS = ["system", "tools", "context", "history", "turn"] as const;
const PART_LABEL: Record<(typeof RING_PARTS)[number], string> = {
  system: "models.partSystem", tools: "models.partTools", context: "models.partContext",
  history: "models.partHistory", turn: "models.partTurn",
};

/** The server's estimated parts scaled to the provider's total (⓪Plan Q8): each row is its share of the
 *  estimate times last_input, and the rounding remainder goes to the biggest row, so the rows add up to
 *  the total shown. Empty when there is nothing to split. */
export function ringRows(parts: ContextParts | null | undefined, total: number | null | undefined) {
  if (!parts || !total) return [];
  const sum = RING_PARTS.reduce((acc, key) => acc + Math.max(0, parts[key] ?? 0), 0);
  if (sum <= 0) return [];
  const rows = RING_PARTS.map((key) => {
    const share = Math.max(0, parts[key] ?? 0) / sum;
    return { key, tokens: Math.round(share * total), pct: Math.round(share * 100) };
  });
  const drift = total - rows.reduce((acc, row) => acc + row.tokens, 0);
  if (drift) rows.reduce((big, row) => (row.tokens > big.tokens ? row : big)).tokens += drift;
  return rows;
}

function Ring({ pct }: { pct: number }) {
  const r = 7, c = 2 * Math.PI * r;
  return <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden>
    <circle cx="9" cy="9" r={r} fill="none" stroke="var(--border)" strokeWidth="2.5" />
    <circle cx="9" cy="9" r={r} fill="none" stroke={pct > 80 ? "var(--warning)" : "var(--muted-foreground)"} strokeWidth="2.5"
      strokeDasharray={`${(c * Math.min(100, pct)) / 100} ${c}`} transform="rotate(-90 9 9)" />
  </svg>;
}

/**
 * The model under the composer (0.1.58 §6, decision 6): which model THIS conversation runs on —
 * any model of any provider, OpenRouter's whole catalog included — chosen from the next
 * message; "设为默认" makes it the default for new conversations. Beside it, how full the
 * context is (the last call's input against the model's context window).
 */
export default function ConversationModelChip({ conversationId, configs, llmProviders, onSetDefault, onManage }: {
  conversationId: string; configs: ProviderConfig[]; llmProviders: ProviderOption[];
  /** Make this config primary (App refreshes the list). */
  onSetDefault: (configId: number) => Promise<void> | void;
  onManage?: () => void;
}) {
  const { t, i18n } = useTranslation();
  const [choice, setChoice] = useState<ModelChoice | null>(null);
  const [open, setOpen] = useState(false);
  const [ringOpen, setRingOpen] = useState(false);
  const ringFloat = useDismissable<HTMLButtonElement, HTMLDivElement>(ringOpen, () => setRingOpen(false));
  const [window_, setWindow] = useState<number | null>(null);
  const { anchorRef, floatingRef } = useDismissable<HTMLButtonElement, HTMLDivElement>(open, () => setOpen(false));
  const lastInput = useArslanStore((s) => {
    for (let i = s.items.length - 1; i >= 0; i--) { const u = s.items[i].usage; if (u?.last_input) return u.last_input; }
    return null;
  });
  // K4b: the same reply's parts (the stored object, so the selector stays stable).
  const parts = useArslanStore((s) => {
    for (let i = s.items.length - 1; i >= 0; i--) { const u = s.items[i].usage; if (u?.last_input) return u.context_parts ?? null; }
    return null;
  });

  useEffect(() => {
    let alive = true;
    setChoice(null);
    // Deferred into the promise so an unavailable client (offline, or a test's partial mock) is a rejection.
    Promise.resolve().then(() => conversationModelApi.get(conversationId))
      .then((r) => { if (alive && r.choice) setChoice({ configId: r.choice.config_id, model: r.choice.model }); })
      .catch(() => {});
    return () => { alive = false; };
  }, [conversationId]);

  const primary = configs.find((c) => c.is_primary) ?? configs[0] ?? null;
  const current: ModelChoice | null = choice && configs.some((c) => c.id === choice.configId) ? choice
    : primary ? { configId: primary.id, model: primary.model } : null;
  const label = (c: ProviderConfig) => llmProviders.find((p) => p.key === c.provider)?.label ?? c.label ?? c.provider;

  useEffect(() => {
    if (!current) return;
    let alive = true;
    void catalog(current.configId).then((ms) => { if (alive) setWindow(ms.find((m) => m.id === current.model)?.context_window ?? null); });
    return () => { alive = false; };
  }, [current?.configId, current?.model]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!current) {
    return <button type="button" onClick={onManage} data-testid="model-chip-empty"
      className="flex items-center gap-1.5 rounded-full border border-border px-2.5 py-1 font-mono text-[10px] text-subtle-foreground">
      <Cpu className="h-3 w-3" />{t("settings.modelSwitcherNone")}</button>;
  }
  const cfg = configs.find((c) => c.id === current.configId)!;
  const pct = lastInput && window_ ? Math.round((lastInput / window_) * 100) : null;
  const rows = ringRows(parts, lastInput);
  const fmt = (n: number) => n.toLocaleString(i18n.resolvedLanguage || undefined);
  const health = providerStatus(cfg);

  async function pick(next: ModelChoice) {
    setOpen(false);
    if (primary && next.configId === primary.id && next.model === primary.model) {
      await conversationModelApi.clear(conversationId).catch(() => {});
      setChoice(null);
    } else {
      await conversationModelApi.set(conversationId, next.configId, next.model);
      setChoice(next);
    }
  }
  async function makeDefault() {
    if (!current) return;
    const target = configs.find((c) => c.id === current.configId);
    if (target && target.model !== current.model) await updateProviderConfig(current.configId, { model: current.model });
    await onSetDefault(current.configId);
    await conversationModelApi.clear(conversationId).catch(() => {});
    setChoice(null);
    setOpen(false);
  }
  const isDefault = !choice || (primary && choice.configId === primary.id && choice.model === primary.model);

  return (
    <span className="relative flex items-center gap-1.5">
      <button ref={anchorRef} type="button" onClick={() => setOpen((v) => !v)} aria-haspopup="dialog" aria-expanded={open}
        data-testid="model-chip"
        title={health.status === "failed" && health.reason ? health.reason : `${label(cfg)} · ${current.model} — ${t("models.pick")}`}
        className="flex max-w-[260px] items-center gap-1.5 rounded-full border border-border bg-background/40 px-2.5 py-1 font-mono text-[10px] text-muted-foreground hover:border-primary/40">
        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${DOT[health.status]}`} data-testid="model-chip-dot" data-status={health.status} />
        <span className="truncate">{shortProvider(label(cfg))} · {current.model}</span><ChevronDown className="h-2.5 w-2.5 shrink-0 opacity-60" />
      </button>
      {pct != null && rows.length === 0 && <span className="flex items-center gap-1 text-[10px] text-subtle-foreground" title={t("models.context", { pct })} data-testid="context-ring">
        <Ring pct={pct} />{pct}%</span>}
      {pct != null && rows.length > 0 && <span className="relative flex items-center">
        <button ref={ringFloat.anchorRef} type="button" onClick={() => setRingOpen((v) => !v)} aria-haspopup="dialog"
          aria-expanded={ringOpen} title={t("models.context", { pct })} data-testid="context-ring"
          className="flex items-center gap-1 rounded-full text-[10px] text-subtle-foreground hover:text-foreground">
          <Ring pct={pct} />{pct}%</button>
        {ringOpen && <div ref={ringFloat.floatingRef} role="dialog" data-testid="context-breakdown"
          className="absolute bottom-full left-0 z-50 mb-2 w-64 rounded-xl border border-border bg-background p-3 text-[11.5px] shadow-lg">
          <div className="font-medium text-foreground">{t("models.contextParts")}</div>
          <div className="mb-2 text-muted-foreground">{t("models.contextTotal", { tokens: fmt(lastInput!) })}</div>
          <ul className="space-y-1">
            {rows.map((row) => <li key={row.key} data-testid={`context-part-${row.key}`} className="flex items-center gap-2">
              <span className="flex-1 text-foreground">{t(PART_LABEL[row.key])}</span>
              <span className="font-mono text-muted-foreground">{t("models.about", { value: fmt(row.tokens) })}</span>
              <span className="w-9 text-right font-mono text-subtle-foreground">{row.pct}%</span>
            </li>)}
          </ul>
          <div className="mt-2 text-[10.5px] text-subtle-foreground">{t("models.contextEstimated")}</div>
        </div>}
      </span>}
      {open && <div ref={floatingRef} role="dialog" className="absolute bottom-full left-0 z-50 mb-2 rounded-xl border border-border bg-background p-2 shadow-lg">
        <ModelPicker configs={configs} current={current} need="tools" onPick={(c) => void pick(c)} label={label} />
        <div className="mt-1 flex items-center gap-2 border-t border-border px-2 pt-2 text-[11.5px] text-muted-foreground">
          <span className="flex-1">{t("models.thisConvOnly")}</span>
          {!isDefault && <button type="button" onClick={() => void pick({ configId: primary!.id, model: primary!.model })}
            className="hover:text-foreground" data-testid="model-use-default">{t("models.useDefault")}</button>}
          <button type="button" onClick={() => void makeDefault()} data-testid="model-set-default"
            className="rounded-md bg-fill px-2 py-1 font-medium text-foreground hover:bg-fill-strong">{t("models.setDefault")}</button>
        </div>
      </div>}
    </span>
  );
}
