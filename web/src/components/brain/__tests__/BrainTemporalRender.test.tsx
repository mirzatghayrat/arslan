import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import BrainGraph from "../BrainGraph";
import BrainLineage from "../BrainLineage";
import type { GraphNodeDto } from "../../../api/client";

/** 🔴 The i18n mock INTERPOLATES.
 *
 * The house default is `t: (k) => k`, which throws interpolated values away. Under it,
 * an assertion like "this text contains no digits" can never see a number no matter
 * what the component does — so a component fabricating `{{at}}: 2026-07-20` would pass
 * a test written to forbid exactly that. (That is not hypothetical: it shipped in the
 * previous batch and the final review caught it.) Every temporal assertion below reads
 * rendered VALUES, so the mock has to carry them through. */
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (k: string, vars?: Record<string, unknown>) =>
      vars ? `${k} ${Object.values(vars).join(" ")}` : k,
  }),
}));

// vi.mock is hoisted above every const, so the spy has to be created inside vi.hoisted
// or it is still in its temporal dead zone when the factory runs.
const { getBrainGraph } = vi.hoisted(() => ({ getBrainGraph: vi.fn() }));
vi.mock("../../../api/client", () => ({ api: { getBrainGraph } }));

const T = (d: string) => `${d}T00:00:00.000000Z`;

const node = (o: Partial<GraphNodeDto> & { id: string }): GraphNodeDto =>
  ({ ref: o.id, kind: "profile", label: o.id, val: 1, ...o }) as GraphNodeDto;

/** two facts: fact:1 superseded BY fact:2 */
const NODES: GraphNodeDto[] = [
  node({ id: "fact:1", label: "旧偏好", valid_from: T("2024-01-01"), superseded_by: 2 }),
  node({ id: "fact:2", label: "新偏好", valid_from: T("2025-01-01") }),
  node({ id: "note:1", kind: "note", label: "笔记", created_at: T("2026-01-01") }),
];
const SELF = node({ id: "self", kind: "self", label: "你" });

/** Every fixture carries the 「你」 hub node AND its edge.
 *
 * 🔴 Leaving the node out while keeping the edge makes d3 throw
 * `Error: node not found: self` and blanks the whole component — which is precisely
 * why hiddenAt returns a set of IDS instead of a filtered node array. An as-of filter
 * that removed nodes would reproduce this crash on the very first hidden node, since
 * brain.py:349-354 gives every otherwise-orphaned entry a self-hub edge. (Learned the
 * hard way: the first draft of this fixture omitted the node and every test blanked.)
 */
const graph = (nodes = NODES) => ({
  nodes: [SELF, ...nodes],
  links: nodes.map((n) => ({ source: "self", target: n.id, type: "hub" })),
});

const props = {
  litId: null, onHover: vi.fn(), onPick: vi.fn(), onCreateNoteWithTitle: vi.fn(),
  showTags: true,
};

const wrap = (id: string) =>
  document.querySelector(`[data-node-wrap][data-id="${id}"]`) as HTMLElement | null;

beforeEach(() => {
  vi.clearAllMocks();
  getBrainGraph.mockResolvedValue(graph());
});

