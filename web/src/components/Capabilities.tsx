import { type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import CapabilityCatalog from "./CapabilityCatalog";
import ToolTransportWarning from "./settings/ToolTransportWarning";
import CapabilitySwitches from "./CapabilitySwitches";

// The Capabilities page. v0.1.64 CAP3a: one list, built in / skills / connections, no tabs (the mock the user
// approved). Connections are added by hand from the connections section, skills by pasting a link, and anything
// new is asked for in a conversation (CAP1a removed Discover; CAP2a the "Create skill" page). The professional
// methods are rows among the skills. Legacy experts, when there are any, keep their own section below, with the
// skill catalog that equips them.
/** The provider whose transport decides whether ANY of this page's equipping
 *  will have an effect. Passed in rather than fetched here: App already holds
 *  the configs, and a second fetch would give this page its own opinion of which
 *  provider is primary. */
export default function Capabilities({ provider, experts }: { provider?: string | null; experts?: ReactNode } = {}) {
  const { t } = useTranslation();
  return (
    <div className="w-full h-full overflow-y-auto">
      <div className="px-6 lg:px-10 pt-6 pb-10 max-w-[1400px] mx-auto w-full">
        {/* ABOVE the list, deliberately. The failure it describes has no symptom anywhere:
            equip a toolset, connect an MCP server, tick "Allow Arslan", and every surface reads
            as installed while the model is never told any of it exists. The warning belongs
            where the equipping happens, not only in Settings, because the person who chose a
            provider three months ago is not going to open Settings before ticking a box here.

            `provider` absent (no provider configured yet) renders nothing:
            first-run has its own path, and telling someone their unset provider
            is unmeasured would be noise dressed as a safety notice. */}
        {provider ? (
          <div className="mb-4">
            <ToolTransportWarning provider={provider} showProviderName />
          </div>
        ) : null}
        <CapabilitySwitches />
        {experts && <section data-testid="legacy-experts" className="mt-10 flex flex-col gap-4">
          <h2 className="text-[12px] font-semibold text-muted-foreground">{t("workspace.legacyExperts")}</h2>
          {experts}
          <CapabilityCatalog assign />
        </section>}
      </div>
    </div>
  );
}
