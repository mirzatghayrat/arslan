import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));

vi.mock("../api/client", () => {
  class ApiError extends Error {
    status: number;
    detail?: unknown;
    constructor(message: string, status: number, detail?: unknown) {
      super(message);
      this.status = status;
      this.detail = detail;
    }
  }
  return {
    ApiError,
    api: {
      getEvolutionProposals: vi.fn(),
      listSpawns: vi.fn(),
      getProposalDetail: vi.fn(),
      getEvolutionDiagnosis: vi.fn(),
      getEvolveEstimate: vi.fn(),
      runEvolve: vi.fn(),
      confirmProposal: vi.fn(),
      rejectProposal: vi.fn(),
      rollbackProposal: vi.fn(),
      refreshProposal: vi.fn(),
    },
  };
});

import EvolutionInbox from "../components/EvolutionInbox";
import { api } from "../api/client";
import type { ProposalListItem, ProposalDetail, SpawnDiagnosis } from "../api/client.types";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

const ROW: ProposalListItem = {
  id: 3, spawn_id: 7, status: "open", gate_passed: true, base_prompt_sha: "abc",
  real_delta: { wins: 6, losses: 4, ties: 1, n: 10, win_rate: 0.6, p_value: 0.04, ci95: [0.3, 0.85] },
  synthetic_delta: { wins: 9, losses: 3, ties: 0, n: 12, win_rate: 0.75, p_value: 0.02, ci95: [0.5, 0.9] },
  evidence_tier: "strong", flags: [], created_at: "2026-07-11T00:00:00", promoted_at: null,
};

const DETAIL: ProposalDetail = {
  id: 3, spawn_id: 7, spawn_name: "小美", status: "open", gate_passed: true,
  generation_level: 1, base_prompt_sha: "abc", base_prompt: "a\nOLD", candidate_prompt: "a\nNEW",
  is_stale: false, estimate: null, actual: null, created_at: "2026-07-11T00:00:00", promoted_at: null,
  evidence: {
    flags: [],
    real_delta: ROW.real_delta!, synthetic_delta: ROW.synthetic_delta!,
    evidence_tier: "strong", pairs: [], excluded_count: 0,
  },
};


const DIAG = {
  spawn_id: 7, generation_level: 1, total_scored: 12, replayable: 12, non_replayable: 0,
  offending_tools: [], baseline_started_at: null, scored_ge_baseline: 12, corpus_total: 12,
  holdout_ceiling: 5, real_holdout: 5, effective_holdout: 5, propose_count: 7,
  corpus_excluded: 0, min_holdout_n: 10, consecutive_fails: 1, threshold: 20,
  count_since_last_attempt: 0, auto_eligible: false, open_proposals: 1, auto_on: true,
  max_est_tokens: null, last_attempts: [], verdict_code: "gate_failure", verdict_params: {},
} as unknown as SpawnDiagnosis;

beforeEach(() => {
  vi.clearAllMocks();
  m.getEvolutionProposals.mockResolvedValue([ROW]);
  m.listSpawns.mockResolvedValue([{ id: 7, name: "小美" }]);
  m.getProposalDetail.mockResolvedValue(DETAIL);
  m.getEvolutionDiagnosis.mockResolvedValue(null); // per-spawn eligibility panel fetch (E9-b)
});

