import { useState } from "react";
import { useTranslation } from "react-i18next";
import { projectsApi, type PlanDiffLine, type PlanProposal } from "../../api/projects";
import { companionError } from "../companion/errors";
import { AskCard, Notice } from "../kit";

/** One line of the change: ＋ added, － removed, ～ changed (with the checkpoints it adds/removes). */
export function PlanDiffList({ diff, cleared }: { diff: PlanDiffLine[]; cleared: number }) {
  const { t } = useTranslation();
  return (
    <ul className="flex flex-col gap-1 text-[13px]" data-testid="plan-diff">
      {diff.map((line, i) => (
        <li key={i} className="flex gap-2">
          <span aria-hidden="true" className={`w-3 shrink-0 font-semibold ${line.op === "add" ? "text-success"
            : line.op === "remove" ? "text-destructive" : "text-muted-foreground"}`}>{line.op === "add" ? "+" : line.op === "remove" ? "−" : "~"}</span>
          <span>{line.op === "add" ? t("projectsUI.diffAdd", { level: line.level })
            : line.op === "remove" ? t("projectsUI.diffRemove", { level: line.level })
            : t("projectsUI.diffChange", { level: line.level, added: line.added.join(", ") || "—", removed: line.removed.join(", ") || "—" })}</span>
        </li>
      ))}
      {cleared > 0 && <li className="flex gap-2 text-muted-foreground"><span aria-hidden="true" className="w-3 shrink-0">=</span>
        {t("projectsUI.diffKept", { count: cleared })}</li>}
    </ul>
  );
}

/**
 * "计划要不要跟着改？" (0.1.56 §7, board Project-Replan): Arslan's changed plan, answered in
 * place — keep the old plan (esc) or take the new one (⌘⏎). Only levels not cleared change.
 */
export default function PlanProposalCard({ projectId, proposal, onDone }: {
  projectId: string; proposal: PlanProposal; onDone?: () => void;
}) {
  const { t } = useTranslation();
  const [state, setState] = useState<"open" | "busy" | "taken" | "kept">("open");
  const [error, setError] = useState<string | null>(null);
  async function answer(accept: boolean) {
    setState("busy"); setError(null);
    try {
      await projectsApi.decidePlan(projectId, proposal.id, accept);
      setState(accept ? "taken" : "kept");
      onDone?.();
    } catch (cause) {
      setError(companionError(cause));
      setState("open");
    }
  }
  if (state === "taken" || state === "kept") {
    return <p className="px-1 text-[12.5px] text-muted-foreground" data-testid="plan-proposal-decided">
      {t(state === "taken" ? "projectsUI.planTaken" : "projectsUI.planKept")}</p>;
  }
  return (
    <div className="flex flex-col gap-2">
      <AskCard testId="plan-proposal" who={t("projectsUI.planAskWho")} title={t("projectsUI.planAskTitle")}
        said={proposal.reason || null} detail={<PlanDiffList diff={proposal.diff} cleared={proposal.cleared} />}
        allowLabel={t("projectsUI.planTake")} declineLabel={t("projectsUI.planKeep")}
        busy={state === "busy"} onAllow={() => void answer(true)} onDecline={() => void answer(false)}
        allowTestId="plan-proposal-take" declineTestId="plan-proposal-keep" />
      {error && <Notice tone="error">{t(error)}</Notice>}
    </div>
  );
}
