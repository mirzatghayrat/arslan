import { describe, expect, it } from "vitest";
import i18n, { SUPPORTED_LANGUAGES } from "../i18n";
import en from "../locales/en.json";
import zh from "../locales/zh.json";
import ja from "../locales/ja.json";
import es from "../locales/es.json";
import de from "../locales/de.json";
import fr from "../locales/fr.json";

const BASE: Record<string, Record<string, unknown>> = { en, zh, ja, es, de, fr };

/**
 * Feature namespaces (panel, proactive, …) are spread INTO `translation` next
 * to the locale JSON. A namespace named like an existing top-level JSON group
 * silently replaces that whole group: 0.1.48 first named the Activity page's
 * strings `activity`, which wiped `activity.*` — the tool-call card copy — and
 * the only symptom was a download card rendering its raw key.
 */
describe("feature namespaces never shadow locale JSON groups", () => {
  for (const lang of SUPPORTED_LANGUAGES) {
    it(lang, () => {
      const merged = i18n.getResourceBundle(lang, "translation") as Record<string, unknown>;
      for (const [key, value] of Object.entries(BASE[lang])) {
        expect(merged[key], `"${key}" from ${lang}.json was replaced by a namespace`).toEqual(value);
      }
    });
  }
});
