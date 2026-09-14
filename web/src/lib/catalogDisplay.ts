import type { TFunction } from "i18next";

/** Unknown/new server hints and user-authored text always retain their source. */
export function catalogText(t: TFunction, key: string | null | undefined, source: string): string {
  return key?.startsWith("catalogUI.") ? t(key, { defaultValue: source }) : source;
}
