/**
 * IMG1-B follow-up (v0.1.64): the splash's Content-Security-Policy.
 *
 * The splash (desktop/splash/index.html) loads on Tauri's own protocol, not
 * from the sidecar, so no server header reaches it. tauri.conf.json's
 * `security.csp` is null, so Tauri neither rewrites the page nor adds a header
 * (tauri-codegen only touches HTML when a CSP is configured), and the policy is
 * a <meta http-equiv> in the file, as recovery.html already has. These pin it
 * exactly, with the hashes computed from the file's own inline script and style.
 */
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const DESKTOP = resolve(dirname(fileURLToPath(import.meta.url)), "../../../desktop");
const html = readFileSync(resolve(DESKTOP, "splash/index.html"), "utf8");

const sha256 = (text: string) => `'sha256-${createHash("sha256").update(text, "utf8").digest("base64")}'`;

/** The text of the page's only element of this kind. */
function only(tag: "script" | "style"): string {
  const found = [...html.matchAll(new RegExp(`<${tag}\\b[^>]*>([\\s\\S]*?)</${tag}>`, "gi"))];
  expect(found, `the splash should have exactly one <${tag}>`).toHaveLength(1);
  return found[0][1];
}

function metaPolicies(): string[] {
  return [...html.matchAll(/<meta\b[^>]*http-equiv=["']?content-security-policy["']?[^>]*>/gi)].map((m) => {
    const content = m[0].match(/\bcontent="([^"]*)"/i);
    expect(content, m[0]).not.toBeNull();
    return content![1];
  });
}

/** As a browser reads it: `;`-separated, names case-insensitive; a repeated directive fails. */
function parse(policy: string): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const part of policy.split(";")) {
    const [name, ...sources] = part.trim().split(/\s+/);
    if (!name) continue;
    expect(out, `${name} appears twice`).not.toHaveProperty(name.toLowerCase());
    out[name.toLowerCase()] = [...sources].sort();
  }
  return out;
}

describe("the splash's policy", () => {
  it("is exactly what the page uses", () => {
    const policies = metaPolicies();
    expect(policies).toHaveLength(1);
    expect(parse(policies[0])).toEqual({
      // Nothing that isn't listed: no image, font, frame, object, worker.
      "default-src": ["'none'"],
      // The page's one inline script and one inline style, by hash. Native code
      // reaches the page through WKUserScripts and evaluateJavaScript, which a
      // page policy doesn't gate.
      "script-src": [sha256(only("script"))],
      "style-src": [sha256(only("style"))],
      // fetch(arslan-splash.mp4) from the page's own origin (tauri://localhost).
      "connect-src": ["'self'"],
      // The clip plays from the blob: URL made from that fetch.
      "media-src": ["blob:"],
      "base-uri": ["'none'"],
      "form-action": ["'none'"],
    });
  });

  it("comes before anything it governs", () => {
    // A <meta> policy applies only to what the parser meets after it.
    const meta = html.search(/<meta\b[^>]*http-equiv=["']?content-security-policy/i);
    expect(meta).toBeGreaterThan(-1);
    expect(meta).toBeLessThan(html.search(/<style\b/i));
    expect(meta).toBeLessThan(html.search(/<script\b/i));
    expect(meta).toBeLessThan(html.search(/<video\b/i));
  });

  it("leaves nothing in the markup that a hash can't allow", () => {
    // Hashes allow <style> and <script> elements only: a style="" or on*=""
    // attribute would be refused.
    const markup = html
      .replace(/<!--[\s\S]*?-->/g, "")
      .replace(/<script\b[\s\S]*?<\/script>/gi, "")
      .replace(/<style\b[\s\S]*?<\/style>/gi, "");
    expect(markup).not.toMatch(/\sstyle\s*=/i);
    expect(markup).not.toMatch(/\son[a-z]+\s*=/i);
  });

  it("fetches its clip from its own origin", () => {
    const clip = html.match(/<video[^>]*\bdata-clip="([^"]+)"/);
    expect(clip).not.toBeNull();
    expect(clip![1]).not.toMatch(/:|^\/\//);
  });

  it("is the only policy: Tauri's own is off, so it neither rewrites the page nor adds a header", () => {
    // A security.csp here would apply to every Tauri-protocol page (this one
    // and recovery.html), and Tauri would rewrite their inline scripts.
    const conf = JSON.parse(readFileSync(resolve(DESKTOP, "src-tauri/tauri.conf.json"), "utf8"));
    expect(conf.app.security.csp).toBeNull();
    expect(conf.app.security.devCsp ?? null).toBeNull();
    expect(conf.app.security.headers ?? null).toBeNull();
  });
});
