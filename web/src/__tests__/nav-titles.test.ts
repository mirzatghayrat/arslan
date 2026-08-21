/**
 * Every page's header title actually resolves (found by looking at the app).
 *
 * The header renders `t(\`nav.${activeSection}\`)`, so a section id and a locale
 * key have to agree — and nothing checked that they did. They did not: `nav`
 * held dashboard/spawns/secondBrain/settings while the sections are
 * arslan/spawn/ledger/capabilities/brain/diagnosis/settings. Six of the seven
 * headers rendered the literal string "nav.capabilities", "nav.ledger", and so
 * on, in all six languages, and it shipped in v0.1.27.
 *
 * 1514 frontend tests were green while that was on screen. What none of them
 * did was ask whether a key resolves — so that is what this asks, DERIVED from
 * SECTIONS rather than from a hand-written list, because a hand-written list is
 * the thing that drifted in the first place.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, test, expect } from "vitest";
import { SECTIONS } from "../lib/sections";
import en from "../locales/en.json";
import zh from "../locales/zh.json";
import ja from "../locales/ja.json";
import de from "../locales/de.json";
import fr from "../locales/fr.json";
import es from "../locales/es.json";

const LOCALES: Record<string, { nav: Record<string, string> }> = {
  en: en as never, zh: zh as never, ja: ja as never,
  de: de as never, fr: fr as never, es: es as never,
};

describe("page header titles", () => {
  for (const [lang, data] of Object.entries(LOCALES)) {
    test(`${lang} has a title for every section`, () => {
      const missing = SECTIONS.filter((s) => !String(data.nav?.[s] ?? "").trim());
      expect(missing).toEqual([]);
    });

    test(`${lang} titles are not the keys themselves`, () => {
      // i18next falls back to the key when a string is absent, which is exactly
      // what was on screen. A value that IS the key would satisfy "present".
      const echoed = SECTIONS.filter((s) => data.nav?.[s] === s || data.nav?.[s] === `nav.${s}`);
      expect(echoed).toEqual([]);
    });
  }

  test("the sections list is the one the app actually uses", () => {
    // Guards the other direction: SECTIONS could be complete and wrong. If
    // App.tsx stops typing its state with Section, this stops proving anything.
    const app = readFileSync(join(process.cwd(), "src/App.tsx"), "utf8");
    expect(app).toContain("useState<Section>('arslan')");
  });
});
