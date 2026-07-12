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
  it("en locale has 862 keys (baseline guard)", () => {
    // 780 → 781: S3-M1 added chat.stopRun (the run-cancelled marker reuses the
    // existing working.stalled key instead of adding a duplicate).
    // 781 → 793: S3-M3 added the usage.* section (Diagnostics usage card —
    // title/daily/empty/notCovered + 3 range + 5 column keys).
    // 793 → 839: S3-M4 added the scheduled.* section (Diagnostics scheduled
    // tasks — card + badges + actions + history + create/edit form, 46 keys).
    // 839 → 854: Provider-P2 added settings model-combobox keys (refresh,
    // custom-id row, stale/last-updated hints, ollama empty state, base URL
    // label, relative-time units, capability chips — 15 keys).
    // 854 → 858: Provider-P3 added custom-provider keys (required base_url
    // hint, quick-fill label, Ollama-remote chip, compatibility note — 4 keys).
    // 858 → 862: Provider-P4 added connectivity-dot tooltips (healthDotModels/
    // NoList/Unreachable/Unknown — 4 keys).
    expect(enKeys).toHaveLength(862);
  });

  for (const [lang, data] of Object.entries(LOCALES)) {
    if (lang === "en") continue;

    it(`${lang} has the same keys as en`, () => {
      const langKeys = collectKeys(data as JsonObj);
      expect(langKeys).toEqual(enKeys);
    });
  }
});
