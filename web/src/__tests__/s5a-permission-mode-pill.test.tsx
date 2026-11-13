/**
 * S5a-2: the permission mode pill by the composer, the strip above it (a fallback's banner, Plan's Start), and how
 * the window keeps them current with no pushed event (docs/plans/0164/S5a-permission-modes.md).
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: object) => (o ? `${k}:${JSON.stringify(o)}` : k) }),
}));
const api = vi.hoisted(() => ({ get: vi.fn(), set: vi.fn(), start: vi.fn() }));
vi.mock("../api/permissionMode", () => ({ permissionModeApi: api }));
vi.mock("../api/client", () => ({ api: { extractAttachmentUrl: vi.fn(), extractAttachmentFile: vi.fn() } }));

import OrchestratorChat from "../components/OrchestratorChat";
import type { Message } from "../types";
import { DEFAULT_SETTINGS } from "../data";

import PermissionModePill from "../components/modes/PermissionModePill";
import ModeStrip from "../components/modes/ModeStrip";
import { usePermissionMode } from "../components/modes/usePermissionMode";
import type { ModeState } from "../api/permissionMode";
import { useArslanStore } from "../stores/arslanStore";
import { useSettingsStore } from "../stores/settingsStore";
import type { AppSettings } from "../api/client.types";

const state = (over: Partial<ModeState> = {}): ModeState =>
  ({ own: null, chosen: "ask_risky", mode: "ask_risky", fallback: "", previous: null, ...over });

function Harness({ id }: { id: string }) {
  const pm = usePermissionMode(id);
  return <><ModeStrip pm={pm} /><PermissionModePill pm={pm} /></>;
}

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}

const pill = () => screen.getByTestId("permission-mode-pill");
const open = () => fireEvent.click(pill());
const rows = () => screen.getAllByRole("menuitemradio");

beforeEach(() => {
  api.get.mockReset(); api.set.mockReset(); api.start.mockReset();
  useSettingsStore.setState({ settings: { default_permission_mode: "ask" } as AppSettings });
  useArslanStore.setState({ streaming: false });
});

describe("the pill", () => {
  it("shows the conversation's mode; the menu has four modes, Current on the chosen one, and the footnote", async () => {
    api.get.mockResolvedValue(state());
    render(<Harness id="conv-1" />);
    await waitFor(() => expect(pill().textContent).toContain("modes.askRisky"));
    expect(api.get).toHaveBeenCalledWith("conv-1");
    open();
    expect(rows()).toHaveLength(4);
    const checked = rows().filter((r) => r.getAttribute("aria-checked") === "true");
    expect(checked).toHaveLength(1);
    expect(checked[0].textContent).toContain("modes.askRiskyLine");
    expect(checked[0].textContent).toContain("modes.current");
    expect(screen.getByRole("menu").textContent).toContain("modes.footnote");
    expect(screen.queryByTestId("permission-mode-narrowed")).toBeNull();
  });

  it("picking a mode shows what the server stored, not a guess", async () => {
    api.get.mockResolvedValue(state());
    api.set.mockResolvedValue(state({ own: "ask", chosen: "ask", mode: "ask" }));
    render(<Harness id="conv-1" />);
    await waitFor(() => expect(pill().textContent).toContain("modes.askRisky"));
    open();
    fireEvent.click(rows().find((r) => r.textContent?.includes("modes.fullAccessLine"))!);
    expect(api.set).toHaveBeenCalledWith("conv-1", "full_access");
    await waitFor(() => expect(pill().textContent).toContain("modes.ask"));
    expect(pill().textContent).not.toContain("modes.fullAccess");
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("a failed change keeps the old mode and says so", async () => {
    api.get.mockResolvedValue(state());
    api.set.mockRejectedValue(new Error("offline"));
    render(<Harness id="conv-1" />);
    await waitFor(() => expect(pill().textContent).toContain("modes.askRisky"));
    open();
    fireEvent.click(rows()[1]);
    expect(api.set).toHaveBeenCalledWith("conv-1", "ask");
    expect(await screen.findByRole("alert")).toHaveTextContent("modes.saveFailed");
    expect(pill().textContent).toContain("modes.askRisky");
  });

  it("a sub-session narrowed by its parent says so under the menu (Q4)", async () => {
    api.get.mockResolvedValue(state({ own: "full_access", chosen: "ask", mode: "ask" }));
    render(<Harness id="conv-1" />);
    await waitFor(() => expect(pill().textContent).toContain("modes.ask"));
    open();
    expect(screen.getByTestId("permission-mode-narrowed").textContent).toBe("modes.narrowed");
  });

  it("every control is at least 44px tall", async () => {
    api.get.mockResolvedValue(state({ chosen: "plan", mode: "plan" }));
    render(<Harness id="conv-1" />);
    await waitFor(() => expect(screen.getByTestId("mode-start")).toBeTruthy());
    open();
    for (const el of [pill(), ...rows(), screen.getByTestId("mode-start")]) {
      expect(el.className).toMatch(/min-h-\[44px\]|h-11/);
    }
  });
});

describe("the fallback", () => {
  it.each([
    ["sandbox_off", "modes.reasonSandboxOff"],
    ["home_folder", "modes.reasonHomeFolder"],
    ["no_checkpoint", "modes.reasonNoCheckpoint"],
  ] as const)("%s: the pill says 'for now' and the banner names why", async (fallback, reason) => {
    api.get.mockResolvedValue(state({ mode: "ask", fallback }));
    render(<Harness id="conv-1" />);
    await waitFor(() => expect(pill().textContent).toContain("modes.askForNow"));
    expect(screen.getByTestId("mode-fallback").textContent).toContain(reason);
    open();
    const checked = rows().filter((r) => r.getAttribute("aria-checked") === "true");
    expect(checked.map((r) => r.textContent)).toEqual([expect.stringContaining("modes.askRiskyLine")]);
  });

  it("no fallback, no banner", async () => {
    api.get.mockResolvedValue(state());
    render(<Harness id="conv-1" />);
    await waitFor(() => expect(pill().textContent).toContain("modes.askRisky"));
    expect(screen.queryByTestId("mode-fallback")).toBeNull();
  });
});

describe("Plan's Start", () => {
  it("names the default when there was no mode before plan", async () => {
    api.get.mockResolvedValue(state({ own: "plan", chosen: "plan", mode: "plan" }));
    render(<Harness id="conv-1" />);
    await waitFor(() => expect(screen.getByTestId("mode-starts-in").textContent).toContain("modes.ask\""));
  });

  it("names the mode before plan, and Start goes back to it", async () => {
    api.get.mockResolvedValue(state({ own: "plan", chosen: "plan", mode: "plan", previous: "ask_risky" }));
    api.start.mockResolvedValue(state({ own: "ask_risky" }));
    render(<Harness id="conv-1" />);
    await waitFor(() => expect(screen.getByTestId("mode-starts-in").textContent).toContain("modes.askRisky"));
    fireEvent.click(screen.getByTestId("mode-start"));
    expect(api.start).toHaveBeenCalledWith("conv-1");
    await waitFor(() => expect(screen.queryByTestId("mode-start")).toBeNull());
    expect(pill().textContent).toContain("modes.askRisky");
  });

  it("a 409 (already started elsewhere) asks again, with no error", async () => {
    api.get.mockResolvedValueOnce(state({ own: "plan", chosen: "plan", mode: "plan" }))
      .mockResolvedValue(state({ own: "ask" , chosen: "ask", mode: "ask" }));
    api.start.mockRejectedValue(Object.assign(new Error("not_in_plan"), { status: 409 }));
    render(<Harness id="conv-1" />);
    await waitFor(() => expect(screen.getByTestId("mode-start")).toBeTruthy());
    fireEvent.click(screen.getByTestId("mode-start"));
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByTestId("mode-start")).toBeNull());
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("in the chat", () => {
  const history: Message[] = [
    { id: "m1", sender: "arslan", senderName: "Arslan", senderAvatar: "🦁", text: "hi", timestamp: "10:00" }];
  const chat = (chatHistory: Message[]) => render(<OrchestratorChat chatHistory={chatHistory} setChatHistory={vi.fn()}
    onSendMessage={vi.fn()} spawns={[]} currentStyle="linear" setCurrentStyle={vi.fn()} activeThread={null}
    conversationId="conv-1" />);

  it("the thread composer has the pill and Plan's Start above it; the old posture line is gone", async () => {
    Element.prototype.scrollIntoView = vi.fn();
    api.get.mockResolvedValue(state({ own: "plan", chosen: "plan", mode: "plan" }));
    chat(history);
    await waitFor(() => expect(screen.getByTestId("mode-start")).toBeTruthy());
    expect(screen.getByTestId("composer-input-tools").contains(pill())).toBe(true);
    expect(screen.queryByTestId("execution-options")).toBeNull();
  });

  it("the window starts strict (ask every step) until the server says what the default is", () => {
    expect(DEFAULT_SETTINGS.defaultPermissionMode).toBe("ask");
  });

  it("the empty conversation's composer has the pill only", async () => {
    api.get.mockResolvedValue(state({ own: "plan", chosen: "plan", mode: "plan" }));
    chat([]);
    await waitFor(() => expect(pill().textContent).toContain("modes.plan"));
    expect(screen.queryByTestId("mode-start")).toBeNull();
  });
});

describe("keeping it current", () => {
  it("a late answer for the last conversation never shows in the next one", async () => {
    const one = deferred<ModeState>();
    api.get.mockImplementation((id: string) => id === "conv-1" ? one.promise
      : Promise.resolve(state({ own: "ask", chosen: "ask", mode: "ask" })));
    const view = render(<Harness id="conv-1" />);
    view.rerender(<Harness id="conv-2" />);
    await waitFor(() => expect(pill().textContent).toContain("modes.ask"));
    await act(async () => { one.resolve(state({ own: "full_access", chosen: "full_access", mode: "full_access" })); });
    expect(pill().textContent).not.toContain("modes.fullAccess");
  });

  it("switching conversations never shows the last one's mode while the next loads", async () => {
    api.get.mockResolvedValueOnce(state({ own: "full_access", chosen: "full_access", mode: "full_access" }))
      .mockReturnValue(new Promise(() => {}));
    const view = render(<Harness id="conv-1" />);
    await waitFor(() => expect(pill().textContent).toContain("modes.fullAccess"));
    view.rerender(<Harness id="conv-2" />);
    expect(pill().textContent).not.toContain("modes.fullAccess");
    expect(pill().textContent).toContain("modes.ask");          // the default, dimmed, until it answers
  });

  it("asks again when a turn ends, and a fallback found then shows", async () => {
    api.get.mockResolvedValueOnce(state()).mockResolvedValue(state({ mode: "ask", fallback: "sandbox_off" }));
    render(<Harness id="conv-1" />);
    await waitFor(() => expect(pill().textContent).toContain("modes.askRisky"));
    act(() => useArslanStore.setState({ streaming: true }));
    expect(api.get).toHaveBeenCalledTimes(1);
    act(() => useArslanStore.setState({ streaming: false }));
    await waitFor(() => expect(screen.getByTestId("mode-fallback")).toBeTruthy());
    expect(api.get).toHaveBeenCalledTimes(2);
  });

  it("asks again when the sandbox setting changes", async () => {
    api.get.mockResolvedValue(state());
    render(<Harness id="conv-1" />);
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(1));
    act(() => useSettingsStore.setState({
      settings: { default_permission_mode: "ask", terminal_sandbox_enabled: false } as AppSettings }));
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2));
  });
});
