import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// 🔴 The mock MUST interpolate. Returning the bare key discards every {{value}}, so a
// component whose numbers all go through t(key, {vars}) — which is this one — renders
// digit-free text under test. Any assertion about the NUMBERS shown then has nothing to
// look at and passes no matter what. That is exactly how this file's "never renders a
// ratio" test came to certify a property it could not observe.
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (k: string, vars?: Record<string, unknown>) =>
      vars ? `${k} ${Object.values(vars).join(" ")}` : k,
  }),
}));

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
      confirmProposal: vi.fn(),
      rejectProposal: vi.fn(),
      rollbackProposal: vi.fn(),
      refreshProposal: vi.fn(),
    },
  };
});

import PromotionCard from "../components/PromotionCard";
import { api, ApiError } from "../api/client";
import type { ProposalDetail, DeltaStat, EvidencePair } from "../api/client.types";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

function delta(over: Partial<DeltaStat>): DeltaStat {
  return {
    wins: 0, losses: 0, ties: 0, n: 0, win_rate: 0, p_value: 1, ci95: [0, 0], ...over,
  };
}

function pair(over: Partial<EvidencePair>): EvidencePair {
  return {
    task_hash: "h", corpus_label: "real", source_ref: 1, split_side: "holdout",
    baseline_run_id: 10, candidate_run_id: 20, base_out_len: 100, cand_out_len: 110,
    per_dim: { fabrication: "b", identity: "tie", completion: "b" }, overall: "b",
    position_sensitive: false, ...over,
  };
}

function proposal(over: Partial<ProposalDetail> = {}): ProposalDetail {
  return {
    id: 1, spawn_id: 7, spawn_name: "小美", status: "open", gate_passed: true,
    generation_level: 1, base_prompt_sha: "abc", base_prompt: "line1\nOLD\nline3",
    candidate_prompt: "line1\nNEW\nline3", is_stale: false,
    estimate: null, actual: null, created_at: "2026-07-11T00:00:00", promoted_at: null,
    evidence: {
      passed: true, reason: "pass", flags: [],
      real_delta: delta({ wins: 6, losses: 4, ties: 1, n: 10, win_rate: 0.6, p_value: 0.04, ci95: [0.3, 0.85] }),
      synthetic_delta: delta({ wins: 7, losses: 2, ties: 0, n: 9, win_rate: 0.78, p_value: 0.09, ci95: [0.4, 0.97] }),
      evidence_tier: "strong",
      pairs: [pair({})],
      excluded_count: 3,
    },
    ...over,
  };
}

beforeEach(() => vi.clearAllMocks());

