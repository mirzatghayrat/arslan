import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Wrench, BookOpen, Boxes, Check, Lock, Save, X, Sparkles,
  Trash2, Search, Users, Loader2,
} from "lucide-react";
import { api } from "../api/client";
import type { RegistryCatalog, SpawnDetail, SeedRef, SuggestDraft } from "../api/client.types";
import { SpawnAvatar } from "./SpawnAvatar";

interface Props {
  mode: "edit" | "create";
  /** Numeric spawn id (backend id) — required for edit mode. */
  spawnId?: number;
  onClose: () => void;
  /** Called after a successful save / create / delete so the caller can refresh. */
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
 * Spawn Studio — a roomy panel that both CREATES and CONFIGURES spawns,
 * replacing the cramped SpawnEditPopup.
 *
 * Two modes:
 *  - edit:   load the spawn, show its details + composed seed identities,
 *            pre-check its equipment in the library panels, Save (updateEquipment)
 *            / Delete (deleteSpawn).
 *  - create: a scope/mission textarea + a Recommend button (draftSpawn) that
 *            pre-fills name/domain/persona AND pre-selects seeds + tools + skills
 *            + mcps in the panels; Create (createSpawn) persists it.
 *
 * Library panels are sourced from the REAL registry (api.getRegistry). MCPs are
 * toolsets whose key starts with "mcp_"; Tools are the other toolsets; Skills are
 * the skills partition. Tools AND MCPs both mutate one `selectedToolsets` set —
 * MCPs fold into `toolsets` at the storage layer (exactly like SpawnEditPopup).
 */
export default function SpawnStudio({ mode, spawnId, onClose, onSaved }: Props) {
  const { t } = useTranslation();

  const [cat, setCat] = useState<RegistryCatalog | null>(null);
  const [selectedToolsets, setSelectedToolsets] = useState<Set<string>>(new Set());
  const [selectedSkills, setSelectedSkills] = useState<Set<string>>(new Set());
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // edit-mode spawn detail (header + composed seeds).
  const [detail, setDetail] = useState<SpawnDetail | null>(null);

  // create-mode editable header fields + recommend state.
  const [description, setDescription] = useState("");
  const [name, setName] = useState("");
  const [domain, setDomain] = useState("");
  const [role, setRole] = useState("");
  const [tone, setTone] = useState("");
  const [capabilities, setCapabilities] = useState<string[]>([]);
  const [drafting, setDrafting] = useState(false);

  // create-mode seed selection (collected for createSpawn's seed_refs).
  const [seedQuery, setSeedQuery] = useState("");
  const [seedResults, setSeedResults] = useState<SeedRef[]>([]);
  const [selectedSeeds, setSelectedSeeds] = useState<Map<string, SeedRef>>(new Map());

  // Delete affordance — built-in (system default) spawns are undeletable.
  const deletable = !detail?.is_default;
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  // Esc to close.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Load registry (both modes) + spawn detail (edit mode).
  useEffect(() => {
    let alive = true;
    const reg = api.getRegistry();
    if (mode === "edit" && spawnId != null) {
      Promise.all([reg, api.getSpawn(spawnId)])
        .then(([registry, d]) => {
          if (!alive) return;
          setCat(registry);
          setDetail(d);
          setSelectedToolsets(new Set((d.equipment?.toolsets ?? []).map((e) => e.key)));
          setSelectedSkills(new Set((d.equipment?.skills ?? []).map((e) => e.key)));
          setLoaded(true);
        })
        .catch((e) => alive && setError(String(e instanceof Error ? e.message : e)));
    } else {
      reg
        .then((registry) => {
          if (!alive) return;
          setCat(registry);
          setLoaded(true);
        })
        .catch((e) => alive && setError(String(e instanceof Error ? e.message : e)));
    }
    return () => {
      alive = false;
    };
  }, [mode, spawnId]);

  // create-mode: initial seed browse (and re-fetch on search).
  useEffect(() => {
    if (mode !== "create") return;
    let alive = true;
    api
      .getSeeds(seedQuery || undefined, 40)
      .then((r) => alive && setSeedResults(r.seeds))
      .catch(() => alive && setSeedResults([]));
    return () => {
      alive = false;
    };
  }, [mode, seedQuery]);

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

  function toggleSeed(seed: SeedRef) {
    setSelectedSeeds((prev) => {
      const next = new Map(prev);
      next.has(seed.slug) ? next.delete(seed.slug) : next.set(seed.slug, seed);
      return next;
    });
  }

  // create-mode: Recommend → draft a spawn and pre-fill everything below.
  async function handleRecommend() {
    if (!description.trim() || drafting) return;
    setDrafting(true);
    setError(null);
    try {
      const draft: SuggestDraft = await api.draftSpawn(description.trim());
      setName(draft.name ?? "");
      setDomain(draft.domain ?? "");
      setRole(draft.persona_role ?? "");
      setTone(draft.persona_tone ?? "");
      setCapabilities(draft.capabilities ?? []);
      // Pre-select tools + mcps into the merged toolset set, skills into skills.
      const ts = new Set<string>([...(draft.tools ?? []), ...(draft.mcps ?? [])]);
      setSelectedToolsets(ts);
      setSelectedSkills(new Set(draft.skills ?? []));
      // Pre-select recommended seeds; resolve their display info from the catalog.
      const refs = draft.seed_refs ?? [];
      if (refs.length > 0) {
        const r = await api.getSeeds(undefined, 249).catch(() => null);
        const bySlug = new Map<string, SeedRef>((r?.seeds ?? []).map((s) => [s.slug, s] as [string, SeedRef]));
        setSelectedSeeds(() => {
          const next = new Map<string, SeedRef>();
          for (const slug of refs) {
            const s: SeedRef = bySlug.get(slug) ?? { slug, name: slug, division: "", summary: "" };
            next.set(slug, s);
          }
          return next;
        });
      }
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setDrafting(false);
    }
  }

  async function handleSaveEdit() {
    if (spawnId == null) return;
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

  async function handleCreate() {
    if (!name.trim() || saving) return;
    setSaving(true);
    setError(null);
    try {
      await api.createSpawn({
        name: name.trim(),
        domain: domain.trim(),
        capabilities,
        persona_role: role || null,
        persona_tone: tone || null,
        seed_refs: Array.from(selectedSeeds.keys()),
        equipment: {
          toolsets: Array.from(selectedToolsets),
          skills: Array.from(selectedSkills),
        },
      });
      setSaved(true);
      onSaved?.();
      setTimeout(() => onClose(), 600);
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (spawnId == null || !deletable) return;
    setSaving(true);
    setError(null);
    try {
      await api.deleteSpawn(spawnId);
      onSaved?.();
      onClose();
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
      setSaving(false);
      setConfirmingDelete(false);
    }
  }

  // Statically-present class strings per panel (Tailwind v4 prunes interpolated names).
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

  const headerName = mode === "edit" ? detail?.name ?? "" : name || t("spawn_studio.untitled");
  const headerDomain = mode === "edit" ? detail?.domain ?? "" : domain;
  const composedSeeds = detail?.seeds ?? [];

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-background/55 backdrop-blur-sm animate-fade-in"
      data-testid="spawn-studio"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <div
        className="w-full max-w-5xl max-h-[85vh] flex flex-col bg-surface border border-border-strong rounded-2xl shadow-2xl shadow-background/60 overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <header className="flex items-center justify-between gap-4 px-6 py-4 border-b border-border/60 bg-gradient-to-r from-surface to-background">
          <div className="flex items-center gap-3.5 min-w-0">
            <SpawnAvatar seed={headerName || "spawn"} size={48} />
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <h2 className="text-base font-bold text-foreground font-sans truncate">
                  {headerName || t("spawn_studio.new_spawn")}
                </h2>
                <span className="text-[9px] font-mono uppercase tracking-widest px-2 py-0.5 rounded bg-primary/15 text-primary font-bold shrink-0">
                  {t(mode === "edit" ? "spawn_studio.badge_edit" : "spawn_studio.badge_create")}
                </span>
              </div>
              {headerDomain && <p className="text-[11px] text-muted-foreground font-mono mt-0.5 truncate">{headerDomain}</p>}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-subtle-foreground hover:text-foreground transition-colors p-1.5 rounded-lg hover:bg-background/40 shrink-0"
            aria-label={t("spawn_studio.close")}
            data-testid="spawn-studio-close"
          >
            <X className="w-4 h-4" />
          </button>
        </header>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-5">
          {error && (
            <div className="text-[11px] text-danger font-mono" role="alert" data-testid="spawn-studio-error">
              {error}
            </div>
          )}
          {!loaded && !error && (
            <div className="text-[11px] text-subtle-foreground py-10 text-center">{t("spawn_studio.loading")}</div>
          )}

          {loaded && (
            <>
              {/* CREATE: scope/mission + recommend */}
              {mode === "create" && (
                <section className="space-y-3" data-testid="spawn-studio-recommend">
                  <label className="block text-[10px] font-bold font-mono tracking-widest uppercase text-primary">
                    {t("spawn_studio.scope_label")}
                  </label>
                  <textarea
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    rows={2}
                    placeholder={t("spawn_studio.scope_placeholder")}
                    data-testid="spawn-studio-scope"
                    className="w-full bg-background border border-border-strong focus:border-primary/60 focus:ring-1 focus:ring-ring/20 rounded-xl px-3.5 py-2.5 text-xs text-foreground placeholder-subtle-foreground focus:outline-none transition-all resize-none font-sans"
                  />
                  <div className="flex items-center justify-between gap-3">
                    <div className="grid grid-cols-2 gap-2 flex-1">
                      <input
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        placeholder={t("spawn_studio.name_label")}
                        aria-label={t("spawn_studio.name_label")}
                        data-testid="spawn-studio-name"
                        className="bg-background border border-border-strong focus:border-primary/60 rounded-lg px-3 py-2 text-xs text-foreground placeholder-subtle-foreground focus:outline-none font-sans"
                      />
                      <input
                        value={domain}
                        onChange={(e) => setDomain(e.target.value)}
                        placeholder={t("spawn_studio.domain_label")}
                        aria-label={t("spawn_studio.domain_label")}
                        data-testid="spawn-studio-domain"
                        className="bg-background border border-border-strong focus:border-primary/60 rounded-lg px-3 py-2 text-xs text-foreground placeholder-subtle-foreground focus:outline-none font-mono"
                      />
                    </div>
                    <button
                      type="button"
                      onClick={handleRecommend}
                      disabled={!description.trim() || drafting}
                      data-testid="spawn-studio-recommend-btn"
                      className="px-4 py-2 text-[11px] font-bold font-sans uppercase rounded-lg bg-primary hover:bg-primary-hover text-primary-foreground shadow-lg shadow-primary/15 transition-all flex items-center gap-1.5 disabled:opacity-50 shrink-0"
                    >
                      {drafting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
                      {drafting ? t("spawn_studio.recommending") : t("spawn_studio.recommend")}
                    </button>
                  </div>
                  <input
                    value={role}
                    onChange={(e) => setRole(e.target.value)}
                    placeholder={t("spawn_studio.role_label")}
                    aria-label={t("spawn_studio.role_label")}
                    data-testid="spawn-studio-role"
                    className="w-full bg-background border border-border-strong focus:border-primary/60 rounded-lg px-3 py-2 text-xs text-foreground placeholder-subtle-foreground focus:outline-none font-sans"
                  />
                </section>
              )}

              {/* EDIT: scope/mission read-out + composed seeds */}
              {mode === "edit" && detail && (
                <section className="space-y-3">
                  {detail.persona_role && (
                    <div className="bg-background/50 border border-border/40 rounded-xl px-4 py-3">
                      <div className="text-[9px] font-mono uppercase tracking-widest text-subtle-foreground mb-1">
                        {t("spawn_studio.mission")}
                      </div>
                      <p className="text-[12px] text-foreground font-sans leading-relaxed">{detail.persona_role}</p>
                    </div>
                  )}
                  <div>
                    <div className="text-[9px] font-mono uppercase tracking-widest text-subtle-foreground mb-1.5 flex items-center gap-1.5">
                      <Users className="w-3 h-3" />
                      {t("spawn_studio.composed_from")}
                    </div>
                    {composedSeeds.length === 0 ? (
                      <span className="text-[11px] text-subtle-foreground">—</span>
                    ) : (
                      <div className="flex flex-wrap gap-1.5" data-testid="spawn-studio-composed-seeds">
                        {composedSeeds.map((s) => (
                          <span
                            key={s.slug}
                            title={s.summary}
                            className="inline-flex items-center gap-1.5 text-[10px] font-mono px-2 py-1 rounded-lg bg-primary/10 border border-primary/25 text-foreground"
                          >
                            <span className="font-medium">{s.name}</span>
                            {s.division && <span className="text-subtle-foreground">· {s.division}</span>}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                </section>
              )}

              {/* CREATE: seeds library panel + library panels in one grid */}
              <div className={`grid grid-cols-1 gap-4 ${mode === "create" ? "md:grid-cols-4" : "md:grid-cols-3"}`}>
                {mode === "create" && (
                  <section className="flex flex-col min-h-0" data-testid="spawn-studio-panel-seed">
                    <div className="flex items-center justify-between mb-2">
                      <h3 className="text-[10px] font-bold font-mono tracking-widest uppercase flex items-center gap-1.5 text-foreground">
                        <Users className="w-3.5 h-3.5" />
                        <span>{t("spawn_studio.panel_seeds")}</span>
                      </h3>
                      <span className="text-[9px] font-mono text-subtle-foreground uppercase">
                        {t("spawn_studio.selected_count", { count: selectedSeeds.size })}
                      </span>
                    </div>
                    <div className="relative mb-2">
                      <Search className="w-3 h-3 absolute left-2 top-1/2 -translate-y-1/2 text-subtle-foreground" />
                      <input
                        value={seedQuery}
                        onChange={(e) => setSeedQuery(e.target.value)}
                        placeholder={t("spawn_studio.seed_search")}
                        aria-label={t("spawn_studio.seed_search")}
                        data-testid="spawn-studio-seed-search"
                        className="w-full bg-background/60 border border-border/60 rounded-lg pl-7 pr-2 py-1.5 text-[11px] text-foreground placeholder-subtle-foreground focus:outline-none focus:border-primary/50 font-sans"
                      />
                    </div>
                    <div className="space-y-1.5 max-h-72 overflow-y-auto pr-1 rounded-lg">
                      {seedResults.length === 0 && (
                        <div className="text-[10px] text-subtle-foreground py-3 px-2">{t("spawn_studio.empty")}</div>
                      )}
                      {seedResults.map((s) => {
                        const isOn = selectedSeeds.has(s.slug);
                        return (
                          <button
                            type="button"
                            key={s.slug}
                            onClick={() => toggleSeed(s)}
                            data-testid={`spawn-studio-seed-${s.slug}`}
                            aria-pressed={isOn}
                            className={`w-full text-left rounded-lg border px-2.5 py-2 transition-all flex items-start gap-2 ${
                              isOn
                                ? "bg-primary/10 border-primary/40 cursor-pointer hover:border-primary/60"
                                : "bg-background/60 border-border/60 cursor-pointer hover:border-border-strong"
                            }`}
                          >
                            <span
                              className={`mt-0.5 w-4 h-4 shrink-0 rounded border flex items-center justify-center ${
                                isOn ? "bg-primary border-primary text-primary-foreground" : "border-border-strong bg-background"
                              }`}
                            >
                              {isOn && <Check className="w-3 h-3 text-primary-foreground" />}
                            </span>
                            <span className="min-w-0">
                              <span className="block text-[11px] font-medium text-foreground truncate">{s.name}</span>
                              {s.division && (
                                <span className="block text-[9px] font-mono text-subtle-foreground uppercase tracking-wide">{s.division}</span>
                              )}
                              {s.summary && (
                                <span className="block text-[10px] text-subtle-foreground leading-snug line-clamp-2">{s.summary}</span>
                              )}
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  </section>
                )}

                {panelMeta.map(({ kind, items, selected, toggle, icon: Icon, accent }) => (
                  <section key={kind} className="flex flex-col min-h-0" data-testid={`spawn-studio-panel-${kind}`}>
                    <div className="flex items-center justify-between mb-2">
                      <h3 className={`text-[10px] font-bold font-mono tracking-widest uppercase flex items-center gap-1.5 ${accent.heading}`}>
                        <Icon className="w-3.5 h-3.5" />
                        <span>{t(`spawn_studio.panel_${kind}`)}</span>
                      </h3>
                      <span className="text-[9px] font-mono text-subtle-foreground uppercase">
                        {t("spawn_studio.selected_count", {
                          count: items.filter((it) => selected.has(it.key)).length,
                        })}
                      </span>
                    </div>
                    <div className="space-y-1.5 max-h-72 overflow-y-auto pr-1 rounded-lg">
                      {items.length === 0 && (
                        <div className="text-[10px] text-subtle-foreground py-3 px-2">{t("spawn_studio.empty")}</div>
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
                            data-testid={`spawn-studio-item-${it.key}`}
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
            </>
          )}
        </div>

        {/* Footer */}
        <footer className="flex items-center justify-between gap-2 px-6 py-3.5 border-t border-border/60 bg-background/40">
          <div>
            {mode === "edit" && deletable && (
              confirmingDelete ? (
                <div className="flex items-center gap-2" data-testid="spawn-studio-delete-confirm">
                  <span className="text-[11px] text-danger font-mono">{t("spawn_studio.delete_confirm")}</span>
                  <button
                    type="button"
                    onClick={handleDelete}
                    disabled={saving}
                    data-testid="spawn-studio-delete-yes"
                    className="px-3 py-1.5 text-[11px] font-bold font-sans uppercase rounded-lg bg-danger text-primary-foreground hover:bg-danger/90 transition-colors disabled:opacity-50"
                  >
                    {t("spawn_studio.delete_yes")}
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirmingDelete(false)}
                    className="px-3 py-1.5 text-[11px] font-bold font-sans uppercase rounded-lg border border-border text-muted-foreground hover:text-foreground transition-colors"
                  >
                    {t("spawn_studio.cancel")}
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => setConfirmingDelete(true)}
                  data-testid="spawn-studio-delete"
                  className="px-3 py-2 text-[11px] font-bold font-sans uppercase rounded-lg border border-danger/30 text-danger/80 hover:text-danger hover:border-danger/60 transition-colors flex items-center gap-1.5"
                >
                  <Trash2 className="w-3.5 h-3.5" /> {t("spawn_studio.delete")}
                </button>
              )
            )}
            {mode === "edit" && !deletable && (
              <span
                className="text-[10.5px] font-mono text-subtle-foreground flex items-center gap-1.5"
                data-testid="spawn-studio-builtin"
              >
                <Lock className="w-3 h-3" /> {t("spawn_studio.builtin")}
              </span>
            )}
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-3.5 py-2 text-[11px] font-bold font-sans uppercase rounded-lg border border-border text-muted-foreground hover:text-foreground hover:border-border-strong transition-colors"
              data-testid="spawn-studio-cancel"
            >
              {t("spawn_studio.cancel")}
            </button>
            {mode === "edit" ? (
              <button
                type="button"
                onClick={handleSaveEdit}
                disabled={saving || !loaded}
                data-testid="spawn-studio-save"
                className={`px-4 py-2 text-[11px] font-bold font-sans uppercase rounded-lg transition-all flex items-center gap-1.5 disabled:opacity-50 ${
                  saved ? "bg-success text-primary-foreground" : "bg-primary hover:bg-primary-hover text-primary-foreground shadow-lg shadow-primary/15"
                }`}
              >
                {saved ? (
                  <><Check className="w-3.5 h-3.5" /> {t("spawn_studio.saved")}</>
                ) : (
                  <><Save className="w-3.5 h-3.5" /> {saving ? t("spawn_studio.saving") : t("spawn_studio.save")}</>
                )}
              </button>
            ) : (
              <button
                type="button"
                onClick={handleCreate}
                disabled={saving || !name.trim()}
                data-testid="spawn-studio-create"
                className={`px-4 py-2 text-[11px] font-bold font-sans uppercase rounded-lg transition-all flex items-center gap-1.5 disabled:opacity-50 ${
                  saved ? "bg-success text-primary-foreground" : "bg-primary hover:bg-primary-hover text-primary-foreground shadow-lg shadow-primary/15"
                }`}
              >
                {saved ? (
                  <><Check className="w-3.5 h-3.5" /> {t("spawn_studio.created")}</>
                ) : (
                  <><Sparkles className="w-3.5 h-3.5" /> {saving ? t("spawn_studio.creating") : t("spawn_studio.create")}</>
                )}
              </button>
            )}
          </div>
        </footer>
      </div>
    </div>
  );
}
