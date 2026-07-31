import { Fragment, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronRight, Plus, CalendarClock } from "lucide-react";
import { api, ApiError } from "../api/client";
import type {
  ScheduledTaskCreateBody,
  ScheduledTaskDto,
  ScheduledTaskRunDto,
  SpawnSummary,
} from "../api/client.types";
import Select from "./Select";
import EmptyState, { EmptyStateAction } from "./EmptyState";

/**
 * S3-M4 Diagnostics 定时任务卡 — list + create/edit form + execution history.
 * Follows the UsageCard section idiom (usage-card head + diag-table). History
 * rows link to RunReplay via onOpenRun (the same view-level overlay the
 * evolution inbox uses).
 *
 * Honesty rules mirrored from the backend:
 * - last_outcome == null means "no runs yet" OR "in flight" — render "—",
 *   never a status we don't actually know.
 * - paused_reason is non-null ONLY on the 3-fail auto-pause; the badge tooltip
 *   carries it. A manual pause shows the same badge without a tooltip.
 * - cron is interpreted in the user's LOCAL time on the server (review I5) —
 *   the cadence cell says so next to the raw expression.
 */

// ── cron mirror (loose; the server's parse_cron is the authority) ─────────────
const CRON_RANGES: Array<[number, number]> = [
  [0, 59], // minute
  [0, 23], // hour
  [1, 31], // day of month
  [1, 12], // month
  [0, 6], //  day of week
];

// Client-side mirror of server parse_cron: 5 fields, each `*` | `*/n` (n>0) |
// comma list of in-range numbers. Anything fancier is rejected here too.
export function cronLooksValid(expr: string): boolean {
  const fields = expr.trim().split(/\s+/).filter(Boolean);
  if (fields.length !== 5) return false;
  return fields.every((raw, i) => {
    const [lo, hi] = CRON_RANGES[i];
    if (raw === "*") return true;
    if (raw.startsWith("*/")) {
      const n = raw.slice(2);
      return /^\d+$/.test(n) && Number(n) > 0;
    }
    return raw
      .split(",")
      .every((p) => /^\d+$/.test(p) && Number(p) >= lo && Number(p) <= hi);
  });
}

// ── time helpers ───────────────────────────────────────────────────────────────
/** Backend datetimes are stored utc-naive and serialized without a zone suffix —
 *  read them as UTC (a bare `new Date(iso)` would parse them as LOCAL time). */
