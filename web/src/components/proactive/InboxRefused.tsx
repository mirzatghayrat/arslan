import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ApiError, request } from "../../api/client";
import { formatUiDateTime } from "../../lib/localeFormatting";

/** It changes only when something goes undone for want of someone to ask: twice a minute is enough. */
const POLL_MS = 30_000;

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

/** What a row says: the command, the file, the cadence, the app. Never the raw target ("rules:send-mail"),
 *  and an app list's separator reads as a comma. */
const whatOf = (r: Refusal) => (r.detail || r.target).split("\u001e").join(", ").replace(/\s+/g, " ").trim();
/** What "Always allow" will allow, in the card's words. */
const storesOf = (r: Refusal) => r.always.map((a) => a.label || a.target).join(", ");

/**
 * "Not done while you were away" (0.1.61 §A4, R12, R13). A row says what "Always allow" would store
 * before it is clicked, and offers the click only when the card would have offered "Always". Nothing
 * here says declined or refused: an away entry is an expiry, nobody said no. Fails quietly: an older
 * server has no such list, and the rest of the Inbox must still work.
 */
export default function InboxRefused({ onCount }: { onCount?: (n: number) => void }) {
  const { t, i18n } = useTranslation();
  const [rows, setRows] = useState<Refusal[]>([]);
  // Keyed by the entry's id (its latest ledger row), so a newer refusal of the same thing is a new entry.
  const [allowed, setAllowed] = useState<Set<number>>(new Set());
  const [eachTime, setEachTime] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState<number | null>(null);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

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

  async function allowAlways(r: Refusal) {
    setBusy(r.id);
    try {
      // Only the entry's id: the server stores what its card would have offered, never a kind or a target from here.
      await request("/permissions/rules", { method: "POST", body: JSON.stringify({ refused_id: r.id }) });
      if (alive.current) setAllowed((s) => new Set(s).add(r.id));
    } catch (e) {
      if (!alive.current) return;
      if (e instanceof ApiError && e.status === 409) setEachTime((s) => new Set(s).add(r.id));   // nothing to allow after all
      else if (e instanceof ApiError && e.status === 404) void load();                              // the entry has gone
    } finally {
      if (alive.current) setBusy(null);
    }
  }

  if (!rows.length) return null;
  return (
    <section data-testid="inbox-refused" aria-label={t("inbox.refusedTitle")} className="flex flex-col gap-2">
      <h2 className="flex items-center gap-2 text-[13px] font-semibold">
        <span aria-hidden="true" className="h-[7px] w-[7px] rounded-full bg-subtle-foreground" />{t("inbox.refusedTitle")}
        <span className="font-mono text-[12px] text-subtle-foreground">{rows.length}</span>
      </h2>
      {/* At most 100 entries (the server's cap): they scroll here rather than push the rest of the Inbox away. */}
      <ul className="flex max-h-[28rem] flex-col gap-1.5 overflow-y-auto">
        {rows.map((row) => {
          const what = whatOf(row);
          const done = allowed.has(row.id);
          // Only with something listed to store: the click is never asked for without its result in front of the person.
          const offered = row.always_ok && row.always.length > 0 && !eachTime.has(row.id);
          return (
            <li key={`${row.kind}\u0000${row.target}`} data-testid="inbox-refused-row"
              className="flex items-center gap-3 rounded-xl bg-surface px-3.5 py-2.5">
              <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                <span className="truncate font-mono text-[12px] text-foreground" title={what}>{what}</span>
                <span className="text-[12px] text-muted-foreground">
                  {row.count > 1
                    ? t("inbox.refusedTimes", { count: row.count, since: formatUiDateTime(row.first_at, i18n?.language) })
                    : formatUiDateTime(row.created_at, i18n?.language)}
                </span>
                {offered && !done && <span data-testid="inbox-refused-stores" className="text-[12px] text-muted-foreground">
                  {t("inbox.alwaysStores", { what: storesOf(row) })}</span>}
              </div>
              {done
                ? <span data-testid="inbox-refused-allowed" className="shrink-0 text-[12px] text-muted-foreground">{t("inbox.allowedNow")}</span>
                : offered
                  ? <button type="button" disabled={busy === row.id} onClick={() => void allowAlways(row)} data-testid="inbox-refused-allow"
                      className="shrink-0 rounded-lg bg-fill px-2.5 py-1 text-[12px] font-semibold hover:bg-fill-strong disabled:opacity-50">
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
