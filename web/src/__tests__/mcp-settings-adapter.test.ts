/**
 * mcpServerEnabled adapter round-trip (Task 10).
 *
 * The inbound-MCP toggle rides the existing settings adapter machinery — it
 * must hydrate from the backend's `mcp_server_enabled` and serialize back to
 * it, exactly like every other boolean settings field.
 */

import { describe, it, expect } from "vitest";
import { toUiSettings, toBackendSettings } from "../api/adapters";
import type { AppSettings } from "../types";

describe("mcpServerEnabled adapter round-trip", () => {
  it("round-trips mcpServerEnabled", () => {
    const ui = toUiSettings({ mcp_server_enabled: true } as never);
    expect(ui.mcpServerEnabled).toBe(true);
    expect(
      toBackendSettings({ ...ui, mcpServerEnabled: true } as AppSettings).mcp_server_enabled,
    ).toBe(true);
  });

  it("defaults mcpServerEnabled to false when the backend field is absent", () => {
    const ui = toUiSettings({} as never);
    expect(ui.mcpServerEnabled).toBe(false);
  });

  it("serializes mcpServerEnabled=false to the backend body", () => {
    const ui = toUiSettings({ mcp_server_enabled: false } as never);
    expect(
      toBackendSettings({ ...ui, mcpServerEnabled: false } as AppSettings).mcp_server_enabled,
    ).toBe(false);
  });
});