describe("EvolutionInbox", () => {
  it("lists proposals with SEPARATE real + synthetic deltas (never merged)", async () => {
    render(<EvolutionInbox onOpenRun={() => {}} />);
    const row = await screen.findByTestId("inbox-row");
    expect(row.textContent).toContain("小美");
    // both corpus numbers appear, distinctly
    expect(row.textContent).toContain("60%"); // real
    expect(row.textContent).toContain("75%"); // synthetic
    // no averaged number (67.5 → 68%)
    expect(row.textContent).not.toContain("68%");
  });

  it("opens a proposal's PromotionCard on click", async () => {
    render(<EvolutionInbox onOpenRun={() => {}} />);
    fireEvent.click(await screen.findByTestId("inbox-row"));
    await waitFor(() => expect(m.getProposalDetail).toHaveBeenCalledWith(3));
    expect(await screen.findByTestId("promotion-card")).toBeTruthy();
  });

  it("shows the estimate before enqueuing a run", async () => {
    m.getEvolveEstimate.mockResolvedValue({
      pairs: 12, dispatches: 156, judge_calls: 24, optimizer_calls: 3,
      synth_calls: 0, est_tokens: 48000, lower_bound: true,
    });
    m.runEvolve.mockResolvedValue({ attempt_id: 42 });
    render(<EvolutionInbox onOpenRun={() => {}} />);
    await screen.findByTestId("inbox-row");

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "7" } });
    fireEvent.click(screen.getByTestId("estimate-btn"));
    await waitFor(() => expect(m.getEvolveEstimate).toHaveBeenCalledWith(7));
    expect(await screen.findByTestId("estimate-box")).toBeTruthy();

    fireEvent.click(screen.getByTestId("enqueue-btn"));
    // 批1 P5: the click must NOT send force. The gate is fail-closed, so an ordinary
    // click asks the server whether this would re-run an already-failed corpus; only the
    // confirmation dialog's own button sends force: true.
    await waitFor(() => expect(m.runEvolve).toHaveBeenCalledWith(7, { force: false }));
    // P7: with an attempt_id we now FOLLOW the attempt, so the panel shows "running…"
    // rather than a terminal-looking success line that never updates.
    expect(await screen.findByTestId("watching-msg")).toBeTruthy();
  });

  it("renders the empty state when there are no proposals", async () => {
    m.getEvolutionProposals.mockResolvedValue([]);
    render(<EvolutionInbox onOpenRun={() => {}} />);
    await waitFor(() => expect(screen.getByText("evolution.inbox.empty")).toBeTruthy());
  });

  it("shows the eligibility panel in the empty state once a spawn is selected", async () => {
    m.getEvolutionProposals.mockResolvedValue([]);
    const diag: SpawnDiagnosis = {
      spawn_id: 7, spawn_name: "小美", generation_level: 1, total_scored: 12, replayable: 12,
      non_replayable: 0, offending_tools: {}, baseline_started_at: null, scored_ge_baseline: 12,
      corpus_total: 12, holdout_ceiling: 6, real_holdout: 6, effective_holdout: 10,
      propose_count: 6, corpus_excluded: 0, min_holdout_n: 10, consecutive_fails: 0,
      threshold: 10, count_since_last_attempt: 0, auto_eligible: false, open_proposals: 0,
      auto_on: true, max_est_tokens: null, last_attempts: [],
      verdict_code: "holdout_via_synthetic_topup", verdict_params: { real_holdout: 6, min: 10 },
    };
    m.getEvolutionDiagnosis.mockResolvedValue(diag);
    render(<EvolutionInbox onOpenRun={() => {}} />);
    await waitFor(() => expect(screen.getByText("evolution.inbox.empty")).toBeTruthy());
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "7" } });
    await waitFor(() => expect(m.getEvolutionDiagnosis).toHaveBeenCalledWith(7));
    expect(await screen.findByTestId("eligibility-panel")).toBeTruthy();
  });

  // ── P7/P8/P9 ────────────────────────────────────────────────────────────────────

  it("P8: shows the eligibility panel on FIRST PAINT, without the user picking a spawn", async () => {
    // The panel already existed but was unreachable in practice: `diag` loaded only after
    // the user chose a spawn from a control labelled "Run evolution…", i.e. the answer to
    // "why are there no proposals?" sat behind the button a confused user would not press.
    m.getEvolutionDiagnosis.mockResolvedValue(DIAG);
    render(<EvolutionInbox onOpenRun={() => {}} />);

    await waitFor(() => expect(m.getEvolutionDiagnosis).toHaveBeenCalledWith(7));
    expect(await screen.findByTestId("eligibility-panel")).toBeTruthy();
  });

  it("P8: the panel is NOT gated on the global proposal list being empty", async () => {
    // A user holding a proposal for one spawn could otherwise never learn why ANOTHER
    // spawn has none — the old empty-state gate hid the explanation exactly when the
    // fleet was partly working.
    m.getEvolutionProposals.mockResolvedValue([ROW]);   // non-empty list
    m.getEvolutionDiagnosis.mockResolvedValue(DIAG);
    render(<EvolutionInbox onOpenRun={() => {}} />);

    expect(await screen.findByTestId("inbox-row")).toBeTruthy();
    expect(await screen.findByTestId("eligibility-panel")).toBeTruthy();
  });

  it("P9: a 409 from the spend gate becomes a confirmation built from the SERVER's facts", async () => {
    m.getEvolveEstimate.mockResolvedValue({
      pairs: 12, dispatches: 156, judge_calls: 24, optimizer_calls: 3,
      synth_calls: 0, est_tokens: 48000, lower_bound: true,
    });
    const { ApiError } = await import("../api/client");
    m.runEvolve.mockRejectedValueOnce(
      new (ApiError as unknown as new (m: string, s: number, d: unknown) => Error)(
        "same_corpus_as_failed_attempt", 409, {
          code: "same_corpus_as_failed_attempt", last_attempt_id: 41,
          last_outcome: "failed", last_reason: "holdout_winrate", new_runs_since: 0,
          est_tokens: 48000, est_is_lower_bound: true,
        }),
    );
    render(<EvolutionInbox onOpenRun={() => {}} />);
    await screen.findByTestId("inbox-row");
    fireEvent.click(screen.getByTestId("estimate-btn"));
    fireEvent.click(await screen.findByTestId("enqueue-btn"));

    const dialog = await screen.findByTestId("repeat-confirm");
    expect(dialog).toBeTruthy();
    // it must NOT have silently enqueued anything
    expect(await screen.queryByTestId("watching-msg")).toBeNull();
  });

  it("P9: confirming re-sends with force, cancelling sends nothing", async () => {
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
    render(<EvolutionInbox onOpenRun={() => {}} />);
    await screen.findByTestId("inbox-row");
    fireEvent.click(screen.getByTestId("estimate-btn"));
    fireEvent.click(await screen.findByTestId("enqueue-btn"));
    fireEvent.click(await screen.findByTestId("repeat-force"));

    await waitFor(() => expect(m.runEvolve).toHaveBeenLastCalledWith(7, { force: true }));
  });

  it("P7: follows the attempt IT launched and reports the terminal outcome", async () => {
    // Keyed on the launched attempt id, never on last_attempts[0]: the auto watcher runs
    // on the same spawn, so that slot can hold a DIFFERENT attempt and we would report
    // someone else's outcome as the result of this click.
    m.getEvolveEstimate.mockResolvedValue({
      pairs: 12, dispatches: 156, judge_calls: 24, optimizer_calls: 3,
      synth_calls: 0, est_tokens: 48000, lower_bound: true,
    });
    m.runEvolve.mockResolvedValue({ attempt_id: 99 });
    m.getEvolutionDiagnosis
      // an unrelated attempt occupies slot 0 while ours is still in flight
      .mockResolvedValueOnce({ ...DIAG, last_attempts: [{ id: 100, outcome: "passed", reason: "" }] })
      .mockResolvedValue({
        ...DIAG,
        last_attempts: [
          { id: 100, outcome: "passed", reason: "" },
          { id: 99, outcome: "skipped_budget", reason: "estimate 48000 exceeds budget 500" },
        ],
      });

    render(<EvolutionInbox onOpenRun={() => {}} />);
    await screen.findByTestId("inbox-row");
    fireEvent.click(screen.getByTestId("estimate-btn"));
    fireEvent.click(await screen.findByTestId("enqueue-btn"));

    expect(await screen.findByTestId("watching-msg")).toBeTruthy();
    // 🔴 the refusal must SURFACE — before this, skipped_budget was decided server-side
    // after the 202 and the UI never mentioned it at all.
    const msg = await screen.findByTestId("enqueued-msg", {}, { timeout: 8000 });
    expect(msg.textContent).toContain("outcome_skipped_budget");
  }, 15000);
});
