/**
 * nanoid stays past the advisory, and the reasoning that made it harmless stays true.
 *
 * HONEST FRAMING FIRST: this bump bought ZERO security. GHSA-2v37-7h3g-55p8
 * (customAlphabet/customRandom loop forever when size is 0) was triaged on
 * 2026-08-10 as unreachable here, and the `non-secure/` directory — the only
 * part postcss loads — is byte-identical between 3.3.16 and 3.3.17. What the
 * bump buys is silence: an alert that would otherwise keep coming back.
 *
 * So the version assertion is hygiene. The tripwire below is the part that
 * actually protects something.
 *
 * 🔴 WHY THE TRIPWIRE. "Unreachable" rested on three independent layers, and two
 * of them are properties of OUR code rather than of nanoid:
 *
 *   1. postcss imports `nanoid/non-secure`, whose customAlphabet cannot loop
 *      (`let i = size|0; while (i--)` — i is 0, so the body never runs).
 *   2. it calls plain `nanoid`, not the affected customAlphabet/customRandom.
 *   3. postcss/lib/input.js:80 passes the literal 6, so size is not attacker-
 *      controlled.
 *
 * The day anything under web/src imports nanoid directly, layers 2 and 3 stop
 * being anybody's guarantee and the triage has to be re-run. A verdict that
 * silently stops applying looks exactly like a verdict that still holds — which
 * is the whole reason this file exists rather than a note in a memory file.
 *
 * 🔴 AND THE COMPARISON IS NUMERIC. "3.3.9" > "3.3.17" as strings, so a lexical
 * compare would wave through every 3.3.9-and-below while looking like a working
 * guard. Same trap as the pypdf floor.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

/** The release that carries the fix. Raise on a later advisory; never lower. */
const PATCHED = [3, 3, 17] as const;

const WEB_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");

const parse = (v: string): number[] => v.split(".").map((n) => parseInt(n, 10));

const gte = (a: number[], b: readonly number[]): boolean => {
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    const x = a[i] ?? 0;
    const y = b[i] ?? 0;
    if (x !== y) return x > y;
  }
  return true;
};

describe("the lockfile stays past the advisory", () => {
  it("pins a patched nanoid", () => {
    const lock = JSON.parse(readFileSync(join(WEB_ROOT, "package-lock.json"), "utf8"));
    const entry = lock.packages["node_modules/nanoid"];

    expect(entry, "nanoid is not in package-lock.json any more").toBeTruthy();
    expect(
      gte(parse(entry.version), PATCHED),
      `package-lock.json pins nanoid ${entry.version}`,
    ).toBe(true);
  });

  it("compares versions numerically, not as text", () => {
    // Guarding the guard. If someone rewrites `gte` as a string compare, 3.3.9
    // would satisfy ">= 3.3.17" and every 3.3.x below the fix would pass.
    expect(gte(parse("3.3.9"), PATCHED)).toBe(false);
    expect(gte(parse("3.3.17"), PATCHED)).toBe(true);
    expect(gte(parse("3.4.0"), PATCHED)).toBe(true);
    expect("3.3.9" > "3.3.17", "string ordering assumed by this test changed").toBe(true);
  });
});

describe("the triage's premise still holds", () => {
  const walk = (dir: string): string[] =>
    readdirSync(dir).flatMap((name) => {
      const p = join(dir, name);
      return statSync(p).isDirectory() ? walk(p) : [p];
    });

  it("nothing under web/src imports nanoid", () => {
    // THE tripwire. Not a style rule — the 2026-08-10 verdict ("the affected
    // functions are never called, and size is a literal") is only true while
    // postcss is the sole importer. A direct import here would put the choice of
    // API and of `size` in our hands, and nobody would notice.
    const src = join(WEB_ROOT, "src");
    const offenders = walk(src)
      .filter((p) => /\.(ts|tsx|js|jsx)$/.test(p) && !p.endsWith("nanoid-advisory.test.ts"))
      .filter((p) => /from\s+["']nanoid|require\(["']nanoid/.test(readFileSync(p, "utf8")));

    expect(
      offenders.map((p) => p.slice(WEB_ROOT.length + 1)),
      "web/src now imports nanoid directly — re-run the reachability triage",
    ).toEqual([]);
  });

  it("the walker actually reads files", () => {
    // Without this, an offenders list that is empty because the walk found
    // nothing at all would read as "clean". A blind guard and a passing guard
    // look identical.
    const files = walk(join(WEB_ROOT, "src")).filter((p) => /\.(ts|tsx)$/.test(p));

    expect(files.length).toBeGreaterThan(50);
  });
});
