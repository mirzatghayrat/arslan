// 0.1.53 Arslan Hands: the confirmation cards for Mac apps, the Settings block
// (the never-list the helper enforces, the user's own additions), the Activity
// trace, and the island's Stop.
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string, o?: Record<string, string>) =>
  o ? `${k}:${Object.values(o).join("|")}` : k, i18n: { language: "en" } }) }));
const request = vi.fn();
vi.mock("../api/client", () => ({ request: (...args: unknown[]) => request(...args) }));

import ActionApprovalCard from "../components/ActionApprovalCard";
import HandsSection from "../components/settings/HandsSection";
import HandsTraceCard from "../components/HandsTraceCard";
import { usingHands } from "../island/IslandApp";
import { stopHands } from "../island/feed";
import { handsMessages } from "../locales/hands";
import { stepText } from "../locales/island";

afterEach(() => { cleanup(); request.mockReset(); vi.unstubAllGlobals(); });

const state = (over: Record<string, unknown> = {}) => ({
  available: true, enabled: true, cursor: true, never: ["Mail"], running: false,
  built_in: { never: ["Keychain Access", "System Settings", "Arslan"], look_only: ["Web browsers"],
              click_only: ["Terminals and code editors"] }, ...over });

describe("desktop cards", () => {
  it("a look is not a background job; acting is; a risky button is marked and named", () => {
    const { rerender } = render(<ActionApprovalCard kind="desktop_look" target="Notes" detail="read" onConfirm={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.queryByText("jobs.askingBadge")).toBeNull();
    expect(screen.getByText("hands.title.desktop_look:Notes")).toBeInTheDocument();
    rerender(<ActionApprovalCard kind="desktop_app" target="Notes" detail="click" onConfirm={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByText("jobs.askingBadge")).toBeInTheDocument();
    rerender(<ActionApprovalCard kind="desktop_risky" target="Mail · “Send”" detail="send" onConfirm={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByTestId("action-card").className).toContain("runcmd-card--risky");
    expect(screen.getByText("hands.title.desktop_risky:Mail · “Send”")).toBeInTheDocument();
  });

  it("every card kind has copy in all six languages", () => {
    for (const messages of Object.values(handsMessages)) {
      for (const kind of ["desktop_look", "desktop_app", "desktop_risky"] as const) {
        expect(messages.title[kind]).toBeTruthy();
        expect(messages.scope[kind]).toBeTruthy();
      }
    }
  });
});

describe("settings", () => {
  it("shows the built-in lists read-only and edits only the user's own list", async () => {
    request.mockImplementation(async (path: string, init?: RequestInit) =>
      init?.method === "PUT" ? state(JSON.parse(String(init.body))) : state());
    render(<HandsSection />);
    expect(await screen.findByTestId("settings-hands")).toHaveTextContent("Keychain Access · System Settings · Arslan");
    expect(screen.getByTestId("hands-never-mine")).toHaveTextContent("Mail");
    fireEvent.change(screen.getByTestId("hands-never-input"), { target: { value: "Notes" } });
    fireEvent.click(screen.getByTestId("hands-never-add"));
    await waitFor(() => expect(request).toHaveBeenCalledWith("/hands", expect.objectContaining({ method: "PUT" })));
    const put = request.mock.calls.find(([, init]) => init?.method === "PUT")!;
    expect(JSON.parse(put[1].body)).toEqual({ never: ["Mail", "Notes"] });
    expect(JSON.stringify(request.mock.calls)).not.toContain("Keychain Access\",\"never");
  });

  it("offers macOS's prompt only when Accessibility is known to be missing", async () => {
    request.mockResolvedValue(state({ running: true, accessibility: false }));
    render(<HandsSection />);
    expect(await screen.findByTestId("hands-access")).toHaveTextContent("hands.settings.notGranted");
    expect(screen.getByTestId("hands-ask")).toBeInTheDocument();
    cleanup();
    request.mockResolvedValue(state({ running: true, accessibility: true }));
    render(<HandsSection />);
    expect(await screen.findByTestId("hands-access")).toHaveTextContent("hands.settings.granted");
    expect(screen.queryByTestId("hands-ask")).toBeNull();
  });

  it("says so when this copy has no Hands", async () => {
    request.mockResolvedValue(state({ available: false }));
    render(<HandsSection />);
    expect(await screen.findByTestId("hands-unavailable")).toBeInTheDocument();
    expect(screen.queryByTestId("hands-enabled-toggle")).toBeNull();
  });
});

describe("activity", () => {
  it("lists recent Hands calls, with typed text as a length only, and nothing when empty", async () => {
    request.mockResolvedValue({ entries: [{ at: "2026-10-03T10:00:00+00:00", app: "Notes", op: "set_value",
      outcome: "ok", target: "Body", typed_chars: 9 }] });
    render(<HandsTraceCard />);
    expect(await screen.findByTestId("hands-trace")).toHaveTextContent("Notes");
    expect(screen.getByTestId("hands-trace")).toHaveTextContent("Body (9)");
    cleanup();
    request.mockResolvedValue({ entries: [] });
    const { container } = render(<HandsTraceCard />);
    await act(async () => { await Promise.resolve(); });
    expect(container).toBeEmptyDOMElement();
  });
});

describe("island", () => {
  it("knows when Hands is at work and says the step in words", () => {
    expect(usingHands([{ step: { tool: "desktop_click" } }])).toBe(true);
    expect(usingHands([{ step: { tool: "web_search" } }, { step: null }])).toBe(false);
    expect(stepText("en", "desktop_click", "Notes · New Note")).toBe("Click Notes · New Note");
    expect(stepText("zh", "desktop_type", "Notes · Body")).toBe("在 Notes · Body 输入");
  });

  it("Stop posts to the backend with the island's token", async () => {
    (window as unknown as { __ARSLAN_TOKEN__?: string }).__ARSLAN_TOKEN__ = "tok";
    const fetchMock = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    expect(await stopHands()).toBe(true);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/v1/hands/stop");
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok");
    delete (window as unknown as { __ARSLAN_TOKEN__?: string }).__ARSLAN_TOKEN__;
  });
});
