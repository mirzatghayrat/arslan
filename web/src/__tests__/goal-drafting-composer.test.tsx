// L7-5h: the drafting chip sits in the chat's composer, and its Cancel stops the run the server named.
import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import OrchestratorChat from "../components/OrchestratorChat";
import { initialArslanState, useArslanStore } from "../stores/arslanStore";
import type { Message } from "../types";

const { cancelRun } = vi.hoisted(() => ({ cancelRun: vi.fn(async () => ({ ok: true })) }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));
vi.mock("../api/client", () => ({
  api: { extractAttachmentUrl: vi.fn(), extractAttachmentFile: vi.fn(), cancelRun },
}));
beforeAll(() => { window.HTMLElement.prototype.scrollIntoView = vi.fn(); });

const history: Message[] = [
  { id: "m1", sender: "user", senderName: "You", senderAvatar: "🦁", text: "/goal tidy the notes", timestamp: "10:00" },
];
const base = {
  chatHistory: history, setChatHistory: vi.fn(), spawns: [] as never[], currentStyle: "quartz" as const,
  setCurrentStyle: vi.fn(), activeThread: null, onSendMessage: vi.fn(),
};

beforeEach(() => {
  cancelRun.mockClear();
  useArslanStore.setState(initialArslanState(), true);
});

describe("drafting a goal in the composer", () => {
  it("shows drafting the checks with a Cancel that stops that run once", () => {
    render(<OrchestratorChat {...base} />);
    expect(screen.queryByTestId("goal-drafting")).toBeNull();
    act(() => { useArslanStore.getState().handleFrame({ type: "goal_drafting", run_id: 9 }); });
    const chip = screen.getByTestId("goal-drafting");
    expect(chip.textContent).toContain("jobs.goal.drafting");
    const cancel = screen.getByRole("button", { name: "jobs.goal.cancelDraft" });
    fireEvent.click(cancel);
    expect((cancel as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(cancel);
    expect(cancelRun).toHaveBeenCalledTimes(1);
    expect(cancelRun).toHaveBeenCalledWith(9);
    act(() => { useArslanStore.getState().handleFrame({ type: "run_cancelled", run_id: 9 }); });
    expect(screen.queryByTestId("goal-drafting")).toBeNull();
  });
});
