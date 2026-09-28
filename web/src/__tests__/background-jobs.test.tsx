// 0.1.42 background jobs in the chat: the live card, the result label, the
// sidebar count, and the one spoken line in voice conversation.
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { backgroundJobsApi } from "../api/tasks";
import { toUiMessages } from "../api/adapters";
import JobCard, { JobResultLabel } from "../components/JobCard";
import BackgroundJobs from "../components/companion/BackgroundJobs";
import { jobMessages } from "../locales/jobs";
import { initialArslanState, useArslanStore } from "../stores/arslanStore";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, opts?: Record<string, string>) =>
    opts ? `${key}:${Object.values(opts).join("|")}` : key }),
}));

const update = (over: Record<string, unknown> = {}) => ({
  type: "job_update" as const, job_id: "job-1", conversation_id: "c", goal: "Tidy my notes",
  phase: "running" as const, step: "read_file", outcome: null, detail: "",
  criteria: [{ id: "c1", description: "Saved as notes.md", status: "pending" }], ...over,
});

beforeEach(() => { useArslanStore.setState(initialArslanState(), true); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("store", () => {
  it("places one card where the job started and updates it in place", () => {
    const store = useArslanStore.getState();
    store.handleFrame(update());
    useArslanStore.getState().handleFrame(update({ step: "write_file" }));
    const { items, jobs } = useArslanStore.getState();
    expect(items.filter(it => it.kind === "job")).toHaveLength(1);
    expect(jobs["job-1"].step).toBe("write_file");
  });

  it("keeps live cards when a reconnect replays history", () => {
    useArslanStore.getState().handleFrame(update());
    useArslanStore.getState().handleFrame({ type: "history", messages: [
      { message_id: 1, role: "user", content: "tidy", spawn_id: null }] });
    const kinds = useArslanStore.getState().items.map(it => it.kind);
    expect(kinds).toEqual(["message", "job"]);
  });

  it("tags a job's result message with its job and outcome", () => {
    useArslanStore.getState().handleFrame({ type: "message", message_id: 9, content: "Report ready", role: "arslan",
      job_id: "job-1", outcome: "partial" });
    const [msg] = toUiMessages(useArslanStore.getState().items);
    expect(msg.resultOfJob).toBe("job-1");
    expect(msg.jobOutcome).toBe("partial");
  });

  it("keeps a result's label across a reload, including an interrupted job", () => {
    useArslanStore.getState().handleFrame({ type: "history", messages: [
      { message_id: 1, role: "arslan", content: "Report ready", spawn_id: null, job_outcome: "done" },
      { message_id: 2, role: "arslan", content: "Interrupted", spawn_id: null, job_outcome: "interrupted" },
      { message_id: 3, role: "arslan", content: "plain answer", spawn_id: null, job_outcome: null }] });
    const msgs = toUiMessages(useArslanStore.getState().items);
    expect(msgs.map(m => [Boolean(m.resultOfJob), m.jobOutcome ?? null])).toEqual([
      [true, "done"], [true, "interrupted"], [false, null]]);
  });

  it("raises a notice when a job finishes and when a job's card asks", () => {
    useArslanStore.getState().handleFrame(update());
    useArslanStore.getState().handleFrame({ type: "propose_schedule", call_id: "k", name: "n", when: "w", background: true });
    expect(useArslanStore.getState().jobNotice).toMatchObject({ kind: "needs_approval", jobId: "job-1", seq: 1 });
    expect(useArslanStore.getState().pendingSchedule?.background).toBe(true);
    useArslanStore.getState().handleFrame({ type: "job_spoken", job_id: "job-1", outcome: "done", goal: "Tidy my notes" });
    expect(useArslanStore.getState().jobNotice).toMatchObject({ kind: "finished", outcome: "done", seq: 2 });
  });

  it("drops a successful job-tool step from the trail but keeps a failed one", () => {
    const h = useArslanStore.getState().handleFrame;
    h({ type: "tool_call", tool: "start_background_work", args_summary: "" });
    h({ type: "tool_result", tool: "start_background_work", ok: true, summary: "ok" });
    expect(useArslanStore.getState().activitySteps).toEqual([]);
    h({ type: "tool_call", tool: "start_background_work", args_summary: "" });
    h({ type: "tool_result", tool: "start_background_work", ok: false, summary: "queue full" });
    expect(useArslanStore.getState().activitySteps).toMatchObject([{ tool: "start_background_work", status: "error" }]);
    h({ type: "tool_call", tool: "read_file", args_summary: "" });
    h({ type: "tool_result", tool: "read_file", ok: true, summary: "ok" });
    expect(useArslanStore.getState().activitySteps.map(s => s.tool)).toEqual(["start_background_work", "read_file"]);
  });

  it.each([
    ["propose_schedule", { name: "n", when: "w" }, "pendingSchedule"],
    ["propose_run_command", { pretty: "ls" }, "pendingCommand"],
    ["propose_workspace_write", { workspace: "/w", action: "write", path: "a" }, "pendingWorkspaceWrite"],
  ] as const)("%s: only a background card raises a job notice", (type, fields, slot) => {
    const h = useArslanStore.getState().handleFrame;
    h({ type, call_id: "fg", ...fields } as never);
    expect(useArslanStore.getState().jobNotice).toBeNull();
    expect((useArslanStore.getState()[slot] as { background?: boolean }).background).toBe(false);
    h({ type, call_id: "bg", background: true, ...fields } as never);
    expect(useArslanStore.getState().jobNotice).toMatchObject({ kind: "needs_approval" });
    expect((useArslanStore.getState()[slot] as { background?: boolean }).background).toBe(true);
  });
});

describe("card", () => {
  it("shows goal, criteria and step while running, and stops by id", async () => {
    useArslanStore.getState().handleFrame(update());
    const stop = vi.spyOn(backgroundJobsApi, "stop").mockResolvedValue({ ok: true });
    render(<JobCard jobId="job-1" />);
    expect(screen.getByText("Tidy my notes")).toBeInTheDocument();
    expect(screen.getByText(/Saved as notes.md/)).toBeInTheDocument();
    expect(screen.getByText("jobs.now:read_file")).toBeInTheDocument();
    fireEvent.click(screen.getByText("jobs.stop"));
    await waitFor(() => expect(stop).toHaveBeenCalledWith("job-1"));
  });

  it("shows the checked outcome and no stop button once finished", () => {
    useArslanStore.getState().handleFrame(update({ phase: "finished", outcome: "blocked", detail: "missing input",
      criteria: [{ id: "c1", description: "Saved as notes.md", status: "failed" }] }));
    render(<JobCard jobId="job-1" />);
    expect(screen.getByText("jobs.outcome.blocked")).toBeInTheDocument();
    expect(screen.getByText("missing input")).toBeInTheDocument();
    expect(screen.getByText(/jobs.check.failed/)).toBeInTheDocument();
    expect(screen.queryByText("jobs.stop")).toBeNull();
  });

  it("says when stopping failed instead of pretending", async () => {
    useArslanStore.getState().handleFrame(update());
    vi.spyOn(backgroundJobsApi, "stop").mockRejectedValue(new Error("409"));
    render(<JobCard jobId="job-1" />);
    fireEvent.click(screen.getByText("jobs.stop"));
    expect(await screen.findByText("jobs.stopFailed")).toBeInTheDocument();
  });

  it("labels a result with its outcome", () => {
    render(<JobResultLabel outcome="done" />);
    expect(screen.getByTestId("job-result-label")).toHaveTextContent("jobs.resultOf:jobs.outcome.done");
  });
});

describe("sidebar", () => {
  it("renders nothing when no job runs, so a chat never shows up as a task", async () => {
    const list = vi.spyOn(backgroundJobsApi, "list").mockResolvedValue({ active: 0, jobs: [
      { ...update(), phase: "finished", outcome: "done" }] });
    const { container } = render(<BackgroundJobs onOpen={vi.fn()} />);
    await waitFor(() => expect(list).toHaveBeenCalled());
    await act(async () => {});
    expect(container).toBeEmptyDOMElement();
  });

  it("lists running jobs across conversations and opens the one clicked", async () => {
    vi.spyOn(backgroundJobsApi, "list").mockResolvedValue({ active: 1, jobs: [update({ conversation_id: "other" })] });
    const open = vi.fn();
    render(<BackgroundJobs onOpen={open} />);
    fireEvent.click(await screen.findByTitle("Tidy my notes"));
    expect(open).toHaveBeenCalledWith("other");
    expect(screen.getByLabelText("jobs.inProgress")).toHaveTextContent("1");
  });
});

// The spoken line: only while voice conversation is on, one per notice, and
// the confirmation line never approves anything by itself.
vi.mock("../hooks/useConversationMode", () => ({
  useConversationMode: () => ({ phase: "listening", partial: "" }),
}));
vi.mock("../api/client", async (orig) => ({
  ...(await orig<typeof import("../api/client")>()),
  api: { extractAttachmentUrl: vi.fn(), extractAttachmentFile: vi.fn() },
}));

describe("spoken notices", () => {
  async function chat(voiceMode: "conversation" | "push_to_talk") {
    const { useSettingsStore } = await import("../stores/settingsStore");
    useSettingsStore.setState({ settings: { voice_mode: voiceMode, language: "en" } as never });
    const OrchestratorChat = (await import("../components/OrchestratorChat")).default;
    window.HTMLElement.prototype.scrollIntoView = vi.fn();
    const speak = vi.fn();
    useArslanStore.setState({ speakLine: speak });
    render(<OrchestratorChat chatHistory={[]} setChatHistory={vi.fn()} onSendMessage={vi.fn()} spawns={[]}
      currentStyle="linear" setCurrentStyle={vi.fn()} activeThread={null} />);
    return speak;
  }

  it("says one line when a job finishes while voice conversation is on", async () => {
    const speak = await chat("conversation");
    fireEvent.click(screen.getByTestId("conversation-toggle"));
    act(() => useArslanStore.getState().handleFrame({ type: "job_spoken", job_id: "j", outcome: "done", goal: "Tidy" }));
    expect(speak).toHaveBeenCalledTimes(1);
    expect(speak.mock.calls[0][0]).toBe("jobs.spokenFinished:Tidy|jobs.outcome.done");
    act(() => useArslanStore.getState().handleFrame({ type: "propose_schedule", call_id: "k", name: "n", when: "w", background: true }));
    expect(speak).toHaveBeenCalledTimes(2);
    expect(speak.mock.calls[1][0]).toBe("jobs.spokenApproval");
    expect(useArslanStore.getState().pendingSchedule).not.toBeNull();   // still waiting on a click
  });

  it("says each notice once, even when the conversation toggle changes afterwards", async () => {
    const speak = await chat("conversation");
    fireEvent.click(screen.getByTestId("conversation-toggle"));
    act(() => useArslanStore.getState().handleFrame({ type: "job_spoken", job_id: "j", outcome: "done", goal: "Tidy" }));
    fireEvent.click(screen.getByTestId("conversation-toggle"));   // off
    fireEvent.click(screen.getByTestId("conversation-toggle"));   // on again
    expect(speak).toHaveBeenCalledTimes(1);
  });

  it("stays silent when voice conversation is off", async () => {
    const speak = await chat("conversation");   // available but not switched on
    act(() => useArslanStore.getState().handleFrame({ type: "job_spoken", job_id: "j", outcome: "done", goal: "Tidy" }));
    expect(speak).not.toHaveBeenCalled();
  });
});

describe("jobs copy", () => {
  it("has the same keys in all six languages, every outcome and check word included", () => {
    const flat = (o: object, p = ""): string[] => Object.entries(o).flatMap(([k, v]) =>
      typeof v === "object" ? flat(v, `${p}${k}.`) : [`${p}${k}`]);
    const keys = flat(jobMessages.en).sort();
    expect(Object.keys(jobMessages).sort()).toEqual(["de", "en", "es", "fr", "ja", "zh"]);
    for (const messages of Object.values(jobMessages)) expect(flat(messages).sort()).toEqual(keys);
    for (const outcome of ["done", "partial", "blocked", "stopped", "interrupted"]) expect(keys).toContain(`outcome.${outcome}`);
    for (const check of ["passed", "failed", "unverified", "not_run", "not_applicable", "pending"]) expect(keys).toContain(`check.${check}`);
  });
});
