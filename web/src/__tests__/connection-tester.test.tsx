/**
 * Settings Task 3 — ConnectionTester (two-level connectivity + usability test).
 *
 * Level 1 "Test connection" = the fast /health probe (onProbeHealth); it renders
 * the PERSISTENT tri-state result (config.last_health / last_health_at) + a
 * relative time, and the reachable_no_list caveat. Level 2 "Deep test" = the
 * existing real-chat round-trip (onDeepTest) and shows its transient result.
 */

import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { changeLanguage: vi.fn() },
  }),
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}));

import ConnectionTester from "../components/settings/ConnectionTester";
import type { ProviderConfig } from "../api/client.types";

/** naive-UTC ISO (no timezone suffix) ~5 minutes ago. */
const fiveMinAgo = new Date(Date.now() - 5 * 60_000).toISOString().slice(0, -1);

function makeConfig(overrides: Partial<ProviderConfig> = {}): ProviderConfig {
  return {
    id: 7,
    label: "A",
    provider: "deepseek",
    model: "deepseek-chat",
    base_url: "",
    api_key: "de...cd",
    is_primary: true,
    last_health: "reachable_models",
    last_health_at: fiveMinAgo,
    ...overrides,
  };
}

describe("ConnectionTester", () => {
  it("level-1 button calls onProbeHealth with the config", () => {
    const config = makeConfig();
    const onProbeHealth = vi.fn();
    render(
      <ConnectionTester
        config={config}
        onProbeHealth={onProbeHealth}
        onDeepTest={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("connection-test-level1"));
    expect(onProbeHealth).toHaveBeenCalledWith(config);
  });

  it("renders the persistent tri-state dot + relative time from config fields", () => {
    render(
      <ConnectionTester
        config={makeConfig()}
        onProbeHealth={vi.fn()}
        onDeepTest={vi.fn()}
      />,
    );
    const dot = screen.getByTestId("connection-health-dot");
    expect(dot).toHaveAttribute("data-health-state", "reachable_models");
    // relative time derived from last_health_at (~5m ago → the minutes key).
    expect(screen.getByText("settings.timeMinutesAgo")).toBeInTheDocument();
  });

  it("shows the reachable_no_list caveat when the state is reachable_no_list", () => {
    render(
      <ConnectionTester
        config={makeConfig({ last_health: "reachable_no_list" })}
        onProbeHealth={vi.fn()}
        onDeepTest={vi.fn()}
      />,
    );
    expect(
      screen.getByTestId("connection-reachable-no-list-note"),
    ).toHaveTextContent("settings.reachableNoListNote");
  });

  it("does NOT show the caveat for reachable_models", () => {
    render(
      <ConnectionTester
        config={makeConfig()}
        onProbeHealth={vi.fn()}
        onDeepTest={vi.fn()}
      />,
    );
    expect(
      screen.queryByTestId("connection-reachable-no-list-note"),
    ).toBeNull();
  });

  it("level-2 button calls onDeepTest and shows its result", () => {
    const config = makeConfig();
    const onDeepTest = vi.fn();
    render(
      <ConnectionTester
        config={config}
        onProbeHealth={vi.fn()}
        onDeepTest={onDeepTest}
        deepTestStatus={{ state: "ok", latency: 200 }}
      />,
    );
    fireEvent.click(screen.getByTestId("connection-test-level2"));
    expect(onDeepTest).toHaveBeenCalledWith(config);
    // transient level-2 (usability) result is visible (ok + latency)
    expect(screen.getByText(/settings\.deepTestOk/)).toBeInTheDocument();
    expect(screen.getByText(/· 200ms/)).toBeInTheDocument();
  });

  it("shows the level-2 failure error", () => {
    render(
      <ConnectionTester
        config={makeConfig()}
        onProbeHealth={vi.fn()}
        onDeepTest={vi.fn()}
        deepTestStatus={{ state: "failed", error: "Invalid API key" }}
      />,
    );
    expect(screen.getByText(/Invalid API key/)).toBeInTheDocument();
  });

  it("prefers the live health overlay prop over the config fields", () => {
    render(
      <ConnectionTester
        config={makeConfig({ last_health: "reachable_models" })}
        health="unreachable"
        lastHealthAt={fiveMinAgo}
        onProbeHealth={vi.fn()}
        onDeepTest={vi.fn()}
      />,
    );
    expect(screen.getByTestId("connection-health-dot")).toHaveAttribute(
      "data-health-state",
      "unreachable",
    );
  });
});
