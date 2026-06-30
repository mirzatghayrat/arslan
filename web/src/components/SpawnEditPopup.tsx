import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Wrench, BookOpen, Boxes, Check, Lock, Save, X } from "lucide-react";
import { api } from "../api/client";
import type { RegistryCatalog, SpawnDetail } from "../api/client.types";
import { SpawnAvatar } from "./SpawnAvatar";

interface Props {
  /** Numeric spawn id (the backend id, not the UI string id). */
  spawnId: number;
  spawnName: string;
  spawnDomain: string;
  /** Called after a successful save (and on close) so the rail/roster can refresh. */
  onClose: () => void;
  onSaved?: () => void;
}

type PanelKind = "skill" | "tool" | "mcp";

interface PanelItem {
  key: string;
  name: string;
  description: string;
  tier: string;
  assignable: boolean;
}

/**
 * Inline edit popup for a spawn's equipment, opened from the right-rail
 * "Spawns Pipeline" list (keeps the user in the chat view instead of jumping
 * to the full-screen Ledger editor).
 *
 * Three scrollable library panels — Skills / Tools / MCPs — each sourced from
 * the REAL registry (api.getRegistry). MCPs are toolsets whose key starts with
 * "mcp_"; Tools are the other toolsets; Skills are the skills partition.
 * Currently-equipped items (from the full spawn detail) are pre-checked.
 *
 * Save merges the selected TOOL keys AND selected MCP keys into a single
 * `toolsets` array (since MCPs are toolsets at the registry/storage layer),
 * with `skills` carrying the selected skill keys → api.updateEquipment.
 */
