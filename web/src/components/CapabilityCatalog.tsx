// Capability catalog (TOOLS & SKILLS tabs) — usable-first visibility.
// Availability chips derived from the real registry flags:
//   可用 (default)  = assignable items only — what a spawn can actually equip
//   未实装          = catalog-only placeholders (no body / no wired tool), muted + honest note
//   仅 Arslan       = orchestrator-tier items (real, but security-gated to the orchestrator)
//   全部            = everything with badges
// Infeasible items stay hidden entirely (existing behavior).
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Stethoscope } from "lucide-react";
import { api } from "../api/client";
import type { RegistryCatalog, RegistrySkill, RegistryToolset, SkillHealth } from "../api/client.types";
import FilterChips from "./FilterChips";
import EquipPopover from "./EquipPopover";

type AvailChip = "usable" | "unimplemented" | "orchestrator" | "all";
type AvailClass = Exclude<AvailChip, "all">;

function classify(it: { tier: string; assignable: boolean }): AvailClass {
  if (it.assignable) return "usable";
  if (it.tier === "orchestrator") return "orchestrator";
  return "unimplemented"; // safe-tier but not functional yet (honesty gate)
}

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

/** The shared availability chip row: 可用 (default) | 未实装 | 仅 Arslan | 全部. */
function availabilityChips(
  t: (k: string) => string,
  groups: Record<AvailClass, { length: number }>,
  total: number,
) {
  return [
    { id: "usable", label: t("capabilities.chips.usable"), count: groups.usable.length },
    ...(groups.unimplemented.length > 0
      ? [{ id: "unimplemented", label: t("capabilities.chips.unimplemented"), count: groups.unimplemented.length }]
      : []),
    ...(groups.orchestrator.length > 0
      ? [{ id: "orchestrator", label: t("capabilities.chips.arslan_only"), count: groups.orchestrator.length }]
      : []),
    { id: "all", label: t("capabilities.chips.all"), count: total },
  ];
}

function groupByClass<T extends { tier: string; assignable: boolean }>(items: T[]) {
  const groups: Record<AvailClass, T[]> = { usable: [], unimplemented: [], orchestrator: [] };
  for (const it of items) groups[classify(it)].push(it);
  return groups;
}

function OrchestratorNote() {
  const { t } = useTranslation();
  return (
    <p className="text-[10px] text-subtle-foreground font-sans mb-3">
      {t("capabilities.catalog.orchestrator_note")}
    </p>
  );
}

function ToolsView({ toolsets }: { toolsets: RegistryToolset[] }) {
  const { t } = useTranslation();
  const [chip, setChip] = useState<AvailChip>("usable");
  const groups = groupByClass(toolsets);
  const shown = chip === "all" ? toolsets : groups[chip];

  return (
    <div>
      <FilterChips
        chips={availabilityChips(t, groups, toolsets.length)}
        active={chip}
        onSelect={(id) => setChip(id as AvailChip)}
      />
      {chip === "orchestrator" && <OrchestratorNote />}
      {shown.length === 0 ? (
        <div className="text-[11px] text-subtle-foreground">{t("capabilities.catalog.empty")}</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {shown.map((ts) => (
            <ToolCard key={ts.key} ts={ts} />
          ))}
        </div>
      )}
    </div>
  );
}

function ToolCard({ ts }: { ts: RegistryToolset }) {
  const { t } = useTranslation();
  const avail = classify(ts);
  return (
    <div
      className={`bg-surface/40 border border-border/60 rounded-xl p-4 ${
        avail === "unimplemented" ? "opacity-60" : ""
      }`}
    >
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs font-bold text-foreground">{ts.name ?? ts.key}</span>
        <Badge tier={ts.tier} status={ts.status} assignable={ts.assignable} />
        {ts.degraded && (
          // P0-1 决定①b: reuse the PB-4 health-dot pattern — an amber dot + warning tooltip
          // so the user always sees when run_python is running UNSANDBOXED.
          <span
            data-testid={`toolset-degraded-${ts.key}`}
            title={ts.warning ?? t("capabilities.catalog.degraded")}
            className="flex items-center gap-1 text-[9px] font-mono uppercase px-1.5 py-0.5 rounded bg-danger/15 text-danger"
          >
            <span className="w-1.5 h-1.5 rounded-full bg-danger" />
            {t("capabilities.catalog.degraded")}
          </span>
        )}
        {avail === "usable" && (
          <span className="ml-auto">
            <EquipPopover kind="toolset" capKey={ts.key} />
          </span>
        )}
      </div>
      <p className="text-[11px] text-subtle-foreground mt-0.5">{ts.description}</p>
      {ts.degraded && ts.warning && (
        <p className="text-[10px] text-danger font-mono mt-1">{ts.warning}</p>
      )}
      {avail === "unimplemented" && (
        <p className="text-[10px] text-muted-foreground font-mono mt-1">
          {t("capabilities.catalog.unimplemented_note")}
        </p>
      )}
    </div>
  );
}

