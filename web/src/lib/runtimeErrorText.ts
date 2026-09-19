import { LANGUAGE_OPTIONS, normalizeLanguage } from './languages';

export type RuntimeErrorTranslations = Record<string, string>;

/** Only complete, bounded server-owned catalogs are accepted. No prose matching. */
export function runtimeErrorTranslations(value: unknown): RuntimeErrorTranslations | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const result: RuntimeErrorTranslations = {};
  for (const { code } of LANGUAGE_OPTIONS) {
    const text = (value as Record<string, unknown>)[code];
    if (typeof text !== 'string' || !text.trim() || text.length > 2000) return null;
    result[code] = text;
  }
  return result;
}

export function runtimeErrorText(fallback: string, translations: RuntimeErrorTranslations | null | undefined, language?: string): string {
  return translations?.[normalizeLanguage(language?.split('-')[0])] ?? fallback;
}
