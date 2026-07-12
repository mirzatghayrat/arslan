/**
 * Relative-time helpers shared by the provider settings components
 * (ProviderConfigList container + ConnectionTester detail-pane widget).
 *
 * Extracted verbatim from ProviderConfigList so the container and the pane share
 * ONE implementation instead of two copies. Backend timestamps are naive-UTC ISO
 * strings WITHOUT a timezone suffix — append "Z" before parsing so they are not
 * read as browser-local time.
 */

/** Parse a possibly-naive-UTC ISO timestamp to epoch ms (NaN when invalid). */
export function parseUtcMs(iso: string): number {
  const hasTz = iso.endsWith('Z') || /[+-]\d{2}:?\d{2}$/.test(iso);
  return new Date(hasTz ? iso : `${iso}Z`).getTime();
}

/** Tiny relative-time helper (minutes/hours/days). `iso` is naive-UTC without
 *  a timezone suffix — append "Z" before parsing so it isn't read as local. */
export function formatRelativeTime(
  iso: string,
  t: (key: string, opts?: Record<string, unknown>) => string,
): string {
  const then = parseUtcMs(iso);
  if (Number.isNaN(then)) return iso;
  const mins = Math.floor((Date.now() - then) / 60_000);
  if (mins < 1) return t('settings.timeJustNow');
  if (mins < 60) return t('settings.timeMinutesAgo', { n: mins });
  const hours = Math.floor(mins / 60);
  if (hours < 24) return t('settings.timeHoursAgo', { n: hours });
  return t('settings.timeDaysAgo', { n: Math.floor(hours / 24) });
}
