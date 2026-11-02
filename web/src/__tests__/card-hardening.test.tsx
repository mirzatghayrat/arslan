/** 0.1.61 §A4 (review of PR 2b Task 3): a frame the server should never send must not leave a card that says nothing, closes at once,
 *  spills out of its box, or reads as resolved when nothing was shown. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act, cleanup, fireEvent } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k) }),
}));

import AskSlot from "../components/AskSlot";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";

beforeEach(() => { useArslanStore.setState(initialArslanState(), true); });
afterEach(() => { cleanup(); vi.useRealTimers(); });
const frame = (f: Record<string, unknown>) => act(() => { useArslanStore.getState().handleFrame(f as never); });
const ACTION = { type: "propose_action", call_id: "a1", kind: "app", target: "com.tencent.xinWeChat", detail: "", options: ["task", "conversation"] };

describe("a card that says what it asks, whatever the frame", () => {
  it("a title of spaces is no title: the heading is the target, with or without the model's why", () => {
    render(<AskSlot send={vi.fn()} />);
    frame({ ...ACTION, title: "   " });
    expect(screen.getByTestId("action-title").textContent).toBe("com.tencent.xinWeChat");
    frame({ ...ACTION, call_id: "a2", title: "\n", why: "Send Li the notes" });
    fireEvent.click(screen.getByLabelText("kit.next"));                                              // a2 waits behind a1
    expect(screen.getByTestId("action-title")).toHaveTextContent("Send Li the notes");
    expect(screen.getByTestId("action-subject").textContent).toBe("com.tencent.xinWeChat");        // the server's words, not a blank line
    expect(screen.getByTestId("action-subject")).not.toHaveAttribute("lang");                       // a bare target is not English words
  });

  it("the model's line is one long token (a URL): it may break anywhere instead of spilling out of the card", () => {
    render(<AskSlot send={vi.fn()} />);
    frame({ ...ACTION, title: "Use App?", why: "https://example.com/" + "a".repeat(200) });
    expect(screen.getByTestId("action-title").className).toContain("overflow-wrap:anywhere");
  });

  it("the line under it breaks words too, so a long target never spills out (moved from the Inbox's test, INB5b-2)", () => {
    render(<AskSlot send={vi.fn()} />);
    frame({ ...ACTION, target: "com.example." + "a".repeat(200), title: "Use App?", why: "Send the notes" });
    expect(screen.getByTestId("action-subject").className).toContain("break-words");
  });
});

describe("the model's own line under \"Arslan says\", whatever it is", () => {
  const URL_WHY = "https://example.com/" + "a".repeat(200);
  it("a kind with words of its own shows a long unbroken why that may break anywhere, instead of spilling out of the card", () => {
    render(<AskSlot send={vi.fn()} />);
    frame({ ...ACTION, kind: "desktop_app", target: "Notes", title: "Use Notes?", why: URL_WHY });
    expect(screen.getByTestId("action-said").className).toContain("overflow-wrap:anywhere");
  });

  it("so does the command card's sandbox why", () => {
    render(<AskSlot send={vi.fn()} />);
    frame({ type: "propose_run_command", call_id: "c1", pretty: "mv a ~/b", reason: "", sandbox: "outside", why: URL_WHY, options: ["once", "conversation"] });
    expect(screen.getByTestId("runcmd-why").className).toContain("overflow-wrap:anywhere");
  });
});

describe("a card's time, whatever the frame says", () => {
  const writeCard = (extra: Record<string, unknown>) => ({ type: "propose_workspace_write", call_id: "w1", workspace: "/w", action: "write_file", path: "a", options: ["once", "conversation"], ...extra });

  it.each([["zero", 0], ["negative", -5], ["more than setTimeout can count (35 days)", 3_000_000]])(
    "an expires_at that is %s does not close the card at once, nor does it outlive the 30 minutes the Mac waits", (_what, offset) => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-13T10:00:00Z"));
    render(<AskSlot send={vi.fn()} />);
    frame(writeCard({ expires_at: offset <= 0 ? offset : Date.now() / 1000 + offset }));
    act(() => { vi.advanceTimersByTime(1_000); });
    expect(screen.getByTestId("wswrite-card")).toBeInTheDocument();
    act(() => { vi.advanceTimersByTime(1_799_000); });                  // 30 minutes after it arrived
    expect(screen.getByTestId("wswrite-card")).toBeInTheDocument();     // the server closes it first
    act(() => { vi.advanceTimersByTime(2_100); });
    expect(screen.queryByTestId("wswrite-card")).toBeNull();
    expect(screen.getByTestId("ask-expired")).toBeInTheDocument();
  });

  it.each([["a duration sent as an epoch (1800)", 1800], ["a day and a second before it arrived", -86_401]])(
    "an expires_at that is %s is no time: the card waits the 30 minutes the Mac does, as if it had none", (_what, value) => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-13T10:00:00Z"));
    render(<AskSlot send={vi.fn()} />);
    frame(writeCard({ expires_at: value < 0 ? Date.now() / 1000 + value : value }));
    act(() => { vi.advanceTimersByTime(5_000); });
    expect(screen.getByTestId("wswrite-card")).toBeInTheDocument();
    expect(screen.getByTestId("ask-countdown")).toHaveAccessibleName(/^29:5\d$/);     // counting down 30 minutes from its arrival
    act(() => { vi.advanceTimersByTime(1_795_000); });                                   // 30 minutes after it arrived
    expect(screen.getByTestId("wswrite-card")).toBeInTheDocument();                      // the server closes it first
    act(() => { vi.advanceTimersByTime(2_100); });
    expect(screen.queryByTestId("wswrite-card")).toBeNull();
    expect(screen.getByTestId("ask-expired")).toBeInTheDocument();
  });

  it.each([["just inside the day before it arrived", -86_399], ["ten seconds ago", -10]])(
    "an expires_at that is %s is a real time that has passed: the card leaves at once, as a card the server already closed", (_what, value) => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-13T10:00:00Z"));
    render(<AskSlot send={vi.fn()} />);
    frame(writeCard({ expires_at: Date.now() / 1000 + value }));
    act(() => { vi.advanceTimersByTime(10); });
    expect(screen.queryByTestId("wswrite-card")).toBeNull();
    expect(screen.getByTestId("ask-expired")).toBeInTheDocument();
  });

  it("a card_resolved with no call id resolves nothing and says nothing ran out", () => {
    render(<AskSlot send={vi.fn()} />);
    frame({ type: "card_resolved", outcome: "expired" });
    expect(useArslanStore.getState().cardExpired).toBe(false);
    frame(writeCard({}));
    frame({ type: "card_resolved", outcome: "approved" });
    expect(screen.getByTestId("wswrite-card")).toBeInTheDocument();     // not this one: it names no card
    act(() => { useArslanStore.getState().expireCard(undefined as never); });
    expect(useArslanStore.getState().cardExpired).toBe(false);
  });

  it("a card that itself came with no call id is not matched by one that names none: nothing is closed, nothing ran out", () => {
    render(<AskSlot send={vi.fn()} />);
    frame({ type: "propose_workspace_write", workspace: "/w", action: "write_file", path: "a", options: ["once", "conversation"] });   // malformed: no call_id
    expect(useArslanStore.getState().pendingWorkspaceWrites).toHaveLength(1);
    frame({ type: "card_resolved", outcome: "expired" });
    act(() => { useArslanStore.getState().expireCard(undefined as never); });
    expect(useArslanStore.getState().pendingWorkspaceWrites).toHaveLength(1);
    expect(useArslanStore.getState().cardExpired).toBe(false);
  });
});
