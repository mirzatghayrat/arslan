import { useState } from "react";
import { useTranslation } from "react-i18next";
import CapabilityTabs from "./CapabilityTabs";

export default function Capabilities() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<"tools" | "skills" | "mcps">("mcps");
  return (
    <div className="p-6 max-w-5xl mx-auto w-full overflow-y-auto">
      <h2 className="text-sm font-bold font-mono uppercase tracking-widest text-foreground mb-1">
        {t("capabilities.title")}
      </h2>
      <p className="text-[11px] text-subtle-foreground font-sans mb-6">{t("capabilities.subtitle")}</p>
      {/* Discover (Task 2) mounts here */}
      <CapabilityTabs
        active={tab}
        onChange={(id) => setTab(id as "tools" | "skills" | "mcps")}
        tabs={[
          { id: "tools", label: t("capabilities.tabs.tools") },
          { id: "skills", label: t("capabilities.tabs.skills") },
          { id: "mcps", label: t("capabilities.tabs.mcps") },
        ]}
      />
      {/* Tab panels (Tasks 3/4) */}
      {tab === "tools" && <div className="text-xs text-subtle-foreground">…</div>}
      {tab === "skills" && <div className="text-xs text-subtle-foreground">…</div>}
      {tab === "mcps" && <div className="text-xs text-subtle-foreground">…</div>}
    </div>
  );
}
