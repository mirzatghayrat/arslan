import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, expect, it, vi } from "vitest";

const html = readFileSync(resolve(process.cwd(), "../desktop/splash/index.html"), "utf8");
const script = html.match(/<script>([\s\S]*?)<\/script>/)![1];
const messages = JSON.parse(readFileSync(resolve(process.cwd(), "../desktop/src-tauri/native_messages.json"), "utf8"));

afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = "";
});

it("refreshes the shipped splash DOM across all six locales after a profile change", () => {
  vi.useFakeTimers();
  document.body.innerHTML = html.replace(/<script>[\s\S]*?<\/script>/, "");
  const host: Record<string, unknown> = {};
  const copy = (locale: string) => ({ locale, starting: messages[locale].boot_starting, slow: messages[locale].boot_slow });
  host.__ARSLAN_BOOT_COPY__ = copy("en");
  // Exercise the shipped script, with media fetch left inert. No network or
  // animation capture is needed to verify text-only startup language changes.
  new Function("window", "document", "fetch", "setTimeout", "clearTimeout", "URL", script)(
    host, document, () => new Promise(() => {}), setTimeout, clearTimeout, URL,
  );
  for (const locale of ["zh", "ja", "es", "de", "fr", "en", "zh"]) {
    host.__ARSLAN_BOOT_COPY__ = copy(locale);
    (host.__arslanRefreshBootCopy as () => void)();
    expect(document.documentElement.lang).toBe(locale);
    expect(document.getElementById("starting")!.textContent).toBe(messages[locale].boot_starting);
    expect(document.getElementById("slow")!.textContent).toBe(messages[locale].boot_slow);
  }
  const untrusted = '<img src=x onerror="window.injected=true">';
  host.__ARSLAN_BOOT_COPY__ = { locale: "en", starting: untrusted, slow: untrusted };
  (host.__arslanRefreshBootCopy as () => void)();
  expect(document.getElementById("starting")!.textContent).toBe(untrusted);
  expect(document.getElementById("starting")!.querySelector("img")).toBeNull();
  expect(host.injected).toBeUndefined();
});
