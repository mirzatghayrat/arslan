import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/client", () => ({ api: { getBrainUsageEvents: vi.fn() } }));

import BrainActivityStrip from "./BrainActivityStrip";
import { api } from "../../api/client";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

const DTO = (over: Record<string, unknown> = {}) => ({
  covered_kinds: ["material", "learning", "note"],
  coverage_note: "Covers material / learning / note only — profile facts are not recorded.",
  window_start: new Date(Date.now() - 30 * 86400_000).toISOString(),
  applied_limit: 5000,
  truncated: false,
  events: [
    { kind: "note", ref_key: "note:1", used_at: new Date(Date.now() - 3600_000).toISOString(), used_ref: "conv:a" },
    { kind: "note", ref_key: "note:1", used_at: new Date(Date.now() - 7200_000).toISOString(), used_ref: "conv:a" },
    { kind: "learning", ref_key: "learning:2", used_at: new Date(Date.now() - 86400_000).toISOString(), used_ref: null },
  ],
  ...over,
});

const props = { litId: null, onHover: vi.fn(), onPick: vi.fn() };

beforeEach(() => { vi.clearAllMocks(); m.getBrainUsageEvents.mockResolvedValue(DTO()); });

describe("BrainActivityStrip", () => {
  it("draws one row per entity and one tick per use", async () => {
    render(<BrainActivityStrip {...props} />);
    await waitFor(() => expect(document.querySelectorAll("[data-strip-row]").length).toBe(2));
    const note = document.querySelector('[data-ref="note:1"]')!;
    expect(note.querySelectorAll(".brain-strip__tick").length).toBe(2);
  });

  it("🔴 asks for an explicit 30-day window — the endpoint DEFAULTS to seven days", async () => {
    // Without `since`, a month-wide grid renders three empty weeks as a quiet period.
    // Asserting merely that the call happened would pass under that bug; assert the arg.
    render(<BrainActivityStrip {...props} />);
    await waitFor(() => expect(m.getBrainUsageEvents).toHaveBeenCalled());
    const arg = m.getBrainUsageEvents.mock.calls[0][0];
    const days = (Date.now() - Date.parse(arg.since)) / 86400_000;
    expect(days).toBeGreaterThan(29);
    expect(days).toBeLessThan(31);
  });

  it("🔴 renders a FAILURE as text, never as an empty raster", async () => {
    // The endpoint answers 503 when the event table is unmigrated. An empty raster is a
    // positive claim ("never used") — the strongest false statement this component can
    // make. A test asserting "no rows" would pass under that bug, so assert the message.
    m.getBrainUsageEvents.mockRejectedValue(new Error("503"));
    render(<BrainActivityStrip {...props} />);
    const el = await screen.findByTestId("brain-strip");
    expect(el.textContent).toContain("暂时不可用");
    expect(el.textContent).toContain("不代表这些记忆没被用过");
    expect(document.querySelectorAll("[data-strip-row]").length).toBe(0);
  });

  it("🔴 surfaces the backend's coverage note verbatim, and never invents one", async () => {
    // profile facts produce NO events (there is no record("profile") in the repo), so a
    // raster drawing four kinds' worth of rows would silently omit one. The coverage
    // statement is the BACKEND's, so the frontend cannot drift from it.
    render(<BrainActivityStrip {...props} />);
    const note = await screen.findByTestId("brain-strip-note");
    expect(note.textContent).toContain("profile facts are not recorded");
  });

  it("🔴 says so when the page was truncated", async () => {
    m.getBrainUsageEvents.mockResolvedValue(DTO({ truncated: true, applied_limit: 5000 }));
    render(<BrainActivityStrip {...props} />);
    const note = await screen.findByTestId("brain-strip-note");
    expect(note.textContent).toContain("已截断");
  });

  it("does not draw a row for a kind that produces no events", async () => {
    // the fixture has no profile events; there must be no profile row inventing zeros
    render(<BrainActivityStrip {...props} />);
    await waitFor(() => expect(document.querySelectorAll("[data-strip-row]").length).toBe(2));
    expect(document.querySelector('[data-ref^="fact:"]')).toBeNull();
  });

  it("lights the row matching litId", async () => {
    const { rerender } = render(<BrainActivityStrip {...props} />);
    await waitFor(() => expect(document.querySelector('[data-ref="note:1"]')).toBeTruthy());
    rerender(<BrainActivityStrip {...props} litId="note:1" />);
    expect(document.querySelector('[data-ref="note:1"]')!.className).toContain("is-lit");
    expect(document.querySelector('[data-ref="learning:2"]')!.className).not.toContain("is-lit");
  });

  it("states the window in words — an empty left edge must not speak for itself", async () => {
    // Retention can be set BELOW the window, in which case pruned days render blank.
    // The component cannot know the setting, so it says what it asked for.
    render(<BrainActivityStrip {...props} />);
    expect((await screen.findByTestId("strip-window")).textContent).toContain("保留策略");
  });

  it("says so when rows were dropped by the row cap", async () => {
    // Zero coverage before: deleting the hidden-rows line left the suite green.
    const many = Array.from({ length: 60 }, (_, i) => ({
      kind: "note", ref_key: `note:${i}`,
      used_at: new Date(Date.now() - 3600_000).toISOString(), used_ref: null,
    }));
    m.getBrainUsageEvents.mockResolvedValue(DTO({ events: many }));
    render(<BrainActivityStrip {...props} />);
    expect((await screen.findByTestId("strip-hidden")).textContent).toContain("未显示");
  });

  it("says nothing was recorded rather than drawing a blank raster silently", async () => {
    m.getBrainUsageEvents.mockResolvedValue(DTO({ events: [] }));
    render(<BrainActivityStrip {...props} />);
    expect((await screen.findByTestId("strip-empty")).textContent).toContain("没有记录到检索");
  });

  it("opens a row under a readable name, not a raw ref key", async () => {
    const onPick = vi.fn();
    render(<BrainActivityStrip {...props} onPick={onPick} />);
    await waitFor(() => expect(document.querySelector('[data-ref="note:1"]')).toBeTruthy());
    (document.querySelector('[data-ref="note:1"]') as HTMLElement).click();
    expect(onPick).toHaveBeenCalledWith(expect.objectContaining({ ref: "note:1", label: "1" }));
  });
});
