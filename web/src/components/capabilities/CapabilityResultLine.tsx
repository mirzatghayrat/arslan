import { useTranslation } from "react-i18next";
import type { CapabilityResult } from "../../api/client.types";

/** One quiet line where an approved install ended (0.1.57): on and tested, waiting for sign-in, stopped, or removed by the scan. */
export default function CapabilityResultLine({ result }: { result: CapabilityResult }) {
  const { t } = useTranslation();
  const tone = result.state === "on" ? "text-success" : result.state === "needs_sign_in" ? "text-ask" : "text-danger-strong";
  return (
    <p data-testid="capability-result" data-state={result.state} className={`px-1 text-[12.5px] ${tone}`}>
      {result.state === "on" ? t("discover.result_on", { name: result.name, count: result.tools })
        : result.state === "needs_sign_in" ? t("discover.result_signIn", { name: result.name })
        : result.state === "blocked" ? t("discover.result_blocked", { name: result.name })
        : t("discover.result_failed", { name: result.name, stage: result.stage ?? "", detail: result.detail ?? result.code ?? "" })}
    </p>
  );
}
