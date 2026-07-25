/**
 * evolution_auto adapter round-trip (S4.2-a).
 *
 * 🔴 This file exists because the component test could not see the hydrate direction:
 * it passes `evolutionAuto` straight in as a prop, which bypasses toUiSettings entirely.
 * Breaking the hydrate line to a constant `false` left every component test green — the
 * toggle would have read OFF forever while the backend said ON, which is precisely the
 * "UI reads OFF while the loop runs" failure the backend tests guard against, arriving
 * from the other side.
 *
 * The wire type is the STRING "on"/"off", not a boolean: sending `true` would be dropped
 * by the pydantic schema without an error, the same way embedding_config_id was.
 */

import { describe, expect, it } from "vitest";

import { toBackendSettings, toUiSettings } from "../api/adapters";
import type { AppSettings } from "../types";

describe("evolution_auto adapter round-trip", () => {
  it('hydrates "on" to true', () => {
    expect(toUiSettings({ evolution_auto: "on" } as never).evolutionAuto).toBe(true);
  });

  it('hydrates "off" to false', () => {
    expect(toUiSettings({ evolution_auto: "off" } as never).evolutionAuto).toBe(false);
  });

  it("defaults to false when the backend omits the field", () => {
    // Matches the backend default. A fresh install must not show a control that claims
    // the loop is running when it is not — or the reverse.
    expect(toUiSettings({} as never).evolutionAuto).toBe(false);
  });

  it('serializes true to the STRING "on", not a boolean', () => {
    const body = toBackendSettings({ evolutionAuto: true } as AppSettings);
    expect(body.evolution_auto).toBe("on");
    expect(typeof body.evolution_auto).toBe("string");
  });

  it('serializes false to the STRING "off"', () => {
    const body = toBackendSettings({ evolutionAuto: false } as AppSettings);
    expect(body.evolution_auto).toBe("off");
  });

  it("survives a full round-trip in both directions", () => {
    for (const wire of ["on", "off"] as const) {
      const ui = toUiSettings({ evolution_auto: wire } as never);
      expect(toBackendSettings(ui as AppSettings).evolution_auto).toBe(wire);
    }
  });
});
