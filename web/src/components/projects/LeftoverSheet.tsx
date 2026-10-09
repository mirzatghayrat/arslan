import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { Leftover } from "../../api/projects";
import { Button, Dialog } from "../kit";

/**
 * 0.1.58 §5 "提前过关…": a level is cleared with checkpoints still open only after you say
 * what happens to them — moved first into the next level (the default) or dropped from the
 * plan. Like Jira's "Complete sprint", nothing unfinished silently counts as done. On the
 * last level there is no next one, so only dropping is offered.
 */
export default function LeftoverSheet({ level, next, open, busy, onCancel, onConfirm }: {
  level: string; next: string | null; open: { id: string; text: string }[]; busy?: boolean;
  onCancel: () => void; onConfirm: (leftover: Leftover, note: string) => void;
}) {
  const { t } = useTranslation();
  const [choice, setChoice] = useState<Leftover>(next ? "move" : "drop");
  const [note, setNote] = useState("");
  const options: { key: Leftover; title: string; hint: string }[] = [
    ...(next ? [{ key: "move" as const, title: t("projectsUI.leftMove", { next }), hint: t("projectsUI.leftMoveHint") }] : []),
    { key: "drop", title: t("projectsUI.leftDrop"), hint: t("projectsUI.leftDropHint") },
  ];
  return (
    <Dialog open onClose={onCancel} width={460} testId="leftover-sheet" title={t("projectsUI.leftTitle", { level })}
      onSubmit={() => onConfirm(choice, note)}
      footer={<div className="flex justify-end gap-2">
        <Button onClick={onCancel} data-testid="leftover-cancel">{t("projectsUI.leftCancel")}</Button>
        <Button tone="primary" disabled={busy} onClick={() => onConfirm(choice, note)} data-testid="leftover-confirm">
          {t("projectsUI.leftConfirm")}</Button>
      </div>}>
      <div className="flex flex-col gap-3 text-[13px]">
        <p className="text-muted-foreground">{t("projectsUI.leftBody", { count: open.length })}</p>
        <ul className="-mt-1 overflow-hidden rounded-lg border border-border" data-testid="leftover-open">
          {open.map((cp) => <li key={cp.id} className="border-t border-border px-3 py-2 first:border-t-0">{cp.text}</li>)}
        </ul>
        <div role="radiogroup" className="flex flex-col gap-2">
          {options.map((o) => (
            <label key={o.key} data-testid={`leftover-${o.key}`}
              className={`flex cursor-pointer gap-2.5 rounded-lg px-3 py-2.5 ${choice === o.key ? "bg-info-soft" : "border border-border"}`}>
              <input type="radio" name="leftover" className="mt-0.5" checked={choice === o.key} onChange={() => setChoice(o.key)} />
              <span className="flex flex-col gap-0.5"><span className="font-semibold">{o.title}</span>
                <span className="text-[12px] text-muted-foreground">{o.hint}</span></span>
            </label>
          ))}
        </div>
        <label className="flex flex-col gap-1">
          <span className="text-[12.5px] text-muted-foreground">{t("projectsUI.leftNote")}</span>
          <input value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} data-testid="leftover-note"
            className="rounded-lg border border-border bg-background px-2.5 py-1.5 text-[13px]" />
        </label>
      </div>
    </Dialog>
  );
}
