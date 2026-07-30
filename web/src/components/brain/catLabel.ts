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

/** Display labels for the brain's BRANCH kinds.
 *
 * These used to arrive from the backend as Chinese literals ("材料", "心得",
 * "画像", "笔记"), so an English interface showed Chinese and nothing could
 * catch it: the no-hardcoded-CJK guard scans web/src, and those strings were
 * born in server/api/brain.py. The backend now ships the stable `kind` and the
 * translation happens here, where the user's language is known. */
export const BRAIN_KINDS = ["material", "learning", "profile", "note", "self"] as const;

export function brainKindLabel(t: TFunction, kind: string): string {
  return (BRAIN_KINDS as readonly string[]).includes(kind)
    ? t(`brain.kind_${kind}`)
    : kind;
}

/** Display labels for a leaf's PROVENANCE.
 *
 * Deliberately a partial translation. Two of these values are ours and are now
 * stable keys ("fed", "spawn", "handwritten"); the others come straight out of
 * the database (a fact's `source`, a learning's `source_kind`) and we do not
 * own them. An unknown value passes through as-is rather than being forced
 * through a lookup — showing the raw string beats inventing a label for data
 * whose vocabulary is not ours. */
export const KNOWN_PROVENANCE = ["fed", "spawn", "handwritten"] as const;

export function provenanceLabel(t: TFunction, value: string): string {
  return (KNOWN_PROVENANCE as readonly string[]).includes(value)
    ? t(`brain.prov_${value}`)
    : value;
}
