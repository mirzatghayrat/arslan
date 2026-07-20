import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

/**
 * 🔴 This file exists because component-level tests could not see a real defect.
 *
 * BrainLineage was first mounted as a SIBLING of BrainEntryDetail inside a shared
 * `absolute` wrapper. BrainEntryDetail's own root is `absolute top-0 right-0 h-full`
 * and opaque, so it became the containing block and painted over the lineage entirely:
 * the whole genealogy was unreachable in the app while every BrainLineage test passed,
 * because those render it standalone.
 *
 * The lesson generalises past this bug — a panel that renders correctly in isolation
 * proves nothing about whether the app ever shows it. So this asserts through
 * BrainSection, the real composition.
 */

const { graph, tree } = vi.hoisted(() => ({
  graph: {
    nodes: [
      { id: "self", ref: "self", kind: "self", label: "你", val: 9 },
      { id: "fact:1", ref: "fact:1", kind: "profile", label: "旧偏好", val: 1,
        valid_from: "2024-01-01T00:00:00.000000Z", superseded_by: 2 },
      { id: "fact:2", ref: "fact:2", kind: "profile", label: "新偏好", val: 1,
        valid_from: "2025-01-01T00:00:00.000000Z" },
    ],
    links: [
      { source: "self", target: "fact:1", type: "hub" },
      { source: "self", target: "fact:2", type: "hub" },
    ],
  },
  tree: {
    branches: [{
      kind: "profile", label: "画像",
      children: [{ kind: "profile", ref: "fact:1", label: "旧偏好", provenance: "auto",
        confidence: 0.8, usage_count: 0, last_used_at: null, last_used_ref: null,
        value: 1, superseded_by: 2 }],
    }],
  },
}));

vi.mock("../../../api/client", () => ({
  ApiError: class extends Error { status = 0; },
  api: {
    getBrainGraph: vi.fn().mockResolvedValue(graph),
    getBrainTree: vi.fn().mockResolvedValue(tree),
    getBrainEntry: vi.fn().mockResolvedValue({
      kind: "profile", ref: "fact:1", label: "旧偏好", provenance: "auto",
      confidence: 0.8, excerpt: "旧偏好", usage_count: 0, last_used_at: null,
      last_used_ref: null, valid_from: "2024-01-01T00:00:00.000000Z",
      superseded_by: 2, provenance_record: null,
    }),
    getBrainUsageEvents: vi.fn().mockResolvedValue({ events: [], covered_kinds: [] }),
    getEmbeddingStatus: vi.fn().mockResolvedValue({ active_provider: null, pending: 0 }),
    listMemoryProposals: vi.fn().mockResolvedValue({ proposals: [] }),
  },
}));

import BrainSection from "../BrainSection";

describe("BrainSection composition", () => {
  it("shows the lineage panel, not just mounts it", async () => {
    render(<BrainSection />);
    // pick the superseded fact through the real graph node
    await waitFor(() =>
      expect(document.querySelector('[data-node][data-kind="profile"]')).toBeTruthy());
    const n = document.querySelector('[data-node-wrap][data-id="fact:1"] circle[data-node]')!;
    (n as HTMLElement).dispatchEvent(new MouseEvent("click", { bubbles: true }));

    const lineage = await screen.findByTestId("brain-lineage");
    expect(lineage).toBeTruthy();

    // and it is genuinely painted, not stacked under the opaque detail panel:
    // its nearest positioned ancestor must be the detail panel itself, i.e. it is a
    // CHILD of that panel rather than a sibling competing with it for the same box
    const detail = lineage.closest('[data-testid="brain-entry-detail"]');
    expect(detail).not.toBeNull();

    // both generations are listed, oldest first
    const rows = lineage.querySelectorAll("[data-lineage-id]");
    expect([...rows].map((r) => r.getAttribute("data-lineage-id")))
      .toEqual(["fact:1", "fact:2"]);
  });
});