function parseUtc(iso: string): Date {
  return new Date(/[zZ]$|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
}

function fmtInterval(s: number): string {
  return s % 3600 === 0 ? `${s / 3600}h` : `${Math.round(s / 60)}m`;
}

function fmtWhen(iso: string | null): string {
  if (!iso) return "—";
  const d = parseUtc(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString(undefined, {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}

const INTERVAL_PRESETS = [
  { value: "900", label: "15m" },
  { value: "1800", label: "30m" },
  { value: "3600", label: "1h" },
  { value: "21600", label: "6h" },
  { value: "86400", label: "24h" },
];

const ACTION_BTN =
  "text-[11px] font-mono text-muted-foreground hover:text-foreground disabled:opacity-50 disabled:cursor-default transition-colors";
const INPUT_CLS =
  "w-full bg-background border border-border-strong rounded-xl px-3 py-2 text-xs font-sans text-foreground focus:outline-none focus:border-primary";

// ── outcome badge ──────────────────────────────────────────────────────────────
function OutcomeBadge({ task }: { task: ScheduledTaskDto }) {
  const { t } = useTranslation();
  if (!task.enabled) {
    return (
      <span
        className="sched-badge sched-badge--paused"
        data-testid="sched-badge"
        title={task.paused_reason ?? undefined}
      >
        {t("scheduled.outcome.paused")}
      </span>
    );
  }
  const o = task.last_outcome;
  if (o === "ok") {
    return <span className="sched-badge sched-badge--ok" data-testid="sched-badge">{t("scheduled.outcome.ok")}</span>;
  }
  if (o === "error") {
    return <span className="sched-badge sched-badge--error" data-testid="sched-badge">{t("scheduled.outcome.error")}</span>;
  }
  if (o === "skipped_overlap") {
    return <span className="sched-badge sched-badge--muted" data-testid="sched-badge">{t("scheduled.outcome.skipped")}</span>;
  }
  // null = no runs yet OR in flight — we honestly don't know; show "—".
  return <span className="sched-badge sched-badge--muted" data-testid="sched-badge">—</span>;
}

// ── create / edit form (inline panel) ──────────────────────────────────────────
function TaskForm({
  editing,
  onSaved,
  onCancel,
}: {
  editing: ScheduledTaskDto | null;
  onSaved: (task: ScheduledTaskDto, edited: boolean) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [spawns, setSpawns] = useState<SpawnSummary[]>([]);
  const [name, setName] = useState(editing?.name ?? "");
  const [prompt, setPrompt] = useState(editing?.prompt ?? "");
  const [spawnId, setSpawnId] = useState(editing?.spawn_id != null ? String(editing.spawn_id) : "");
  const [kind, setKind] = useState<"interval" | "cron">(editing?.schedule_kind === "cron" ? "cron" : "interval");
  const [intervalS, setIntervalS] = useState(editing?.interval_s != null ? String(editing.interval_s) : "3600");
  const [cron, setCron] = useState(editing?.cron ?? "");
  const [conversationId, setConversationId] = useState(editing?.conversation_id ?? "");
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api.listSpawns()
      .then((s) => { if (!cancelled) setSpawns(s); })
      .catch(() => { /* the select just stays empty */ });
    return () => { cancelled = true; };
  }, []);

  // Default to the first spawn once the list loads (create mode).
  useEffect(() => {
    if (!spawnId && spawns.length > 0) setSpawnId(String(spawns[0].id));
  }, [spawns, spawnId]);

  // Keep a non-preset interval (possible via API/edit) selectable.
  const intervalOptions = useMemo(() => {
    if (intervalS && !INTERVAL_PRESETS.some((p) => p.value === intervalS)) {
      return [{ value: intervalS, label: fmtInterval(Number(intervalS)) }, ...INTERVAL_PRESETS];
    }
    return INTERVAL_PRESETS;
  }, [intervalS]);

  const submit = async () => {
    const nm = name.trim();
    const pr = prompt.trim();
    if (!nm || !pr || !spawnId) {
      setFormError(t("scheduled.form.required"));
      return;
    }
    if (kind === "cron" && !cronLooksValid(cron)) {
      setFormError(t("scheduled.form.cron_invalid"));
      return;
    }
    const body: ScheduledTaskCreateBody = {
      name: nm,
      prompt: pr,
      spawn_id: Number(spawnId),
      schedule_kind: kind,
      interval_s: kind === "interval" ? Number(intervalS) : null,
      cron: kind === "cron" ? cron.trim() : null,
      conversation_id: conversationId.trim() || null,
    };
    setSaving(true);
    setFormError(null);
    try {
      const saved = editing
        ? await api.updateScheduledTask(editing.id, body)
        : await api.createScheduledTask(body);
      onSaved(saved, editing != null);
    } catch (e) {
      // Server 422/409 detail (interval floor, cron grammar, enabled cap) verbatim.
      setFormError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const kindBtn = (k: "interval" | "cron", label: string) => (
    <button
      type="button"
      role="radio"
      aria-checked={kind === k}
      data-testid={`sched-kind-${k}`}
      className={`diag-catalog__range-btn${kind === k ? " diag-catalog__range-btn--active" : ""}`}
      onClick={() => setKind(k)}
    >
      {label}
    </button>
  );

  return (
    <div className="sched-form" data-testid="sched-form">
      <div className="text-xs font-semibold text-foreground">
        {editing ? t("scheduled.form.edit_title") : t("scheduled.form.create_title")}
      </div>

      <label className="sched-form__row">
        <span className="sched-form__label">{t("scheduled.form.name")}</span>
        <input
          className={INPUT_CLS}
          data-testid="sched-form-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </label>

      <label className="sched-form__row">
        <span className="sched-form__label">{t("scheduled.form.prompt")}</span>
        <textarea
          className={`${INPUT_CLS} min-h-[64px] resize-y`}
          data-testid="sched-form-prompt"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
        />
      </label>

      <div className="sched-form__row">
        <span className="sched-form__label">{t("scheduled.form.spawn")}</span>
        <Select
          ariaLabel="spawn"
          value={spawnId}
          onChange={setSpawnId}
          options={spawns.map((s) => ({ value: String(s.id), label: s.name }))}
          placeholder={t("scheduled.form.spawn_placeholder")}
        />
      </div>

      <div className="sched-form__row">
        <span className="sched-form__label">{t("scheduled.col.cadence")}</span>
        <div className="diag-catalog__range" role="radiogroup" aria-label="schedule kind">
          {kindBtn("interval", t("scheduled.form.kind_interval"))}
          {kindBtn("cron", t("scheduled.form.kind_cron"))}
        </div>
      </div>

      {kind === "interval" ? (
        <div className="sched-form__row">
          <span className="sched-form__label">{t("scheduled.form.interval")}</span>
          <Select
            ariaLabel="interval-preset"
            value={intervalS}
            onChange={setIntervalS}
            options={intervalOptions}
          />
        </div>
      ) : (
        <label className="sched-form__row">
          <span className="sched-form__label">{t("scheduled.form.cron")}</span>
          <input
            className={`${INPUT_CLS} font-mono`}
            data-testid="sched-form-cron"
            value={cron}
            onChange={(e) => setCron(e.target.value)}
            placeholder="0 8 * * *"
          />
          <span className="sched-form__hint">{t("scheduled.form.cron_hint")}</span>
        </label>
      )}

      <label className="sched-form__row">
        <span className="sched-form__label">{t("scheduled.form.conversation")}</span>
        <input
          className={INPUT_CLS}
          data-testid="sched-form-conversation"
          value={conversationId}
          onChange={(e) => setConversationId(e.target.value)}
          placeholder={t("scheduled.form.conversation_placeholder")}
        />
      </label>

      {formError && (
        <p className="sched-form__error" data-testid="sched-form-error">{formError}</p>
      )}

      <div className="flex items-center justify-end gap-2">
        <button
          type="button"
          className="px-3 py-1.5 rounded-lg text-[11px] font-sans text-muted-foreground hover:text-foreground transition-colors"
          onClick={onCancel}
        >
          {t("common.cancel")}
        </button>
        <button
          type="button"
          className="px-3 py-1.5 rounded-lg text-[11px] font-sans font-medium bg-primary text-primary-foreground disabled:opacity-50"
          data-testid="sched-form-submit"
          disabled={saving}
          onClick={submit}
        >
          {editing ? t("scheduled.form.submit_save") : t("scheduled.form.submit_create")}
        </button>
      </div>
    </div>
  );
}

// ── the card ───────────────────────────────────────────────────────────────────
interface Props {
  /** Open a run in RunReplay (wired to DiagnosisView's run overlay). */
  onOpenRun?: (runId: number) => void;
}

export default function ScheduledTasksCard({ onOpenRun }: Props) {
  const { t } = useTranslation();
  const [tasks, setTasks] = useState<ScheduledTaskDto[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [runs, setRuns] = useState<Record<number, ScheduledTaskRunDto[]>>({});
  // fire-now bookkeeping: "firing" while the request is pending, "running" after
  // a 202 OR a 409 (already running) — both mean a run is in flight right now.
  const [busy, setBusy] = useState<Record<number, "firing" | "running">>({});
  const [confirmingDelete, setConfirmingDelete] = useState<number | null>(null);
  const [form, setForm] = useState<{ editing: ScheduledTaskDto | null } | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.listScheduledTasks()
      .then((ts) => { if (!cancelled) { setTasks(ts); setLoaded(true); } })
      .catch(() => { if (!cancelled) setLoaded(true); }); // dashboard is best-effort
    return () => { cancelled = true; };
  }, []);

  const replaceTask = (updated: ScheduledTaskDto) =>
    setTasks((ts) => ts.map((x) => (x.id === updated.id ? updated : x)));

  const fmtNextDue = (task: ScheduledTaskDto): string => {
    if (!task.enabled || !task.next_due_at) return "—";
    const d = parseUtc(task.next_due_at);
    if (Number.isNaN(d.getTime())) return "—";
    const diffMin = Math.round((d.getTime() - Date.now()) / 60000);
    if (diffMin <= 0) return t("scheduled.due_now");
    const v = diffMin < 60 ? `${diffMin}m`
      : diffMin < 60 * 24 ? `${Math.round(diffMin / 60)}h`
      : `${Math.round(diffMin / 1440)}d`;
    return t("scheduled.due_in", { v });
  };

  const toggleExpand = (id: number) => {
    if (expanded === id) {
      setExpanded(null);
      return;
    }
    setExpanded(id);
    api.getScheduledTaskRuns(id)
      .then((rs) => setRuns((prev) => ({ ...prev, [id]: rs })))
      .catch(() => { /* history stays empty */ });
  };

  const doPauseResume = async (task: ScheduledTaskDto) => {
    setError(null);
    try {
      const updated = task.enabled
        ? await api.pauseScheduledTask(task.id)
        : await api.resumeScheduledTask(task.id);
      replaceTask(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e)); // e.g. resume over the cap → 409
    }
  };

  const doFire = async (task: ScheduledTaskDto) => {
    setError(null);
    setBusy((b) => ({ ...b, [task.id]: "firing" }));
    try {
      await api.fireScheduledTaskNow(task.id); // 202 — the run is in flight now
      setBusy((b) => ({ ...b, [task.id]: "running" }));
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setBusy((b) => ({ ...b, [task.id]: "running" })); // already running
      } else {
        setBusy((b) => { const n = { ...b }; delete n[task.id]; return n; });
        setError(e instanceof Error ? e.message : String(e));
      }
    }
  };

  const doDelete = async (id: number) => {
    setError(null);
    try {
      await api.deleteScheduledTask(id);
      setTasks((ts) => ts.filter((x) => x.id !== id));
      setConfirmingDelete(null);
      if (expanded === id) setExpanded(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="usage-card sched-card" data-testid="scheduled-tasks-card">
      <div className="usage-card__head">
        <h3 className="usage-card__title">{t("scheduled.title")}</h3>
        <button
          type="button"
          className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-mono text-muted-foreground hover:text-foreground hover:bg-foreground/[0.04] border border-border transition-colors"
          data-testid="sched-new"
          onClick={() => setForm({ editing: null })}
        >
          <Plus className="w-3 h-3" />
          {t("scheduled.new")}
        </button>
      </div>

      {form && (
        <TaskForm
          editing={form.editing}
          onCancel={() => setForm(null)}
          onSaved={(saved, edited) => {
            if (edited) replaceTask(saved);
            else setTasks((ts) => [...ts, saved]);
            setForm(null);
          }}
        />
      )}

      {error && <p className="sched-card__error" data-testid="sched-error">{error}</p>}

      {loaded && tasks.length === 0 ? (
        <EmptyState
          icon={CalendarClock}
          title={t("scheduled.empty")}
          body={t("scheduled.empty_desc")}
          testId="empty-scheduled"
          action={
            <EmptyStateAction onClick={() => setForm({ editing: null })}>
              <Plus className="w-3 h-3" />
              {t("scheduled.new")}
            </EmptyStateAction>
          }
        />
      ) : tasks.length > 0 ? (
        <table className="diag-table sched-table">
          <thead>
            <tr>
              <th>{t("scheduled.col.name")}</th>
              <th>{t("scheduled.col.spawn")}</th>
              <th>{t("scheduled.col.cadence")}</th>
              <th>{t("scheduled.col.last")}</th>
              <th>{t("scheduled.col.next")}</th>
              <th>{t("scheduled.col.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {tasks.map((task) => (
              <Fragment key={task.id}>
                <tr data-testid="sched-row">
                  <td>
                    <button
                      type="button"
                      className="flex items-center gap-1 text-left text-foreground hover:text-primary transition-colors"
                      data-testid={`sched-expand-${task.id}`}
                      onClick={() => toggleExpand(task.id)}
                      title={task.prompt}
                    >
                      <ChevronRight
                        className={`w-3 h-3 shrink-0 text-subtle-foreground transition-transform${expanded === task.id ? " rotate-90" : ""}`}
                      />
                      <span className="diag-table__spawn">{task.name}</span>
                    </button>
                  </td>
                  <td>{task.spawn_name ?? "—"}</td>
                  <td>
                    {task.schedule_kind === "cron" ? (
                      <>
                        <code className="font-mono">{task.cron}</code>
                        {/* I5: the server interprets cron in the user's local time. */}
                        <span className="sched-table__hint">{t("scheduled.localTime")}</span>
                      </>
                    ) : (
                      t("scheduled.every", { v: fmtInterval(task.interval_s ?? 0) })
                    )}
                  </td>
                  <td><OutcomeBadge task={task} /></td>
                  <td className="usage-card__num">{fmtNextDue(task)}</td>
                  <td>
                    {confirmingDelete === task.id ? (
                      <span className="sched-table__confirm">
                        <span className="sched-table__confirm-text">{t("scheduled.delete_confirm")}</span>
                        <button
                          type="button"
                          className="text-[11px] font-mono font-bold text-danger hover:bg-danger/10 px-1.5 rounded transition-colors"
                          data-testid={`sched-delete-confirm-${task.id}`}
                          onClick={() => doDelete(task.id)}
                        >
                          {t("scheduled.action.delete")}
                        </button>
                        <button
                          type="button"
                          className={ACTION_BTN}
                          onClick={() => setConfirmingDelete(null)}
                        >
                          {t("common.cancel")}
                        </button>
                      </span>
                    ) : (
                      <span className="sched-table__actions">
                        <button
                          type="button"
                          className={ACTION_BTN}
                          data-testid={`sched-fire-${task.id}`}
                          disabled={busy[task.id] != null}
                          onClick={() => doFire(task)}
                        >
                          {busy[task.id] === "running" ? t("scheduled.running")
                            : busy[task.id] === "firing" ? "…"
                            : t("scheduled.action.fire")}
                        </button>
                        {task.enabled ? (
                          <button
                            type="button"
                            className={ACTION_BTN}
                            data-testid={`sched-pause-${task.id}`}
                            onClick={() => doPauseResume(task)}
                          >
                            {t("scheduled.action.pause")}
                          </button>
                        ) : (
                          <button
                            type="button"
                            className={ACTION_BTN}
                            data-testid={`sched-resume-${task.id}`}
                            onClick={() => doPauseResume(task)}
                          >
                            {t("scheduled.action.resume")}
                          </button>
                        )}
                        <button
                          type="button"
                          className={ACTION_BTN}
                          data-testid={`sched-edit-${task.id}`}
                          onClick={() => setForm({ editing: task })}
                        >
                          {t("scheduled.action.edit")}
                        </button>
                        <button
                          type="button"
                          className="text-[11px] font-mono text-danger/80 hover:text-danger transition-colors"
                          data-testid={`sched-delete-${task.id}`}
                          onClick={() => setConfirmingDelete(task.id)}
                        >
                          {t("scheduled.action.delete")}
                        </button>
                      </span>
                    )}
                  </td>
                </tr>

                {expanded === task.id && (
                  <tr>
                    <td colSpan={6}>
                      <div className="sched-history" data-testid="sched-history">
                        {(runs[task.id] ?? []).length === 0 ? (
                          <span className="sched-table__hint">{t("scheduled.history.empty")}</span>
                        ) : (
                          <table className="diag-table sched-history__table">
                            <thead>
                              <tr>
                                <th>{t("scheduled.history.outcome")}</th>
                                <th>{t("scheduled.history.started")}</th>
                                <th>{t("scheduled.history.reason")}</th>
                                <th />
                              </tr>
                            </thead>
                            <tbody>
                              {(runs[task.id] ?? []).map((r) => (
                                <tr key={r.id} data-testid="sched-run-row">
                                  <td>
                                    {r.outcome == null ? "—"
                                      : r.outcome === "skipped_overlap" ? t("scheduled.outcome.skipped")
                                      : r.outcome === "ok" ? t("scheduled.outcome.ok")
                                      : t("scheduled.outcome.error")}
                                  </td>
                                  <td className="usage-card__num">{fmtWhen(r.started_at)}</td>
                                  <td title={r.reason ?? undefined}>
                                    {r.reason ? (r.reason.length > 120 ? `${r.reason.slice(0, 120)}…` : r.reason) : "—"}
                                  </td>
                                  <td>
                                    {r.run_id != null && (
                                      <button
                                        type="button"
                                        className="text-[11px] font-mono text-primary hover:underline"
                                        data-testid={`sched-replay-${r.run_id}`}
                                        onClick={() => onOpenRun?.(r.run_id!)}
                                      >
                                        {t("scheduled.history.replay")} →
                                      </button>
                                    )}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        )}
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      ) : null}
    </div>
  );
}
