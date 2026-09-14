import { useEffect, useState } from "react";
import { ClipboardList, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { tasksApi, type TaskSummary } from "../../api/tasks";
import { useArslanStore } from "../../stores/arslanStore";

export default function OngoingTasks({ onOpen }: { onOpen: (task: TaskSummary) => void }) {
  const { t } = useTranslation();
  const frame = useArslanStore(state => state.taskState);
  const [rows, setRows] = useState<TaskSummary[]>([]);
  const [error, setError] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [more, setMore] = useState(false);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let alive = true;
    const load = () => tasksApi.active().then(items => {
      if (!alive) return;
      setRows(items.filter(item => ["queued", "running", "waiting_user", "verifying"].includes(item.state.phase))); setMore(items.length === 20); setError(false);
    }).catch(() => { if (alive) setError(true); }).finally(() => { if (alive) setLoading(false); });
    void load();
    const timer = setInterval(() => { if (document.visibilityState !== "hidden") void load(); }, 15000);
    return () => { alive = false; clearInterval(timer); };
  }, [frame?.task_id, frame?.sequence, refresh]);
  async function loadMore() {
    try {
      const items = await tasksApi.active(rows.length);
      setRows(old => [...old, ...items.filter(item => ["queued", "running", "waiting_user", "verifying"].includes(item.state.phase) && !old.some(row => row.spec.id === item.spec.id))]);
      setMore(items.length === 20); setError(false);
    } catch { setError(true); }
  }
  return <section aria-label={t("workspace.ongoing")} className="px-3 py-2">
    <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
      <span>{t("workspace.ongoing")}</span><button aria-label={t("companion.refresh")} onClick={() => setRefresh(value => value + 1)}><RefreshCw size={12} /></button>
    </div>
    {error && <p role="status" className="mt-2 text-xs text-muted-foreground">{t("workspace.taskListUnavailable")}</p>}
    {rows.length > 0 && <div className="mt-2 max-h-36 space-y-1 overflow-y-auto">{rows.map(task => <button key={task.spec.id}
      onClick={() => onOpen(task)} className="flex w-full items-start gap-2 rounded px-1 py-2 text-left text-xs hover:bg-primary/5">
      <ClipboardList size={14} className="mt-0.5 shrink-0 text-primary" /><span className="min-w-0"><span className="block truncate">{task.spec.instruction}</span>
        <span className="text-[10px] text-muted-foreground">{t(`tasks.${task.state.phase}`)}</span></span>
    </button>)}</div>}
    {loading && <p role="status" className="mt-1 text-[10px] text-muted-foreground">{t("companion.loading")}</p>}
    {!loading && !error && rows.length === 0 && <p className="mt-1 text-[10px] text-muted-foreground">{t("workspace.noOngoing")}</p>}
    {more && <button className="mt-2 text-xs text-primary" onClick={() => void loadMore()}>{t("companion.loadMore")}</button>}
  </section>;
}
