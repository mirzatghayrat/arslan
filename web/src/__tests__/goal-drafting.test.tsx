// L7-5h (the user, 11-17): while `/goal` drafts its checks, the composer says "drafting the checks", with a Cancel
// that stops the run (POST /runs/{id}/cancel); the chip goes once anything answers, ends or stops the turn.
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { GoalDraftingChip } from "../components/GoalCard";
import { jobMessages } from "../locales/jobs";
import { initialArslanState, useArslanStore } from "../stores/arslanStore";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

beforeEach(() => { useArslanStore.setState(initialArslanState(), true); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const drafting = (run_id?: number) => act(() => {
  useArslanStore.getState().handleFrame({ type: "goal_drafting", ...(run_id != null ? { run_id } : {}) });
});

describe("goal drafting chip", () => {
  it("shows nothing until the server says it is drafting", () => {
    render(<GoalDraftingChip />);
    expect(screen.queryByTestId("goal-drafting")).toBeNull();
  });

  it("says it is drafting and Cancel stops that run once", async () => {
    const cancel = vi.spyOn(api, "cancelRun").mockResolvedValue({ ok: true });
    render(<GoalDraftingChip />);
    drafting(42);
    expect(screen.getByTestId("goal-drafting").textContent).toContain("jobs.goal.drafting");
    expect(useArslanStore.getState().activeRunId).toBe(42);          // the composer's stop is armed too
    const button = screen.getByRole("button", { name: "jobs.goal.cancelDraft" });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(cancel).toHaveBeenCalledWith(42);
  });

  it.each(["run_cancelled", "stream_end", "error", "stream_chunk"] as const)("goes once the turn has %s", (type) => {
    render(<GoalDraftingChip />);
    drafting(7);
    const frames = {
      run_cancelled: { type: "run_cancelled", run_id: 7 },
      stream_end: { type: "stream_end", message_id: 3 },
      error: { type: "error", code: "TASK_REVIEW_REQUIRED", message: "task_execution_failed", recoverable: true },
      stream_chunk: { type: "stream_chunk", content: "No checks could be drafted" },
    } as const;
    act(() => { useArslanStore.getState().handleFrame(frames[type] as never); });
    expect(screen.queryByTestId("goal-drafting")).toBeNull();
  });

  it("offers no Cancel when the run has no id to stop", () => {
    render(<GoalDraftingChip />);
    drafting();
    expect(screen.getByTestId("goal-drafting")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("has its words in all six languages", () => {
    const locales = Object.values(jobMessages) as unknown as Array<{ goal: Record<string, unknown> }>;
    expect(locales).toHaveLength(6);
    for (const messages of locales) {
      expect(String(messages.goal.drafting ?? "").trim()).toBeTruthy();
      expect(String(messages.goal.cancelDraft ?? "").trim()).toBeTruthy();
    }
    const zh = locales.find((m) => m.goal.setting === "目标模式")!;
    expect(zh.goal.drafting).toBe("正在起草检查…");
  });
});
