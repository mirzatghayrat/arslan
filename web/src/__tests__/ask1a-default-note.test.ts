/**
 * ASK1-a (v0.1.64): "Ask only for risky commands" is the default again. v0.1.63's known-issue sheet, 0070's notice and
 * the markers that named "S2a-3 and #406" are gone; the one-time note has a text for each policy, in six languages,
 * and each names the other choice by the label Settings shows.
 */
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import en from "../locales/en.json";
import zh from "../locales/zh.json";
import ja from "../locales/ja.json";
import es from "../locales/es.json";
import de from "../locales/de.json";
import fr from "../locales/fr.json";

const repo = (path: string) => readFileSync(resolve(__dirname, "../../..", path), "utf8");
const LOCALES = { en, zh, ja, es, de, fr } as const;
const GONE = ["askRiskyConfirmTitle", "askRiskyConfirmBody", "askRiskyConfirmAction", "askRiskyConfirmCancel",
  "shellPolicyAskRiskyNote", "policyNoticeTitle", "policyNoticeBody"];

describe("ASK1-a: the old sheet and markers are gone", () => {
  it.each([
    "web/src/components/settings/AdvancedSection.tsx",
    "web/src/components/ShellPolicySwitchNotice.tsx",
    "server/services/settings_service.py",
    "server/db/migrations/versions/_0070_ask_every_command.py",
  ])("%s no longer waits on S2a-3 and #406", (path) => {
    const text = repo(path);
    expect(text).not.toContain("DELETE-BY: v0.1.64");
    expect(text).not.toContain("#406");
    expect(text).not.toMatch(/askRiskyConfirm|shellPolicyAskRiskyNote|confirmSheet/);
  });

  it("the note's key now goes in v0.1.65", () => {
    expect(repo("web/src/components/ShellPolicySwitchNotice.tsx")).toContain("DELETE-BY: v0.1.65");
    expect(repo("server/services/settings_service.py")).toContain("DELETE-BY: v0.1.65, with the note.");
  });
});

describe.each(Object.entries(LOCALES))("ASK1-a note in %s", (_lang, data) => {
  const s = data.settings as unknown as Record<string, string>;
  it("drops the old strings", () => {
    for (const key of GONE) expect(s[key]).toBeUndefined();
  });
  it("names the way to the other choice by its Settings label", () => {
    expect(s.policyNoticeRiskyBody).toContain(s.shellPolicyAskAll);
    expect(s.policyNoticeAllBody).toContain(s.shellPolicyAskRisky);
    expect(s.policyNoticeRiskyTitle && s.policyNoticeAllTitle).toBeTruthy();
    expect(`${s.policyNoticeRiskyBody}${s.policyNoticeAllBody}`).not.toContain("0.1.63");
  });
});
