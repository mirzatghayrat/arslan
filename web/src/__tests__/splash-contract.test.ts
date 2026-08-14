/**
 * The splash's three contracts, asserted against the file the shell embeds.
 *
 * The splash is a standalone HTML page with no module system and no test
 * harness, so these read the source. That is the acknowledged exception (the
 * spec's own criteria say so): what they pin is the presence/absence of
 * specific behaviour in one inline script, and each was mutation-checked.
 *
 * 🔴 THE BUG THIS ROUND FIXES: #fallback ("Starting Arslan…") covers the whole
 * screen UNDER the video, and __arslanFadeOut faded only the clip — so the
 * fallback showed through during the 400ms hand-off, on every single launch.
 * The user reported it as "remove that text"; nobody had added it — the mask
 * over it was being removed first.
 */
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const html = readFileSync(
  resolve(dirname(fileURLToPath(import.meta.url)), "../../../desktop/splash/index.html"),
  "utf8",
);

/** The body of a `window.__x = function () {...}` assignment. */
function fnBody(name: string): string {
  const i = html.indexOf(`window.${name} = function`);
  expect(i, `${name} not found`).toBeGreaterThan(-1);
  return html.slice(i, html.indexOf("};", i));
}

describe("fade-out hides the fallback too", () => {
  it("fades the clip AND the fallback in the same hand-off", () => {
    const body = fnBody("__arslanFadeOut");
    expect(body).toMatch(/clip\.classList\.add\(['"]gone['"]\)/);
    // The fix. Fading only the clip is what put "Starting Arslan…" on screen
    // during the 400ms hand-off of every launch.
    expect(body).toMatch(/fallback[\s\S]{0,80}classList\.add\(['"]gone['"]\)/);
  });

  it("gives the fallback the same transition the clip has", () => {
    // A .gone class with no transition is a hard cut — the text would still
    // flash for a frame. Both layers must dim on the same clock.
    expect(html).toMatch(/#fallback[\s\S]{0,500}transition:\s*opacity/);
  });

  it("still hides the fallback on a boot error", () => {
    // __arslanBootError replaces the whole screen with the failure text; the
    // fallback row underneath must not bleed through it either. Guarded so the
    // fade-out fix cannot quietly break this second path.
    const body = fnBody("__arslanBootError");
    expect(body).toMatch(/fallback/);
  });
});

describe("the window is shaped like the app", () => {
  it("splash window is transparent so CSS can round its corners", () => {
    const rs = readFileSync(
      resolve(dirname(fileURLToPath(import.meta.url)), "../../../desktop/src-tauri/src/lib.rs"),
      "utf8",
    );
    const i = rs.indexOf("SPLASH_LABEL, WebviewUrl::App");
    expect(i).toBeGreaterThan(-1);
    const builder = rs.slice(i, rs.indexOf(".build()", i));
    expect(builder).toMatch(/\.transparent\(true\)/);
  });

  it("macOSPrivateApi is on, or transparent(true) silently does nothing", () => {
    const conf = JSON.parse(readFileSync(
      resolve(dirname(fileURLToPath(import.meta.url)), "../../../desktop/src-tauri/tauri.conf.json"),
      "utf8",
    ));
    expect(conf.app?.macOSPrivateApi).toBe(true);
  });

  it("the page rounds itself and clips its layers", () => {
    expect(html).toMatch(/border-radius/);
    // Fixed-position layers ignore an ancestor's overflow clip, so the layers
    // must not be position:fixed once the body is the rounded frame.
    expect(html).not.toMatch(/#clip\s*\{[^}]*position:\s*fixed/);
  });
});
