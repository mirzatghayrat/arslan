/**
 * languages — single source of truth for the UI language selector.
 *
 * `LANGUAGE_OPTIONS` lists the 6 locales the i18n engine actually loads
 * (see i18n.ts SUPPORTED_LANGUAGES), each with its native-script label.
 * `normalizeLanguage` reconciles a stored value into a valid i18next code,
 * mapping legacy label-shaped values (from before the selector stored codes)
 * onto their code and falling back to 'en'.
 */

export const LANGUAGE_OPTIONS = [
  { code: 'en', label: 'English (US)' },
  { code: 'zh', label: '简体中文' },
  { code: 'ja', label: '日本語' },
  { code: 'es', label: 'Español' },
  { code: 'de', label: 'Deutsch' },
  { code: 'fr', label: 'Français' },
] as const

// Legacy label values persisted before the selector stored i18next codes.
const LEGACY: Record<string, string> = {
  'English (US)': 'en',
  'Chinese (Simplified)': 'zh',
  'Japanese': 'ja',
  'German': 'de',
}

const CODES = new Set(LANGUAGE_OPTIONS.map((o) => o.code))

export function normalizeLanguage(v: string | undefined | null): string {
  if (!v) return 'en'
  if (CODES.has(v as (typeof LANGUAGE_OPTIONS)[number]['code'])) return v as string
  return LEGACY[v] ?? 'en'
}
