/** 0.1.57 P3: "Arslan 想加一个能力" — the card, its answer, and the line where it ended. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act, cleanup } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, o?: Record<string, unknown>) => (o ? `${key}:${JSON.stringify(o)}` : key) }),
}));

import AskSlot from "../components/AskSlot";
import CapabilityResultLine from "../components/capabilities/CapabilityResultLine";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";
import { toUiMessages } from "../api/adapters";

beforeEach(() => useArslanStore.setState(initialArslanState(), true));
afterEach(() => cleanup());

const frame = (f: Record<string, unknown>) => act(() => { useArslanStore.getState().handleFrame(f as never); });
const CARD = {
  type: "propose_capability", call_id: "cap-1", kind: "mcp", name: "excel-mcp-server", summary: "Reads and writes .xlsx",
  source_url: "https://github.com/haris-musa/excel-mcp-server", repo: "haris-musa/excel-mcp-server", version: "1.1.2",
  license: { spdx: "MIT", read_from: "github:LICENSE" }, stars: 4216, pushed_days: 10, runtime: "uv",
  runtime_download: { name: "uv", size_mb: 20 }, remote_host: null, network: false,
  folders: ["/Users/x/Downloads", "/Users/x/Documents"],
  keys: [{ name: "EXCEL_TOKEN", secret: true, required: true, description: "a key" }],
  why: "Only values, no formulas", retry: "read the formulas in budget.xlsx",
};

describe("the capability card", () => {
  it("shows what, where from, the license read at the source, how it runs, and what it needs", () => {
    render(<AskSlot send={() => {}} />);
    frame(CARD);
    expect(screen.getByTestId("capability-card")).toHaveTextContent('discover.card_title:{"name":"excel-mcp-server"}');
    expect(screen.getByTestId("capability-card-license")).toHaveTextContent("MIT");
    expect(screen.getByTestId("capability-card-license")).toHaveTextContent("discover.lic_readFrom");
    expect(screen.getByTestId("capability-card-runs")).toHaveTextContent("discover.card_runSandbox");
    expect(screen.getByTestId("capability-card-runs")).toHaveTextContent('discover.card_download:{"name":"uv","size":20}');
    expect(screen.getByTestId("capability-card")).toHaveTextContent("Only values, no formulas");
    expect(screen.getByTestId("capability-card")).toHaveTextContent('discover.card_retry:{"step":"read the formulas in budget.xlsx"}');
    expect(screen.getByTestId("capability-key-EXCEL_TOKEN")).toHaveAttribute("type", "password");
  });

  it("a required key must be typed before it can be added; esc still declines", () => {
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame(CARD);
    expect(screen.getByTestId("capability-card-allow")).toBeDisabled();
    fireEvent.keyDown(window, { key: "Enter", metaKey: true });
    expect(send).not.toHaveBeenCalled();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(send).toHaveBeenCalledWith({ type: "cancel_capability", call_id: "cap-1" });
    expect(useArslanStore.getState().pendingCapability).toBeNull();
  });

  it("adding sends the key and the folders the user kept — nothing else", () => {
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame(CARD);
    fireEvent.change(screen.getByTestId("capability-key-EXCEL_TOKEN"), { target: { value: "s3cr3t" } });
    fireEvent.click(screen.getByTestId("capability-folder-drop-/Users/x/Documents"));
    fireEvent.click(screen.getByTestId("capability-card-allow"));
    expect(send).toHaveBeenCalledWith({ type: "confirm_capability", call_id: "cap-1",
      keys: { EXCEL_TOKEN: "s3cr3t" }, folders: ["/Users/x/Downloads"] });
  });

  it("a remote server and a skill say how they run", () => {
    render(<AskSlot send={() => {}} />);
    frame({ ...CARD, runtime: "remote", remote_host: "https://mcp.example.com/x", runtime_download: null, keys: [], folders: [] });
    expect(screen.getByTestId("capability-card-runs")).toHaveTextContent('discover.card_runRemote:{"host":"mcp.example.com"}');
    cleanup();
    useArslanStore.setState(initialArslanState(), true);
    render(<AskSlot send={() => {}} />);
    frame({ ...CARD, call_id: "cap-2", kind: "skill", runtime: "skill", runtime_download: null, keys: [], folders: [] });
    expect(screen.getByTestId("capability-card")).toHaveTextContent('discover.card_titleSkill:{"name":"excel-mcp-server"}');
    expect(screen.getByTestId("capability-card-runs")).toHaveTextContent("discover.card_runSkill");
  });

  it("closes when the server says it was decided or expired", () => {
    render(<AskSlot send={() => {}} />);
    frame(CARD);
    frame({ type: "card_resolved", call_id: "cap-1", outcome: "expired" });
    expect(screen.queryByTestId("capability-card")).toBeNull();
  });
});

describe("where it ended", () => {
  it("the result becomes one line in the conversation", () => {
    frame({ type: "capability_result", call_id: "cap-1", source_id: "s1", state: "on", name: "excel-mcp-server", tools: 26 });
    const items = useArslanStore.getState().items;
    const msgs = toUiMessages(items as never);
    const last = msgs[msgs.length - 1];
    expect(last.capabilityResult).toMatchObject({ state: "on", tools: 26, sourceId: "s1" });
    render(<CapabilityResultLine result={last.capabilityResult!} />);
    expect(screen.getByTestId("capability-result")).toHaveTextContent('discover.result_on:{"name":"excel-mcp-server","count":26}');
  });

  it("failed and blocked say so", () => {
    const { unmount } = render(<CapabilityResultLine result={{ state: "failed", name: "x", tools: 0, sourceId: "s", stage: "test", detail: "Connection closed" }} />);
    expect(screen.getByTestId("capability-result")).toHaveTextContent('discover.result_failed:{"name":"x","stage":"test","detail":"Connection closed"}');
    unmount();
    render(<CapabilityResultLine result={{ state: "blocked", name: "x", tools: 0, sourceId: "s" }} />);
    expect(screen.getByTestId("capability-result")).toHaveAttribute("data-state", "blocked");
  });
});
