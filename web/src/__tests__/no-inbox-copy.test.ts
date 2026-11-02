/** #605 review F3: the Inbox is gone (INB5), so nothing the app shows, in any language, sends the user there. Two things may still say
 *  the word: the memory proposals' own box (another thing), and the brief's evidence, which nothing shows since the brief went (the
 *  user's Q9; INB7-e deletes it with the brief). */
import { describe, expect, it } from "vitest";
import i18n, { SUPPORTED_LANGUAGES } from "../i18n";

const INBOX: Record<string, RegExp> = { en: /inbox/i, zh: /收件箱/, ja: /受信箱/, de: /Posteingang/i, es: /bandeja/i, fr: /boîte/i };
const ALLOWED = [/^brain\.proposal_inbox$/, /^proactive\.evidence\.brief\./];

function strings(node: unknown, path = ""): [string, string][] {
  if (typeof node === "string") return [[path, node]];
  if (node && typeof node === "object") return Object.entries(node).flatMap(([key, value]) => strings(value, path ? `${path}.${key}` : key));
  return [];
}

describe("no copy points at the Inbox", () => {
  it.each(SUPPORTED_LANGUAGES)("in %s", (language) => {
    const left = strings(i18n.getResourceBundle(language, "translation"))
      .filter(([key, text]) => INBOX[language].test(text) && !ALLOWED.some((allowed) => allowed.test(key)))
      .map(([key]) => key);
    expect(left).toEqual([]);
  });
});
