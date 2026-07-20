import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import BrainAsOfSlider from "../BrainAsOfSlider";
import type { GraphNodeDto } from "../../../api/client";

// interpolating mock — see BrainTemporalRender.test.tsx for why the house
// `t: (k) => k` cannot be used for anything that asserts rendered values
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (k: string, vars?: Record<string, unknown>) =>
      vars ? `${k} ${Object.values(vars).join(" ")}` : k,
  }),
}));

const node = (id: string, valid_from: string | null): GraphNodeDto =>
  ({ id, ref: id, kind: "profile", label: id, val: 1, valid_from }) as GraphNodeDto;

const T = (d: string) => `${d}T00:00:00.000000Z`;
const SPAN = [node("fact:1", T("2024-01-01")), node("fact:2", T("2026-01-01"))];

describe("BrainAsOfSlider", () => {
  it("does not render when the data spans a single instant", () => {
    // a control that cannot move is worse than no control: it implies there is
    // something to see across time when there is not
    render(<BrainAsOfSlider nodes={[node("fact:1", T("2024-01-01"))]} value={null}
      onChange={vi.fn()} />);
    expect(screen.queryByTestId("asof-slider")).toBeNull();
  });

  it("does not render when no node carries a time at all", () => {
    render(<BrainAsOfSlider nodes={[node("fact:1", null)]} value={null} onChange={vi.fn()} />);
    expect(screen.queryByTestId("asof-slider")).toBeNull();
  });

  it("renders at home with NO caveat, because nothing is being filtered", () => {
    render(<BrainAsOfSlider nodes={SPAN} value={null} onChange={vi.fn()} />);
    expect(screen.getByTestId("asof-slider")).toBeTruthy();
    expect(screen.queryByTestId("asof-caveat")).toBeNull();
    expect(screen.getByTestId("asof-value").textContent).toContain("brain.temporal.asOfAll");
  });

  it("shows the honesty caveat whenever it IS filtering", () => {
    // 🔴 This caption is the only disclosure that travels with the feature — the person
    // dragging the slider reads neither the code comment nor the delivery note. If it
    // ever stops rendering, the feature starts silently claiming to show the past.
    render(<BrainAsOfSlider nodes={SPAN} value={T("2025-01-01")} onChange={vi.fn()} />);
    const caveat = screen.getByTestId("asof-caveat");
    expect(caveat.textContent).toContain("brain.temporal.asOfCaveat");
    expect(screen.getByTestId("asof-value").textContent).toContain("2025-01-01");
  });

  it("returns to home when dragged fully right", () => {
    // 🔴 The range input only permits values of min + k*step. With raw utcnow()
    // endpoints and step=1 day, the rightmost REACHABLE value is strictly below max,
    // so an `ms >= max` reset never fires and the user is stranded in a filtered view
    // with no way back. Both bounds are snapped to whole days to make this reachable.
    const onChange = vi.fn();
    render(<BrainAsOfSlider nodes={SPAN} value={T("2025-01-01")} onChange={onChange} />);
    const range = screen.getByTestId("asof-range") as HTMLInputElement;
    fireEvent.change(range, { target: { value: range.max } });
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("emits an ISO instant for any position short of the right edge", () => {
    const onChange = vi.fn();
    render(<BrainAsOfSlider nodes={SPAN} value={null} onChange={onChange} />);
    const range = screen.getByTestId("asof-range") as HTMLInputElement;
    fireEvent.change(range, { target: { value: range.min } });
    expect(onChange).toHaveBeenCalledTimes(1);
    const arg = onChange.mock.calls[0][0];
    expect(arg).not.toBeNull();
    expect(Date.parse(arg)).toBe(Number(range.min));
  });
});
