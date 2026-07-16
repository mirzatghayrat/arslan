import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Zap, FileDown } from "lucide-react";
import CapabilityTabs from "./CapabilityTabs";
import CapabilityCatalog from "./CapabilityCatalog";
import ToolHubDiscover, { type McpPrefill } from "./ToolHubDiscover";
import McpServers from "./McpServers";
import SavedCandidates from "./SavedCandidates";
import SkillForge from "./SkillForge";
import RecommendedMcp from "./RecommendedMcp";
import SkillImportPanel from "./SkillImportPanel";
import FilterChips from "./FilterChips";
import { getMcpCatalog } from "../api/catalog";
import { listMcpServers } from "../api/mcp";

type CapTab = "discover" | "tools" | "skills" | "forge" | "mcps" | "saved";
type McpChip = "all" | "recommended" | "registered";

// Capability Library page: one tab bar at the top
// (DISCOVER | TOOLS | SKILLS | SKILL FORGE | MCPS | SAVED). Discover is the
// default tab and holds the Google-style centered Tool-Hub hero (search →
// project dossier). Curated MCP presets live inside the MCPS tab (behind a
// filter-chip row); the SKILL.md importer inside SKILLS.
export default function Capabilities() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<CapTab>("discover");
  const [mcpPrefill, setMcpPrefill] = useState<McpPrefill | null>(null);
  // Bumped when an MCP is added/connected elsewhere (dossier, recommended list) so the
  // McpServers list remounts and picks the new server up.
  const [mcpRefreshKey, setMcpRefreshKey] = useState(0);

  // MCPS tab chip row: jump between the curated presets and the registered
  // server list. Both counts are fetched for the chip badges (null = unknown/offline).
  const [mcpChip, setMcpChip] = useState<McpChip>("all");
  const [mcpServerCount, setMcpServerCount] = useState<number | null>(null);
  const [mcpPresetCount, setMcpPresetCount] = useState<number | null>(null);
  useEffect(() => {
    let alive = true;
    listMcpServers()
      .then((s) => { if (alive) setMcpServerCount(s.length); })
      .catch(() => { if (alive) setMcpServerCount(null); });
    getMcpCatalog()
      .then((c) => { if (alive) setMcpPresetCount(c.length); })
      .catch(() => { if (alive) setMcpPresetCount(null); });
    return () => { alive = false; };
  }, [mcpRefreshKey]);

  // Prefill targets the McpServers add form — make sure it's on screen.
  const prefillMcp = (p: McpPrefill) => {
    setMcpPrefill(p);
    setMcpChip("all");
  };

  const sectionLabel =
    "flex items-center gap-1.5 text-[10px] font-mono text-subtle-foreground uppercase tracking-widest mb-3";

  return (
    <div className="w-full h-full overflow-y-auto">
      <div className="px-6 lg:px-10 pt-6 pb-10 max-w-[1400px] mx-auto w-full">
        <CapabilityTabs
          active={tab}
          onChange={(id) => setTab(id as CapTab)}
          tabs={[
            { id: "discover", label: t("capabilities.tabs.discover") },
            { id: "tools", label: t("capabilities.tabs.tools") },
            { id: "skills", label: t("capabilities.tabs.skills") },
            { id: "forge", label: t("capabilities.tabs.forge") },
            { id: "mcps", label: t("capabilities.tabs.mcps") },
            { id: "saved", label: t("capabilities.tabs.saved") },
          ]}
        />

        {/* Discover: the Tool-Hub hero (centered search input + RESEARCH → dossier) */}
        {tab === "discover" && (
          <ToolHubDiscover onMcpAdded={() => setMcpRefreshKey((k) => k + 1)} />
        )}

        {tab === "tools" && <CapabilityCatalog kind="tools" />}

        {tab === "skills" && (
          <div className="space-y-8">
            <section className="bg-surface/40 border border-border-strong rounded-2xl p-5">
              <div className={sectionLabel}>
                <FileDown className="w-3 h-3 text-primary" />
                <span>{t("capabilities.sections.import_skills")}</span>
              </div>
              <SkillImportPanel />
            </section>
            <CapabilityCatalog kind="skills" />
          </div>
        )}

        {tab === "forge" && <SkillForge />}

        {tab === "mcps" && (
          <div>
            <FilterChips
              chips={[
                { id: "all", label: t("capabilities.chips.all") },
                { id: "recommended", label: t("capabilities.chips.recommended"), count: mcpPresetCount ?? undefined },
                { id: "registered", label: t("capabilities.chips.registered"), count: mcpServerCount ?? undefined },
              ]}
              active={mcpChip}
              onSelect={(id) => setMcpChip(id as McpChip)}
            />
            <div className="space-y-8">
              {mcpChip !== "registered" && (
                <section>
                  <div className={sectionLabel}>
                    <Zap className="w-3 h-3 text-success" />
                    <span>{t("capabilities.sections.recommended_mcp")}</span>
                  </div>
                  <RecommendedMcp
                    onPrefillMcp={prefillMcp}
                    onChanged={() => setMcpRefreshKey((k) => k + 1)}
                  />
                </section>
              )}
              {mcpChip !== "recommended" && (
                <McpServers key={mcpRefreshKey} prefill={mcpPrefill ?? undefined} />
              )}
            </div>
          </div>
        )}

        {tab === "saved" && (
          <SavedCandidates onPrefillMcp={(p) => { prefillMcp(p); setTab("mcps"); }} />
        )}
      </div>
    </div>
  );
}