describe("superseded nodes in the rendered graph", () => {
  it("marks the superseded node and leaves the current one unmarked", async () => {
    render(<BrainGraph {...props} />);
    await waitFor(() => expect(wrap("fact:1")).not.toBeNull());
    // both are kind=profile, so an assertion by kind could not tell them apart —
    // that is why the wrapper carries data-id and data-superseded
    expect(wrap("fact:1")?.getAttribute("data-superseded")).toBe("true");
    expect(wrap("fact:2")?.getAttribute("data-superseded")).toBeNull();
  });

  it("keeps the superseded node VISIBLE — it is dimmed, never removed", async () => {
    render(<BrainGraph {...props} />);
    await waitFor(() => expect(wrap("fact:1")).not.toBeNull());
    const el = wrap("fact:1")!;
    expect(el.getAttribute("data-hidden")).toBeNull();
    expect(el.style.display).not.toBe("none");
    expect(Number(el.style.opacity)).toBeGreaterThan(0);
    expect(Number(el.style.opacity)).toBeLessThan(1);   // and visually distinct
  });

  it("draws a directed supersede edge, derived from superseded_by", async () => {
    render(<BrainGraph {...props} />);
    await waitFor(() => expect(wrap("fact:1")).not.toBeNull());
    const sup = document.querySelectorAll('[data-link][data-link-type="supersede"]');
    expect(sup).toHaveLength(1);
    expect(sup[0].getAttribute("marker-end")).toContain("supersede-arrow");
  });

  it("draws NO supersede edge for a dangling pointer", async () => {
    // the successor was hard-deleted (brain.py:745 etc). d3 forceLink throws on an
    // endpoint outside the node set, so this must produce nothing rather than a stub.
    getBrainGraph.mockResolvedValue(graph([
      node({ id: "fact:1", valid_from: T("2024-01-01"), superseded_by: 999 }),
    ]));
    render(<BrainGraph {...props} />);
    await waitFor(() => expect(wrap("fact:1")).not.toBeNull());
    expect(document.querySelectorAll('[data-link-type="supersede"]')).toHaveLength(0);
  });

  it("drops the edge and the badge once the pointer is cleared (undo)", async () => {
    // nail 1, BOTH directions in one body: an implementation reading a field that does
    // not exist would render neither, and would pass the "after" half on its own.
    const { unmount } = render(<BrainGraph {...props} />);
    await waitFor(() => expect(wrap("fact:1")).not.toBeNull());
    expect(wrap("fact:1")?.getAttribute("data-superseded")).toBe("true");
    expect(document.querySelectorAll('[data-link-type="supersede"]')).toHaveLength(1);
    unmount();

    getBrainGraph.mockResolvedValue(graph([
      node({ id: "fact:1", label: "旧偏好", valid_from: T("2024-01-01"), superseded_by: null }),
      node({ id: "fact:2", label: "新偏好", valid_from: T("2025-01-01") }),
    ]));
    render(<BrainGraph {...props} />);
    await waitFor(() => expect(wrap("fact:1")).not.toBeNull());
    expect(wrap("fact:1")?.getAttribute("data-superseded")).toBeNull();
    expect(document.querySelectorAll('[data-link-type="supersede"]')).toHaveLength(0);
  });
});

describe("as-of filtering, through the rendered component", () => {
  // a predicate that is written and unit-tested but never wired into the render path
  // passes every pure-function test in temporal.test.ts. These go through the DOM.

  it("hides an entry that did not exist yet at T", async () => {
    render(<BrainGraph {...props} asOf={T("2025-06-01")} />);
    await waitFor(() => expect(wrap("fact:2")).not.toBeNull());
    expect(wrap("note:1")?.getAttribute("data-hidden")).toBe("true");
    expect(wrap("note:1")?.style.display).toBe("none");
    expect(wrap("fact:2")?.getAttribute("data-hidden")).toBeNull();
  });

  it("hides a belief already superseded at T, and shows it again at home", async () => {
    const { unmount } = render(<BrainGraph {...props} asOf={T("2026-06-01")} />);
    await waitFor(() => expect(wrap("fact:1")).not.toBeNull());
    expect(wrap("fact:1")?.getAttribute("data-hidden")).toBe("true");
    unmount();

    render(<BrainGraph {...props} asOf={null} />);
    await waitFor(() => expect(wrap("fact:1")).not.toBeNull());
    expect(wrap("fact:1")?.getAttribute("data-hidden")).toBeNull();
  });

  it("hides the edges of a hidden node — d3 keeps them, the paint must not", async () => {
    render(<BrainGraph {...props} asOf={T("2025-06-01")} />);
    await waitFor(() => expect(wrap("fact:2")).not.toBeNull());
    const supEdge = document.querySelector('[data-link-type="supersede"]') as HTMLElement;
    // fact:1 was superseded at 2025-01-01, which is <= this T, so it IS hidden —
    // and the supersede edge that ends on it must go with it.
    expect(wrap("fact:1")?.getAttribute("data-hidden")).toBe("true");
    expect(supEdge.getAttribute("data-hidden")).toBe("true");
  });

  it("issues NO request when the as-of value changes", async () => {
    // as-of is a paint-time filter. If it ever became a query parameter, the honest
    // claim "this never refetches and never touches injection" would be false.
    // NOTE: no global-fetch spy here. The whole api/client module is mocked above, so
    // nothing in this component can reach `fetch` under ANY implementation — such an
    // assertion could not fail and would be coverage theatre. The call-count checks on
    // the mocked client below are what actually carry this test.
    const { rerender } = render(<BrainGraph {...props} asOf={null} />);
    await waitFor(() => expect(wrap("fact:1")).not.toBeNull());
    expect(getBrainGraph).toHaveBeenCalledTimes(1);

    rerender(<BrainGraph {...props} asOf={T("2024-06-01")} />);
    rerender(<BrainGraph {...props} asOf={T("2025-06-01")} />);
    await waitFor(() => expect(wrap("fact:1")?.getAttribute("data-hidden")).toBe("true"));

    expect(getBrainGraph).toHaveBeenCalledTimes(1);   // still one, from mount
    expect(getBrainGraph).toHaveBeenLastCalledWith();  // and with no as-of argument
  });
});

