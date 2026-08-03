/**
 * Lockstep guard for the desktop launch hand-off.
 *
 * The hand-off works by having four independent things agree on one colour and
 * two durations. They live in a Rust file, two HTML files and an mp4, and there
 * is no runtime at which any two of them meet — the splash window and the main
 * window are different processes' worth of webview, on different origins, and
 * the video's fade is baked into pixels. So there is nothing to observe, and
 * this file asserts on source text.
 *
 * That is the narrow case where a source-level assertion is the right tool:
 * what is being asserted IS "these literals are equal", not "this behaviour
 * happens". (See the constitution note on assert-behaviour-not-source — the
 * dividing line is that asserting *behaviour* requires observing behaviour.)
 *
 * The failure this prevents is a re-encode or a palette tweak that puts the
 * launch flash back. That failure is visible to a human on the very next
 * launch, which is why a text guard is proportionate here rather than the
 * per-frame decode used when the asset was cut.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const REPO = join(__dirname, "..", "..", "..");
const read = (p: string) => readFileSync(join(REPO, p), "utf8");

/**
 * Drop HTML and CSS comments.
 *
 * Needed because these files explain themselves at length, and the splash page
 * documents the very rule asserted below ("not `color-scheme: light dark`") —
 * which a naive text match reads as a violation. Matching prose instead of code
 * is the standing failure mode of any guard that greps: it can fail on a file
 * that is correct, and it can pass on a file whose only mention of the right
 * thing is a comment saying it should be done.
 */
const code = (src: string) =>
  src.replace(/<!--[\s\S]*?-->/g, "").replace(/\/\*[\s\S]*?\*\//g, "");

/**
 * The one colour. Verified per-frame against the shipped clip when it was cut:
 * frame 0 and frame 95 of desktop/splash/arslan-splash.mp4 both decode to
 * exactly this value, which is what lets either end of the clip be swapped away
 * from without a step.
 */
const HANDOFF_BG = "#17150f";

describe("launch hand-off constants", () => {
  it("uses one background colour on both sides of the swap", () => {
    const splash = code(read("desktop/splash/index.html")).toLowerCase();
    const spa = code(read("web/index.html")).toLowerCase();

    expect(splash).toContain(`--arslan-boot-bg: ${HANDOFF_BG}`);
    expect(spa).toContain(`background: ${HANDOFF_BG}`);
  });

  it("never lets the splash pick a colour from the OS appearance", () => {
    // The splash is matched against fixed video pixels, so a light/dark switch
    // there would tear the clip away from its own background in one appearance
    // and nobody would see it unless they happened to be in that appearance.
    const splash = code(read("desktop/splash/index.html"));
    expect(splash).not.toMatch(/prefers-color-scheme/);
    expect(splash).not.toMatch(/color-scheme:\s*light dark/);
  });

  it("waits in Rust for exactly as long as the page fades", () => {
    const rust = read("desktop/src-tauri/src/lib.rs");
    const html = code(read("desktop/splash/index.html"));

    const rustMs = rust.match(
      /const SPLASH_FADE_OUT:[^=]+=\s*std::time::Duration::from_millis\((\d+)\)/,
    );
    const cssMs = html.match(/#clip\s*\{[^}]*transition:\s*opacity\s+(\d+)ms/s);

    expect(rustMs, "SPLASH_FADE_OUT not found in lib.rs").not.toBeNull();
    expect(cssMs, "#clip opacity transition not found in the splash page").not.toBeNull();
    // Too short in Rust swaps mid-fade; too long adds dead time to every
    // launch. Either way nothing errors, so only this comparison catches it.
    expect(Number(rustMs![1])).toBe(Number(cssMs![1]));
  });

  it("keeps the splash asset and the page that plays it in agreement", () => {
    const html = code(read("desktop/splash/index.html"));
    const src = html.match(/<video[^>]*\bsrc="([^"]+)"/);
    expect(src, "the splash page no longer references a clip").not.toBeNull();
    // Throws if the file is missing — which is the whole point, since a missing
    // asset degrades to the pulsing-dot fallback and looks deliberate.
    expect(readFileSync(join(REPO, "desktop/splash", src![1])).byteLength).toBeGreaterThan(0);
  });
});