describe("PromotionCard", () => {
  it("(a) renders real and synthetic as SEPARATE numbers, never a merged/averaged win-rate", () => {
    const p = proposal({
      evidence: {
        flags: [],
        real_delta: delta({ wins: 1, losses: 10, ties: 0, n: 11, win_rate: 0.09 }),
        synthetic_delta: delta({ wins: 2, losses: 9, ties: 0, n: 11, win_rate: 0.18 }),
        evidence_tier: "strong",
        pairs: [pair({})],
        excluded_count: 0,
      },
    });
    render(<PromotionCard proposal={p} onOpenRun={() => {}} />);

    // Both corpus numbers appear, in two distinct labeled blocks.
    expect(screen.getByTestId("corpus-real").textContent).toContain("9%");
    expect(screen.getByTestId("corpus-synthetic").textContent).toContain("18%");

    // No merged/averaged win-rate anywhere: (9+18)/2 = 13.5 → 14% must NOT be rendered.
    const body = document.body.textContent ?? "";
    expect(body).not.toContain("13.5%");
    expect(body).not.toContain("14%");
    // And there is no combined block — only the two labeled corpus blocks exist.
    expect(screen.getAllByTestId(/corpus-/)).toHaveLength(2);
  });

  it("(b) shows the synthetic-driven banner when real_delta.n < 3", () => {
    const p = proposal({
      evidence: {
        flags: [],
        real_delta: delta({ wins: 1, losses: 1, ties: 0, n: 2, win_rate: 0.5 }),
        synthetic_delta: delta({ wins: 8, losses: 1, ties: 0, n: 9, win_rate: 0.89 }),
        evidence_tier: "medium",
        pairs: [pair({})],
        excluded_count: 0,
      },
    });
    render(<PromotionCard proposal={p} onOpenRun={() => {}} />);
    expect(screen.getByTestId("synthetic-driven-banner")).toBeTruthy();
  });

  it("(c) weak tier → 建议再等数据 hint + subdued (non-primary) promote button", () => {
    const p = proposal({ evidence: { ...proposal().evidence, evidence_tier: "weak" } });
    render(<PromotionCard proposal={p} onOpenRun={() => {}} />);
    expect(screen.getByTestId("weak-hint")).toBeTruthy();
    const btn = screen.getByTestId("confirm-btn");
    // subdued style = no solid primary background
    expect(btn.className).not.toContain("bg-primary");
  });

  it("(d) a pair row's 查看重放 targets the candidate_run_id", () => {
    const onOpenRun = vi.fn();
    const p = proposal({
      evidence: { ...proposal().evidence, pairs: [pair({ baseline_run_id: 55, candidate_run_id: 77 })] },
    });
    render(<PromotionCard proposal={p} onOpenRun={onOpenRun} />);
    const link = screen.getByTestId("view-replay");
    expect(link.getAttribute("data-run-id")).toBe("77");
    fireEvent.click(link);
    expect(onOpenRun).toHaveBeenCalledWith(77);
  });

  it("(e) diff renders add and del lines from base vs candidate", () => {
    render(<PromotionCard proposal={proposal()} onOpenRun={() => {}} />);
    const diff = screen.getByTestId("prompt-diff");
    const del = diff.querySelector('[data-diff="del"]');
    const add = diff.querySelector('[data-diff="add"]');
    expect(del?.textContent).toContain("OLD");
    expect(add?.textContent).toContain("NEW");
  });

  it("(f) confirm on a drifted proposal surfaces the stale (过期) message path via 409", async () => {
    m.confirmProposal.mockRejectedValue(new ApiError("stale", 409));
    render(<PromotionCard proposal={proposal()} onOpenRun={() => {}} />);
    fireEvent.click(screen.getByTestId("confirm-btn"));
    await waitFor(() => expect(screen.getByTestId("stale-banner")).toBeTruthy());
  });

  it("shows the stale banner immediately for a status='stale' proposal", () => {
    render(<PromotionCard proposal={proposal({ status: "stale", is_stale: true })} onOpenRun={() => {}} />);
    expect(screen.getByTestId("stale-banner")).toBeTruthy();
    // stale proposals offer re-run, not a direct promote
    expect(screen.getByTestId("rerun-btn")).toBeTruthy();
  });

  it("shows a rollback button for a promoted proposal", () => {
    render(<PromotionCard proposal={proposal({ status: "promoted" })} onOpenRun={() => {}} />);
    expect(screen.getByTestId("rollback-btn")).toBeTruthy();
  });

  it("per-dimension table aggregates W/L/T from the pairs (never propose-set)", () => {
    const p = proposal({
      evidence: {
        ...proposal().evidence,
        pairs: [
          pair({ per_dim: { fabrication: "b", identity: "b", completion: "a" }, overall: "b" }),
          pair({ per_dim: { fabrication: "a", identity: "tie", completion: "b" }, overall: "tie" }),
        ],
      },
    });
    render(<PromotionCard proposal={p} onOpenRun={() => {}} />);
    // fabrication: 1 win (b) + 1 loss (a) → N=2
    const fab = screen.getByTestId("dim-row-fabrication");
    expect(fab.textContent).toContain("2");
  });

  // ── B: est vs actual honesty ────────────────────────────────────────────────────
  //
  // 🔴 The two numbers are unreliable in OPPOSITE directions — the estimate over-counts
  // and grows with corpus size, this figure can under-count and may itself be a
  // heuristic. Rendered as adjacent lines they read as forecast-vs-outcome and invite a
  // ratio that means nothing. These tests pin the separation and the caveats.

  const withActual = (actual: Record<string, unknown>) => proposal({
    estimate: { pairs: 4, dispatches: 56, judge_calls: 56, optimizer_calls: 3,
                synth_calls: 0, est_tokens: 40000, lower_bound: true },
    actual,
  } as Partial<ProposalDetail>);

  it("renders the actual cost in its OWN block, not as a sibling of the estimate", async () => {
    // 🔴 "the estimate is not INSIDE the actual block" is true of the adjacent-sibling
    // layout this change exists to end, so asserting only that proves nothing. Assert
    // the structural fact instead: they are in different containers, and the estimate's
    // container is not the actual block's immediate previous sibling.
    render(<PromotionCard proposal={withActual({
      est_tokens: 12000, dispatch_tokens: 10000, direct_tokens: 2000,
      failed_dispatches: 0, estimated: false })} onOpenRun={() => {}} />);
    const block = await screen.findByTestId("actual-cost");
    const estimateEl = [...document.querySelectorAll("div")].find(
      (d) => d.textContent?.startsWith("evolution.card.estimate_line"));
    expect(estimateEl).toBeTruthy();
    expect(block.contains(estimateEl!)).toBe(false);
    expect(estimateEl!.parentElement).not.toBe(block.parentElement);
  });

  it("🔴 says the two numbers are not comparable, always", async () => {
    render(<PromotionCard proposal={withActual({
      est_tokens: 12000, dispatch_tokens: 10000, direct_tokens: 2000,
      failed_dispatches: 0, estimated: false })} onOpenRun={() => {}} />);
    expect(await screen.findByTestId("not-comparable")).toBeTruthy();
  });

  it("🔴 renders ONLY the numbers it is allowed to — no derived comparison", async () => {
    // A reader given two adjacent token counts will compute a ratio; the component must
    // not do it FOR them, because the ratio is meaningless.
    //
    // 🔴 An ALLOWLIST, not a list of forbidden shapes. My first version banned three
    // regexes I happened to think of (%, signed delta, multiplier) — and since the t()
    // mock swallowed interpolation, it was checking digit-free text and could not fail at
    // all: a real Math.round(actual/estimate*100) rendered through t() passed 16/16.
    // Enumerating what MAY appear catches derived numbers nobody thought to forbid.
    const allowed = new Set(["12000", "10000", "2000"]);   // the raw fields, nothing else
    render(<PromotionCard proposal={withActual({
      est_tokens: 12000, dispatch_tokens: 10000, direct_tokens: 2000,
      failed_dispatches: 0, estimated: false })} onOpenRun={() => {}} />);
    const block = await screen.findByTestId("actual-cost");
    const numbers = (block.textContent ?? "").match(/\d+/g) ?? [];
    const unexpected = numbers.filter((n) => !allowed.has(n));
    expect(unexpected).toEqual([]);
  });

  it("shows the dispatch/direct split rather than one opaque total", async () => {
    render(<PromotionCard proposal={withActual({
      est_tokens: 12000, dispatch_tokens: 10000, direct_tokens: 2000,
      failed_dispatches: 0, estimated: false })} onOpenRun={() => {}} />);
    expect(await screen.findByTestId("actual-split")).toBeTruthy();
  });

  it("🔴 admits when the figure contains a heuristic", async () => {
    render(<PromotionCard proposal={withActual({
      est_tokens: 12000, dispatch_tokens: 10000, direct_tokens: 2000,
      failed_dispatches: 0, estimated: true })} onOpenRun={() => {}} />);
    expect(await screen.findByTestId("actual-estimated")).toBeTruthy();
  });

  it("🔴 admits when a failed arm may have gone uncounted", async () => {
    render(<PromotionCard proposal={withActual({
      est_tokens: 12000, dispatch_tokens: 10000, direct_tokens: 2000,
      failed_dispatches: 2, estimated: false })} onOpenRun={() => {}} />);
    expect(await screen.findByTestId("actual-incomplete")).toBeTruthy();
  });

  it("stays quiet about caveats that do not apply", async () => {
    render(<PromotionCard proposal={withActual({
      est_tokens: 12000, dispatch_tokens: 10000, direct_tokens: 2000,
      failed_dispatches: 0, estimated: false })} onOpenRun={() => {}} />);
    await screen.findByTestId("actual-cost");
    expect(screen.queryByTestId("actual-estimated")).toBeNull();
    expect(screen.queryByTestId("actual-incomplete")).toBeNull();
  });
});
