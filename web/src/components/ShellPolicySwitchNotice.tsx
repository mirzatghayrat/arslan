import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { useSettingsStore } from "../stores/settingsStore";
import { Button, Dialog } from "./kit";

/**
 * ASK1-a (v0.1.64; the user, 2026-11-07): "Ask only for risky commands" is the default again. An existing install
 * whose stored policy isn't ask_risky is told once how it now asks and how to switch: migration 0095 sets
 * `shell_policy_switch_notice = "pending"`. The text follows the default mode as the server reads it (S5a: the
 * settings API sends that): ask_risky (an unset policy, moved) or ask (a stored ask_all, kept). Plan or full access
 * can't be what 0095 left, only the user's own choice since, so then nothing shows and the note is marked seen.
 * The first time the window sees "pending", the note opens and "seen" is written at once, so it never opens again,
 * whether or not it is dismissed. DELETE-BY: v0.1.65, with the note's settings key.
 */
export default function ShellPolicySwitchNotice() {
  const { t } = useTranslation();
  const flag = useSettingsStore((s) => s.settings?.shell_policy_switch_notice);
  const mode = useSettingsStore((s) => s.settings?.default_permission_mode);
  const risky = mode === "ask_risky";
  const title = risky ? t("settings.policyNoticeRiskyTitle") : t("settings.policyNoticeAllTitle");
  const body = risky ? t("settings.policyNoticeRiskyBody") : t("settings.policyNoticeAllBody");
  const [open, setOpen] = useState(false);
  const shown = useRef(false);

  useEffect(() => {
    if (flag !== "pending" || shown.current) return;
    shown.current = true;
    setOpen(mode === "ask_risky" || mode === "ask");
    void api.updateSettings({ shell_policy_switch_notice: "seen" }).then(() => {
      const store = useSettingsStore.getState();
      if (store.settings) store.setSettings({ ...store.settings, shell_policy_switch_notice: "seen" });
    }).catch(() => { /* shown this session; at worst it shows once more next start */ });
  }, [flag, mode]);

  if (!open) return null;
  return (
    <Dialog open onClose={() => setOpen(false)} width={460} testId="shell-policy-switch-notice"
      title={title}>
      <div className="flex flex-col gap-4 px-5 pb-4 pt-2">
        <p className="text-[14px] leading-normal text-muted-foreground" data-testid="shell-policy-switch-notice-body">
          {body}
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
