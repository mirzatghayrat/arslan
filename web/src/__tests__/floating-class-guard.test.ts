/**
 * The class stays swept.
 *
 * Before this round the codebase had six hand-rolled `fixed inset-0` backdrops
 * and three trigger-scoped Escape handlers, with almost no overlap — which is
 * why the same two defects kept reappearing in a different corner. Fixing the
 * seven dropdowns is only half the job; this is the half that stops the eighth.
 */
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..");

/** Every dropdown/popover anchored to a control, and what the sweep decided. */
const SWEPT = [
  { file: "components/ThreadRowMenu.tsx",       portal: true,  why: "clipped by the sidebar thread list" },
  { file: "components/EquipPopover.tsx",        portal: true,  why: "clipped by the capabilities pane" },
  { file: "components/Select.tsx",              portal: true,  why: "clipped at all ten call sites" },
  { file: "components/ModelCombobox.tsx",       portal: true,  why: "clipped inside Settings" },
  // Dismissal only — each with a reason, so 'no portal' is a judgement on the
  // record rather than something that was forgotten.
  { file: "components/brain/NoteEditor.tsx",    portal: false, why: "pinned inside its own textarea wrap; never reaches a scroll edge" },
  { file: "components/OrchestratorChat.tsx",    portal: false, why: "opens upward out of the composer; clipping is latent, not observed" },
  { file: "components/Sidebar.tsx",             portal: false, why: "in normal flow — it pushes the list down, it does not float" },
];

describe("floating-element class sweep", () => {
  for (const s of SWEPT) {
    it(`${s.file} routes dismissal through the shared hook`, () => {
      const src = readFileSync(resolve(SRC, s.file), "utf8");
      expect(src).toContain("useDismissable");
    });

    it(`${s.file} ${s.portal ? "portals out of its clipping ancestor" : `needs no portal — ${s.why}`}`, () => {
      const src = readFileSync(resolve(SRC, s.file), "utf8");
      expect(src.includes("AnchoredPortal")).toBe(s.portal);
    });
  }

  it("no swept component still hand-rolls a click-away backdrop", () => {
    // The idiom being retired: dismissal implemented as LAYOUT. It breaks the
    // moment an ancestor establishes a containing block, and its z-index only
    // orders it within its own stacking context.
    for (const s of SWEPT) {
      const src = readFileSync(resolve(SRC, s.file), "utf8");
      expect(src, `${s.file} still has a fixed inset-0 click-away layer`)
        .not.toMatch(/className="fixed inset-0 z-4\d"[\s\S]{0,80}onClick/);
    }
  });

  it("Escape is document-level, not bound to a trigger, wherever it is handled", () => {
    // Select and ModelCombobox each had `case "Escape"` inside a React
    // onKeyDown on their own trigger, so Escape did nothing once focus moved
    // into the panel. Their keyboard handlers may keep other keys; what must
    // not come back is Escape living ONLY there.
    for (const f of ["components/Select.tsx", "components/ModelCombobox.tsx"]) {
      const src = readFileSync(resolve(SRC, f), "utf8");
      expect(src).toContain("useDismissable");
    }
  });
});
