/** S1b (U14 d): the schedule card shows the text the task runs each time, beside its bounds: a yes no longer
 *  covers a prompt nobody saw. The frame's `prompt` reaches the window's card through the store (AskSlot)
 *  and the Inbox (AskForFrame); a frame without one (an older server) shows the card as before. */
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import AskSlot from "../components/AskSlot";
import AskForFrame from "../components/AskForFrame";
import ScheduleGrantCard from "../components/ScheduleGrantCard";
import { initialArslanState, useArslanStore } from "../stores/arslanStore";

beforeEach(() => { useArslanStore.setState(initialArslanState(), true); });
afterEach(() => { cleanup(); });

const schedule = { type: "propose_schedule", call_id: "s1", name: "digest", when: "every: 86400",
                   prompt: "Summarise my inbox", options: ["once", "conversation"] };

describe("S1b: the schedule card shows what the task will do", () => {
  it("shows the prompt and the bounds of a scheduled run", () => {
    render(<ScheduleGrantCard callId="s1" name="digest" when="every: 86400" prompt="Summarise my inbox"
      onConfirm={() => {}} onCancel={() => {}} />);
    expect(screen.getByTestId("schedule-prompt")).toHaveTextContent("Summarise my inbox");
    expect(screen.getByTestId("schedule-unattended")).toHaveTextContent("schedgrant.unattended");
  });

  it("a frame without a prompt shows the card as before", () => {
    render(<ScheduleGrantCard callId="s1" name="digest" when="every: 86400" onConfirm={() => {}} onCancel={() => {}} />);
    expect(screen.getByTestId("schedule-card")).toBeInTheDocument();
    expect(screen.queryByTestId("schedule-prompt")).toBeNull();
  });

  it("the prompt reaches the window's card from the frame", () => {
    act(() => { useArslanStore.getState().handleFrame(schedule as never); });
    render(<AskSlot send={() => {}} />);
    expect(screen.getByTestId("schedule-prompt")).toHaveTextContent("Summarise my inbox");
  });

  it("and the Inbox's", () => {
    render(<AskForFrame ask={{ call_id: "s1", conversation_id: "c", frame: schedule } as never}
      onAnswer={() => {}} />);
    expect(screen.getByTestId("schedule-prompt")).toHaveTextContent("Summarise my inbox");
  });
});
