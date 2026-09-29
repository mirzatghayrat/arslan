// 0.1.44: a task-status code is not a model failure (field case: "Model error —
// An action may already have happened" after a read-only screenshot failed).
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

function chatWithError(error: string) {
  useArslanStore.setState({ ...initialArslanState(), error });
  render(<OrchestratorChat chatHistory={[]} setChatHistory={vi.fn()} onSendMessage={vi.fn()} spawns={[]}
    currentStyle="linear" setCurrentStyle={vi.fn()} activeThread={null} />);
  return screen.getByTestId("chat-error");
}

describe("chat error card", () => {
  it("titles a task-status code as something to check, in words, never 'Model error'", () => {
    const card = chatWithError("task_reconciliation_required");
    expect(card).toHaveAttribute("data-kind", "task");
    expect(card).toHaveTextContent("ui.needsYourCheck");
    expect(card).toHaveTextContent("tasks.uncertain");
    expect(card).not.toHaveTextContent("ui.modelError");
  });

  it("keeps 'Model error' for a real model failure", () => {
    const card = chatWithError("The provider returned 401");
    expect(card).toHaveAttribute("data-kind", "model");
    expect(card).toHaveTextContent("ui.modelError");
  });
});
