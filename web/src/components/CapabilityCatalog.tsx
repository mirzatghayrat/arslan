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
  if (items.length === 0) return <div className="text-[11px] text-subtle-foreground">{t("capabilities.catalog.empty")}</div>;

  return (
    <div>
      <p className="text-[10px] text-subtle-foreground font-sans mb-3">{t("capabilities.catalog.equip_hint")}</p>
      {kind === "tools" ? (
        <div className="space-y-3">
          {cat.toolsets.map((ts) => (
            <div key={ts.key} className="bg-surface/40 border border-border/60 rounded-xl p-4">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs font-bold text-foreground">{ts.name ?? ts.key}</span>
                <Badge tier={ts.tier} status={ts.status} assignable={ts.assignable} />
              </div>
              <p className="text-[11px] text-subtle-foreground mt-0.5">{ts.description}</p>
            </div>
          ))}
        </div>
      ) : (
        <div className="space-y-2">
          {cat.skills.map((s) => (
            <div
              key={s.key}
              className="bg-surface/40 border border-border/60 rounded-lg px-3 py-2 flex items-center gap-2 flex-wrap"
            >
              <span className="text-xs font-medium text-foreground">{s.name}</span>
              <span className="text-[9px] font-mono text-subtle-foreground">{s.category}</span>
              <Badge tier={s.tier} status={s.status} assignable={s.assignable} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Badge({ tier, status, assignable }: { tier: string; status: string; assignable?: boolean }) {
  const ok = assignable ?? (tier === "safe" && (status === "wired" || status === "registered"));
  return (
    <span
      className={`text-[9px] font-mono uppercase px-1.5 py-0.5 rounded ${
        ok ? "bg-success/15 text-success" : "bg-surface-raised text-subtle-foreground"
      }`}
    >
      {ok ? "assignable" : `${tier}/${status}`}
    </span>
  );
}
