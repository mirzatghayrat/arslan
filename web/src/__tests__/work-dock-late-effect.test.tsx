/**
 * The Workbench's browser dock keeps what the person did when its effects run late.
 *
 * Two effects read `tabs` / `selected` from the render they closed over and then wrote them outright: dropping a
 * conversation's saved tabs when it turns temporary, and re-anchoring the selection when the selected tab is gone.
 * The privacy flag reaches the dock after an API answer (ConversationControls → onChanged), so that render's effects
 * wait for React's scheduler task; a click in between was undone when they ran (a closed tab came back, a picked tab
 * moved to the first one). Same race as AskQueue's (askqueue-late-effect.test.tsx); here the task is delayed on
 * purpose, so the order is the bad one every time.
 */
import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";

vi.hoisted(() => {
  // React's scheduler runs passive effects on setImmediate in Node, captured when it loads: make it late.
  const g = globalThis as unknown as { setImmediate: (cb: (...a: unknown[]) => void, ...a: unknown[]) => unknown };
  g.setImmediate = (cb, ...a) => setTimeout(() => cb(...a), 80);
});

import { useEffect, useState } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import WorkDock from "../components/WorkDock";
import { saveDock } from "../lib/workDock";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("../components/BrowserReader", () => ({ default: ({ conversationId }: { conversationId: string }) => <div>Reader: {conversationId}</div> }));
vi.mock("../components/BrowserPanel", () => ({ default: () => null }));

beforeEach(() => {
  localStorage.clear();
  // c's tab is the one the privacy change drops; q and r belong to other conversations and stay.
  saveDock([{ id: "c", kind: "browser", conversationId: "c", taskId: null },
    { id: "q", kind: "browser", conversationId: "q", taskId: null },
    { id: "r", kind: "browser", conversationId: "r", taskId: null }], 420, false);
});
afterEach(cleanup);

/** The conversation turns temporary from an async answer, so the dock re-renders outside act. */
function TurnsTemporary() {
  const [temporary, setTemporary] = useState(false);
  useEffect(() => { void Promise.resolve().then(() => setTemporary(true)); }, []);
  return <>
    {temporary && <span data-testid="temporary" />}
    <WorkDock embedded open onOpen={() => {}} onClose={() => {}} conversationId="c" taskId={null} temporary={temporary} />
  </>;
}

const late = () => act(async () => { await new Promise((r) => setTimeout(r, 400)); });   // every late effect has run by now

describe("WorkDock (embedded)", () => {
  it("keeps a tab closed when the effect that drops the conversation's saved tabs runs late", async () => {
    render(<TurnsTemporary />);
    await screen.findByTestId("temporary", {}, { timeout: 2000 });   // committed; the drop is still pending
    fireEvent.click(screen.getAllByLabelText("dock.closeTab")[2]);   // r
    await late();
    expect(screen.queryByText("Reader: r")).toBeNull();
    expect(screen.queryByText("Reader: c")).toBeNull();
    expect(screen.getByText("Reader: q")).toBeInTheDocument();
  });

  it("keeps the tab picked when the effect that re-anchors the selection runs late", async () => {
    render(<TurnsTemporary />);
    // c (the selected tab) is gone and the re-anchor is still pending.
    await waitFor(() => expect(screen.getAllByRole("tab")).toHaveLength(2), { timeout: 2000 });
    fireEvent.click(screen.getAllByRole("tab")[1]);   // r
    await late();
    const [q, r] = screen.getAllByRole("tab");
    expect(r).toHaveAttribute("aria-selected", "true");
    expect(q).toHaveAttribute("aria-selected", "false");
  });

  it("keeps a tab opened in that moment selected, though the late effect's list does not have it", async () => {
    render(<TurnsTemporary />);
    await waitFor(() => expect(screen.getAllByRole("tab")).toHaveLength(2), { timeout: 2000 });
    fireEvent.click(screen.getByLabelText("dock.newBrowser"));
    await late();
    const tabs = screen.getAllByRole("tab");
    expect(tabs).toHaveLength(3);
    expect(tabs[2]).toHaveAttribute("aria-selected", "true");
  });
});
