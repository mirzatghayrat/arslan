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
  // 0.1.61 PR 2b: a card's "Always" must say what it allows, in every language: the literal scope is interpolated.
  it("kit.scope.always keeps its {{label}} in every language", () => {
    for (const [lang, data] of Object.entries(LOCALES)) {
      expect((data as { kit: { scope: { always: string } } }).kit.scope.always, lang).toContain("{{label}}");
    }
  });

  // 0.1.61 PR 2b: the words on the command and schedule cards point at the app's own places and name its own
  // things, in every language, so a rewording in one place cannot leave another one lying.
  describe("the card words", () => {
    type CardWords = {
      runcmd: { remember: string; sandboxOutsideLabel: string; sandboxOutsideNote: string };
      settings: { navAbilities: string; terminalRulesEmpty: string };
      kit: { scope: { always: string } };
      schedgrant: { unattended: string };
    };
    /** The app's own word for the sandbox and for Arslan's working folder (runcmd.sandboxOutside*). */
    const SANDBOX_AND_FOLDER: Record<string, [string, string]> = {
      en: ["sandbox", "working folder"], zh: ["沙盒", "工作文件夹"], ja: ["サンドボックス", "作業フォルダ"],
      es: ["entorno aislado", "carpeta de trabajo"], de: ["Sandbox", "Arbeitsordner"], fr: ["bac à sable", "dossier de travail"],
    };
    for (const [lang, data] of Object.entries(LOCALES)) {
      const d = data as unknown as CardWords;

      if (lang === "zh" || lang === "ja") {
        it(`${lang}: schedgrant.unattended is written with full-width punctuation throughout`, () => {
          expect(d.schedgrant.unattended).not.toMatch(/[,;:]/);                  // an ASCII , ; : in a sentence here is a slip
        });
      }

      it(`${lang}: terminalRulesEmpty names the card's own "Always" word (kit.scope.always)`, () => {
        const word = d.kit.scope.always.split(/[:：]/)[0].trim();
        expect(d.settings.terminalRulesEmpty).toContain(word);
      });

      it(`${lang}: schedgrant.unattended also says what still runs, in the app's own words: writes in the working folder, and no commands`, () => {
        const [sandbox, folder] = SANDBOX_AND_FOLDER[lang];
        expect(d.runcmd.sandboxOutsideLabel).toContain(sandbox);     // the table is the app's own word, not an invention
        expect(d.runcmd.sandboxOutsideNote).toContain(folder);
        expect(d.schedgrant.unattended).toContain(folder);
        // v0.1.63: a scheduled run runs no command (until S2a-3), so the card no longer offers the sandbox.
        expect(d.schedgrant.unattended).not.toContain(sandbox);
      });
    }
  });

  for (const [lang, data] of Object.entries(LOCALES)) {
    if (lang === "en") continue;

    it(`${lang} has the same key set as en (the six languages share one key set)`, () => {
      const langKeys = collectKeys(data as JsonObj);
      expect(langKeys).toEqual(enKeys);
    });
  }
});
