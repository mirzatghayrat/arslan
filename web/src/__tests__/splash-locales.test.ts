import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../../desktop");
const html = readFileSync(resolve(root, "splash/index.html"), "utf8");
const catalog = JSON.parse(readFileSync(resolve(root, "src-tauri/native_messages.json"), "utf8"));
const script = html.match(/<script>([\s\S]*?)<\/script>/)![1];
type SplashWindow = Window & typeof globalThis & {
  __ARSLAN_BOOT_COPY__?: { locale: string; starting: string; slow: string };
  __arslanBootError?: (message: string) => void;
  __arslanFadeOut?: () => void;
};
const splash = window as SplashWindow;

afterEach(() => {
  vi.useRealTimers(); vi.unstubAllGlobals();
  document.body.innerHTML = "";
  document.documentElement.lang = "en";
  delete splash.__ARSLAN_BOOT_COPY__;
  delete splash.__arslanBootError;
  delete splash.__arslanFadeOut;
});

describe("bundled splash executes localized display copy", () => {
  it("keeps the English fallback and cancels a pending wait notice on early failure", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("synthetic missing clip")));
    document.body.innerHTML = html.replace(/<script>[\s\S]*?<\/script>/, "");
    new Function(script)();
    expect(document.getElementById("starting")?.textContent).toBe(catalog.en.boot_starting);
    expect(document.getElementById("slow")?.textContent).toBe(catalog.en.boot_slow);
    splash.__arslanBootError!(catalog.en.boot_failed);
    await vi.advanceTimersByTimeAsync(6000);
    expect(document.getElementById("slow")).not.toHaveClass("shown");
    expect(document.getElementById("slow")).not.toBeVisible();
  });

  it.each(["en", "zh", "ja", "es", "de", "fr"])("uses native %s data and hides waiting text on failure", async locale => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("synthetic missing clip")));
    document.body.innerHTML = html.replace(/<script>[\s\S]*?<\/script>/, "");
    splash.__ARSLAN_BOOT_COPY__ = {
      locale, starting: catalog[locale].boot_starting, slow: catalog[locale].boot_slow,
    };
    // Execute the actual trusted bundled page script, not a reimplementation.
    new Function(script)();
    await Promise.resolve();
    expect(document.documentElement.lang).toBe(locale);
    expect(document.getElementById("starting")?.textContent).toBe(catalog[locale].boot_starting);
    expect(document.getElementById("slow")?.textContent).toBe(catalog[locale].boot_slow);
    await vi.advanceTimersByTimeAsync(5000);
    expect(document.getElementById("slow")).toHaveClass("shown");
    const error = catalog[locale].boot_failed + '\n\n<script>window.injected=true</script>';
    splash.__arslanBootError!(error);
    expect(document.getElementById("failed")?.textContent).toBe(error);
    expect(document.getElementById("failed")?.querySelector("script")).toBeNull();
    expect(document.getElementById("slow")).not.toHaveClass("shown");
    expect(document.getElementById("slow")).not.toBeVisible();
    expect(document.getElementById("fallback")).not.toBeVisible();
  });
});
