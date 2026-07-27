import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SpawnDetail from "../components/SpawnDetail";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));
vi.mock("../api/client", () => ({
  ApiError: class ApiError extends Error {
    status: number;
    detail?: unknown;
    constructor(message: string, status: number, detail?: unknown) {
      super(message);
      this.status = status;
      this.detail = detail;
    }
  },
  api: {
    getKnowledge: vi.fn(),
    getPreferences: vi.fn().mockResolvedValue({ preferences: [] }),
    deletePreference: vi.fn(),
    ingestKnowledgeText: vi.fn(),
    ingestKnowledgeFile: vi.fn(),
    ingestKnowledgeUrl: vi.fn(),
    deleteKnowledge: vi.fn(),
    getEvolveEstimate: vi.fn(),
    runEvolve: vi.fn(),
  },
}));
import { api } from "../api/client";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

beforeEach(() => {
  vi.clearAllMocks();
  m.getKnowledge.mockResolvedValue([{ source: "policy.txt", chunks: 4 }]);
});

describe("SpawnDetail", () => {
  it("lists knowledge sources on mount", async () => {
    render(<SpawnDetail spawnId={7} spawnName="小美" onClose={() => {}} />);
    await screen.findByText("policy.txt");
    expect(screen.getByText("spawn.chunks_n")).toBeTruthy();
  });

  it("adds text knowledge and refreshes", async () => {
    m.ingestKnowledgeText.mockResolvedValue({ source: "note", chunks_added: 2 });
    render(<SpawnDetail spawnId={7} spawnName="小美" onClose={() => {}} />);
    await screen.findByText("policy.txt");

    fireEvent.change(screen.getByPlaceholderText("spawn.label_placeholder"), { target: { value: "note" } });
    fireEvent.change(screen.getByPlaceholderText("spawn.text_placeholder"), { target: { value: "some material" } });
    fireEvent.click(screen.getByText("spawn.add_text"));

    await waitFor(() => expect(m.ingestKnowledgeText).toHaveBeenCalledWith(7, "note", "some material", false));
    expect(m.getKnowledge).toHaveBeenCalledTimes(2);
  });

  it("shows the cost estimate before enqueuing evolution", async () => {
    m.getEvolveEstimate.mockResolvedValue({
      pairs: 12, dispatches: 156, judge_calls: 24, optimizer_calls: 3,
      synth_calls: 0, est_tokens: 48000, lower_bound: true,
    });
    render(<SpawnDetail spawnId={7} spawnName="小美" onClose={() => {}} />);
    await screen.findByText("policy.txt");
    fireEvent.click(screen.getByText("evolution.inbox.estimate_title"));
    await waitFor(() => expect(m.getEvolveEstimate).toHaveBeenCalledWith(7));
    // The enqueue button only appears once the estimate is shown.
    await screen.findByText("evolution.inbox.enqueue");
  });

  it("enqueues a background evolution attempt", async () => {
    m.getEvolveEstimate.mockResolvedValue({
      pairs: 12, dispatches: 156, judge_calls: 24, optimizer_calls: 3,
      synth_calls: 0, est_tokens: 48000, lower_bound: true,
    });
    m.runEvolve.mockResolvedValue({ attempt_id: 99 });
    render(<SpawnDetail spawnId={7} spawnName="小美" onClose={() => {}} />);
    await screen.findByText("policy.txt");
    fireEvent.click(screen.getByText("evolution.inbox.estimate_title"));
    fireEvent.click(await screen.findByText("evolution.inbox.enqueue"));
    // 批1 P5: this surface must not send force either — the gate is fail-closed and
    // every enqueue surface asks the server first.
    await waitFor(() => expect(m.runEvolve).toHaveBeenCalledWith(7, { force: false }));
    await screen.findByText("evolution.inbox.enqueued");
  });

  it("renders the spend gate's 409 instead of dead-ending on a raw error", async () => {
    // This is the SECOND enqueue surface. It receives the server's fail-closed gate
    // whether or not it handles it, so without the 409 branch its Evolve button became an
    // unrecoverable dead end: a raw error code in the error slot and no way forward.
    m.getEvolveEstimate.mockResolvedValue({
      pairs: 12, dispatches: 156, judge_calls: 24, optimizer_calls: 3,
      synth_calls: 0, est_tokens: 48000, lower_bound: true,
    });
    const { ApiError } = await import("../api/client");
    m.runEvolve
      .mockRejectedValueOnce(
        new (ApiError as unknown as new (m: string, s: number, d: unknown) => Error)(
          "same_corpus_as_failed_attempt", 409, {
            code: "same_corpus_as_failed_attempt", last_attempt_id: 41,
            last_outcome: "failed", last_reason: "holdout_winrate", new_runs_since: 0,
            est_tokens: 48000, est_is_lower_bound: true,
          }))
      .mockResolvedValueOnce({ attempt_id: 99 });

    render(<SpawnDetail spawnId={7} spawnName="小美" onClose={() => {}} />);
    await screen.findByText("policy.txt");
    fireEvent.click(screen.getByText("evolution.inbox.estimate_title"));
    fireEvent.click(await screen.findByText("evolution.inbox.enqueue"));

    expect(await screen.findByTestId("sd-repeat-confirm")).toBeTruthy();
    fireEvent.click(screen.getByTestId("sd-repeat-force"));
    await waitFor(() => expect(m.runEvolve).toHaveBeenLastCalledWith(7, { force: true }));
  });

  it("ingests a URL and refreshes", async () => {
    m.ingestKnowledgeUrl.mockResolvedValue({ source: "https://x.com", chunks_added: 2 });
    render(<SpawnDetail spawnId={7} spawnName="小美" onClose={() => {}} />);
    await screen.findByText("policy.txt");
    fireEvent.change(screen.getByPlaceholderText("spawn.url_placeholder"), { target: { value: "https://x.com" } });
    fireEvent.click(screen.getByText("spawn.fetch"));
    await waitFor(() => expect(m.ingestKnowledgeUrl).toHaveBeenCalledWith(7, "https://x.com", false));
  });
});
