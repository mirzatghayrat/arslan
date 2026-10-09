import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, ChevronDown, ChevronRight, Search, Star } from "lucide-react";
import { fetchProviderModels } from "../../api/client";
import type { ModelInfo, ProviderConfig } from "../../api/client.types";
import { providerStatus } from "../../lib/providerStatus";

/** What a role needs from a model (the conversation needs tools; 看图 needs image input). */
export type ModelNeed = "tools" | "vision" | null;
export interface ModelChoice { configId: number; model: string }

const FAV_KEY = "arslan.model.favourites.v1";
const SHOWN = 60;          // rows per provider before searching narrows them

export function loadFavourites(): string[] {
  try { const v = JSON.parse(localStorage.getItem(FAV_KEY) ?? "[]"); return Array.isArray(v) ? v.filter((x) => typeof x === "string") : []; }
  catch { return []; }
}
const favKey = (c: ModelChoice) => `${c.configId}::${c.model}`;

export function fmtContext(n: number | null | undefined): string {
  if (!n) return "";
  return n >= 1_000_000 ? `${+(n / 1_000_000).toFixed(1)}M` : `${Math.round(n / 1000)}K`;
}
export function fmtPrice(m: Pick<ModelInfo, "price_in" | "price_out">): string {
  if (m.price_in == null || m.price_out == null) return "";
  const f = (n: number) => (n === 0 ? "$0" : n < 0.1 ? `$${+n.toFixed(3)}` : `$${+n.toFixed(2)}`);
  return `${f(m.price_in)} / ${f(m.price_out)}`;
}

/** Why a role cannot use this model, or null. Unknown capabilities (a provider that does not say) never block. */
export function unusableWhy(m: ModelInfo | undefined, need: ModelNeed, t: (k: string) => string): string | null {
  if (!m || !need || m.source !== "api") return null;
  if (need === "tools" && !m.capabilities.includes("tools")) return t("models.noTools");
  if (need === "vision" && !m.capabilities.includes("vision")) return t("models.noVision");
  return null;
}

function matches(q: string, ...fields: (string | null | undefined)[]): boolean {
  const hay = fields.filter(Boolean).join(" ").toLowerCase();
  return q.toLowerCase().split(/\s+/).filter(Boolean).every((w) => hay.includes(w));
}

/**
 * Any model of any provider (0.1.58 §6): a search box; ★ favourites on top; then each provider
 * with its own model first and "全部 N 个" opening its live catalog (OpenRouter's hundreds
 * included) — each row with context length, price per million tokens and what it can do. A row
 * the role cannot use is disabled with the reason.
 */
