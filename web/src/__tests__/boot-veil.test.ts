/**
 * Behaviour of the boot veil — the SPA's half of the desktop launch hand-off.
 *
 * These drive a real DOM and assert what is on it, rather than asserting that
 * bootVeil.ts contains certain lines. The distinction matters here more than
 * usual: every failure mode of this feature is silent. A veil that never fades
 * looks like a hung app with no error; a veil that fades too early looks like a
 * launch flash; a veil that fades but is never removed looks like an app that
 * ignores clicks. None of them log anything, and a source-level assertion would
 * stay green through all three.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BOOT_VEIL_FADE_MS, BOOT_VEIL_ID, dismissBootVeil } from "../lib/bootVeil";

function mountVeil(): HTMLElement {
  document.body.innerHTML = `<div id="${BOOT_VEIL_ID}"></div><div id="root">app</div>`;
  return document.getElementById(BOOT_VEIL_ID) as HTMLElement;
}

describe("dismissBootVeil", () => {
  beforeEach(() => {
    vi.useRealTimers();
    document.body.innerHTML = "";
  });

  it("fades the veil out instead of removing it on the spot", () => {
    const veil = mountVeil();
    vi.useFakeTimers();

    dismissBootVeil(document);

    // Still present, now transparent: an instant removal would expose the page
    // in one frame, which is the cut this exists to replace with a fade.
    expect(document.getElementById(BOOT_VEIL_ID)).not.toBeNull();
    expect(veil.style.opacity).toBe("0");
  });

  it("removes the veil from the DOM once the fade is over", () => {
    mountVeil();
    vi.useFakeTimers();

    dismissBootVeil(document);
    expect(document.getElementById(BOOT_VEIL_ID)).not.toBeNull();

    vi.advanceTimersByTime(BOOT_VEIL_FADE_MS);

    // Not "invisible" — gone. A veil parked at opacity 0 is one CSS edit away
    // from a window that silently swallows every click.
    expect(document.getElementById(BOOT_VEIL_ID)).toBeNull();
  });

  it("keeps the veil up for the whole fade, not part of it", () => {
    mountVeil();
    vi.useFakeTimers();

    dismissBootVeil(document);
    vi.advanceTimersByTime(BOOT_VEIL_FADE_MS - 1);

    expect(document.getElementById(BOOT_VEIL_ID)).not.toBeNull();
  });

  it("cancels the dead-man's-switch animation before setting opacity", () => {
    const veil = mountVeil();
    // index.html gives the veil `animation: … forwards` as a fallback for a
    // bundle that never loads. A running `forwards` animation outranks inline
    // styles, so leaving it in place would pin the veil visible until 2.5s no
    // matter what opacity we set — the fade would simply not happen, and
    // nothing would report it.
    veil.style.animation = "boot-veil-deadman 350ms ease-out 2500ms forwards";

    dismissBootVeil(document);

    expect(veil.style.animation).toBe("none");
  });

  it("does nothing when there is no veil", () => {
    // The browser path: index.html removes the veil during parse when the
    // desktop shell has not asked for a fade. This must not throw.
    document.body.innerHTML = `<div id="root">app</div>`;
    expect(() => dismissBootVeil(document)).not.toThrow();
  });

  it("is safe to call twice", () => {
    mountVeil();
    vi.useFakeTimers();

    dismissBootVeil(document);
    dismissBootVeil(document);
    vi.advanceTimersByTime(BOOT_VEIL_FADE_MS);

    expect(document.getElementById(BOOT_VEIL_ID)).toBeNull();
  });
});
