import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { resolve } from "node:path";
import { createInterface } from "node:readline";
import { afterEach, expect, it } from "vitest";

const root = resolve(process.cwd(), "..");
const children: ChildProcessWithoutNullStreams[] = [];
async function runtime() {
  const child = spawn(process.execPath, [resolve(root, "server/resources/browser_reader.cjs"),
    resolve(root, "scripts/fixtures/browser_reader_runtime.cjs"), "unused", "unused"],
    { env: { PATH: "/usr/bin:/bin" }, stdio: "pipe" });
  children.push(child);
  const lines = createInterface({ input: child.stdout })[Symbol.asyncIterator]();
  async function next() {
    const line = await lines.next();
    if (line.done) throw new Error("Reader exited before replying");
    return JSON.parse(line.value);
  }
  expect(await next()).toEqual({ ready: true });
  return async (request: Record<string, unknown>) => {
    child.stdin.write(JSON.stringify(request) + "\n");
    return next();
  };
}
afterEach(async () => {
  await Promise.all(children.splice(0).map(child => new Promise<void>(resolve => {
    if (child.exitCode !== null || child.signalCode !== null) return resolve();
    child.once("exit", () => resolve());
    child.kill("SIGKILL");
  })));
});

it.each(["capture-fails", "title-fails", "oversize", "goto-fails"])(
  "rejects old frame IDs after %s without following a newly captured link", async path => {
    const act = await runtime();
    const first = await act({ action: "navigate", url: "https://example.com/original" });
    expect(first.ok).toBe(true);
    expect((await act({ action: "navigate", url: `https://example.com/${path}` })).ok).toBe(false);
    expect(await act({ action: "link", link_id: first.links[0].id, revision: first.revision }))
      .toEqual({ ok: false, code: "browser.stale_view" });
    if (path === "capture-fails") {
      expect(await act({ action: "refresh" })).toMatchObject({ ok: true, url: "https://example.com/capture-fails" });
    }
    const recovered = await act({ action: "navigate", url: "https://example.com/recovered" });
    expect(recovered.ok).toBe(true);
    expect(recovered.revision).toBeGreaterThan(first.revision);
    const followed = await act({ action: "link", link_id: recovered.links[0].id, revision: recovered.revision });
    expect(followed.url).toBe("https://example.com/recovered/target");
  });

it("does not consume a failed back or forward step", async () => {
  const act = await runtime();
  const a = "https://example.com/a-history-fails-once";
  const b = "https://example.com/b-history-fails-once";
  await act({ action: "navigate", url: a });
  await act({ action: "navigate", url: b });
  expect((await act({ action: "back" })).ok).toBe(false);
  const back = await act({ action: "back" });
  expect(back).toMatchObject({ ok: true, url: a, can_back: false, can_forward: true });
  expect((await act({ action: "forward" })).ok).toBe(false);
  expect(await act({ action: "forward" })).toMatchObject({ ok: true, url: b, can_back: true, can_forward: false });
});

it("invalidates a frame when scrolling fails, and refresh publishes a fresh one", async () => {
  const act = await runtime();
  const first = await act({ action: "navigate", url: "https://example.com/scroll-fails" });
  expect((await act({ action: "scroll", direction: 1 })).ok).toBe(false);
  expect(await act({ action: "link", link_id: first.links[0].id, revision: first.revision }))
    .toEqual({ ok: false, code: "browser.stale_view" });
  expect(await act({ action: "refresh" })).toMatchObject({ ok: true, revision: first.revision + 1 });
});

it("records the actual location after refreshing a partially navigated page", async () => {
  const act = await runtime();
  await act({ action: "navigate", url: "https://example.com/original" });
  await act({ action: "navigate", url: "https://example.com/capture-fails" });
  expect(await act({ action: "refresh" })).toMatchObject({ ok: true, url: "https://example.com/capture-fails", can_back: true });
  expect(await act({ action: "back" })).toMatchObject({ ok: true, url: "https://example.com/original", can_forward: true });
});
