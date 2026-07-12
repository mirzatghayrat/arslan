/**
 * Settings Task 3 — CapabilityBadges (spec B2 Cherry-override model).
 *
 * Renders tools / vision / reasoning badges for the selected model. A badge is
 * "active" when the API-derived capabilities include it, but the user can click
 * to override ON/OFF; overrides persist in localStorage keyed by
 * `${configId}:${model}:${cap}` and are MERGED over the API caps at render time
 * (effective = override ?? apiHas) so a manual override is NOT clobbered when
 * the model list refreshes.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { changeLanguage: vi.fn() },
  }),
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}));

import CapabilityBadges, {
  capabilityOverrideKey,
  purgeCapabilityOverrides,
} from "../components/settings/CapabilityBadges";

describe("CapabilityBadges", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("renders a badge for each of tools / vision / reasoning", () => {
    render(<CapabilityBadges configId={1} model="m1" capabilities={[]} />);
    expect(screen.getByTestId("cap-badge-tools")).toBeInTheDocument();
    expect(screen.getByTestId("cap-badge-vision")).toBeInTheDocument();
    expect(screen.getByTestId("cap-badge-reasoning")).toBeInTheDocument();
  });

  it("marks an API-derived capability as active and others inactive", () => {
    render(
      <CapabilityBadges configId={1} model="m1" capabilities={["tools"]} />,
    );
    expect(screen.getByTestId("cap-badge-tools")).toHaveAttribute(
      "data-active",
      "true",
    );
    expect(screen.getByTestId("cap-badge-vision")).toHaveAttribute(
      "data-active",
      "false",
    );
    expect(screen.getByTestId("cap-badge-reasoning")).toHaveAttribute(
      "data-active",
      "false",
    );
  });

  it("clicking a badge toggles it, persists to localStorage, and fires onOverride", () => {
    const onOverride = vi.fn();
    render(
      <CapabilityBadges
        configId={42}
        model="gpt-x"
        capabilities={[]}
        onOverride={onOverride}
      />,
    );
    const vision = screen.getByTestId("cap-badge-vision");
    expect(vision).toHaveAttribute("data-active", "false");
    fireEvent.click(vision);
    expect(onOverride).toHaveBeenCalledWith("vision", true);
    expect(localStorage.getItem(capabilityOverrideKey(42, "gpt-x", "vision"))).toBe(
      "on",
    );
    expect(screen.getByTestId("cap-badge-vision")).toHaveAttribute(
      "data-active",
      "true",
    );
  });

  it("can override an API-active capability OFF", () => {
    render(
      <CapabilityBadges configId={1} model="m1" capabilities={["tools"]} />,
    );
    const tools = screen.getByTestId("cap-badge-tools");
    expect(tools).toHaveAttribute("data-active", "true");
    fireEvent.click(tools);
    expect(screen.getByTestId("cap-badge-tools")).toHaveAttribute(
      "data-active",
      "false",
    );
    expect(localStorage.getItem(capabilityOverrideKey(1, "m1", "tools"))).toBe(
      "off",
    );
  });

  it("purgeCapabilityOverrides removes every override key for a config id (PK-reuse safety)", () => {
    localStorage.setItem(capabilityOverrideKey(2, "X", "tools"), "on");
    localStorage.setItem(capabilityOverrideKey(2, "X", "vision"), "off");
    localStorage.setItem(capabilityOverrideKey(2, "Y", "reasoning"), "on");
    // A different config that must NOT be purged.
    localStorage.setItem(capabilityOverrideKey(3, "X", "tools"), "on");
    // A config whose id merely SHARES the "2" prefix (20) must survive — the
    // purge prefix ends in a colon so id 2 does not match id 20.
    localStorage.setItem(capabilityOverrideKey(20, "X", "tools"), "on");
    // An unrelated key must be untouched.
    localStorage.setItem("arslan.other", "keep");

    purgeCapabilityOverrides(2);

    expect(localStorage.getItem(capabilityOverrideKey(2, "X", "tools"))).toBeNull();
    expect(localStorage.getItem(capabilityOverrideKey(2, "X", "vision"))).toBeNull();
    expect(localStorage.getItem(capabilityOverrideKey(2, "Y", "reasoning"))).toBeNull();
    expect(localStorage.getItem(capabilityOverrideKey(3, "X", "tools"))).toBe("on");
    expect(localStorage.getItem(capabilityOverrideKey(20, "X", "tools"))).toBe("on");
    expect(localStorage.getItem("arslan.other")).toBe("keep");
  });

  it("after a purge, a config reusing the id + model shows the API caps (no stale override)", () => {
    // Config 2 / model X had tools overridden ON despite no API tools cap.
    localStorage.setItem(capabilityOverrideKey(2, "X", "tools"), "on");
    purgeCapabilityOverrides(2);
    // A brand-new config reclaims id 2 with the same model string but the API
    // says it has NO tools — the stale override must not leak through.
    render(<CapabilityBadges configId={2} model="X" capabilities={[]} />);
    expect(screen.getByTestId("cap-badge-tools")).toHaveAttribute(
      "data-active",
      "false",
    );
  });

  it("a stored override survives a capabilities prop change (override wins over refresh)", () => {
    // Pre-seed an ON override for vision (not in the API caps).
    localStorage.setItem(capabilityOverrideKey(1, "m1", "vision"), "on");
    const { rerender } = render(
      <CapabilityBadges configId={1} model="m1" capabilities={["tools"]} />,
    );
    expect(screen.getByTestId("cap-badge-vision")).toHaveAttribute(
      "data-active",
      "true",
    );
    // Model list "refreshes" with a different API cap set that STILL omits vision.
    rerender(
      <CapabilityBadges configId={1} model="m1" capabilities={["reasoning"]} />,
    );
    // The manual override wins — vision stays active despite the refresh.
    expect(screen.getByTestId("cap-badge-vision")).toHaveAttribute(
      "data-active",
      "true",
    );
    // And the refreshed API cap (reasoning) becomes active with no override.
    expect(screen.getByTestId("cap-badge-reasoning")).toHaveAttribute(
      "data-active",
      "true",
    );
  });
});
