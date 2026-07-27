/** S4.2-d §5 — the structural guard against hardcoded CJK re-growth.
 *
 * locale-parity.test.ts can only see REGISTERED keys; it is structurally blind
 * to strings that never went through i18n. This test scans every production
 * source under web/src (locales and tests excluded, comments stripped) for CJK
 * codepoints and enforces two directions:
 *
 *   1. a file with CJK that is NOT in the inventory below → FAIL
 *      (new hardcoded Chinese entered the codebase — register a locale key instead)
 *   2. a file in the inventory that no longer has CJK → FAIL
 *      (you fixed it — DELETE its inventory line; the list only ever shrinks)
 *
 * PERMANENT_ALLOWLIST is the one deliberate exception class: native language
 * names in the language picker ("简体中文", "日本語") are correct in every UI
 * language by design and never migrate to locale keys.
 *
 * DEBT_INVENTORY is the S4.2-d starting debt (23 files when the gate landed).
 * Entries may ONLY be removed. Adding one back is the exact regression this
 * test exists to stop — fix the string via a locale key instead.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = join(__dirname, "..");

const PERMANENT_ALLOWLIST = new Set<string>([
  "lib/languages.ts", // native language names in the picker — by design
]);

const DEBT_INVENTORY = new Set<string>([
  // EMPTY since S4.2-d M6 — every production file is clean. New hardcoded CJK
  // has no grace period: register a locale key instead.
]);

// CJK unified ideographs + CJK punctuation + Hiragana/Katakana + full-width forms.
const CJK = /[　-〿぀-ヿ一-鿿＀-￯]/;

function stripComments(text: string): string {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(?<![:/])\/\/[^\n]*/g, "");
}

function* sources(dir: string): Generator<string> {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) {
      if (name === "locales" || name === "__tests__" || name === "test") continue;
      yield* sources(p);
    } else if (/\.(ts|tsx)$/.test(name) && !/\.test\.(ts|tsx)$/.test(name)) {
      yield p;
    }
  }
}

function offenders(): Set<string> {
  const out = new Set<string>();
  for (const p of sources(ROOT)) {
    const rel = relative(ROOT, p).replaceAll("\\", "/");
    if (PERMANENT_ALLOWLIST.has(rel)) continue;
    if (CJK.test(stripComments(readFileSync(p, "utf8")))) out.add(rel);
  }
  return out;
}

describe("no hardcoded CJK outside i18n (S4.2-d §5)", () => {
  const found = offenders();

  it("no file outside the debt inventory contains CJK", () => {
    const fresh = [...found].filter((f) => !DEBT_INVENTORY.has(f)).sort();
    expect(fresh, "new hardcoded CJK — register a locale key instead").toEqual([]);
  });

  it("every debt-inventory entry still has CJK (list only shrinks)", () => {
    const stale = [...DEBT_INVENTORY].filter((f) => !found.has(f)).sort();
    expect(stale, "fixed files must be DELETED from DEBT_INVENTORY").toEqual([]);
  });

  it("the permanent allowlist stays exactly the language picker", () => {
    expect([...PERMANENT_ALLOWLIST]).toEqual(["lib/languages.ts"]);
  });
});
