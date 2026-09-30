/**
 * Every sentence the Inbox can show has words in all six languages.
 *
 * What the backend raises is a KEY plus params. A key with no words renders as the key itself,
 * in the user's language of choice, which is exactly the bug that once put `nav.capabilities`
 * in six page headers (see nav-titles.test.ts). The key list is DERIVED from
 * locales/proactive-keys.json (a copy of the backend's catalog, kept fresh by a Python test),
 * not written out here, so a key added on the server fails this test until it is translated.
 */
import { describe, expect, it } from "vitest";
import i18n, { SUPPORTED_LANGUAGES } from "../i18n";
import catalog from "../locales/proactive-keys.json";
import { proactiveMessages } from "../locales/proactive";

type Node = string | { [key: string]: Node };
const at = (root: Node, path: string): Node | undefined => path.split(".").reduce<Node | undefined>(
  (node, part) => (node && typeof node === "object" ? node[part] : undefined), root);
/** The strings a catalog key stands for: one sentence, plural forms, or a set of wordings. */
function sentences(root: Node, path: string): string[] {
  const direct = at(root, path);
  if (typeof direct === "string") return [direct];
  if (direct && typeof direct === "object") return Object.values(direct).filter((v): v is string => typeof v === "string");
  const parent = path.split(".").slice(0, -1).join(".");
  const leaf = path.split(".").pop() as string;
  const holder = parent ? at(root, parent) : root;
  if (holder && typeof holder === "object") {
    return Object.entries(holder).filter(([k, v]) => (k === `${leaf}_other` || k === `${leaf}_one`) && typeof v === "string").map(([, v]) => v as string);
  }
  return [];
}
const tokens = (value: string) => [...new Set(value.match(/\{\{[^}]+\}\}/g) ?? [])].sort();
/** Every catalog key as a path into {title, evidence}; `sched.state` has two wordings, chosen by a flag. */
const catalogPaths = [...catalog.title, ...catalog.evidence.filter((k) => k !== "sched.state").map((k) => `evidence.${k}`),
  "evidence.sched.state.failing", "evidence.sched.state.paused"];

describe("proactive catalog coverage", () => {
  for (const language of SUPPORTED_LANGUAGES) {
    const root = { title: proactiveMessages[language].title, evidence: proactiveMessages[language].evidence } as unknown as Node;
    const paths = catalogPaths;

    it(`${language}: every catalog key has words`, () => {
      const missing = paths.filter((path) => sentences(root, path).every((s) => !s.trim()) || sentences(root, path).length === 0);
      expect(missing).toEqual([]);
    });

    it(`${language}: no sentence is just its own key`, () => {
      for (const path of paths) for (const s of sentences(root, path)) {
        expect(s).not.toBe(path);
        expect(s).not.toMatch(/^(proactive\.)?[a-z_]+(\.[a-z_]+)+$/);
      }
    });
  }

  it("the catalog is not empty and every key has an English sentence", () => {
    expect(catalogPaths.length).toBeGreaterThan(15);
    const root = { title: proactiveMessages.en.title, evidence: proactiveMessages.en.evidence } as unknown as Node;
    expect(catalogPaths.filter((p) => sentences(root, p).length === 0)).toEqual([]);
  });

  it("every language has the same messages and the same {{variables}} as English", () => {
    const flatten = (node: Node, prefix = ""): Record<string, string> => typeof node === "string" ? { [prefix]: node }
      : Object.assign({}, ...Object.entries(node).map(([k, v]) => flatten(v, prefix ? `${prefix}.${k}` : k)));
    const base = (key: string) => key.replace(/_(one|other)$/, "");
    const en = flatten(proactiveMessages.en as unknown as Node);
    const enTokens: Record<string, string[]> = {};
    for (const [key, value] of Object.entries(en)) enTokens[base(key)] = [...new Set([...(enTokens[base(key)] ?? []), ...tokens(value)])].sort();
    for (const language of SUPPORTED_LANGUAGES) {
      const flat = flatten(proactiveMessages[language] as unknown as Node);
      expect([...new Set(Object.keys(flat).map(base))].sort(), language).toEqual([...new Set(Object.keys(en).map(base))].sort());
      for (const [key, value] of Object.entries(flat)) {
        expect(value.trim(), `${language}.${key}`).not.toBe("");
        // A translation may drop a variable a plural form does not need ("one" says 'a file'), never invent one.
        for (const token of tokens(value)) expect(enTokens[base(key)], `${language}.${key} uses ${token}`).toContain(token);
      }
    }
  });

  it("no non-English sentence is still the English one", () => {
    const flatten = (node: Node, prefix = ""): Record<string, string> => typeof node === "string" ? { [prefix]: node }
      : Object.assign({}, ...Object.entries(node).map(([k, v]) => flatten(v, prefix ? `${prefix}.${k}` : k)));
    const en = flatten(proactiveMessages.en as unknown as Node);
    for (const language of SUPPORTED_LANGUAGES.filter((l) => l !== "en")) {
      const flat = flatten(proactiveMessages[language] as unknown as Node);
      const same = Object.entries(flat).filter(([k, v]) => en[k] === v && !/^https?:/.test(v));
      // Words that really are the same in a language are listed one by one, not waved through.
      const allowed = language === "fr" ? ["settings.type", "settings.intervals.1800"] : language === "de" ? ["settings.label"] : [];
      expect(same.map(([k]) => k).filter((k) => !allowed.includes(k)), language).toEqual([]);
    }
  });

  it("is registered for all six languages in i18n", async () => {
    for (const language of SUPPORTED_LANGUAGES) {
      const t = i18n.getFixedT(language);
      expect(t("proactive.page.title")).toBe(proactiveMessages[language].page.title);
      expect(t("settings.navProactive"), language).not.toBe("settings.navProactive");
      expect(t("nav.inbox"), language).not.toBe("nav.inbox");
    }
  });
});
