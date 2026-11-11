import { useTranslation } from "react-i18next";
import { Row } from "./CapabilityProposeCard";

/** The events a hook may fire on and still come in (server/services/plugin_package.py, QUIET_HOOK_EVENTS). A key is
 *  built only from this list, never from what the server sent. */
const QUIET = new Set(["SessionStart", "Setup", "PermissionDenied", "PostToolUse", "PostToolUseFailure", "Notification",
  "MessageDisplay", "SubagentStart", "StopFailure", "InstructionsLoaded", "CwdChanged", "DirectoryAdded", "FileChanged",
  "PostCompact", "PostModelSwitch", "SessionEnd"]);

/**
 * CAP8-2's Hooks row (board 7), by the user's hook rule: how many hooks there are, when each fires, and that Arslan
 * doesn't run them, so what depends on them may not work. One per hook in `hooks` (its event); nothing when empty.
 * The plugin card, CAP4's skill card and CAP6a's folder card all show it.
 */
export function HooksRow({ hooks, kind }: { hooks?: string[]; kind: "plugin" | "skill" }) {
  const { t } = useTranslation();
  if (!hooks?.length) return null;
  const events = [...new Set(hooks)].map(event => QUIET.has(event)
    ? t("capabilityList.hookEvent", { event, when: t(`capabilityList.hookWhen_${event}`) }) : event)
    .join(t("capabilityList.hookJoin"));
  return <Row label={t("capabilityList.hooksRow")}>
    <span data-testid="import-card-hooks" className="flex flex-col gap-0.5">
      <span>{t("capabilityList.import_cardHooks", { count: hooks.length, events })}</span>
      <span className="text-[12px] text-warning">
        {t(kind === "skill" ? "capabilityList.hooksWarnSkill" : "capabilityList.import_cardHooksWarn")}</span>
    </span>
  </Row>;
}
