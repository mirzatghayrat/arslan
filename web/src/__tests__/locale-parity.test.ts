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
  it("en locale has 908 keys (baseline guard)", () => {
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
    // 862 → 872: Settings-T1 added the SettingsShell side-nav keys (settings.
    // navProviders/navSearch/navAppearance/navAccess/navMemory/navAdvanced/
    // navScheduled/navUsage + navComingSoon + placeholderHint — 10 keys).
    // 872 → 873: Settings-T2 added settings.navRegion (side-nav aria-label).
    // 873 → 878: Settings-T3 added the ConnectionTester + CapabilityBadges keys
    // (capabilitiesLabel, testConnection, deepTest, deepTestOk,
    // reachableNoListNote — 5 keys).
    // 878 → 885: Settings-T5 i18n'd the retention label/hint, the spawn-mode
    // desc + 3 option labels, the page-header lore, and the footer note
    // (spawnModeDesc/Auto/Interactive/Strict, retentionLabel/Hint, headerLore,
    // footerNote = +8) and removed the now-orphaned settings.sectionInterface
    // (−1) → net +7.
    // 885 → 886: Settings-T6 replaced the top Save button with instant auto-save
    // — removed the now-dead btnSave/btnSaving (−2) and added the auto-save
    // status keys savingLabel/savedTick/saveFailed (+3) → net +1.
    // 886 → 904: E9-b Task 4d added the evolution.diag.* block for the inbox
    // eligibility panel (title + pick_spawn + verdict_* codes + chain_* +
    // auto_off = 18 keys). Review fix: swapped the unreachable
    // verdict_drought_holdout_split for chain_holdout_plain (−1 +1, net 0).
    // 904 → 908: provider-key-input fix added the saved-config key-field keys
    // (settings.keyEnter/keySavedReplace/keyReenter/keyUndecryptableReason —
    // fresh-entry placeholder states + the honest undecryptable reason, 4 keys).
    // 908 → 913: Task 10 (S4.1-C) added the inbound-MCP-server toggle +
    // generate-token control keys (settings.labelMcpServer/mcpServerDesc +
    // settings.mcpToken.generate/generating/generateError — 5 keys).
    expect(enKeys).toHaveLength(913);
  });

  for (const [lang, data] of Object.entries(LOCALES)) {
    if (lang === "en") continue;

    it(`${lang} has the same keys as en`, () => {
      const langKeys = collectKeys(data as JsonObj);
      expect(langKeys).toEqual(enKeys);
    });
  }
});
