import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));

vi.mock("../api/client", () => {
  class ApiError extends Error {
    status: number;
    constructor(message: string, status: number) {
      super(message);
      this.status = status;
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
    await waitFor(() => expect(m.runEvolve).toHaveBeenCalledWith(7));
    expect(await screen.findByTestId("enqueued-msg")).toBeTruthy();
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
});
