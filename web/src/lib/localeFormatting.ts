const LANGUAGES = new Set(["en", "zh", "ja", "es", "de", "fr"]);

export function uiLocale(language?: string): string {
  const base = language?.split(/[-_]/)[0]?.toLowerCase() ?? "en";
  return LANGUAGES.has(base) ? base : "en";
}

/** Backend timestamps without a zone are UTC, not browser-local wall time. */
export function uiDate(value: string | number | Date): Date {
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}[T ]\d/.test(value) &&
    !/(?:Z|[+-]\d{2}:?\d{2})$/i.test(value)) value += "Z";
  return new Date(value);
}

export function formatUiTime(value: string | number | Date, language?: string): string {
  const date = uiDate(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleTimeString(uiLocale(language), { hour: "2-digit", minute: "2-digit" });
}

export function formatUiDate(value: string | number | Date, language?: string): string {
  const date = uiDate(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleDateString(uiLocale(language));
}

export function formatUiDateTime(value: string | number | Date, language?: string): string {
  const date = uiDate(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString(uiLocale(language), {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}
