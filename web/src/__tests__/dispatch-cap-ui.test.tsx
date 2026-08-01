/**
 * The UI half of the dispatch cap: what the estimate box shows, and what the Settings
 * warning is allowed to claim.
 *
 * 🔴 Every pre-existing estimate fixture in this suite is the OLD shape, and the
 * components fall back to the old keys, so those tests keep passing whatever the new
 * code does. Nothing here reuses them.
 */

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    // interpolating: the assertions below read rendered VALUES, and the house
    // `t: (k) => k` throws them away
    t: (k: string, vars?: Record<string, unknown>) =>
      vars ? `${k} ${Object.values(vars).join(" ")}` : k,
    i18n: { changeLanguage: vi.fn() },
  }),
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}));

// Relocated with the control it tests: the cap and its warning moved from
// Advanced to Automation, beside the other things that spend. The ASSERTIONS
// are unchanged on purpose — a move is only a move if what it guaranteed
// before it still guarantees after.
import AutomationSection from "../components/settings/AutomationSection";

const base = {
  evolutionAuto: false,
  onEvolutionAutoChange: vi.fn(),
  curationEnabled: false,
  onCurationEnabledChange: vi.fn(),
};

describe("the spend warning may only claim a cap that exists", () => {
  it("says there is NO cap in effect when none is set", () => {
    // 🔴 The point of the whole conditional. Describing "the limit counts dispatches"
    // while no limit is in force describes a guard that is not there — the same
    // "looks armed" failure that made auto-evolution default to off, relocated into
    // copy. Unset is the default and will be most users' state.
    render(<AutomationSection {...base} evolutionMaxDispatches={null} />);
    const warn = screen.getByTestId("evolution-auto-warning");
    expect(warn.textContent).toContain("settings.evolutionAutoSpendWarning");
    expect(warn.textContent).not.toContain("Capped");
  });

  it("switches to the capped wording, carrying the actual number, once one is set", () => {
    render(<AutomationSection {...base} evolutionMaxDispatches={250} />);
    const warn = screen.getByTestId("evolution-auto-warning");
    expect(warn.textContent).toContain("settings.evolutionAutoSpendWarningCapped");
    expect(warn.textContent).toContain("250");
  });

  it("emits null when the field is cleared, not 0", () => {
    // 0 would be a cap of zero dispatches — every attempt refused. Empty means "no cap".
    const onChange = vi.fn();
    render(<AutomationSection {...base} evolutionMaxDispatches={5}
                            onEvolutionMaxDispatchesChange={onChange} />);
    const input = document.getElementById(
      "settings-evolution-max-dispatches") as HTMLInputElement;
    expect(input.value).toBe("5");
    return userEvent.clear(input).then(() => {
      expect(onChange).toHaveBeenCalledWith(null);
      expect(onChange).not.toHaveBeenCalledWith(0);
    });
  });
});
