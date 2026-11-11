/**
 * IMG1-B: the main window's CSP is `font-src 'self'` (server/main.py), so the build must never inline a font as a
 * data: URL. Vite does that to any asset under 4 KiB unless told otherwise, and KaTeX_Size3's woff2 (3.6 KB) was one:
 * real WebKit refused it under the policy.
 *
 * This loads the project's own vite.config.ts the way Vite does and builds a tiny font with its asset rule, so dropping
 * the rule from the config fails here. In a child Node: esbuild refuses to run under jsdom.
 */
import { execFileSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const WEB = resolve(dirname(fileURLToPath(import.meta.url)), "../..");

const BUILD_A_FONT = `
import { mkdtempSync, readdirSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { build, loadConfigFromFile } from "vite";

const { config } = await loadConfigFromFile({ command: "build", mode: "production" }, "vite.config.ts", process.cwd(), "silent");
// Real path: macOS's temp dir is behind a symlink, and Rollup refuses an output name that climbs out of the root.
const root = realpathSync(mkdtempSync(join(tmpdir(), "arslan-fonts-")));
// Different bytes each: Vite emits identical files once.
["woff2", "woff", "ttf"].forEach((kind, i) => writeFileSync(join(root, "tiny." + kind), Buffer.alloc(512, i + 1)));
writeFileSync(join(root, "style.css"), "@font-face{font-family:Tiny;src:url(./tiny.woff2) format('woff2'),"
  + "url(./tiny.woff) format('woff'),url(./tiny.ttf) format('truetype')}");
writeFileSync(join(root, "index.html"), '<!doctype html><link rel="stylesheet" href="./style.css">');
async function css(assetsInlineLimit, out) {
  const outDir = join(root, out);
  await build({ root, configFile: false, logLevel: "silent", build: { outDir, emptyOutDir: true, assetsInlineLimit } });
  const name = readdirSync(join(outDir, "assets")).find((f) => f.endsWith(".css"));
  return readFileSync(join(outDir, "assets", name), "utf8");
}
const result = { project: await css(config.build.assetsInlineLimit, "project"), viteDefault: await css(undefined, "default") };
rmSync(root, { recursive: true, force: true });
process.stdout.write(JSON.stringify(result));
`;

describe("fonts in the build", () => {
  const built = JSON.parse(execFileSync(process.execPath, ["--input-type=module", "-e", BUILD_A_FONT], {
    cwd: WEB, encoding: "utf8", timeout: 60_000,
  })) as { project: string; viteDefault: string };

  it("are files the page loads from its own origin, not data: URLs", () => {
    expect(built.project).not.toContain("data:");
    for (const kind of ["woff2", "woff", "ttf"]) expect(built.project).toMatch(new RegExp(`url\\(/assets/tiny-[\\w-]+\\.${kind}\\)`));
  });

  it("would be inlined by Vite's default (the control)", () => {
    for (const kind of ["woff2", "woff", "ttf"]) expect(built.viteDefault).toContain(`data:font/${kind};base64,`);
  });
});