export { ToolCard };

function SkillsView({ skills }: { skills: RegistrySkill[] }) {
  const { t } = useTranslation();
  const [chip, setChip] = useState<AvailChip>("usable");
  const [catChip, setCatChip] = useState<string>("all");
  const subHeader = "text-[10px] font-mono uppercase tracking-wider text-muted-foreground mt-4 mb-2";

  const groups = groupByClass(skills);
  // Category chips filter WITHIN the active availability set.
  const pool = chip === "all" ? skills : groups[chip];
  const byCategory = new Map<string, RegistrySkill[]>();
  for (const s of pool) {
    const cat = s.category ?? "";
    if (!byCategory.has(cat)) byCategory.set(cat, []);
    byCategory.get(cat)!.push(s);
  }
  const categories = [...byCategory.keys()].sort();
  // If the selected category vanished (availability switch / data refresh), fall back to all.
  const activeCat = catChip !== "all" && !byCategory.has(catChip) ? "all" : catChip;
  const visibleCategories = activeCat === "all" ? categories : [activeCat];

  return (
    <div>
      <FilterChips
        chips={availabilityChips(t, groups, skills.length)}
        active={chip}
        onSelect={(id) => { setChip(id as AvailChip); setCatChip("all"); }}
      />
      {chip === "orchestrator" && <OrchestratorNote />}
      {pool.length > 0 && (
        <FilterChips
          chips={[
            { id: "all", label: t("capabilities.chips.all"), count: pool.length },
            ...categories.map((cat) => ({ id: cat, label: cat || "—", count: byCategory.get(cat)!.length })),
          ]}
          active={activeCat}
          onSelect={setCatChip}
        />
      )}
      {pool.length === 0 && (
        <div className="text-[11px] text-subtle-foreground">{t("capabilities.catalog.empty")}</div>
      )}
      {visibleCategories.map((cat) => (
        <div key={cat}>
          <div className={subHeader}>{cat} ({byCategory.get(cat)!.length})</div>
          <div className="space-y-2">
            {byCategory.get(cat)!.map((s) => (
              <SkillRow key={s.key} s={s} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function SkillRow({ s }: { s: RegistrySkill }) {
  const { t } = useTranslation();
  const avail = classify(s);
  // PC-5 health: probe on demand (mirrors RailMcpList's 体检). null = never checked.
  const [health, setHealth] = useState<SkillHealth | null>(null);
  const [checking, setChecking] = useState(false);
  const [open, setOpen] = useState(false);

  const runCheck = async () => {
    setChecking(true);
    try {
      const r = await api.checkSkillHealth(s.key);
      setHealth(r);
      setOpen(true);
    } catch {
      // fail-open: endpoint unreachable → keep whatever we knew before
    }
    setChecking(false);
  };

  // Dot colour mirrors the MCP health dot: ok → success, degraded → danger, unchecked → muted.
  // A degraded run whose ONLY problem is an unavailable sandbox reads as warning (honest amber)
  // rather than danger — nothing is broken, the host just can't run scripts.
  const sandboxOnly = health != null && health.status === "degraded"
    && !health.sandbox_available && health.storage.ok
    && health.references.every((r) => r.readable);
  const dotClass = health == null ? "bg-subtle-foreground"
    : health.status === "ok" ? "bg-success"
    : sandboxOnly ? "bg-warning" : "bg-danger";
  const dotTitle = health == null ? t("capabilities.skill_health.unknown")
    : health.status === "ok" ? t("capabilities.skill_health.ok")
    : sandboxOnly ? t("capabilities.skill_health.sandbox_unavailable")
    : t("capabilities.skill_health.degraded");

  return (
    <div
      className={`bg-surface/40 border border-border/60 rounded-lg px-3 py-2 flex flex-col gap-1 ${
        avail === "unimplemented" ? "opacity-60" : ""
      }`}
    >
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs font-medium text-foreground">{s.name}</span>
        <span className="text-[11px] text-subtle-foreground">{s.description}</span>
        <CompatBadge compatibility={s.compatibility} />
        <Badge tier={s.tier} status={s.status} assignable={s.assignable} />
        <span
          data-testid={`skill-health-dot-${s.key}`}
          title={dotTitle}
          className={`w-1.5 h-1.5 rounded-full ${dotClass}`}
        />
        <button
          type="button"
          onClick={() => (health ? setOpen((o) => !o) : runCheck())}
          disabled={checking}
          title={t("capabilities.skill_health.check")}
          data-testid={`skill-health-check-${s.key}`}
          className="flex items-center gap-0.5 text-[9px] font-mono text-subtle-foreground hover:text-info disabled:opacity-50"
        >
          <Stethoscope className="w-2.5 h-2.5" />
          {t("capabilities.skill_health.check")}
        </button>
        {avail === "usable" && (
          <span className="ml-auto">
            <EquipPopover kind="skill" capKey={s.key} />
          </span>
        )}
      </div>
      {avail === "unimplemented" && (
        <span className="w-full text-[10px] text-muted-foreground font-mono">
          {t("capabilities.catalog.unimplemented_note")}
        </span>
      )}
      {open && health && <SkillHealthPanel health={health} />}
    </div>
  );
}

// PC-5 health breakdown: storage integrity + per-script runnability + references, with the
// honest reasons the backend returns verbatim (e.g. "sandbox unavailable", "requires network").
function SkillHealthPanel({ health }: { health: SkillHealth }) {
  const { t } = useTranslation();
  const row = (label: string, ok: boolean, reason: string, key: string) => (
    <li key={key} className="flex items-baseline gap-1.5">
      <span className={`w-1.5 h-1.5 rounded-full shrink-0 translate-y-[3px] ${ok ? "bg-success" : "bg-warning"}`} />
      <span className="font-mono text-foreground">{label}</span>
      <span className="text-subtle-foreground">— {reason}</span>
    </li>
  );
  return (
    <div
      data-testid={`skill-health-panel-${health.key}`}
      className="mt-1 rounded-md bg-surface-raised/60 border border-border/50 px-2.5 py-2 text-[10px] space-y-1.5"
    >
      {!health.sandbox_available && (
        <p data-testid="skill-health-sandbox-warning" className="text-warning font-mono">
          {t("capabilities.skill_health.sandbox_unavailable")} (backend={health.sandbox_backend})
        </p>
      )}
      {health.error && <p className="text-danger font-mono">{health.error}</p>}
      {/* storage */}
      <div>
        <div className="font-mono uppercase tracking-wider text-muted-foreground">
          {t("capabilities.skill_health.storage")}
          <span className={health.storage.ok ? "text-success ml-1" : "text-warning ml-1"}>
            {health.storage.ok ? t("capabilities.skill_health.ok") : t("capabilities.skill_health.degraded")}
          </span>
        </div>
        {health.storage.missing.length > 0 && (
          <p className="text-warning font-mono">
            {t("capabilities.skill_health.missing")}: {health.storage.missing.join(", ")}
          </p>
        )}
        {health.storage.orphaned.length > 0 && (
          <p className="text-subtle-foreground font-mono">
            {t("capabilities.skill_health.orphaned")}: {health.storage.orphaned.join(", ")}
          </p>
        )}
      </div>
      {/* scripts */}
      {health.scripts.length > 0 && (
        <div>
          <div className="font-mono uppercase tracking-wider text-muted-foreground">
            {t("capabilities.skill_health.scripts")}
          </div>
          <ul className="space-y-0.5">
            {health.scripts.map((sc) => row(sc.name, sc.runnable, sc.reason, sc.name))}
          </ul>
        </div>
      )}
      {/* references */}
      {health.references.length > 0 && (
        <div>
          <div className="font-mono uppercase tracking-wider text-muted-foreground">
            {t("capabilities.skill_health.references")}
          </div>
          <ul className="space-y-0.5">
            {health.references.map((rf) => row(rf.name, rf.readable, rf.reason, rf.name))}
          </ul>
        </div>
      )}
    </div>
  );
}

// PC-4: honest sandbox-compatibility pill on each skill row. full=全兼容 (positive),
// partial=部分 (warning), text=仅文本 (muted). Semantic tokens only, matching the Badge style.
function CompatBadge({ compatibility }: { compatibility?: "full" | "partial" | "text" }) {
  const { t } = useTranslation();
  const compat = compatibility ?? "text";
  const cls =
    compat === "full" ? "bg-success/15 text-success"
    : compat === "partial" ? "bg-warning/15 text-warning"
    : "bg-surface-raised text-muted-foreground";
  return (
    <span
      data-testid={`skill-compat-${compat}`}
      title={t(`capabilities.compat.${compat}_hint`)}
      className={`text-[9px] font-mono uppercase px-1.5 py-0.5 rounded ${cls}`}
    >
      {t(`capabilities.compat.${compat}`)}
    </span>
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
