import { useState } from "react";
import { useTranslation } from "react-i18next";
import { ApiError } from "../api/client";
import { lessonsApi } from "../api/lessons";
import { useWorkbench } from "../stores/workbenchStore";
import { isolate } from "./CapabilitySwitches";

type State = "offered" | "added" | "skipped" | "removed" | "kept" | "failed" | "full" | "changed";

/**
 * L11-2 (the user's L11-0 picks, 2026-10-31): after the same correction twice, "Make this a rule for this folder?".
 * "Add" (the user's click) appends the lesson to the folder's AGENTS.md (or the CLAUDE.md it has); "Not now" says no
 * once; "Remove" takes the line back out. The lesson's words are the user's own correction, shown as they are.
 */
export default function RuleOfferCard({ lessonId, file, text, conversationId }: {
  lessonId: number; file: string; text: string; conversationId: string;
}) {
  const { t } = useTranslation();
  const openReader = useWorkbench((s) => s.openReader);
  const [state, setState] = useState<State>("offered");
  const [busy, setBusy] = useState(false);
  async function act(action: "add" | "skip" | "remove") {
    setBusy(true);
    try {
      const r = await lessonsApi.rule(lessonId, conversationId, action);
      setState(r.in_file === false ? "kept" : r.state as State);     // #621 re-check, R2
    } catch (err) {
      const code = err instanceof ApiError ? (err.detail as { detail?: string } | string | undefined) : undefined;
      const text = typeof code === "string" ? code : code?.detail ?? (err instanceof Error ? err.message : "");
      setState(text.includes("rules_file_full") ? "full" : text.includes("lesson_changed") ? "changed" : "failed");
    }
    finally { setBusy(false); }
  }
  const line = "py-0.5 text-[12px] text-muted-foreground";
  const link = "ml-2 underline underline-offset-2 hover:text-foreground disabled:opacity-50";
  if (state === "added") {
    return <p className={line} data-testid="rule-offer-added">
      <span className="text-success">✓</span> {t("workbench.ruleAdded")}
      <button type="button" className={link} onClick={() => openReader({ kind: "path", path: file })}>
        {t("workbench.ruleOpen", { file: file.split("/").pop() })}</button>
      <button type="button" className={link} disabled={busy} onClick={() => void act("remove")} data-testid="rule-offer-remove">
        {t("workbench.ruleRemove")}</button>
    </p>;
  }
  if (state === "skipped" || state === "removed" || state === "kept") {
    return <p className={line} data-testid={`rule-offer-${state}`}>{t(state === "skipped" ? "workbench.ruleSkipped"
      : state === "kept" ? "workbench.ruleNotInFile" : "workbench.ruleRemoved")}</p>;
  }
  return (
    <div role="group" aria-label={t("workbench.ruleTitle")} data-testid="rule-offer"
      className="my-1 w-full max-w-[520px] rounded-xl border border-border-strong bg-surface px-3.5 py-3">
      <div className="text-[13px] font-semibold">{t("workbench.ruleTitle")}</div>
      <p className="mt-0.5 text-[12px] text-muted-foreground">{t("workbench.ruleWhy")}</p>
      <p className="mt-2 rounded-lg bg-fill px-2.5 py-1.5 text-[12.5px]">{isolate(text)}</p>
      <p className="mt-1.5 break-all font-mono text-[11.5px] text-subtle-foreground">{isolate(file)}</p>
      {(state === "failed" || state === "full" || state === "changed") && <p className="mt-1.5 text-[12px] text-danger"
        data-testid={`rule-offer-${state}`}>{t(state === "full" ? "workbench.ruleFull" : state === "changed" ? "workbench.ruleChanged"
          : "workbench.ruleFailed")}</p>}
      <div className="mt-2.5 flex flex-wrap gap-2">
        {state !== "changed" && <button type="button" disabled={busy} onClick={() => void act("add")} data-testid="rule-offer-add"
          className="rounded-lg bg-foreground px-3 py-1.5 text-[12.5px] text-background disabled:opacity-50">{t("workbench.ruleAdd")}</button>}
        <button type="button" disabled={busy} onClick={() => void act("skip")} data-testid="rule-offer-skip"
          className="rounded-lg border border-border-strong px-3 py-1.5 text-[12.5px] disabled:opacity-50">{t("workbench.ruleNotNow")}</button>
      </div>
    </div>
  );
}
