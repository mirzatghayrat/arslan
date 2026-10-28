import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { FileDown } from "lucide-react";
import CapabilityTabs from "./CapabilityTabs";
import CapabilityCatalog from "./CapabilityCatalog";
import McpServers from "./McpServers";
import SkillForge from "./SkillForge";
import SkillImportPanel from "./SkillImportPanel";
import ToolTransportWarning from "./settings/ToolTransportWarning";
import ProfessionalMethods from "./companion/ProfessionalMethods";
import CapabilitySwitches from "./CapabilitySwitches";
import AddedCapabilities from "./capabilities/AddedCapabilities";

type CapTab = "experts" | "abilities" | "skills" | "forge" | "mcps";

// Capability Library page: one tab bar at the top (ABILITIES | SKILLS | CONNECTIONS, and the
// legacy experts when there are any). The MCPS tab lists the servers you added (0.1.63 C9b
// removed the curated presets); the SKILL.md importer lives inside SKILLS. v0.1.64 CAP1a removed
// the Discover tab, its saved candidates and the "found for later" rail: new capabilities are
// asked for in a conversation.
/** The provider whose transport decides whether ANY of this page's equipping
 *  will have an effect. Passed in rather than fetched here: App already holds
 *  the configs, and a second fetch would give this page its own opinion of which
 *  provider is primary. */
export default function Capabilities({ provider, experts, initialTab }: {
  provider?: string | null; experts?: ReactNode; initialTab?: CapTab;
} = {}) {
  const { t } = useTranslation();
  // 0.1.55 §14: the page opens on the switches — what Arslan can do, and why not.
  const [tab, setTab] = useState<CapTab>(initialTab ?? "abilities");
  useEffect(() => { if (initialTab) setTab(initialTab); }, [initialTab]);

  const sectionLabel =
    "flex items-center gap-1.5 text-[10px] font-mono text-subtle-foreground uppercase tracking-widest mb-3";

  return (
    <div className="w-full h-full overflow-y-auto">
      <div className="px-6 lg:px-10 pt-6 pb-10 max-w-[1400px] mx-auto w-full">
        {/* ABOVE the tab bar, deliberately — one insertion covers every tab.
            The failure it describes has no symptom anywhere: equip a toolset,
            connect an MCP server, tick "Allow Arslan", and every surface reads
            as installed while the model is never told any of it exists. The
            warning belongs where the equipping happens, not only in Settings,
            because the person who chose a provider three months ago is not
            going to open Settings before ticking a box here.

            `provider` absent (no provider configured yet) renders nothing:
            first-run has its own path, and telling someone their unset provider
            is unmeasured would be noise dressed as a safety notice. */}
        {provider ? (
          <div className="mb-4">
            <ToolTransportWarning provider={provider} showProviderName />
          </div>
        ) : null}

        <CapabilityTabs
          active={tab === "forge" ? "skills" : tab}
          onChange={(id) => setTab(id as CapTab)}
          tabs={[
            { id: "abilities", label: t("capabilityList.tab") },
            { id: "skills", label: t("workspace.skillsWorkflows") },
            // 0.1.48: connections (MCP servers) live here; the separate Connections page is gone.
            { id: "mcps", label: t("workspace.connections") },
            // Only for people who still have legacy experts (unchanged condition), and last.
            ...(experts ? [{ id: "experts", label: t("workspace.legacyExperts") }] : []),
          ]}
        />

        {tab === "experts" && experts}
        {tab === "abilities" && <><CapabilitySwitches onOpenTab={(next) => setTab(next)} /><AddedCapabilities /></>}
        {(tab === "skills" || tab === "forge") && <div className="mb-5 flex justify-end">
          <button className="rounded-lg border border-border px-3 py-2 text-sm hover:border-primary" onClick={() => setTab(tab === "forge" ? "skills" : "forge")}>
            {t(tab === "forge" ? "workspace.backToSkills" : "workspace.createSkill")}</button>
        </div>}

        {tab === "skills" && (
          <div className="space-y-8">
            <ProfessionalMethods />
            <section className="bg-surface/40 border border-border-strong rounded-2xl p-5">
              <div className={sectionLabel}>
                <FileDown className="w-3 h-3 text-primary" />
                <span>{t("capabilities.sections.import_skills")}</span>
              </div>
              <SkillImportPanel />
            </section>
            <CapabilityCatalog assign={!!experts} />
          </div>
        )}

        {tab === "forge" && <SkillForge />}

        {tab === "mcps" && <McpServers />}
      </div>
    </div>
  );
}