describe("BrainLineage — never invents an end time", () => {
  const render1 = (nodes: GraphNodeDto[], sel = "fact:1") =>
    render(<BrainLineage selectedId={sel} nodes={nodes} onPickId={vi.fn()} />);

  it("shows the derived end instant when it is trustworthy (positive control)", () => {
    // 🔴 The control that makes the 未知 test below meaningful. Without it, "renders no
    // digits" is satisfied by a component that renders nothing at all.
    render1(NODES);
    const row = document.querySelector('[data-lineage-id="fact:1"]')!;
    expect(row.textContent).toContain("2025-01-01");
  });

  it("says 未知 — and prints NO digits — when the successor has no valid_from", () => {
    // nail 2. Allowlist form: any digit other than the ones legitimately on this row
    // fails, so a fabricated `Date.now()` fallback cannot slip through as plausible text.
    render1([
      node({ id: "fact:1", label: "旧", valid_from: null, superseded_by: 2 }),
      node({ id: "fact:2", label: "新", valid_from: null }),
    ]);
    const row = document.querySelector('[data-lineage-id="fact:1"]')!;
    expect(row.textContent).toContain("brain.temporal.endUnknown");
    // the only digit allowed on this row is the ordinal "1"
    expect(row.textContent!.replace(/1/g, "")).not.toMatch(/\d/);
  });

  it("RENDERS the truncation warning when the walk was actually cut", () => {
    // the flag being correct in temporal.ts proves nothing about the panel showing it —
    // a banner that is computed and never rendered is the "guard defined but never
    // wired" failure, and it is silent by construction
    const long = Array.from({ length: 200 }, (_, i) =>
      node({ id: `fact:${i + 1}`, label: `v${i + 1}`,
        ...(i + 1 < 200 ? { superseded_by: i + 2 } : {}) }));
    render1(long);
    expect(screen.getByTestId("lineage-truncated").textContent)
      .toContain("brain.temporal.lineageTruncated");
  });

  it("does NOT warn about truncation on a chain that fits exactly", () => {
    const exact = Array.from({ length: 64 }, (_, i) =>
      node({ id: `fact:${i + 1}`, label: `v${i + 1}`,
        ...(i + 1 < 64 ? { superseded_by: i + 2 } : {}) }));
    render1(exact);
    expect(screen.queryByTestId("lineage-truncated")).toBeNull();
  });

  it("RENDERS the merged-ancestors warning when the genealogy branches", () => {
    // two rows superseded by the same survivor (dedup merge): only one branch is
    // walked, so presenting it as the whole story would be a completeness claim
    render1([
      node({ id: "fact:1", label: "甲", superseded_by: 3 }),
      node({ id: "fact:2", label: "乙", superseded_by: 3 }),
      node({ id: "fact:3", label: "合并后", valid_from: T("2025-01-01") }),
    ], "fact:3");
    expect(screen.getByTestId("lineage-merged").textContent)
      .toContain("brain.temporal.lineageMerged");
  });

  it("does NOT warn about merges on a plain linear chain", () => {
    render1(NODES);
    expect(screen.queryByTestId("lineage-merged")).toBeNull();
  });

  it("renders nothing when the entry has no supersede relation", () => {
    render1([node({ id: "fact:9", valid_from: T("2024-01-01") })], "fact:9");
    expect(screen.queryByTestId("brain-lineage")).toBeNull();
  });
});
