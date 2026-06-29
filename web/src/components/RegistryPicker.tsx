import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import type { RegistryCatalog } from "../api/client.types";

export type PickKind = "tool" | "mcp" | "skill";

interface Props {
  /** Which registry partition to show. */
  kind: PickKind;
  /** Keys already equipped — shown disabled so they can't be added twice. */
  selected: string[];
  onPick: (kind: PickKind, key: string) => void;
  onClose: () => void;
}

/**
 * Compact picker over the REAL registry (api.getRegistry), filtered to
 * assignable === true. Tools = non-`mcp_` toolsets; MCPs = `mcp_` toolsets;
 * skills = the skills partition. Reuses CapabilityCatalog styling.
 */
export default function RegistryPicker({ kind, selected, onPick, onClose }: Props) {
  const { t } = useTranslation();
  const [cat, setCat] = useState<RegistryCatalog | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getRegistry().then(setCat).catch((e) => setError(String(e)));
  }, []);

  let items: { key: string; name: string; description: string }[] = [];
  if (cat) {
    if (kind === "skill") {
      items = cat.skills
        .filter((s) => s.assignable === true)
        .map((s) => ({ key: s.key, name: s.name, description: s.description }));
    } else {
      const assignable = cat.toolsets.filter((ts) => ts.assignable === true);
      const partition =
        kind === "mcp"
          ? assignable.filter((ts) => ts.key.startsWith("mcp_"))
          : assignable.filter((ts) => !ts.key.startsWith("mcp_"));
      items = partition.map((ts) => ({ key: ts.key, name: ts.name ?? ts.key, description: ts.description }));
    }
  }

  return (
    <div
      className="registry-picker bg-surface/60 border border-border/60 rounded-xl p-3 mt-2"
      data-testid={`picker-${kind}`}
    >
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
          {t(`create_card.picker.${kind}`)}
        </span>
        <button
          type="button"
          className="text-[11px] text-subtle-foreground hover:text-foreground"
          onClick={onClose}
          data-testid={`picker-close-${kind}`}
        >
          {t("create_card.picker.close")}
        </button>
      </div>

      {error && <div className="text-[11px] text-danger font-mono">{error}</div>}
      {!cat && !error && (
        <div className="text-[11px] text-subtle-foreground">{t("create_card.picker.loading")}</div>
      )}
      {cat && items.length === 0 && (
        <div className="text-[11px] text-subtle-foreground">{t("create_card.picker.empty")}</div>
      )}

      <div className="space-y-1.5 max-h-56 overflow-y-auto">
        {items.map((it) => {
          const taken = selected.includes(it.key);
          return (
            <button
              type="button"
              key={it.key}
              disabled={taken}
              onClick={() => onPick(kind, it.key)}
              data-testid={`pick-${kind}-${it.key}`}
              className={`w-full text-left bg-surface/40 border border-border/60 rounded-lg px-3 py-1.5 transition-colors ${
                taken ? "opacity-40 cursor-not-allowed" : "hover:border-accent/60"
              }`}
            >
              <span className="text-xs font-medium text-foreground">{it.name}</span>
              {it.description && (
                <span className="text-[11px] text-subtle-foreground ml-2">{it.description}</span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
