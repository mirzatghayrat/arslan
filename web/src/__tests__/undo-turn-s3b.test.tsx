/**
 * 0.1.63 S3b: a reply's ⋯ offers "Undo this turn…"; the sheet says what an undo covers, with the later turns
 * that go first and plainly, and offers only what can happen (files, conversation, both); the conversation the
 * server now has replaces the open one's messages; Settings say when the workspace's changes can't be undone.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k),
    i18n: { resolvedLanguage: "en", language: "en" } }),
}));
const { runCheckpoint, undoTurn, toast } = vi.hoisted(() => ({ runCheckpoint: vi.fn(), undoTurn: vi.fn(), toast: vi.fn() }));
vi.mock("../api/client", async (orig) => ({ ...(await orig<object>()), api: { runCheckpoint, undoTurn, runProcess: vi.fn() } }));
vi.mock("../components/kit", async (orig) => ({ ...(await orig<object>()), toast }));

import { ApiError } from "../api/client";
import type { ArslanHistoryRow, RunCheckpoint } from "../api/client.types";
import ReplyFooter from "../components/reply/ReplyFooter";
import { TURN_UNDONE_EVENT, showUndone } from "../components/reply/UndoTurnSheet";
import AdvancedSection from "../components/settings/AdvancedSection";
import { initialArslanState, useArslanStore } from "../stores/arslanStore";

beforeEach(() => { useArslanStore.setState(initialArslanState(), true); });
afterEach(() => { cleanup(); vi.clearAllMocks(); });

const BOTH: RunCheckpoint = {
  exists: true, changed: 2, created: 1, skipped: [], excluded: ["node_modules"], later: [9], running: false,
  restored_at: null, conversation: true, reason: null, messages_after: 6, later_turns: 2, facts: 1, last_message_id: 42,
};
const NO_FILES: RunCheckpoint = { exists: false, conversation: true, reason: null, messages_after: 6, later_turns: 2,
  facts: 1, last_message_id: 42 };
const HISTORY: ArslanHistoryRow[] = [{ message_id: 1, role: "user", content: "one", spawn_id: null },
  { message_id: 2, role: "arslan", content: "reply", spawn_id: null, run_id: 3 }];

async function openSheet(info: RunCheckpoint) {
  runCheckpoint.mockResolvedValue(info);
  render(<ReplyFooter text="reply" process={{ runId: 7, entries: [], summary: { steps: 0, failed: 0, ms: null, usage: null } }} latest />);
  fireEvent.click(screen.getByTestId("reply-more"));
  fireEvent.click(screen.getByTestId("reply-undo"));
  await screen.findByTestId("undo-turn");
  expect(runCheckpoint).toHaveBeenCalledWith(7);
}

describe("undo this turn", () => {
  it("is offered only for a reply with a run", () => {
    render(<ReplyFooter text="x" process={{ runId: null, entries: [], summary: { steps: 0, failed: 0, ms: null, usage: null } }} latest />);
    fireEvent.click(screen.getByTestId("reply-more"));
    expect(screen.queryByTestId("reply-undo")).toBeNull();
  });

  it("says the later turns first, what goes, the iPhone, and with files offers them alone or with the conversation", async () => {
    await openSheet(BOTH);
    expect(screen.getByTestId("undo-later-turns").textContent).toContain('process.undoLater:{"count":2}');
    expect(screen.getByTestId("undo-facts").textContent).toContain('process.undoFacts:{"count":1}');
    expect(screen.getByTestId("undo-phone").textContent).toBe("process.undoPhone");
    expect(screen.getByText('process.undoLaterRuns:{"count":1}')).toBeTruthy();
    expect(screen.getByText('process.undoExcluded:{"names":"node_modules"}')).toBeTruthy();
    for (const id of ["undo-files", "undo-both"]) expect(screen.getByTestId(id)).toBeTruthy();
    expect(screen.queryByTestId("undo-conversation")).toBeNull();     // afterwards the menu, and its files, are gone
  });

  it("offers only what can happen, and says why the rest can't", async () => {
    await openSheet({ ...BOTH, conversation: false, reason: "summarised" });
    expect(screen.getByTestId("undo-why").textContent).toBe("process.undoWhy_summarised");
    expect(screen.getByTestId("undo-files")).toBeTruthy();
    expect(screen.queryByTestId("undo-conversation")).toBeNull();
    expect(screen.queryByTestId("undo-both")).toBeNull();
    cleanup();
    await openSheet({ exists: false, conversation: true, reason: null, messages_after: 2, later_turns: 0, facts: 0 });
    expect(screen.getByText("process.undoNoFiles")).toBeTruthy();
    expect(screen.getByTestId("undo-conversation")).toBeTruthy();
    expect(screen.queryByTestId("undo-later-turns")).toBeNull();
    expect(screen.queryByTestId("undo-files")).toBeNull();
    expect(screen.queryByTestId("undo-both")).toBeNull();
  });

  it("undoing the conversation hands the server's history to the window", async () => {
    undoTurn.mockResolvedValue({ conversation: { conversation_id: "c1", messages: 6, later_turns: 2, facts: 1, history: HISTORY } });
    const seen = vi.fn();
    window.addEventListener(TURN_UNDONE_EVENT, seen);
    await openSheet(NO_FILES);
    fireEvent.click(screen.getByTestId("undo-conversation"));
    await waitFor(() => expect(seen).toHaveBeenCalled());
    window.removeEventListener(TURN_UNDONE_EVENT, seen);
    expect(undoTurn).toHaveBeenCalledWith(7, "conversation", 42);     // held to what the box counted
    expect((seen.mock.calls[0][0] as CustomEvent).detail.history).toEqual(HISTORY);
    expect(toast).toHaveBeenCalledWith("process.undoDone");
    await waitFor(() => expect(screen.queryByTestId("undo-turn")).toBeNull());
  });

  it("a refusal says why and keeps the sheet", async () => {
    undoTurn.mockRejectedValue(new ApiError("refused", 409, { code: "finishing" }));
    await openSheet(BOTH);
    fireEvent.click(screen.getByTestId("undo-both"));
    await waitFor(() => expect(toast).toHaveBeenCalledWith("process.undoWhy_finishing"));
    expect(undoTurn).toHaveBeenCalledWith(7, "both", 42);
    expect(screen.getByTestId("undo-turn")).toBeTruthy();
  });

  it("files that could not go back are listed and the sheet stays, so they can be tried again", async () => {
    undoTurn.mockRejectedValue(new ApiError("refused", 409, { code: "files_failed",
      files: { runs: [{ failed: ["plan.md"], git: null }, { failed: [], git: "failed" }] } }));
    await openSheet(BOTH);
    fireEvent.click(screen.getByTestId("undo-both"));
    await screen.findByTestId("undo-not-back");
    expect(screen.getByTestId("undo-not-back").textContent).toContain('"paths":"plan.md, .git"');
    expect(toast).not.toHaveBeenCalledWith("process.undoDone");
    expect(screen.getByTestId("undo-files")).toBeTruthy();
  });

  it("a conversation that failed after the files went back says so", async () => {
    undoTurn.mockRejectedValue(new ApiError("refused", 409, { code: "conversation_failed", reason: "changed",
      files: { runs: [{ failed: [] }] } }));
    await openSheet(BOTH);
    fireEvent.click(screen.getByTestId("undo-both"));
    await waitFor(() => expect(toast).toHaveBeenCalledWith("process.undoConversationFailed"));
  });

  it("the open conversation shows what the server now has; another one is left alone", () => {
    useArslanStore.getState().handleFrame({ type: "history", messages: [...HISTORY,
      { message_id: 3, role: "user", content: "two" }, { message_id: 4, role: "arslan", content: "reply two" }] } as never);
    expect(showUndone({ conversation_id: "other", messages: 2, later_turns: 0, facts: 0, history: HISTORY }, "c1")).toBe(false);
    expect(useArslanStore.getState().items).toHaveLength(4);
    expect(showUndone({ conversation_id: "c1", messages: 2, later_turns: 0, facts: 0, history: HISTORY }, "c1")).toBe(true);
    expect(useArslanStore.getState().items.map((i) => i.content)).toEqual(["one", "reply"]);
  });
});

describe("settings", () => {
  type Props = React.ComponentProps<typeof AdvancedSection>;
  const props = (over: Partial<Props> = {}): Props => ({
    telemetry: false, onTelemetryChange: vi.fn(), orchestratorShellEnabled: false, onOrchestratorShellChange: vi.fn(),
    shellConfirmPolicy: "ask_all", onShellConfirmPolicyChange: vi.fn(), workspaceDir: "/Volumes/x", onWorkspaceDirChange: vi.fn(),
    lanDiscoveryEnabled: false, onLanDiscoveryChange: vi.fn(), sshEnabled: false, onSshChange: vi.fn(),
    defaultReadEnabled: true, onDefaultReadChange: vi.fn(), voiceInputLocale: "", onVoiceInputLocaleChange: vi.fn(),
    voiceMode: "push_to_talk", onVoiceModeChange: vi.fn(), voiceEndpointSilenceMs: 900, onVoiceEndpointSilenceChange: vi.fn(),
    ...over,
  });

  it("say when the workspace's changes can't be undone", () => {
    const { rerender } = render(<AdvancedSection {...props()} />);
    expect(screen.queryByTestId("settings-workspace-other-volume")).toBeNull();
    rerender(<AdvancedSection {...props({ workspaceOtherVolume: true })} />);
    expect(screen.getByTestId("settings-workspace-other-volume").textContent).toContain("settings.workspaceOtherVolume");
  });
});
