import { useState } from "react";
import { useTranslation } from "react-i18next";
import CapabilityTabs from "./CapabilityTabs";
import CapabilityCatalog from "./CapabilityCatalog";
import ToolHubDiscover, { type McpPrefill } from "./ToolHubDiscover";
import McpServers from "./McpServers";
import SavedCandidates from "./SavedCandidates";

export default function Capabilities() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<"tools" | "skills" | "mcps" | "saved">("mcps");
  const [mcpPrefill, setMcpPrefill] = useState<McpPrefill | null>(null);
  return (
    <div className="p-6 max-w-5xl mx-auto w-full overflow-y-auto">
      <h2 className="text-sm font-bold font-mono uppercase tracking-widest text-foreground mb-1">
        {t("capabilities.title")}
      </h2>
      <p className="text-[11px] text-subtle-foreground font-sans mb-6">{t("capabilities.subtitle")}</p>
      {/* Shared Discover area (Tool-Hub) — stays fixed above the scrollable tab content. */}
      <ToolHubDiscover onPrefillMcp={(p) => { setMcpPrefill(p); setTab("mcps"); }} />
      <CapabilityTabs
        active={tab}
        onChange={(id) => setTab(id as "tools" | "skills" | "mcps" | "saved")}
        tabs={[
          { id: "tools", label: t("capabilities.tabs.tools") },
          { id: "skills", label: t("capabilities.tabs.skills") },
          { id: "mcps", label: t("capabilities.tabs.mcps") },
          { id: "saved", label: t("capabilities.tabs.saved") },
        ]}
      />
      {/* Tab panels — only the content scrolls; title/Discover/tab-strip stay fixed above. */}
      <div className="max-h-[62vh] overflow-y-auto pr-1">
        {tab === "tools" && <CapabilityCatalog kind="tools" />}
        {tab === "skills" && <CapabilityCatalog kind="skills" />}
        {tab === "mcps" && <McpServers prefill={mcpPrefill ?? undefined} />}
        {tab === "saved" && <SavedCandidates onPrefillMcp={(p) => { setMcpPrefill(p); setTab("mcps"); }} />}
      </div>
    </div>
  );
}
