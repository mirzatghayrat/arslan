import { useTranslation } from "react-i18next";
import type { CapabilityResult } from "../../api/client.types";

/** Why a plugin was refused, by its code (plugin_package.Refused), where one line says it better than the code. */
const REFUSED: Record<string, string> = {
  hooks: "hooks", commands: "commands", agents: "agents", lsp: "lsp", other: "other", cannot_pin: "cannot_pin",
  runs_from_source: "cannot_pin", add_by_hand: "add_by_hand", unsafe_setting: "unsafe_setting",
  needs_plugin_folder: "needs_plugin_folder", moved: "moved", not_a_plugin: "not_a_plugin",
};

/** One quiet line where an approved install ended (0.1.57): on and tested, waiting for sign-in, stopped, or removed by
 *  the scan. CAP7b (board Refused): a plugin that can't be added gets no card, only this line, plain and red, naming
 *  what isn't supported and that nothing was installed. */
export default function CapabilityResultLine({ result }: { result: CapabilityResult }) {
  const { t } = useTranslation();
  const tone = result.state === "on" ? "text-success" : result.state === "needs_sign_in" || result.state === "stopped"
    ? "text-ask" : "text-danger-strong";
  const refused = REFUSED[result.code ?? ""];
  return (
    <p data-testid="capability-result" data-state={result.state} className={`px-1 text-[12.5px] ${tone}`}>
      {result.state === "on" ? t("discover.result_on", { name: result.name, count: result.tools })
        : result.state === "needs_sign_in" ? t("discover.result_signIn", { name: result.name })
        : result.state === "blocked" ? t("discover.result_blocked", { name: result.name })
        : result.state === "stopped" ? t("discover.result_stopped", { name: result.name })
        : result.state === "refused" ? t(refused ? `discover.result_refused_${refused}` : "discover.result_refused", {
          name: result.name, part: result.detail ?? "", code: result.code ?? "" })
        : t("discover.result_failed", { name: result.name, stage: result.stage ?? "", detail: result.detail ?? result.code ?? "" })}
    </p>
  );
}
