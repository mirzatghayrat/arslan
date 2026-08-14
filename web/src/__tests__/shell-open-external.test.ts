/** The doorway to the OS browser: present in the shell, silent in a browser. */
import { afterEach, describe, expect, it, vi } from "vitest";

import { openExternal, shellAvailable } from "../lib/shell";

type W = Window & { __TAURI_INTERNALS__?: { invoke: ReturnType<typeof vi.fn> } };
const win = window as unknown as W;

afterEach(() => { delete win.__TAURI_INTERNALS__; });

describe("openExternal", () => {
  it("no-ops in a plain browser", async () => {
    expect(shellAvailable()).toBe(false);
    await openExternal("https://x.example");   // must not throw
  });

  it("invokes the shell command with the url", async () => {
    const invoke = vi.fn(async () => undefined);
    win.__TAURI_INTERNALS__ = { invoke };
    await openExternal("https://accounts.example/authorize");
    expect(invoke).toHaveBeenCalledWith("open_external", { url: "https://accounts.example/authorize" });
  });

  it("swallows a shell refusal instead of crashing the caller", async () => {
    win.__TAURI_INTERNALS__ = { invoke: vi.fn(async () => { throw new Error("refused"); }) };
    await openExternal("http://nope.example");  // resolves, no throw
  });
});
