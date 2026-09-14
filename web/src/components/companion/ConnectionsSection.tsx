import { useEffect, useState } from "react";
import { Plug, Settings2, ShieldCheck } from "lucide-react";
import { useTranslation } from "react-i18next";
import McpServers from "../McpServers";
import RecommendedMcp from "../RecommendedMcp";
import type { McpPrefill } from "../ToolHubDiscover";
import { request } from "../../api/client";
import type { SettingsSectionId } from "../settings/sectionRegistry";
import ToolTransportWarning from "../settings/ToolTransportWarning";

export default function ConnectionsSection({ prefill, onOpenSettings, provider }: {
  prefill?: McpPrefill; onOpenSettings: (section: SettingsSectionId) => void; provider?: string;
}) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState(prefill);
  const [refresh, setRefresh] = useState(0);
  const [catalog, setCatalog] = useState(false);
  const [ascKnown, setAscKnown] = useState(false);
  useEffect(() => { setDraft(prefill); }, [prefill]);
  useEffect(() => {
    let alive = true;
    request<{ local: { read_account: boolean; write_draft: boolean; submit_review: boolean; publish: boolean } }>("/connections/app-store-connect/capabilities")
      .then(value => { if (alive) setAscKnown(value.local?.read_account === false && value.local?.write_draft === false && value.local?.submit_review === false && value.local?.publish === false); })
      .catch(() => { if (alive) setAscKnown(false); });
    return () => { alive = false; };
  }, []);
  return <div className="h-full overflow-y-auto p-5 lg:p-8"><div className="mx-auto max-w-5xl space-y-6">
    <header><h1 className="flex items-center gap-2 text-xl font-semibold"><Plug size={20} />{t("workspace.connections")}</h1>
      <p className="mt-2 max-w-3xl text-sm text-muted-foreground">{t("workspace.connectionsHint")}</p></header>
    <div className="flex flex-wrap gap-3">
      <button className="inline-flex items-center gap-2 rounded-lg border border-border px-4 py-2 text-sm" onClick={() => onOpenSettings("models")}><Settings2 size={16} />{t("settings.navModels")}</button>
      <button className="inline-flex items-center gap-2 rounded-lg border border-border px-4 py-2 text-sm" onClick={() => onOpenSettings("access")}><ShieldCheck size={16} />{t("settings.navAccess")}</button>
    </div>
    <section className="rounded-xl border border-border p-4"><h2 className="font-semibold">App Store Connect</h2>
      <p className="mt-2 text-sm text-muted-foreground">{t(ascKnown ? "companion.ascDisabled" : "workspace.connectionStatusUnknown")}</p>
    </section>
    <section className="space-y-4"><div className="flex flex-wrap items-center justify-between gap-3"><h2 className="font-semibold">{t("workspace.toolConnections")}</h2>
      <button className="text-sm text-primary underline" aria-expanded={catalog} onClick={() => setCatalog(value => !value)}>{t("capabilities.sections.recommended_mcp")}</button></div>
      {provider && <ToolTransportWarning provider={provider} showProviderName />}
      {catalog && <RecommendedMcp onPrefillMcp={value => { setDraft(value); setCatalog(false); }} onChanged={() => setRefresh(value => value + 1)} />}
      <McpServers key={refresh} prefill={draft} />
    </section>
  </div></div>;
}
