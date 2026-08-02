/**
 * Overlay dismissal (B/C/D) — classified by what CLOSING COSTS.
 *
 * The anchored-dropdown sweep could use one rule for everything, because losing
 * an open dropdown costs nothing. Half of this group is holding something:
 * unsaved text, a half-filled form, a proposal awaiting accept or decline. So
 * the requirement here is two-sided, and a test that only asserts "it closes"
 * has NO discriminating power — half of what must hold is that certain
 * overlays must NOT close.
 *
 * Rulings: ①A dirty editors confirm before Escape closes them · ②A a proposal
 * card's Escape is a silent decline · ③A SpawnStudio's outside-click is
 * removed, which is a FIX — it was the only editor in the app that would
 * discard an in-progress spawn edit on a stray background click.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import DiscardBar from "../components/DiscardChangesBar";

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const read = (f: string) => readFileSync(resolve(SRC, f), "utf8");

beforeEach(() => vi.clearAllMocks());

// ---------------------------------------------------------------------------
// The classification, as data. Each row records the DECISION and its reason, so
// "does not close on an outside click" reads as a choice rather than a gap.
// ---------------------------------------------------------------------------

const OVERLAYS = [
  { file: "components/MessageBody.tsx",     outsideCloses: true,  why: "read-only HTML preview — nothing to lose" },
  { file: "components/SpawnStudio.tsx",     outsideCloses: false, why: "holds an in-progress spawn edit (ruling ③A removed it)" },
  { file: "components/GapFillModal.tsx",    outsideCloses: false, why: "holds form input" },
  { file: "components/FirstRunWizard.tsx",  outsideCloses: false, why: "closing it skips setup" },
];

describe("the classification is recorded, not implied", () => {
  for (const o of OVERLAYS) {
    it(`${o.file} — outside click ${o.outsideCloses ? "closes" : `does NOT close: ${o.why}`}`, () => {
      const src = read(o.file);
      // A backdrop that closes is `onClick` on the full-screen layer itself.
      const backdropCloses = /className="fixed inset-0[^"]*"[\s\S]{0,200}?onClick=\{\(\) =>/.test(src);
      expect(backdropCloses).toBe(o.outsideCloses);
    });
  }

  it("SpawnStudio no longer closes on a background click", () => {
    // The single most important assertion in this file: this is the one that
    // was already losing work, not a gap being filled.
    const src = read("components/SpawnStudio.tsx");
    const dialogOpen = src.slice(src.indexOf('data-testid="spawn-studio"') - 400,
                                 src.indexOf('data-testid="spawn-studio"') + 200);
    expect(dialogOpen).not.toMatch(/onClick=\{onClose\}/);
  });
});

// ---------------------------------------------------------------------------
// Ruling ①A — Escape is safe in an editor
// ---------------------------------------------------------------------------

describe("Escape in an editor", () => {
  it("asks before discarding when the editor is dirty", () => {
    const src = read("components/SpawnStudio.tsx");
    expect(src).toContain("DiscardChangesBar");
    // The guard, not just the component: closing must go through the dirty check.
    expect(src).toMatch(/dirty \? setConfirmingClose\(true\) : onClose\(\)/);
  });

  it("computes dirty from what the mode ACTUALLY edits", () => {
    // Discriminating, and it caught a real error: the first version compared
    // name/description/domain against `detail`. SpawnDetail has no
    // `description`, and in EDIT mode those three are never populated from the
    // loaded spawn — they belong to CREATE. Edit mode edits the equipment sets.
    const src = read("components/SpawnStudio.tsx");
    expect(src).toContain("baselineEquip");
    expect(src).not.toMatch(/detail\.description/);
  });

  it("snapshots the baseline into new Sets", () => {
    // Sharing the Set objects would move the baseline with every edit, so
    // `dirty` would be permanently false — a confirm dialog that never fires
    // looks exactly like a working one.
    const src = read("components/SpawnStudio.tsx");
    expect(src).toMatch(/setBaselineEquip\(\{ toolsets: new Set\(ts0\), skills: new Set\(sk0\) \}\)/);
  });
});

describe("DiscardChangesBar", () => {
  it("offers both ways out and does not close by itself", () => {
    const onDiscard = vi.fn(), onCancel = vi.fn();
    render(<DiscardBar onDiscard={onDiscard} onCancel={onCancel} />);
    fireEvent.click(screen.getByText("common.keep_editing"));
    expect(onCancel).toHaveBeenCalled();
    expect(onDiscard).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId("discard-confirm"));
    expect(onDiscard).toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// The one overlay whose resistance is a FEATURE
// ---------------------------------------------------------------------------

describe("the first-run wizard resists both", () => {
  it("is not wired to the dismissal hook at all", () => {
    // Without this, a later reader sweeping "everything should close on Escape"
    // will helpfully make it possible to skip setup with a keystroke.
    const src = read("components/FirstRunWizard.tsx");
    expect(src).not.toContain("useDismissable");
    expect(src).not.toMatch(/className="fixed inset-0[^"]*"[\s\S]{0,200}?onClick=\{\(\) =>/);
  });
});


// ---------------------------------------------------------------------------
// The option itself, at RUNTIME.
//
// 🔴 Added because a mutation deleting `if (!outsideClick) return;` from the
// hook stayed GREEN: every test above asserts SOURCE SHAPE (no backdrop
// onClick), which proves a string is absent from a file, not that a stray
// click leaves the editor open. Same lesson as the settings round — a grep
// hit is not a user-visible behaviour.
// ---------------------------------------------------------------------------

import { useDismissable } from "../hooks/useDismissable";

function Probe({ outsideClick, onClose }: { outsideClick: boolean; onClose: () => void }) {
  const { anchorRef, floatingRef } = useDismissable<HTMLDivElement, HTMLDivElement>(
    true, onClose, { outsideClick });
  return (
    <div ref={anchorRef}>
      <div ref={floatingRef} data-testid="probe-panel">panel</div>
    </div>
  );
}

describe("useDismissable({ outsideClick: false })", () => {
  it("ignores an outside click", () => {
    const onClose = vi.fn();
    render(<Probe outsideClick={false} onClose={onClose} />);
    fireEvent.mouseDown(document.body);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("still closes on Escape", () => {
    // The half that must keep working: Escape is deliberate, a background
    // click is not. An option that switched BOTH off would satisfy the test
    // above and leave editors with no keyboard exit at all.
    const onClose = vi.fn();
    render(<Probe outsideClick={false} onClose={onClose} />);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("the default still closes on an outside click", () => {
    // ⓪ Proves the probe can observe the behaviour at all — without this, the
    // first test passes even if the listener were never attached.
    const onClose = vi.fn();
    render(<Probe outsideClick onClose={onClose} />);
    fireEvent.mouseDown(document.body);
    expect(onClose).toHaveBeenCalledOnce();
  });
});
