import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, expect, it } from "vitest";

const root = resolve(process.cwd(), "../desktop");
const html = readFileSync(resolve(root, "splash/recovery.html"), "utf8");
const script = html.match(/<script>([\s\S]*?)<\/script>/)![1];
const messages = JSON.parse(readFileSync(resolve(root, "src-tauri/recovery_messages.json"), "utf8"));

afterEach(() => { document.body.innerHTML = ""; });

it("renders working and paused recovery text in all six languages without interpreting markup", () => {
  document.body.innerHTML = html.replace(/<script>[\s\S]*?<\/script>/, "");
  const host: Record<string, unknown> = {};
  new Function("window", "document", script)(host, document);
  for (const locale of ["en", "zh", "ja", "es", "de", "fr"]) {
    for (const paused of [false, true]) {
      const heading = messages[locale][paused ? "restore_paused_title" : "restore_working"];
      const detail = messages[locale][paused ? "restore_paused" : "restore_working_body"];
      host.__ARSLAN_RECOVERY_COPY__ = { locale, heading, detail };
      (host.__arslanRenderRecovery as () => void)();
      expect(document.documentElement.lang).toBe(locale);
      expect(document.title).toBe(heading);
      expect(document.getElementById("heading")!.textContent).toBe(heading);
      expect(document.getElementById("detail")!.textContent).toBe(detail);
    }
  }
  const markup = '<img src=x onerror="window.injected=true">';
  host.__ARSLAN_RECOVERY_COPY__ = { heading: markup, detail: markup };
  (host.__arslanRenderRecovery as () => void)();
  expect(document.getElementById("detail")!.textContent).toBe(markup);
  expect(document.querySelector("img, input, textarea, button, form, a, iframe")).toBeNull();
  expect(host.injected).toBeUndefined();
  expect(html).toContain("default-src 'none'");
});

it("does not grant the recovery display native IPC permissions", () => {
  const directory = resolve(root, "src-tauri/capabilities");
  for (const file of readdirSync(directory).filter(name => name.endsWith(".json"))) {
    const capability = JSON.parse(readFileSync(resolve(directory, file), "utf8"));
    // Explicit window-only grants prevent accidental wildcard/local-webview
    // access from turning the display surface into a second command client.
    expect(capability.windows).toEqual(["main"]);
    expect(capability.webviews ?? []).toEqual([]);
  }
});