export default function ModelPicker({ configs, current, need, onPick, label }: {
  configs: ProviderConfig[]; current: ModelChoice | null; need: ModelNeed;
  onPick: (choice: ModelChoice) => void; label: (c: ProviderConfig) => string;
}) {
  const { t } = useTranslation();
  const [q, setQ] = useState("");
  const [favs, setFavs] = useState<string[]>(loadFavourites);
  const [open, setOpen] = useState<Record<number, boolean>>({});
  const [catalogs, setCatalogs] = useState<Record<number, ModelInfo[] | "loading" | "failed">>({});

  const load = (id: number) => {
    if (catalogs[id]) return;
    setCatalogs((c) => ({ ...c, [id]: "loading" }));
    fetchProviderModels(id).then((r) => setCatalogs((c) => ({ ...c, [id]: r.models })))
      .catch(() => setCatalogs((c) => ({ ...c, [id]: "failed" })));
  };
  // A search looks through every provider's catalog.
  useEffect(() => { if (q.trim()) configs.forEach((c) => load(c.id)); }, [q]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggleFav = (c: ModelChoice) => setFavs((f) => {
    const next = f.includes(favKey(c)) ? f.filter((x) => x !== favKey(c)) : [...f, favKey(c)];
    try { localStorage.setItem(FAV_KEY, JSON.stringify(next)); } catch { /* storage off */ }
    return next;
  });
  const info = (configId: number, model: string): ModelInfo | undefined => {
    const cat = catalogs[configId];
    return Array.isArray(cat) ? cat.find((m) => m.id === model) : undefined;
  };

  // A render helper, not a component: rows must not remount (and lose focus) on every keystroke.
  const row = (choice: ModelChoice, m: ModelInfo | undefined, provider: string, key: string) => {
    const why = unusableWhy(m, need, t);
    const selected = current?.configId === choice.configId && current?.model === choice.model;
    const fav = favs.includes(favKey(choice));
    const free = m?.price_in === 0 && m?.price_out === 0;
    return (
      <div key={key} className={`flex items-center gap-2 rounded-lg px-2 py-1.5 ${selected ? "bg-primary/10" : why ? "opacity-50" : "hover:bg-foreground/[0.04]"}`}
        data-testid={`model-row-${choice.configId}-${choice.model}`}>
        <button type="button" disabled={!!why} onClick={() => onPick(choice)} aria-pressed={selected}
          className="flex min-w-0 flex-1 items-center gap-2 text-left disabled:cursor-not-allowed">
          <span className="min-w-0 flex-1">
            <span className="flex items-center gap-1.5 text-[12.5px] font-medium">
              <span className="truncate">{m?.display_name || choice.model}</span>{selected && <Check size={12} className="shrink-0 text-primary" />}</span>
            <span className="block truncate font-mono text-[10.5px] text-subtle-foreground">{provider} · {choice.model}</span>
            {why && <span className="block text-[11px] text-danger" data-testid="model-why">{why}</span>}
          </span>
          <span className="flex shrink-0 flex-col items-end gap-0.5">
            <span className="font-mono text-[10.5px] text-muted-foreground">
              {[fmtContext(m?.context_window), m ? fmtPrice(m) : ""].filter(Boolean).join(" · ")}</span>
            <span className="flex gap-1">
              {m?.capabilities.includes("tools") && <span className="rounded bg-fill px-1 text-[10px] text-muted-foreground">{t("models.tools")}</span>}
              {m?.capabilities.includes("vision") && <span className="rounded bg-fill px-1 text-[10px] text-muted-foreground">{t("models.vision")}</span>}
              {free && <span className="rounded bg-success/10 px-1 text-[10px] text-success">{t("models.free")}</span>}
            </span>
          </span>
        </button>
        <button type="button" onClick={() => toggleFav(choice)} aria-label={t(fav ? "models.unstar" : "models.star")} aria-pressed={fav}
          className={`shrink-0 ${fav ? "text-warning" : "text-subtle-foreground hover:text-foreground"}`}><Star size={13} fill={fav ? "currentColor" : "none"} /></button>
      </div>
    );
  };

  // A provider whose last real test failed says why, on its own line (its models will fail too).
  const failure = (cfg: ProviderConfig) => {
    const h = providerStatus(cfg);
    return h.status === "failed" ? <p className="line-clamp-2 px-2 pb-0.5 text-[11px] text-danger" title={h.reason ?? undefined}
      data-testid={`model-provider-failed-${cfg.id}`}>{h.reason || t("models.providerFailed")}</p> : null;
  };

  const favRows = useMemo(() => favs.map((k) => {
    const [id, ...rest] = k.split("::");
    return { configId: Number(id), model: rest.join("::") };
  }).filter((c) => configs.some((x) => x.id === c.configId) && (!q.trim() || matches(q, c.model))), [favs, configs, q]);

  return (
    <div className="flex max-h-[60vh] w-[440px] max-w-[90vw] flex-col gap-1" data-testid="model-picker">
      <label className="flex items-center gap-2 rounded-lg bg-fill px-2.5 py-1.5 text-[12.5px]">
        <Search size={13} className="text-subtle-foreground" />
        <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("models.search")}
          className="min-w-0 flex-1 bg-transparent outline-none" data-testid="model-search" />
      </label>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {favRows.length > 0 && <>
          <div className="px-2 pb-0.5 pt-2 text-[10.5px] font-semibold uppercase tracking-wide text-subtle-foreground">★ {t("models.favorites")}</div>
          {favRows.map((c) => row(c, info(c.configId, c.model), label(configs.find((x) => x.id === c.configId)!), `fav-${favKey(c)}`))}
        </>}
        {configs.map((cfg) => {
          const cat = catalogs[cfg.id];
          const own: ModelChoice = { configId: cfg.id, model: cfg.model };
          const list = Array.isArray(cat) ? cat.filter((m) => m.id !== cfg.model && (!q.trim() || matches(q, m.id, m.display_name, label(cfg)))) : [];
          const expanded = open[cfg.id] || !!q.trim();
          const showOwn = !q.trim() || matches(q, cfg.model, label(cfg));
          if (q.trim() && !showOwn && !list.length && cat !== "loading") return null;
          return (
            <div key={cfg.id} data-testid={`model-provider-${cfg.id}`}>
              <div className="flex items-center justify-between gap-2 px-2 pb-0.5 pt-2 text-[10.5px] font-semibold uppercase tracking-wide text-subtle-foreground">
                <span className="truncate">{label(cfg)}</span>
                {!q.trim() && <button type="button" data-testid={`model-all-${cfg.id}`} className="flex shrink-0 items-center gap-0.5 whitespace-nowrap normal-case tracking-normal hover:text-foreground"
                  onClick={() => { load(cfg.id); setOpen((o) => ({ ...o, [cfg.id]: !o[cfg.id] })); }}>
                  {Array.isArray(cat) ? t("models.allN", { count: cat.length }) : t("models.allN", { count: "…" })}
                  {expanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />}</button>}
              </div>
              {failure(cfg)}
              {showOwn && row(own, info(cfg.id, cfg.model), label(cfg), "own")}
              {expanded && cat === "loading" && <p className="px-2 py-1 text-[11.5px] text-subtle-foreground">{t("models.loading")}</p>}
              {expanded && cat === "failed" && <p className="px-2 py-1 text-[11.5px] text-subtle-foreground">{t("models.failedToLoad")}</p>}
              {expanded && list.slice(0, SHOWN).map((m) => row({ configId: cfg.id, model: m.id }, m, label(cfg), m.id))}
            </div>
          );
        })}
        {q.trim() && Object.values(catalogs).every((c) => c !== "loading") && !favRows.length
          && configs.every((cfg) => !matches(q, cfg.model, label(cfg)) && !(Array.isArray(catalogs[cfg.id]) && (catalogs[cfg.id] as ModelInfo[]).some((m) => matches(q, m.id, m.display_name, label(cfg)))))
          && <p className="px-2 py-3 text-[12px] text-subtle-foreground">{t("models.noMatch")}</p>}
      </div>
      <p className="px-2 text-[10.5px] text-subtle-foreground">{t("models.perMillion")}</p>
    </div>
  );
}
