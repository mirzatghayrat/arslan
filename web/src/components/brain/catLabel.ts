/** Display labels for the stable fact-category keys (S4.2-d).
 *
 * The backend persists and ships MACHINE KEYS ("identity", … — see
 * server/services/fact_classify.py FACT_CATEGORIES and migration 0037); the UI
 * translates them here. Anything that is not a known key (note tags, legacy
 * values that predate a boot with 0037 applied) passes through untranslated —
 * that fallback is deliberate: showing a raw string beats showing a missing-key
 * artifact for data we don't own. */
import type { TFunction } from "i18next";

export const FACT_CATEGORY_KEYS = [
  "identity",
  "communication",
  "interest",
  "task",
  "spawn_wish",
  "other",
] as const;

export function factCategoryLabel(t: TFunction, value: string): string {
  return (FACT_CATEGORY_KEYS as readonly string[]).includes(value)
    ? t(`brain.cat.${value}`)
    : value;
}
