import { render, screen } from "@testing-library/react";
import { describe, test, expect, beforeAll } from "vitest";
import { EvolutionEligibilityPanel } from "./EvolutionEligibilityPanel";
import type { SpawnDiagnosis } from "../api/client.types";
import i18n from "../i18n";

beforeAll(async () => {
  await i18n.changeLanguage("en");
});

const base: SpawnDiagnosis = {
  spawn_id: 1,
  spawn_name: "RA",
  generation_level: 1,
  total_scored: 12,
  replayable: 12,
  non_replayable: 0,
  offending_tools: {},
  baseline_started_at: null,
  scored_ge_baseline: 12,
  corpus_total: 12,
  holdout_ceiling: 6,
  real_holdout: 6,
  effective_holdout: 10,
  propose_count: 6,
  corpus_excluded: 0,
  min_holdout_n: 10,
  consecutive_fails: 0,
  threshold: 10,
  count_since_last_attempt: 0,
  auto_eligible: false,
  open_proposals: 0,
  auto_on: true,
  max_est_tokens: null,
  last_attempts: [],
  verdict_code: "holdout_via_synthetic_topup",
  verdict_params: { real_holdout: 6, min: 10 },
};

describe("EvolutionEligibilityPanel (E9-b Task 4d)", () => {
  test("renders the top-up verdict + the honest holdout blocker chain", () => {
    render(<EvolutionEligibilityPanel diag={base} />);
    // verdict interpolates real_holdout + min from verdict_params
    expect(screen.getByTestId("eligibility-verdict").textContent).toMatch(
      /real holdout has 6 pairs/i,
    );
    expect(screen.getByText(/tops it up to 10 with synthetic tasks/i)).toBeInTheDocument();
    // blocker chain: real → effective after top-up (honest, not "6/10 can't reach")
    expect(screen.getByText(/Holdout pairs: 6 real → 10 after top-up \(need 10\)/i)).toBeInTheDocument();
    expect(screen.getByText(/Replayable runs: 12\/12/i)).toBeInTheDocument();
    // no attempts yet
    expect(screen.getByText(/no attempts yet/i)).toBeInTheDocument();
    // auto_on = true → the auto-off line is NOT shown
    expect(screen.queryByText(/Auto-evolution is off/i)).not.toBeInTheDocument();
  });

  test("shows the last-attempt line + the auto-off line when applicable", () => {
    const diag: SpawnDiagnosis = {
      ...base,
      auto_on: false,
      verdict_code: "gate_failure",
      verdict_params: { attempt_id: 3, reason: "holdout_winrate" },
      last_attempts: [
        {
          id: 3,
          outcome: "failed",
          reason: "holdout_winrate",
          started_at: "2026-07-12T00:00:00",
          finished_at: "2026-07-12T00:01:00",
        },
      ],
    };
    render(<EvolutionEligibilityPanel diag={diag} />);
    expect(screen.getByTestId("eligibility-verdict").textContent).toMatch(
      /last attempt \(#3\) failed the gate: holdout_winrate/i,
    );
    expect(screen.getByText(/Last attempt: failed \(holdout_winrate\)/i)).toBeInTheDocument();
    expect(screen.getByText(/Auto-evolution is off/i)).toBeInTheDocument();
  });
});
