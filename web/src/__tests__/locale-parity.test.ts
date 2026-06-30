/**
 * Locale parity test — all 6 locale JSONs must have the exact same nested key set.
 * Fails immediately if any locale drifts from en (the reference).
 */

import { describe, it, expect } from "vitest";

import en from "../locales/en.json";
import zh from "../locales/zh.json";
import ja from "../locales/ja.json";
import es from "../locales/es.json";
import de from "../locales/de.json";
import fr from "../locales/fr.json";

type JsonObj = Record<string, unknown>;

/** Recursively collect all dot-separated key paths from a JSON object. */
function collectKeys(obj: JsonObj, prefix = ""): string[] {
  const keys: string[] = [];
  for (const [k, v] of Object.entries(obj)) {
    const path = prefix ? `${prefix}.${k}` : k;
    if (v !== null && typeof v === "object" && !Array.isArray(v)) {
      keys.push(...collectKeys(v as JsonObj, path));
    } else {
      keys.push(path);
    }
  }
  return keys.sort();
}

const LOCALES: Record<string, JsonObj> = { en, zh, ja, es, de, fr };
const enKeys = collectKeys(en as JsonObj);

describe("locale parity", () => {
  it("en locale has 475 keys (baseline guard)", () => {
    expect(enKeys).toHaveLength(475);
  });

  for (const [lang, data] of Object.entries(LOCALES)) {
    if (lang === "en") continue;

    it(`${lang} has the same keys as en`, () => {
      const langKeys = collectKeys(data as JsonObj);
      expect(langKeys).toEqual(enKeys);
    });
  }
});
