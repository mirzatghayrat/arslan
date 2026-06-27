// web/src/__tests__/no-raw-colors.test.ts
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
// Add each component here as it is migrated (Tasks 10–16).
const MIGRATED: string[] = ["components/OrchestratorChat.tsx", "components/SpawnsDashboard.tsx", "App.tsx", "components/SpawnEditor.tsx", "components/SettingsScreen.tsx", "components/SpawnDirectChat.tsx", "components/Sidebar.tsx", "components/Markdown.tsx", "components/SFSymbol.tsx", "components/LedgerRow.tsx", "components/ProviderConfigList.tsx", "components/Select.tsx", "components/NoModelHint.tsx", "components/McpServers.tsx", "components/Capabilities.tsx", "components/CapabilityTabs.tsx", "components/ToolHubDiscover.tsx"];

const RAW = /(?:bg|text|border|ring|outline|placeholder|divide|shadow|from|to|via|fill|stroke|accent|caret|decoration)-\[#|#[0-9a-fA-F]{3,6}\b|(?:bg|text|border|ring|outline|placeholder|divide|shadow|from|to|via|fill|stroke|accent|caret|decoration)-(?:gray|slate|zinc|neutral|stone|amber|emerald|green|red|rose|orange|blue|sky|cyan|indigo|violet|purple|teal|yellow)-\d{2,3}/;

describe("migrated components contain no raw color literals", () => {
  it("guard is active", () => {
    // Sentinel so the suite is valid while MIGRATED is empty; grows per file (Tasks 10–16).
    expect(Array.isArray(MIGRATED)).toBe(true);
  });
  for (const rel of MIGRATED) {
    it(rel, () => {
      const src = readFileSync(resolve(here, "..", rel), "utf8");
      const offending = src.split("\n").map((l, i) => [i + 1, l] as const).filter(([, l]) => RAW.test(l));
      expect(offending.map(([n, l]) => `${n}: ${l.trim()}`)).toEqual([]);
    });
  }
});
