import { useCallback, useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from "react";
import { useTranslation } from "react-i18next";
import { ApiError, request } from "../../api/client";
import { formatUiDateTime } from "../../lib/localeFormatting";
import { useAnswerGuardState } from "../kit/guard";

/** It changes only when something goes undone for want of someone to ask: twice a minute is enough. */
const POLL_MS = 30_000;
/** How long "Undo" is offered after an "Always allow": a durable one-click, taken with the list moving, must be reversible. */
const UNDO_MS = 10_000;

/**
 * One entry of GET /approvals/refused (0.1.61 §A4, R12): something that could not be asked while nobody
 * was there — a scheduled run's step, or a card a job or a chat turn never opened once an earlier one
 * went unanswered — one entry per kind and target, newest first, at most 100.
 */
export interface Refusal {
  /** The entry's latest ledger row: what "Always allow" sends back. */
  id: number;
  /** Its latest time and its first, both UTC. */
  created_at: string;
  first_at: string;
  count: number;
  conversation_id: string | null;
  /** One of the server's permission kinds (`permissions.KINDS`). */
  kind: string;
  target: string;
  detail: string;
  /** The card would have offered "Always". Without it there is nothing to allow. */
  always_ok: boolean;
  /** Exactly what "Always allow" will store, each rule in the words its card used. */
  always: { kind: string; target: string; label: string }[];
}

/** What a row says, a line to a thing: the command, the file, the cadence, each app of a many-app entry (their detail is newline-joined; their target
 *  is joined by a separator). Never the raw target ("rules:send-mail"); never merged into one string. */
const whatLines = (r: Refusal) => (r.detail || r.target).split(/[\n\u001e]+/).map((line) => line.replace(/\s+/g, " ").trim()).filter(Boolean);

/** What "Always allow" made: the entry it was clicked on, where it stood, and the rules the server created (what Undo deletes). */
interface Allowed { row: Refusal; at: number; rules: number[] }

/**
 * "Not done while you were away" (0.1.61 §A4, R12, R13). A row says what "Always allow" would store
 * before it is clicked — every rule, one to a line, in the words its card used, wrapping rather than
 * clipped — and offers the click only when the card would have offered "Always". The click is held for
 * 500 ms after the list changes (a row that shifts under the pointer is not clicked), and can be undone
 * for ten seconds. Nothing here says declined or refused: an away entry is an expiry, nobody said no.
 * Fails quietly: an older server has no such list, and the rest of the Inbox must still work.
 */
export default function InboxRefused({ onCount }: { onCount?: (n: number) => void }) {
  const { t, i18n } = useTranslation();
  const [rows, setRows] = useState<Refusal[]>([]);
  // Keyed by the entry's id (its latest ledger row), so a newer refusal of the same thing is a new entry.
  const [allowed, setAllowed] = useState<Map<number, Allowed>>(new Map());
  const [undoable, setUndoable] = useState<Set<number>>(new Set());
  const [eachTime, setEachTime] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState<number | null>(null);
  const alive = useRef(true);
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>());
  useEffect(() => {
    alive.current = true;
    const open = timers.current;
    return () => { alive.current = false; open.forEach((timer) => clearTimeout(timer)); open.clear(); };
  }, []);

  // One gesture, one change: when the list changes (a new entry on top, one gone) the rows move, and for 500 ms no "Always allow" is taken.
  const guard = useAnswerGuardState();
  const held = useSyncExternalStore(guard.subscribe, guard.held, guard.held);
  const listKey = rows.map((r) => r.id).join(",");
  useLayoutEffect(() => { guard.shown(listKey || null); }, [guard, listKey]);

  const load = useCallback(async () => {
    try {
      const body = await request<Refusal[]>("/approvals/refused?hours=24");
      if (!alive.current) return;
      const list = Array.isArray(body) ? body : [];
      setRows(list);
      onCount?.(list.length);
    } catch { /* the rest of the Inbox still works */ }
  }, [onCount]);
  useEffect(() => {
    void load();
    const timer = setInterval(() => { if (document.visibilityState !== "hidden") void load(); }, POLL_MS);
    return () => clearInterval(timer);
  }, [load]);

  const closeUndo = (id: number) => {
    clearTimeout(timers.current.get(id));
    timers.current.delete(id);
    setUndoable((s) => { const n = new Set(s); n.delete(id); return n; });
  };

  async function allowAlways(r: Refusal) {
    if (guard.held()) return;
    setBusy(r.id);
    try {
      // Only the entry's id: the server stores what its card would have offered, never a kind or a target from here.
      const made = await request<{ id?: number; rules?: { id: number }[] }>("/permissions/rules", { method: "POST", body: JSON.stringify({ refused_id: r.id }) });
      if (!alive.current) return;
      const rules = Array.isArray(made?.rules) ? made.rules.map((rule) => rule.id) : typeof made?.id === "number" ? [made.id] : [];
      setAllowed((m) => new Map(m).set(r.id, { row: r, at: Math.max(0, rows.findIndex((x) => x.id === r.id)), rules }));
      if (rules.length) {
        setUndoable((s) => new Set(s).add(r.id));
        timers.current.set(r.id, setTimeout(() => closeUndo(r.id), UNDO_MS));
      }
    } catch (e) {
      if (!alive.current) return;
      if (e instanceof ApiError && e.status === 409) setEachTime((s) => new Set(s).add(r.id));   // nothing to allow after all
      else if (e instanceof ApiError && e.status === 404) void load();                              // the entry has gone
    } finally {
      if (alive.current) setBusy(null);
    }
  }

  /** Delete exactly the rules the click created. A rule that is gone already counts as undone; any other failure keeps Undo for a retry. */
  async function undo(r: Refusal) {
    const made = allowed.get(r.id);
    if (!made) return;
    setBusy(r.id);
    let failed = false;
    for (const id of made.rules) {
      try { await request(`/permissions/rules/${id}`, { method: "DELETE" }); }
      catch (e) { if (!(e instanceof ApiError && e.status === 404)) failed = true; }
    }
    if (!alive.current) return;
    setBusy(null);
    if (failed) return;
    closeUndo(r.id);
    setAllowed((m) => { const n = new Map(m); n.delete(r.id); return n; });
    void load();                                                        // the server lists it again
  }

  // The server leaves out what is allowed: a row allowed a moment ago stays where it was while its Undo is open.
  const shown = [...rows];
  for (const made of [...allowed.values()].sort((a, b) => a.at - b.at)) {
    if (undoable.has(made.row.id) && !shown.some((r) => r.id === made.row.id)) shown.splice(Math.min(made.at, shown.length), 0, made.row);
  }
  if (!shown.length) return null;
  return (
    <section data-testid="inbox-refused" aria-label={t("inbox.refusedTitle")} className="flex flex-col gap-2">
      <h2 className="flex items-center gap-2 text-[13px] font-semibold">
        <span aria-hidden="true" className="h-[7px] w-[7px] rounded-full bg-subtle-foreground" />{t("inbox.refusedTitle")}
        <span className="font-mono text-[12px] text-subtle-foreground">{rows.length}</span>
      </h2>
      {/* At most 100 entries (the server's cap): they scroll here rather than push the rest of the Inbox away. */}
      <ul className="flex max-h-[28rem] flex-col gap-1.5 overflow-y-auto">
        {shown.map((row) => {
          const lines = whatLines(row);
          const done = allowed.has(row.id);
          // Only with something listed to store: the click is never asked for without its result in front of the person.
          const offered = row.always_ok && row.always.length > 0 && !eachTime.has(row.id);
          return (
            <li key={`${row.kind}\u0000${row.target}`} data-testid="inbox-refused-row"
              className="flex items-center gap-3 rounded-xl bg-surface px-3.5 py-2.5">
              <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                <div className="flex min-w-0 flex-col" title={lines.join(", ")}>
                  {lines.map((line, i) => <span key={i} data-testid="inbox-refused-what" className="truncate font-mono text-[12px] text-foreground">{line}</span>)}
                </div>
                <span className="text-[12px] text-muted-foreground">
                  {row.count > 1
                    ? t("inbox.refusedTimes", { count: row.count, since: formatUiDateTime(row.first_at, i18n?.language) })
                    : formatUiDateTime(row.created_at, i18n?.language)}
                </span>
                {offered && !done && <div data-testid="inbox-refused-stores" className="flex flex-col gap-0.5">
                  {row.always.map((rule, i) => {
                    const label = rule.label || rule.target;
                    return <span key={i} data-testid="inbox-refused-rule" title={label} className="text-[12px] text-muted-foreground [overflow-wrap:anywhere]">
                      {t("inbox.alwaysStores", { what: label })}</span>;
                  })}
                </div>}
              </div>
              {done
                ? <span className="flex shrink-0 items-center gap-2">
                    <span data-testid="inbox-refused-allowed" className="text-[12px] text-muted-foreground">{t("inbox.allowedNow")}</span>
                    {undoable.has(row.id) && <button type="button" disabled={busy === row.id} onClick={() => void undo(row)} data-testid="inbox-refused-undo"
                      className="rounded-lg bg-fill px-2.5 py-1 text-[12px] font-semibold hover:bg-fill-strong disabled:opacity-50">{t("inbox.undo")}</button>}
                  </span>
                : offered
                  ? <button type="button" disabled={busy === row.id} aria-disabled={held || undefined} onClick={() => void allowAlways(row)} data-testid="inbox-refused-allow"
                      className="shrink-0 rounded-lg bg-fill px-2.5 py-1 text-[12px] font-semibold hover:bg-fill-strong disabled:opacity-50 aria-disabled:cursor-not-allowed aria-disabled:opacity-50">
                      {t("inbox.alwaysAllow")}
                    </button>
                  : <span data-testid="inbox-refused-each-time" className="shrink-0 text-[12px] text-muted-foreground">{t("inbox.asksEachTime")}</span>}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
