/**
 * Every useDismissable call must ATTACH the refs it returns.
 *
 * 🔴 Regression shipped in v0.1.17 and found by the user: opening "+ INVITE
 * SPAWNS" gave a modal that closed on any click, including on its own search
 * box, so spawns could not be invited at all.
 *
 * Cause: the hook was called for the ledger modal but neither `anchorRef` nor
 * `floatingRef` was ever bound to an element. `inside()` then answers false for
 * every target, so EVERY document mousedown counts as outside — the exact
 * failure the hook's own test suite already covers ("does NOT close on a click
 * inside"). That test only ever exercised ThreadRowMenu.
 *
 * So this is a guard that existed and was applied to one sample. This file
 * checks the population instead: for each call site, the refs it names must
 * appear on an element in the same file.
 */
import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { resolve, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((e) => {
    const p = join(dir, e);
    if (statSync(p).isDirectory()) return e === "__tests__" ? [] : walk(p);
    return /\.tsx?$/.test(e) ? [p] : [];
  });
}

/** Files that call the hook, with the ref names they destructure. */
function callSites() {
  const out: { file: string; refs: string[] }[] = [];
  for (const file of walk(SRC)) {
    const src = readFileSync(file, "utf8");
    if (!src.includes("useDismissable(") && !src.includes("useDismissable<")) continue;
    if (file.endsWith("useDismissable.ts")) continue;
    const refs: string[] = [];
    // `const { anchorRef, floatingRef } = useDismissable…`
    // `const { anchorRef: a, floatingRef: b } = useDismissable…`
    for (const m of src.matchAll(/const\s*\{([^}]*)\}\s*=\s*useDismissable/g)) {
      for (const part of m[1].split(",")) {
        const name = part.includes(":") ? part.split(":")[1] : part;
        if (name.trim()) refs.push(name.trim());
      }
    }
    out.push({ file: file.slice(SRC.length + 1), refs });
  }
  return out;
}

describe("useDismissable refs are attached wherever they are taken", () => {
  const sites = callSites();

  it("finds the call sites at all", () => {
    // ⓪ Without this the loop below could pass by iterating over nothing.
    expect(sites.length).toBeGreaterThan(4);
  });

  for (const site of callSites()) {
    it(`${site.file} binds every ref it destructures`, () => {
      const src = readFileSync(resolve(SRC, site.file), "utf8");
      for (const ref of site.refs) {
        // "Attached" means the ref appears inside a JSX ref attribute — bound
        // directly (`ref={x}`), handed to a component that binds it
        // (`floatingRef={x}` → AnchoredPortal), or assigned in a callback ref
        // (`ref={(el) => { x.current = … }}`, which Sidebar uses).
        //
        // Narrowed twice, because the first two versions flagged four innocent
        // files between them. A guard that cries wolf gets switched off, and
        // then it is not a guard.
        expect(src, `${site.file} takes ${ref} from useDismissable and never binds it — ` +
          "every click then counts as outside, so the overlay closes on its own contents")
          .toMatch(new RegExp(`[a-zA-Z]*[Rr]ef=\\{[\\s\\S]{0,140}?\\b${ref}\\b`));
      }
    });
  }

  it("a call site that discards BOTH refs is either a modal that wants it, or a bug", () => {
    // Discarding both is only defensible with `outsideClick: false`, where the
    // refs are unused because nothing is dismissed by clicking. With
    // outside-click ON and no refs, the overlay closes on itself — which is
    // precisely what shipped.
    for (const site of callSites()) {
      if (site.refs.length) continue;
      const src = readFileSync(resolve(SRC, site.file), "utf8");
      const calls = [...src.matchAll(/useDismissable<[^>]*>\(([\s\S]{0,220}?)\);/g)];
      for (const c of calls) {
        if (/const\s*\{/.test(c[0])) continue;
        expect(c[1], `${site.file}: useDismissable with no refs must pass outsideClick:false`)
          .toContain("outsideClick: false");
      }
    }
  });
});
