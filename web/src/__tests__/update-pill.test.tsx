import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import UpdatePill from "../components/UpdatePill";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));

// Captures the event subscriber the component registers, so tests can push a
// status the way the Rust shell does. null until the component subscribes.
let pushStatus: ((s: { state: string; version: string; error: string }) => void) | null = null;
vi.mock("@tauri-apps/api/event", () => ({
  listen: vi.fn(async (_name: string, cb: (e: { payload: unknown }) => void) => {
    pushStatus = (s) => cb({ payload: s });
    return () => { pushStatus = null; };
  }),
}));

type W = Window & { __TAURI_INTERNALS__?: { invoke: ReturnType<typeof vi.fn> } };
const win = window as unknown as W;

function mockShell(status: { state: string; version?: string; error?: string }) {
  const invoke = vi.fn(async (cmd: string) =>
    cmd === "update_status"
      ? { state: status.state, version: status.version ?? "", error: status.error ?? "" }
      : undefined,
  );
  win.__TAURI_INTERNALS__ = { invoke };
  return invoke;
}

beforeEach(() => sessionStorage.clear());
afterEach(() => {
  cleanup();
  delete win.__TAURI_INTERNALS__;
});

describe("UpdatePill (v0.1.5 corner update UX)", () => {
  it("renders nothing in a plain browser (no Tauri IPC)", () => {
    render(<UpdatePill />);
    expect(screen.queryByTestId("update-pill")).toBeNull();
  });

  it("shows the pill when the shell staged an update, and Install invokes install_update", async () => {
    const invoke = mockShell({ state: "available", version: "0.1.6" });
    render(<UpdatePill />);
    await waitFor(() => expect(screen.getByTestId("update-pill")).toBeTruthy());
    expect(screen.getByText("updater.available")).toBeTruthy();
    fireEvent.click(screen.getByText("updater.install"));
    await waitFor(() => expect(invoke).toHaveBeenCalledWith("install_update"));
    // optimistic transition — the Install button must not offer a second click
    expect(screen.queryByText("updater.install")).toBeNull();
    expect(screen.getByText("updater.installing")).toBeTruthy();
  });

  it("Later dismisses THIS version for the session; a fresh version re-offers", async () => {
    mockShell({ state: "available", version: "0.1.6" });
    render(<UpdatePill />);
    await waitFor(() => expect(screen.getByTestId("update-pill")).toBeTruthy());
    fireEvent.click(screen.getByLabelText("updater.later"));
    expect(screen.queryByTestId("update-pill")).toBeNull();
    expect(sessionStorage.getItem("arslan-update-dismissed")).toBe("0.1.6");
    cleanup();
    // same version stays hidden on remount within the session…
    mockShell({ state: "available", version: "0.1.6" });
    render(<UpdatePill />);
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByTestId("update-pill")).toBeNull();
    cleanup();
    // …but a NEWER version must reappear despite the old dismissal
    mockShell({ state: "available", version: "0.1.7" });
    render(<UpdatePill />);
    await waitFor(() => expect(screen.getByTestId("update-pill")).toBeTruthy());
  });

  it("surfaces an install failure instead of pretending", async () => {
    mockShell({ state: "error", version: "0.1.6", error: "signature mismatch" });
    render(<UpdatePill />);
    await waitFor(() => expect(screen.getByText("updater.failed")).toBeTruthy());
    expect(screen.getByText("signature mismatch")).toBeTruthy();
    expect(screen.queryByText("updater.install")).toBeNull();
  });

  it("renders nothing for the pre-check default / unknown states (allow-list)", async () => {
    // The shell's state machine starts at "none"; a bug once made the default
    // an EMPTY string, which a deny-list (state !== 'none') would render as a
    // blank pill. Caught by the packaged IPC probe; pinned here.
    mockShell({ state: "" });
    render(<UpdatePill />);
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByTestId("update-pill")).toBeNull();
  });
});


describe("checking state (menu-triggered feedback)", () => {
  // 🔴 Why these exist: the check takes 1-3s and the pill polls every 60s, so
  // without the event push the state would end between two polls and the
  // feature would be invisible. The event path is therefore not an
  // optimisation — it is the feature.

  it("renders the matrix and the checking line, with no actions", async () => {
    mockShell({ state: "checking" });
    render(<UpdatePill />);
    await waitFor(() => expect(screen.getByTestId("update-pill")).toBeTruthy());
    expect(screen.getByTestId("checking-matrix")).toBeTruthy();
    expect(screen.getByText("updater.checking")).toBeTruthy();
    // A transient state, not a todo: nothing to click, nothing to dismiss.
    expect(screen.queryByText("updater.install")).toBeNull();
    expect(screen.queryByText("updater.later")).toBeNull();
    expect(screen.queryByLabelText("updater.dismiss")).toBeNull();
  });

  it("updates from a pushed event without waiting for the poll", async () => {
    mockShell({ state: "none" });
    render(<UpdatePill />);
    // The mock module below captured the subscriber; fire it like the shell would.
    await waitFor(() => expect(pushStatus).not.toBeNull());
    pushStatus!({ state: "checking", version: "", error: "" });
    await waitFor(() => expect(screen.getByTestId("checking-matrix")).toBeTruthy());
    pushStatus!({ state: "none", version: "", error: "" });
    await waitFor(() => expect(screen.queryByTestId("update-pill")).toBeNull());
  });

  it("keeps the reduced-motion escape hatch in the sweep styles", async () => {
    mockShell({ state: "checking" });
    render(<UpdatePill />);
    await waitFor(() => expect(screen.getByTestId("checking-matrix")).toBeTruthy());
    // jsdom applies no media queries, so assert the sheet itself carries the
    // escape hatch — the mutation that deletes it must go red here.
    const css = Array.from(document.querySelectorAll("style"))
      .map((e) => e.textContent ?? "").join("");
    expect(css).toMatch(/prefers-reduced-motion/);
  });
});
