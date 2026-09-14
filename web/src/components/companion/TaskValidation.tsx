import { useTranslation } from "react-i18next";
import { FileCheck2 } from "lucide-react";
import type { TaskDetail } from "../../api/tasks";

export default function TaskValidation({ task }: { task: TaskDetail }) {
  const { t } = useTranslation();
  const report = task.validation ?? { checks: [], artifacts: [] };
  const status = (value: string) => t(`validation.${["passed", "failed", "not_run", "not_applicable", "unverified"].includes(value) ? value : "not_run"}`);
  return <section className="space-y-3 rounded-lg border border-border p-3" aria-label={t("validation.title")}>
    <h3 className="flex items-center gap-2 font-medium"><FileCheck2 size={16} />{t("validation.title")}</h3>
    <p className="text-xs leading-relaxed text-muted-foreground">{t("validation.intro")}</p>
    {task.spec.acceptance.map(check => {
      const result = task.state.results.find(item => item.check_id === check.id);
      return <div key={check.id} className="space-y-1 text-xs">
        <p className="break-words">{check.description}</p>
        <p className={result?.status === "failed" ? "text-destructive" : "text-muted-foreground"}>
          {t(`validation.${check.evaluator}`)} · {status(result?.status ?? "not_run")}
        </p>
      </div>;
    })}
    {!!report.artifacts.length && <div className="space-y-2 border-t border-border pt-3">
      <h4 className="text-xs font-medium">{t("validation.artifacts")}</h4>
      {report.artifacts.map(artifact => <div key={artifact.id} className="space-y-1 text-xs">
        <p className="break-all">{artifact.title || artifact.filename || t("validation.unknownFile")}</p>
        <p className={artifact.status === "failed" ? "text-destructive" : "text-muted-foreground"}>
          {artifact.code === "artifact_superseded" ? t("validation.superseded") : status(artifact.status)}
        </p>
      </div>)}
    </div>}
    {!!(report.checks.length + report.artifacts.length) && <details className="text-xs text-muted-foreground"><summary className="cursor-pointer">{t("validation.details")}</summary>
      <ul className="mt-2 space-y-1">{[...report.checks, ...report.artifacts].map((item, index) =>
        <li className="break-all font-mono text-[10px]" key={index}>{item.code}</li>)}</ul>
      {report.artifacts.map(artifact => <p key={artifact.id} className="mt-1 break-all font-mono text-[10px]">{artifact.id}</p>)}
    </details>}
  </section>;
}
