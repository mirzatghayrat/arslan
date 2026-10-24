import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { useSettingsStore } from "../stores/settingsStore";
import { Button, Dialog } from "./kit";

/**
 * R63 (the user's decision, 10-24): someone migration 0070 switched from "Ask only for risky commands" to "Ask before
 * every command" is told once, after the upgrade: that they were switched, why (v0.1.63's known issue), and how to
 * switch back. The server sets `shell_policy_switch_notice = "pending"`; the first time the window sees it, the notice
 * opens and "seen" is written at once, so it never opens again, whether or not it is dismissed.
 * DELETE-BY: v0.1.64, with migration 0070's notice, when S2a-3 and #406 land (then its text is no longer true).
 */
export default function ShellPolicySwitchNotice() {
  const { t } = useTranslation();
  const flag = useSettingsStore((s) => s.settings?.shell_policy_switch_notice);
  const [open, setOpen] = useState(false);
  const shown = useRef(false);

  useEffect(() => {
    if (flag !== "pending" || shown.current) return;
    shown.current = true;
    setOpen(true);
    void api.updateSettings({ shell_policy_switch_notice: "seen" }).then(() => {
      const store = useSettingsStore.getState();
      if (store.settings) store.setSettings({ ...store.settings, shell_policy_switch_notice: "seen" });
    }).catch(() => { /* shown this session; at worst it shows once more next start */ });
  }, [flag]);

  if (!open) return null;
  return (
    <Dialog open onClose={() => setOpen(false)} width={460} testId="shell-policy-switch-notice"
      title={t("settings.policyNoticeTitle")}>
      <div className="flex flex-col gap-4 px-5 pb-4 pt-2">
        <p className="text-[14px] leading-normal text-muted-foreground" data-testid="shell-policy-switch-notice-body">
          {t("settings.policyNoticeBody")}
        </p>
        <div className="flex justify-end">
          <Button tone="primary" onClick={() => setOpen(false)} data-testid="shell-policy-switch-notice-ok">
            {t("settings.policyNoticeOk")}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
