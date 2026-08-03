/**
 * The v0.1.18 batch's behavioural halves, tested as behaviour.
 *
 * 🔴 Written because three mutations of this batch all stayed GREEN: "system"
 * theme resolving to a fixed value, the OS-change listener deleted, and the
 * inbound-MCP token control shown regardless of the toggle. Nothing in the
 * suite was watching any of them — the existing tests cover rendering, not the
 * rules the batch added.
 *
 * Same lesson as the round before: a change is only tested if a wrong version
 * of it fails something.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

beforeEach(() => {
  localStorage.clear();
  vi.resetModules();
  document.documentElement.className = "";
});

/** Install a matchMedia whose value we control, and capture its listener. */
function fakeMatchMedia(prefersDark: boolean) {
  const listeners: (() => void)[] = [];
  const mq = {
    matches: prefersDark,
    addEventListener: (_: string, fn: () => void) => listeners.push(fn),
    removeEventListener: () => {},
    addListener: (fn: () => void) => listeners.push(fn),
    removeListener: () => {},
  };
  Object.defineProperty(window, "matchMedia", {
    value: () => mq, configurable: true, writable: true,
  });
  return {
    /** Flip the OS preference and fire the change, as the OS would. */
    flip(toDark: boolean) { mq.matches = toDark; listeners.forEach((f) => f()); },
    listenerCount: () => listeners.length,
  };
}

describe('theme mode "system"', () => {
  it("follows the OS at load", async () => {
    fakeMatchMedia(false);                       // OS says light
    localStorage.setItem("arslan_theme", JSON.stringify({ palette: "current", mode: "system" }));
    await import("../stores/themeStore");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("keeps following when the OS changes later", async () => {
    // The whole promise of the option. Reading the preference once at launch
    // and never again looks exactly like a broken setting when the user's Mac
    // switches to dark at sunset.
    const os = fakeMatchMedia(false);
    localStorage.setItem("arslan_theme", JSON.stringify({ palette: "current", mode: "system" }));
    await import("../stores/themeStore");
    expect(document.documentElement.classList.contains("dark")).toBe(false);

    os.flip(true);
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("does NOT follow the OS when an explicit mode is chosen", async () => {
    // Discriminating: a listener that ignored the stored mode would satisfy the
    // test above and override a user who deliberately picked light.
    const os = fakeMatchMedia(false);
    localStorage.setItem("arslan_theme", JSON.stringify({ palette: "current", mode: "light" }));
    await import("../stores/themeStore");

    os.flip(true);
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("resolves system to the OS value, not to a constant", async () => {
    fakeMatchMedia(true);                        // OS says dark
    localStorage.setItem("arslan_theme", JSON.stringify({ palette: "current", mode: "system" }));
    const { useThemeStore } = await import("../stores/themeStore");
    expect(useThemeStore.getState().mode).toBe("system");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });
});

describe("the inbound-MCP token control", () => {
  async function renderAccess(enabled: boolean) {
    vi.doMock("../stores/authStore", () => ({
      useAuthStore: Object.assign((sel: (s: unknown) => unknown) => sel({ token: "" }),
        { getState: () => ({ token: "", setToken: vi.fn() }) }),
    }));
    const { default: AccessTokenSettings } = await import("../components/AccessTokenSettings");
    render(<AccessTokenSettings backendStatus="online" mcpServerEnabled={enabled}
                                onMcpServerChange={vi.fn()} />);
  }

  it("is hidden while the inbound server is off", async () => {
    await renderAccess(false);
    expect(screen.queryByText(/mcpToken/i)).toBeNull();
  });

  it("appears once it is on", async () => {
    // Discriminating: hiding it unconditionally would satisfy the test above and
    // remove the only way to mint the token.
    await renderAccess(true);
    expect(screen.queryByText(/mcpToken/i)).not.toBeNull();
  });
});
