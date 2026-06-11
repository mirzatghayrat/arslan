import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { EscalationInfo } from "../../types";

// Maps the orchestrator's `how` values (arslan.py emits exactly "granted",
// "data_provided", or "unresolved") to i18n keys.
function howKey(how: string | undefined): string {
  if (how === "unresolved") return "escalation.unresolved";
  if (how === "granted") return "escalation.granted";
  return "escalation.answered"; // "data_provided"
}

export default function EscalationBanner({ info }: { info: EscalationInfo }) {
  const { t } = useTranslation();
  const [showDetail, setShowDetail] = useState(false);
  const tone =
    info.status === "refused"
      ? "border-amber/50 bg-amber/10 text-amber"
      : info.status === "resolving"
        ? "border-purple-400/30 bg-purple-400/10 text-purple-100"
        : "border-white/15 bg-white/5 text-white/70";
  return (
    <div className={`mx-auto max-w-[85%] rounded-xl border px-4 py-2 text-xs ${tone}`}>
      <p>
        <span className="font-semibold">
          {t("escalation.needs", { name: info.spawnName ?? `#${info.spawnId}` })}
        </span>{" "}
        <span className="rounded-full border border-white/20 px-1.5">
          {t(info.kind === "capability" ? "escalation.kind_capability" : "escalation.kind_data")}
        </span>{" "}
        <span className="italic">{info.need}</span>
      </p>
      {info.status === "resolving" && <p className="mt-1 animate-pulse">{t("escalation.resolving")}</p>}
      {info.status === "resolved" && (
        <p className="mt-1">
          {t(howKey(info.how))}
          {info.detail && (
            <button onClick={() => setShowDetail(!showDetail)} className="ml-2 underline" aria-expanded={showDetail}>
              {t("escalation.detail")}
            </button>
          )}
        </p>
      )}
      {info.status === "refused" && (
        <p className="mt-1 font-medium">{t("escalation.refused", { why: info.why ?? "" })}</p>
      )}
      {showDetail && info.detail && <p className="mt-1 text-white/60">{info.detail}</p>}
    </div>
  );
}
