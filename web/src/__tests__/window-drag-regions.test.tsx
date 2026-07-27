/** The window must be draggable from the top bar on EVERY view, not just chat.
 *
 * The bar is rendered once in App.tsx and shared by all sections, so this
 * pins the attribute at its single source. A shell-side counterpart lives in
 * tests/test_shell_window_config.py (the drag-drop handler must stay off, or
 * HTML5 drop targets go dead in the packaged app). */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const APP = readFileSync(join(__dirname, "..", "App.tsx"), "utf8");

describe("window drag regions", () => {
  it("the shared workspace bar is a drag region", () => {
    const bar = APP.slice(APP.indexOf('data-testid="workspace-bar"') - 200,
                          APP.indexOf('data-testid="workspace-bar"') + 200);
    expect(bar).toContain('data-tauri-drag-region');
  });

  it("the bar is rendered ONCE — a per-section copy would drift", () => {
    // Discrimination: the reported symptom was "only the chat view can be
    // dragged". A fix that added the attribute to one section's own bar would
    // satisfy the assertion above and leave the other views broken.
    expect(APP.split('data-testid="workspace-bar"').length - 1).toBe(1);
  });
});
