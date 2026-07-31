/**
 * Gate item ② — the empty states that a fresh install shows.
 *
 * An audit found 61 empty states in the app; 6 of them had any control inside
 * the block. This does NOT try to fix all 61, because most are sub-sections of
 * an already-populated panel and a full "what this is / what to do next" box
 * there would be noise. The line drawn is:
 *
 *   Tier A — a whole panel area is empty on a fresh install. This is the first
 *            thing a new user ever sees of that feature. Gets the full
 *            treatment. That is the set asserted below.
 *   Tier B — nested sections, and "your filter matched nothing". Stay short.
 *
 * `action` is per-site rather than blanket-required, and the reason is in the
 * table. A button that duplicates a control already visible on the same screen
 * is a decoy, not a next step — so the requirement is "an action must exist
 * where the next step is NOT already on screen".
 */
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..");

type Site = {
  testId: string;
  file: string;
  panel: string;
  needsBody: boolean;
  needsAction: boolean;
  /** Why an in-block control is or isn't required here. */
  why: string;
};

const SITES: Site[] = [
  {
    testId: "empty-spawn-ledger", file: "components/SpawnsDashboard.tsx", panel: "Spawn ledger",
    needsBody: true, needsAction: true,
    why: "the empty box owns the whole screen area; the header button is easy to miss",
  },
  {
    testId: "empty-scheduled", file: "components/ScheduledTasksCard.tsx", panel: "Scheduled tasks",
    needsBody: true, needsAction: true,
    why: "the creator is local (setForm) and the header button sits outside the block",
  },
  {
    testId: "empty-diagnosis", file: "components/DiagnosisCatalog.tsx", panel: "Diagnostics catalog",
    needsBody: true, needsAction: true,
    why: "the next step is on ANOTHER screen — runs only exist once a spawn is dispatched",
  },
  {
    testId: "empty-evolution-inbox", file: "components/EvolutionInbox.tsx", panel: "Evolution inbox",
    needsBody: true, needsAction: false,
    why: "the spawn selector this points at is directly above it",
  },
  {
    testId: "empty-capabilities", file: "components/CapabilityCatalog.tsx", panel: "Capability catalog",
    needsBody: true, needsAction: false,
    why: "the skill-import and MCP panels are on the same page",
  },
  {
    testId: "empty-brain-graph", file: "components/brain/BrainSection.tsx", panel: "Second brain graph",
    needsBody: true, needsAction: false,
    why: "the feed field IS the left panel the copy points at",
  },
  {
    testId: "empty-sidebar-spawns", file: "components/Sidebar.tsx", panel: "Sidebar spawn list",
    needsBody: true, needsAction: false,
    why: "a nav list; creating happens elsewhere and the list is not the place to say so twice",
  },
  // Tier B, listed because the FILTER case must never inherit the empty-catalog
  // advice: telling someone to import their first skill when they merely picked
  // a chip is wrong, and it was wrong — both cases shared one key before this.
  {
    testId: "empty-capabilities-filtered", file: "components/CapabilityCatalog.tsx", panel: "Tools, filtered",
    needsBody: false, needsAction: true,
    why: "the only useful action is undoing the filter that caused it",
  },
  {
    testId: "empty-skills-filtered", file: "components/CapabilityCatalog.tsx", panel: "Skills, filtered",
    needsBody: false, needsAction: true,
    why: "same — and the default chip is 'usable', so this is the COMMON first view",
  },
];

/** The `<EmptyState … />` element carrying `testId`, as source text. */
function block(file: string, testId: string): string {
  const src = readFileSync(resolve(SRC, file), "utf8");
  const at = src.indexOf(`testId="${testId}"`);
  expect(at, `${testId} not found in ${file}`).toBeGreaterThan(-1);
  const open = src.lastIndexOf("<EmptyState", at);
  expect(open, `${testId} is not on an <EmptyState> in ${file}`).toBeGreaterThan(-1);
  // End the block at the first `/>` (or `</EmptyState>`) that is NOT inside a
  // JSX expression, tracking brace depth. Nested elements — `action={<X/>}` —
  // all live inside braces, so this stops at the right place where naive
  // angle-bracket counting does not: `</Foo>` opens with `<` but closes a tag.
  let braces = 0;
  for (let i = open; i < src.length; i++) {
    if (src[i] === "{") braces++;
    else if (src[i] === "}") braces--;
    else if (braces === 0 && (src.startsWith("/>", i) || src.startsWith("</EmptyState>", i))) {
      return src.slice(open, i + 2);
    }
  }
  throw new Error(`unterminated <EmptyState> for ${testId}`);
}

describe("gate item ② — Tier A empty states", () => {
  for (const site of SITES) {
    it(`${site.panel} says what it is`, () => {
      expect(block(site.file, site.testId)).toContain("title=");
    });

    if (site.needsBody) {
      it(`${site.panel} says what to do next`, () => {
        // Discriminating: a title alone is exactly the "No runs yet" this item
        // exists to remove. Every Tier A panel must carry the second line.
        expect(block(site.file, site.testId)).toContain("body=");
      });
    }

    it(`${site.panel} ${site.needsAction ? "offers a control" : `needs no control — ${site.why}`}`, () => {
      const has = block(site.file, site.testId).includes("action=");
      expect(has).toBe(site.needsAction);
    });
  }

  it("no Tier A panel still renders its empty state as a bare one-liner", () => {
    // The shape being outlawed: `<p className="diag-catalog__empty">{t("…empty")}</p>`
    // in the files above. Scoped to keys that name an EMPTY state — a LOADING
    // one-liner (`diag.loading`) is a different state and is legitimately one
    // line, so DiagnosisCatalog keeps its. Narrowing it that far is the point:
    // a guard that also failed on loading text would get relaxed, not obeyed.
    const bare = /className="diag-catalog__empty">\{t\("([^"]*(?:empty|no_runs|none|nothing)[^"]*)"/;
    for (const file of new Set(SITES.map((s) => s.file))) {
      const src = readFileSync(resolve(SRC, file), "utf8");
      const hit = bare.exec(src);
      expect(hit?.[1], `${file} still shows its empty state as one line`).toBeUndefined();
    }
  });

  it("the filtered states do not reuse the empty-catalog copy", () => {
    // The bug this locks down: `capabilities.catalog.empty` used to serve both
    // "you have nothing" and "your filter matched nothing", so a filter chip
    // told the user to go import their first skill.
    const src = readFileSync(resolve(SRC, "components/CapabilityCatalog.tsx"), "utf8");
    for (const id of ["empty-capabilities-filtered", "empty-skills-filtered"]) {
      const b = block("components/CapabilityCatalog.tsx", id);
      expect(b).toContain("capabilities.catalog.filtered_empty");
      expect(b).not.toContain("capabilities.catalog.empty");
    }
    // …and the true-empty case keeps its own copy.
    expect(block("components/CapabilityCatalog.tsx", "empty-capabilities"))
      .toContain("capabilities.catalog.empty_desc");
    expect(src).toBeTruthy();
  });

  it("the sidebar list is translated, not hardcoded English", () => {
    // It read a literal "No spawns yet" — the same disease as the backend
    // Chinese in gate item ①, pointed the other way: a Chinese reader saw
    // English that nothing could translate.
    const src = readFileSync(resolve(SRC, "components/Sidebar.tsx"), "utf8");
    expect(src).not.toContain(">No spawns yet<");
    expect(block("components/Sidebar.tsx", "empty-sidebar-spawns")).toContain("t('sidebar.no_spawns')");
  });
});
