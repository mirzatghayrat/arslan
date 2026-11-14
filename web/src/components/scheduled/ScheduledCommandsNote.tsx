import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../../api/client";
import { useSettingsStore } from "../../stores/settingsStore";
import { Notice } from "../kit";

/**
 * ASK1-b (v0.1.64; the user, 2026-11-07): a scheduled task's own run may now run commands inside the sandbox, and
 * anything that would ask is refused and listed. An existing install is told once, on the Scheduled page: migration
 * 0097 sets `scheduled_commands_note = "pending"`. As ASK1-a's note does, the first time the page sees "pending" the
 * note shows and "seen" is written at once, so it never shows again, whether or not it is closed.
 * DELETE-BY: v0.1.65, with the note's settings key.
 */
export default function ScheduledCommandsNote() {
  const { t } = useTranslation();
  const flag = useSettingsStore((s) => s.settings?.scheduled_commands_note);
  const [open, setOpen] = useState(false);
  const shown = useRef(false);

  useEffect(() => {
    if (flag !== "pending" || shown.current) return;
    shown.current = true;
    setOpen(true);
    void api.updateSettings({ scheduled_commands_note: "seen" }).then(() => {
      const store = useSettingsStore.getState();
      if (store.settings) store.setSettings({ ...store.settings, scheduled_commands_note: "seen" });
    }).catch(() => { /* shown this session; at worst it shows once more next start */ });
  }, [flag]);

  if (!open) return null;
  return (
    <Notice testId="scheduled-commands-note" title={t("scheduledPage.commandsNoteTitle")}
      action={<button className="text-[13px] underline" data-testid="scheduled-commands-note-ok"
        onClick={() => setOpen(false)}>{t("scheduledPage.commandsNoteOk")}</button>}>
      {t("scheduledPage.commandsNoteBody")}
    </Notice>
  );
}
