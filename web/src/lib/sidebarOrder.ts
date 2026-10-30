/**
 * SB1 (v0.1.64): the sidebar's order and date sections, the iPhone's own rules (ArslanApp
 * ConversationsView.swift, `ConversationGroups.make`), so both apps group a conversation the same way:
 * newest first by last activity; calendar days back from today: 0 Today, 1 Yesterday, 2–7 the 7 days,
 * the rest one folded group per month, newest month first. A conversation with no time yet (a new one
 * before its first message) is Today. The user picked "match the iPhone" and "headings only" on the
 * SB1-0 mock (2026-10-30), so rows carry no time of their own.
 */

export type DaySection = "today" | "yesterday" | "week";
export interface MonthGroup<T> { id: string; title: string; rows: T[] }
export interface Grouped<T> { today: T[]; yesterday: T[]; week: T[]; months: MonthGroup<T>[] }

/** Calendar days from `then`'s day to `now`'s day, in local time. Built from the local year, month and
 *  day, so a daylight-saving change (a 23- or 25-hour day) never shifts it. */
export function daysBack(then: Date, now: Date): number {
  const day = (d: Date) => Date.UTC(d.getFullYear(), d.getMonth(), d.getDate());
  return Math.round((day(now) - day(then)) / 86_400_000);
}

/** Newest first by `at` (ms since epoch, null = no time yet, which counts as newest), stable for ties. */
export function newestFirst<T>(rows: T[], at: (row: T) => number | null): T[] {
  return rows.map((row, i) => ({ row, i, t: at(row) }))
    .sort((a, b) => (b.t ?? Infinity) - (a.t ?? Infinity) || a.i - b.i)
    .map(({ row }) => row);
}

/** Group rows (any order) into the iPhone's sections. `locale` names the months: "October" this year,
 *  "September 2025" in an earlier one (the iPhone's "LLLL" and "LLLL yyyy" templates). */
export function groupByDay<T>(rows: T[], at: (row: T) => number | null, now: Date, locale?: string): Grouped<T> {
  const out: Grouped<T> = { today: [], yesterday: [], week: [], months: [] };
  const months = new Map<string, { first: Date; rows: T[] }>();
  for (const row of newestFirst(rows, at)) {
    const t = at(row);
    const when = t == null ? null : new Date(t);
    const back = when == null ? 0 : daysBack(when, now);
    if (back <= 0) out.today.push(row);
    else if (back === 1) out.yesterday.push(row);
    else if (back <= 7) out.week.push(row);
    else {
      const id = `${when!.getFullYear()}-${String(when!.getMonth() + 1).padStart(2, "0")}`;
      const group = months.get(id) ?? { first: when!, rows: [] };
      group.rows.push(row);
      months.set(id, group);
    }
  }
  out.months = [...months.entries()].sort(([a], [b]) => b.localeCompare(a)).map(([id, g]) => ({
    id, rows: g.rows,
    title: new Intl.DateTimeFormat(locale, g.first.getFullYear() === now.getFullYear()
      ? { month: "long" } : { month: "long", year: "numeric" }).format(g.first),
  }));
  return out;
}
