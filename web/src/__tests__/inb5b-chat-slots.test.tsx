/** INB5b (v0.1.64): the conversation has a place above its messages (what wasn't done while you were away) and one after them (a
 *  stopped job's card), so both scroll with the conversation, as the INB5 board drew them. */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import OrchestratorChat from "../components/OrchestratorChat";
import { initialArslanState, useArslanStore } from "../stores/arslanStore";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k, i18n: { resolvedLanguage: "en" } }) }));
vi.mock("../api/client", async (orig) => ({
  ...(await orig<typeof import("../api/client")>()),
  api: { extractAttachmentUrl: vi.fn(), extractAttachmentFile: vi.fn() },
}));
beforeAll(() => { window.HTMLElement.prototype.scrollIntoView = vi.fn(); });
afterEach(() => { cleanup(); useArslanStore.setState(initialArslanState(), true); });

describe("the conversation's slots", () => {
  it("puts the header above the first message and the footer after the last", () => {
    render(<OrchestratorChat chatHistory={[
      { id: "m1", sender: "user", text: "first message", timestamp: "" },
      { id: "m2", sender: "arslan", text: "last message", timestamp: "" },
    ] as never} setChatHistory={vi.fn()} onSendMessage={vi.fn()} spawns={[]} currentStyle="linear" setCurrentStyle={vi.fn()}
      activeThread={null} header={<div data-testid="slot-header" />} footer={<div data-testid="slot-footer" />} />);
    const order = (a: Element, b: Element) => a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING;
    expect(order(screen.getByTestId("slot-header"), screen.getByText("first message"))).toBeTruthy();
    expect(order(screen.getByText("last message"), screen.getByTestId("slot-footer"))).toBeTruthy();
  });
});
