import { useTranslation } from "react-i18next";
import type { TaskWorker } from "../../api/tasks";
import { buttonClass } from "./CompanionDialog";
import { taskErrorKey } from "./errors";

export default function TaskWorkers({ workers, onOpenRun }: { workers: TaskWorker[]; onOpenRun: (id: number) => void }) {
  const { t } = useTranslation();
  if (!workers.length) return null;
  function remaining(value: string) {
    const key = taskErrorKey(value);
    if (key) return t(key);
    return /^[a-z]+(?:_[a-z]+)+$/.test(value) ? t("methods.blockedHint") : value;
  }
  return <details className="rounded-lg border border-border p-3">
    <summary className="cursor-pointer font-medium">{t("methods.collaboration", { count: workers.length })}</summary>
    <p className="my-3 text-xs text-muted-foreground">{t("methods.workerHint")}</p>
    <div className="space-y-3">{workers.map(worker => <article key={worker.id} className="space-y-2 rounded-lg bg-foreground/5 p-3">
      <p className="text-xs text-muted-foreground">{t(`methods.${worker.method}`)} · {t("methods.version", { number: worker.method_revision })}</p>
      <p className="break-words text-sm font-medium">{worker.objective}</p>
      <p className="text-xs">{t(`methods.${worker.status}`)}</p>
      {worker.result?.result && <p className="max-h-52 overflow-y-auto whitespace-pre-wrap break-words text-xs leading-relaxed">{worker.result.result}</p>}
      {!!worker.result?.remaining_work.length && <ul className="list-disc space-y-1 pl-4 text-xs text-muted-foreground">
        {worker.result.remaining_work.map((item, index) => <li key={index}>{remaining(item)}</li>)}
      </ul>}
      {worker.run_id !== null && <button className={buttonClass} onClick={() => onOpenRun(worker.run_id!)}>{t("methods.openResult")}</button>}
    </article>)}</div>
  </details>;
}
