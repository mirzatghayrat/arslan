import { useState } from "react";
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

type CapTab = "tools" | "skills" | "forge" | "mcps" | "saved";

// Capability Library page: a full-width shell = Tool-Hub hero (Google-style discover →
// project dossier) + one tab bar (TOOLS | SKILLS | SKILL FORGE | MCPS | SAVED).
// Curated MCP presets live inside the MCPS tab; the SKILL.md importer inside SKILLS.
export default function Capabilities() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<CapTab>("mcps");
  const [mcpPrefill, setMcpPrefill] = useState<McpPrefill | null>(null);
  // Bumped when an MCP is added/connected elsewhere (dossier, recommended list) so the
  // McpServers list remounts and picks the new server up.
  const [mcpRefreshKey, setMcpRefreshKey] = useState(0);

  const sectionLabel =
    "flex items-center gap-1.5 text-[10px] font-mono text-subtle-foreground uppercase tracking-widest mb-3";

  return (
    <div className="w-full h-full overflow-y-auto">
      <div className="px-6 lg:px-10 pb-10 max-w-[1400px] mx-auto w-full">
        {/* Hero: Tool-Hub discover input + project dossier */}
        <ToolHubDiscover onMcpAdded={() => setMcpRefreshKey((k) => k + 1)} />

        <CapabilityTabs
          active={tab}
          onChange={(id) => setTab(id as CapTab)}
          tabs={[
            { id: "tools", label: t("capabilities.tabs.tools") },
            { id: "skills", label: t("capabilities.tabs.skills") },
            { id: "forge", label: t("capabilities.tabs.forge") },
            { id: "mcps", label: t("capabilities.tabs.mcps") },
            { id: "saved", label: t("capabilities.tabs.saved") },
          ]}
        />

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
          <div className="space-y-8">
            <section>
              <div className={sectionLabel}>
                <Zap className="w-3 h-3 text-success" />
                <span>{t("capabilities.sections.recommended_mcp")}</span>
              </div>
              <RecommendedMcp
                onPrefillMcp={(p) => setMcpPrefill(p)}
                onChanged={() => setMcpRefreshKey((k) => k + 1)}
              />
            </section>
            <McpServers key={mcpRefreshKey} prefill={mcpPrefill ?? undefined} />
          </div>
        )}

        {tab === "saved" && (
          <SavedCandidates onPrefillMcp={(p) => { setMcpPrefill(p); setTab("mcps"); }} />
        )}
      </div>
    </div>
  );
}
