/** v0.1.64 CAP2a: "Arslan 想存一个技能" — the whole SKILL.md as plain text, the outside line, and its answers. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act, cleanup } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, o?: Record<string, unknown>) => (o ? `${key}:${JSON.stringify(o)}` : key) }),
}));

import AskSlot from "../components/AskSlot";
import { ANSWER_GUARD_MS } from "../components/kit";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";

beforeEach(() => useArslanStore.setState(initialArslanState(), true));
afterEach(() => { cleanup(); vi.useRealTimers(); });
const settle = () => act(() => { vi.advanceTimersByTime(ANSWER_GUARD_MS); });
const frame = (f: Record<string, unknown>) => act(() => { useArslanStore.getState().handleFrame(f as never); });

const BODY = "## Trigger\nThe user asks for this week's report.\n\n## Method\n1. Read this week's meeting notes.\n"
  + "2. Keep each meeting's decisions.\n<img src=x onerror=\"alert(1)\"> **not bold** [a link](https://evil.example)\n";
const SAVE = {
  type: "propose_capability", call_id: "cap-9", kind: "authored", key: "weekly-report", name: "Weekly report",
  description: "A one-page report of the week", body: BODY, why: "save what we just did as a skill", outside: false,
};
const INSTALL = {
  type: "propose_capability", call_id: "cap-1", kind: "mcp", name: "excel-mcp-server", summary: "Reads and writes .xlsx",
  source_url: null, repo: null, version: null, license: { spdx: "MIT", read_from: null }, stars: null, pushed_days: null,
  runtime: "uv", runtime_download: null, remote_host: null, network: false, folders: [], keys: [], why: "", retry: "",
};

describe("the save-a-skill card", () => {
  it("shows the whole text exactly, as plain text, with the name, the key and what a skill is", () => {
    render(<AskSlot send={() => {}} />);
    frame(SAVE);
    const card = screen.getByTestId("skill-save-card");
    expect(card).toHaveTextContent('discover.save_title:{"name":"Weekly report"}');
    expect(card).toHaveTextContent("save what we just did as a skill");
    expect(screen.getByTestId("skill-save-rows")).toHaveTextContent("A one-page report of the week");
    expect(screen.getByTestId("skill-save-rows")).toHaveTextContent("weekly-report");
    expect(screen.getByTestId("skill-save-rows")).toHaveTextContent("discover.save_whatText");
    const body = screen.getByTestId("skill-save-body");
    expect(body.textContent).toBe(BODY);                                   // all of it, nothing folded away
    expect(screen.getByTestId("skill-save-lines")).toHaveTextContent('discover.save_lines:{"count":7}');
    expect(body.children).toHaveLength(0);                                 // text only: nothing rendered from it
    expect(card.querySelector("img, a, strong")).toBeNull();
    expect(screen.queryByTestId("ask-risk")).toBeNull();
    expect(screen.queryByTestId("capability-card-license")).toBeNull();     // none of the install card's rows
  });

  it("says when this turn read outside content", () => {
    render(<AskSlot send={() => {}} />);
    frame({ ...SAVE, outside: true });
    expect(screen.getByTestId("ask-risk")).toHaveTextContent("discover.save_outside");
  });

  it("saving answers with the call id alone", () => {
    vi.useFakeTimers();
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame(SAVE);
    settle();
    fireEvent.click(screen.getByTestId("skill-save-allow"));
    expect(send).toHaveBeenCalledWith({ type: "confirm_capability", call_id: "cap-9" });
    expect(useArslanStore.getState().pendingCapabilities).toEqual([]);
  });

  it("esc says no", () => {
    vi.useFakeTimers();
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame(SAVE);
    settle();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(send).toHaveBeenCalledWith({ type: "cancel_capability", call_id: "cap-9" });
    expect(useArslanStore.getState().pendingCapabilities).toEqual([]);
  });

  it("queues with an install card, each drawn as its own kind", () => {
    render(<AskSlot send={() => {}} />);
    frame(INSTALL);
    frame(SAVE);
    expect(screen.getByTestId("capability-card")).toHaveTextContent('discover.card_title:{"name":"excel-mcp-server"}');
    fireEvent.click(screen.getByRole("button", { name: "kit.next" }));
    expect(screen.getByTestId("skill-save-card")).toBeInTheDocument();
    expect(screen.queryByTestId("capability-card")).toBeNull();
  });
});