export default function SpawnEditPopup({ spawnId, spawnName, spawnDomain, onClose, onSaved }: Props) {
  const { t } = useTranslation();
  const [cat, setCat] = useState<RegistryCatalog | null>(null);
  const [selectedToolsets, setSelectedToolsets] = useState<Set<string>>(new Set());
  const [selectedSkills, setSelectedSkills] = useState<Set<string>>(new Set());
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Esc to close.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Fetch the registry + the spawn's current equipment in parallel.
  useEffect(() => {
    let alive = true;
    Promise.all([api.getRegistry(), api.getSpawn(spawnId)])
      .then(([registry, detail]: [RegistryCatalog, SpawnDetail]) => {
        if (!alive) return;
        setCat(registry);
        setSelectedToolsets(new Set((detail.equipment?.toolsets ?? []).map((e) => e.key)));
        setSelectedSkills(new Set((detail.equipment?.skills ?? []).map((e) => e.key)));
        setLoaded(true);
      })
      .catch((e) => {
        if (alive) setError(String(e instanceof Error ? e.message : e));
      });
    return () => {
      alive = false;
    };
  }, [spawnId]);

  const panels = useMemo(() => {
    const skills: PanelItem[] = (cat?.skills ?? []).map((s) => ({
      key: s.key,
      name: s.name ?? s.key,
      description: s.description,
      tier: s.tier,
      assignable: s.assignable === true,
    }));
    const toolsets = cat?.toolsets ?? [];
    const tools: PanelItem[] = toolsets
      .filter((ts) => !ts.key.startsWith("mcp_"))
      .map((ts) => ({ key: ts.key, name: ts.name ?? ts.key, description: ts.description, tier: ts.tier, assignable: ts.assignable === true }));
    const mcps: PanelItem[] = toolsets
      .filter((ts) => ts.key.startsWith("mcp_"))
      .map((ts) => ({ key: ts.key, name: ts.name ?? ts.key, description: ts.description, tier: ts.tier, assignable: ts.assignable === true }));
    return { skills, tools, mcps };
  }, [cat]);

  function toggleSkill(key: string, assignable: boolean) {
    if (!assignable) return;
    setSelectedSkills((prev) => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  }

  // Tools AND MCPs both live in the `toolsets` selection set.
  function toggleToolset(key: string, assignable: boolean) {
    if (!assignable) return;
    setSelectedToolsets((prev) => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      // MCPs fold into `toolsets` — selectedToolsets already holds both tool and mcp_ keys.
      await api.updateEquipment(spawnId, {
        toolsets: Array.from(selectedToolsets),
        skills: Array.from(selectedSkills),
      });
      setSaved(true);
      onSaved?.();
      setTimeout(() => onClose(), 700);
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
      setSaving(false);
    }
  }

  // Explicit, statically-present class strings per panel (Tailwind v4 has no
  // config/safelist, so interpolated class names like `bg-${accent}` would be
  // pruned — these literals guarantee the utilities are generated).
  const ACCENTS = {
    skill: {
      heading: "text-warning",
      itemOn: "bg-warning/10 border-warning/40 cursor-pointer hover:border-warning/60",
      boxOn: "bg-warning border-warning text-primary-foreground",
    },
    tool: {
      heading: "text-primary",
      itemOn: "bg-primary/10 border-primary/40 cursor-pointer hover:border-primary/60",
      boxOn: "bg-primary border-primary text-primary-foreground",
    },
    mcp: {
      heading: "text-info",
      itemOn: "bg-info/10 border-info/40 cursor-pointer hover:border-info/60",
      boxOn: "bg-info border-info text-primary-foreground",
    },
  } as const;

  const panelMeta: {
    kind: PanelKind;
    items: PanelItem[];
    selected: Set<string>;
    toggle: (k: string, a: boolean) => void;
    icon: typeof Wrench;
    accent: (typeof ACCENTS)[PanelKind];
  }[] = [
    { kind: "skill", items: panels.skills, selected: selectedSkills, toggle: toggleSkill, icon: BookOpen, accent: ACCENTS.skill },
    { kind: "tool", items: panels.tools, selected: selectedToolsets, toggle: toggleToolset, icon: Wrench, accent: ACCENTS.tool },
    { kind: "mcp", items: panels.mcps, selected: selectedToolsets, toggle: toggleToolset, icon: Boxes, accent: ACCENTS.mcp },
  ];

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-background/55 backdrop-blur-sm animate-fade-in"
      data-testid="spawn-edit-popup"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <div
        className="w-full max-w-3xl max-h-[85vh] flex flex-col bg-surface border border-border-strong rounded-2xl shadow-2xl shadow-background/60 overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <header className="flex items-center justify-between gap-4 px-5 py-4 border-b border-border/60 bg-gradient-to-r from-surface to-background">
          <div className="flex items-center gap-3">
            <SpawnAvatar seed={spawnName} size={40} />
            <div>
              <h2 className="text-sm font-bold text-foreground font-sans">{spawnName}</h2>
              <p className="text-[11px] text-muted-foreground font-mono mt-0.5">{spawnDomain}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-subtle-foreground hover:text-foreground transition-colors p-1.5 rounded-lg hover:bg-background/40"
            aria-label={t("spawn_edit.close")}
            data-testid="spawn-edit-close"
          >
            <X className="w-4 h-4" />
          </button>
        </header>

        {/* Body — three scrollable library panels */}
        <div className="flex-1 overflow-y-auto p-5">
          {error && (
            <div className="mb-3 text-[11px] text-danger font-mono" role="alert" data-testid="spawn-edit-error">
              {error}
            </div>
          )}
          {!loaded && !error && (
            <div className="text-[11px] text-subtle-foreground py-8 text-center">{t("spawn_edit.loading")}</div>
          )}

          {loaded && (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {panelMeta.map(({ kind, items, selected, toggle, icon: Icon, accent }) => (
                <section key={kind} className="flex flex-col min-h-0" data-testid={`spawn-edit-panel-${kind}`}>
                  <div className="flex items-center justify-between mb-2">
                    <h3 className={`text-[10px] font-bold font-mono tracking-widest uppercase flex items-center gap-1.5 ${accent.heading}`}>
                      <Icon className="w-3.5 h-3.5" />
                      <span>{t(`spawn_edit.panel.${kind}`)}</span>
                    </h3>
                    <span className="text-[9px] font-mono text-subtle-foreground uppercase">
                      {t("spawn_edit.selected_count", {
                        count: items.filter((it) => selected.has(it.key)).length,
                      })}
                    </span>
                  </div>

                  <div className="space-y-1.5 max-h-72 overflow-y-auto pr-1 rounded-lg">
                    {items.length === 0 && (
                      <div className="text-[10px] text-subtle-foreground py-3 px-2">{t("spawn_edit.empty")}</div>
                    )}
                    {items.map((it) => {
                      const isOn = selected.has(it.key);
                      const locked = !it.assignable;
                      return (
                        <button
                          type="button"
                          key={it.key}
                          disabled={locked}
                          onClick={() => toggle(it.key, it.assignable)}
                          data-testid={`spawn-edit-item-${it.key}`}
                          aria-pressed={isOn}
                          className={`w-full text-left rounded-lg border px-2.5 py-2 transition-all flex items-start gap-2 ${
                            locked
                              ? "bg-background/40 border-border/50 opacity-50 cursor-not-allowed"
                              : isOn
                              ? accent.itemOn
                              : "bg-background/60 border-border/60 cursor-pointer hover:border-border-strong"
                          }`}
                        >
                          <span
                            className={`mt-0.5 w-4 h-4 shrink-0 rounded border flex items-center justify-center ${
                              isOn ? accent.boxOn : "border-border-strong bg-background"
                            }`}
                          >
                            {locked ? (
                              <Lock className="w-2.5 h-2.5 text-subtle-foreground" />
                            ) : (
                              isOn && <Check className="w-3 h-3 text-primary-foreground" />
                            )}
                          </span>
                          <span className="min-w-0">
                            <span className="block text-[11px] font-medium text-foreground truncate">{it.name}</span>
                            {it.description && (
                              <span className="block text-[10px] text-subtle-foreground leading-snug line-clamp-2">
                                {it.description}
                              </span>
                            )}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </section>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <footer className="flex items-center justify-end gap-2 px-5 py-3.5 border-t border-border/60 bg-background/40">
          <button
            type="button"
            onClick={onClose}
            className="px-3.5 py-2 text-[11px] font-bold font-sans uppercase rounded-lg border border-border text-muted-foreground hover:text-foreground hover:border-border-strong transition-colors"
            data-testid="spawn-edit-cancel"
          >
            {t("spawn_edit.cancel")}
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving || !loaded}
            data-testid="spawn-edit-save"
            className={`px-4 py-2 text-[11px] font-bold font-sans uppercase rounded-lg transition-all flex items-center gap-1.5 disabled:opacity-50 ${
              saved
                ? "bg-success text-primary-foreground"
                : "bg-primary hover:bg-primary-hover text-primary-foreground shadow-lg shadow-primary/15"
            }`}
          >
            {saved ? (
              <>
                <Check className="w-3.5 h-3.5" /> {t("spawn_edit.saved")}
              </>
            ) : (
              <>
                <Save className="w-3.5 h-3.5" /> {saving ? t("spawn_edit.saving") : t("spawn_edit.save")}
              </>
            )}
          </button>
        </footer>
      </div>
    </div>
  );
}
