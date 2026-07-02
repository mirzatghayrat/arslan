import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import type { RegistryCatalog } from "../api/client.types";

export default function CapabilityCatalog({ kind }: { kind: "tools" | "skills" }) {
  const { t } = useTranslation();
  const [cat, setCat] = useState<RegistryCatalog | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getRegistry().then(setCat).catch((e) => setError(String(e)));
  }, []);

  if (error) return <div className="text-[11px] text-danger font-mono">{error}</div>;
  if (!cat) return <div className="text-[11px] text-subtle-foreground">{t("capabilities.catalog.loading")}</div>;

  const items = kind === "tools" ? cat.toolsets : cat.skills;
  const visible = items.filter((it) => it.status !== "infeasible");
  if (visible.length === 0) return <div className="text-[11px] text-subtle-foreground">{t("capabilities.catalog.empty")}</div>;

  return (
    <div>
      <p className="text-[10px] text-subtle-foreground font-sans mb-3">{t("capabilities.catalog.equip_hint")}</p>
      {kind === "tools" ? (
        <ToolsView toolsets={cat.toolsets.filter((ts) => ts.status !== "infeasible")} />
      ) : (
        <SkillsView skills={cat.skills.filter((s) => s.status !== "infeasible")} />
      )}
    </div>
  );
}

function ToolsView({ toolsets }: { toolsets: RegistryCatalog["toolsets"] }) {
  const { t } = useTranslation();
  const [showLocked, setShowLocked] = useState(false);
  const assignable = toolsets.filter((ts) => ts.assignable === true);
  const locked = toolsets.filter((ts) => ts.assignable !== true);

  const subHeader = "text-[10px] font-mono uppercase tracking-wider text-muted-foreground mt-4 mb-2";

  return (
    <div>
      {assignable.length > 0 && (
        <>
          <div className={subHeader}>{t("capabilities.catalog.assignable_group")} ({assignable.length})</div>
          <div className="space-y-3">
            {assignable.map((ts) => (
              <ToolCard key={ts.key} ts={ts} />
            ))}
          </div>
        </>
      )}
      {locked.length > 0 && (
        <>
          <button
            type="button"
            onClick={() => setShowLocked((v) => !v)}
            className={`${subHeader} flex items-center gap-1 hover:text-foreground transition-colors`}
          >
            {showLocked ? "▾" : "▸"} {t("capabilities.catalog.locked_group")} ({locked.length})
          </button>
          {showLocked && (
            <div className="space-y-3 opacity-70">
              {locked.map((ts) => (
                <ToolCard key={ts.key} ts={ts} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function ToolCard({ ts }: { ts: RegistryCatalog["toolsets"][number] }) {
  return (
    <div className="bg-surface/40 border border-border/60 rounded-xl p-4">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs font-bold text-foreground">{ts.name ?? ts.key}</span>
        <Badge tier={ts.tier} status={ts.status} assignable={ts.assignable} />
      </div>
      <p className="text-[11px] text-subtle-foreground mt-0.5">{ts.description}</p>
    </div>
  );
}

function SkillsView({ skills }: { skills: RegistryCatalog["skills"] }) {
  const subHeader = "text-[10px] font-mono uppercase tracking-wider text-muted-foreground mt-4 mb-2";
  const byCategory = new Map<string, RegistryCatalog["skills"]>();
  for (const s of skills) {
    const cat = s.category ?? "";
    if (!byCategory.has(cat)) byCategory.set(cat, []);
    byCategory.get(cat)!.push(s);
  }
  const categories = [...byCategory.keys()].sort();

  return (
    <div>
      {categories.map((cat) => (
        <div key={cat}>
          <div className={subHeader}>{cat} ({byCategory.get(cat)!.length})</div>
          <div className="space-y-2">
            {byCategory.get(cat)!.map((s) => (
              <div
                key={s.key}
                className="bg-surface/40 border border-border/60 rounded-lg px-3 py-2 flex items-center gap-2 flex-wrap"
              >
                <span className="text-xs font-medium text-foreground">{s.name}</span>
                <span className="text-[11px] text-subtle-foreground">{s.description}</span>
                <Badge tier={s.tier} status={s.status} assignable={s.assignable} />
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function Badge({ tier, status, assignable }: { tier: string; status: string; assignable?: boolean }) {
  const ok = assignable === true;
  // safe + registered but NOT assignable = catalogued-only (no body / no wired tool yet) —
  // honest label so it never reads as an equippable capability.
  const catalogOnly = !ok && tier === "safe" && (status === "wired" || status === "registered");
  return (
    <span
      className={`text-[9px] font-mono uppercase px-1.5 py-0.5 rounded ${
        ok ? "bg-success/15 text-success" : "bg-surface-raised text-subtle-foreground"
      }`}
    >
      {ok ? "assignable" : catalogOnly ? "catalog" : `${tier}/${status}`}
    </span>
  );
}
