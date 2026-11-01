import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { CalendarClock, FolderKanban, MessageSquare } from "lucide-react";
import { api } from "../../api/client";
import type { WaitingView } from "../../hooks/useWaiting";
import { openSection } from "../../lib/sections";

/** What the page needs to name and open what waits on you: the conversations and projects the app already holds, and how it opens
 *  each. A scheduled task opens on the Scheduled page. */
export interface NeedsProps {
  waiting: WaitingView;
  threads?: { id: string; title: string }[];
  projects?: { id: string; name: string }[];
  onOpenConversation?: (id: string) => void;
  onOpenProject?: (id: string) => void;
}

type Row = { key: string; name: string; kind: "conversation" | "project" | "task"; open: () => void };
const ICON = { conversation: MessageSquare, project: FolderKanban, task: CalendarClock } as const;
const KIND_WORD = { conversation: "activityPage.needsConversation", project: "activityPage.needsProject", task: "activityPage.needsTask" } as const;
const UNNAMED = { conversation: "activityPage.needsAConversation", project: "activityPage.needsAProject", task: "activityPage.needsATask" } as const;

/**
 * INB7-c5, board F: while no run is picked, the inspector shows what waits on you, the same units the badge counts (a
 * conversation, a project, a scheduled task), each by name with what it is and a way to open it where it waits. One it cannot find
 * is named by what it is, never by its id. Why each one waits joins its row with #614's reasons; the board's per-row verbs
 * (approve, carry on) stay with the card where it waits, whose answers the hold guards.
 */
export default function NeedsPanel({ waiting, threads = [], projects = [], onOpenConversation, onOpenProject }: NeedsProps) {
  const { t } = useTranslation();
  const tasks = useTaskNames([...waiting.scheduled].sort((a, b) => a - b).join(","));
  const rows: Row[] = [
    ...waiting.conversations.map((id): Row => ({ key: `c-${id}`, kind: "conversation", name: threads.find((x) => x.id === id)?.title ?? "",
      open: () => onOpenConversation?.(id) })),
    ...waiting.projects.map((id): Row => ({ key: `p-${id}`, kind: "project", name: projects.find((x) => x.id === id)?.name ?? "",
      open: () => onOpenProject?.(id) })),
    ...waiting.scheduled.map((id): Row => ({ key: `s-${id}`, kind: "task", name: tasks[id] ?? "", open: () => openSection("scheduled") })),
  ];
  // As the tile does: the warning look only while something waits.
  const asking = waiting.loaded && waiting.count > 0;
  return (
    <section data-testid="needs-panel" data-asking={String(asking)}
      className={`rounded-lg border px-3 py-2.5 ${asking ? "border-warning/30 bg-ask-soft" : "border-border bg-surface/60"}`}>
      <div className="flex items-baseline gap-2">
        <span className="text-[12.5px] font-medium text-foreground">{t("activityPage.kpiNeeds")}</span>
        {waiting.loaded && <span data-testid="needs-count" className={`font-mono text-[12.5px] font-semibold tabular-nums ${asking ? "text-warning" : "text-muted-foreground"}`}>{waiting.count}</span>}
      </div>
      {waiting.loaded && !rows.length && <p className="mt-1.5 text-[12px] font-medium text-success">✓ {t("activityPage.needsNone")}</p>}
      <ul className="mt-1.5 space-y-0.5">
        {rows.map((row) => {
          const Icon = ICON[row.kind];
          return (
            <li key={row.key} data-testid={`needs-row-${row.key}`} className="flex min-h-[38px] items-center gap-2">
              <Icon size={13} aria-hidden className="shrink-0 text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-[12.5px] text-foreground">{row.name || t(UNNAMED[row.kind])}</div>
                <div className="text-[11px] text-muted-foreground">{t(KIND_WORD[row.kind])}</div>
              </div>
              <button type="button" onClick={row.open}
                aria-label={`${t("activityPage.needsOpen")}: ${row.name || t(UNNAMED[row.kind])}`}
                className="shrink-0 rounded-md bg-foreground px-2.5 py-1 text-[11.5px] text-background hover:opacity-90">
                {t("activityPage.needsOpen")}</button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** The scheduled tasks' names, read when the tasks that wait change (the page holds no list of them), keyed on their sorted ids so
 *  one that starts to wait is named too (#633 review, 1) and the same tasks in another order read nothing. A failed read leaves
 *  them unnamed. */
function useTaskNames(waitingIds: string): Record<number, string> {
  const [names, setNames] = useState<Record<number, string>>({});
  useEffect(() => {
    if (!waitingIds) return;
    let alive = true;
    api.listScheduledTasks().then((all) => { if (alive) setNames(Object.fromEntries(all.map((task) => [task.id, task.name]))); })
      .catch(() => { /* named by what it is */ });
    return () => { alive = false; };
  }, [waitingIds]);
  return names;
}
