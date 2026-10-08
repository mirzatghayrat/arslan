/** 0.1.55 §14: Capabilities as switches — on / off / one step away / can't, with the reason. */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor, within } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, o?: Record<string, unknown>) =>
    o && "count" in o ? `${key}:${o.count}` : o && "detail" in o ? `${key}:${o.detail}` : key }),
}));

import CapabilitySwitches from "../components/CapabilitySwitches";
import { capabilitiesApi, type CapabilityRow } from "../api/capabilities";
import { OPEN_SECTION_EVENT } from "../lib/sections";
import { capabilityListMessages } from "../locales/capabilityList";

const row = (over: Partial<CapabilityRow>): CapabilityRow => ({ key: "x", group: "mac", state: "on", tools: [], switch: null,
  reason: null, fix: null, name: null, detail: null, source: "builtin", ...over });

const ROWS: CapabilityRow[] = [
  row({ key: "terminal", state: "on", switch: "setting" }),
  row({ key: "files", state: "off", switch: "setting", detail: "own_folder_only" }),
  row({ key: "hands", state: "setup", reason: "hands_missing", fix: "open_settings:abilities" }),
  row({ key: "web", group: "research", state: "setup", reason: "no-key", fix: "open_settings:connections" }),
  row({ key: "mcp:2", group: "work", state: "na", reason: "runtime_missing", detail: "npx", name: "Files", source: "mcp" }),
  row({ key: "mcp:3", group: "work", state: "setup", reason: "mcp_error", fix: "open_tab:mcps", name: "Broken", source: "mcp", switch: "mcp", detail: "401" }),
  ...Array.from({ length: 8 }, (_, i) => row({ key: `skill:s${i}`, group: "methods", switch: "skill", source: "skill", name: `Skill ${i}` })),
];

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("capability switches", () => {
  it("draws each state its own way: a switch, a one-step button, or the reason", async () => {
    vi.spyOn(capabilitiesApi, "list").mockResolvedValue(ROWS);
    render(<CapabilitySwitches />);
    expect(await screen.findByTestId("cap-switch-terminal")).toBeChecked();
    expect(screen.getByTestId("cap-switch-files")).not.toBeChecked();
    expect(screen.getByTestId("cap-files")).toHaveTextContent("capabilityList.detail_own_folder_only");
    expect(screen.getByTestId("cap-fix-hands")).toHaveTextContent("capabilityList.reason_hands_missing");
    const na = screen.getByTestId("cap-mcp:2");
    expect(within(na).queryByRole("switch")).toBeNull();
    expect(na).toHaveTextContent("capabilityList.reason_runtime_missing:npx");
    // An errored MCP shows why, and its fix, not a switch that would do nothing.
    expect(within(screen.getByTestId("cap-mcp:3")).queryByRole("switch")).toBeNull();
    expect(screen.getByTestId("cap-mcp:3")).toHaveTextContent("401");
  });

  it("a switch writes through the API and shows what the server says now", async () => {
    vi.spyOn(capabilitiesApi, "list").mockResolvedValue(ROWS);
    const put = vi.spyOn(capabilitiesApi, "switch").mockResolvedValue(row({ key: "files", state: "on", switch: "setting" }));
    render(<CapabilitySwitches />);
    fireEvent.click(await screen.findByTestId("cap-switch-files"));
    await waitFor(() => expect(put).toHaveBeenCalledWith("files", true));
    await waitFor(() => expect(screen.getByTestId("cap-switch-files")).toBeChecked());
    expect(screen.getByTestId("cap-files")).toHaveAttribute("data-state", "on");
  });

  it("a failed switch says so and leaves the row as it was", async () => {
    vi.spyOn(capabilitiesApi, "list").mockResolvedValue(ROWS);
    vi.spyOn(capabilitiesApi, "switch").mockRejectedValue(new Error("offline"));
    render(<CapabilitySwitches />);
    fireEvent.click(await screen.findByTestId("cap-switch-terminal"));
    expect(await screen.findByText("capabilityList.failed")).toBeInTheDocument();
    expect(screen.getByTestId("cap-terminal")).toHaveAttribute("data-state", "on");
  });

  it("one step away opens the place that fixes it", async () => {
    vi.spyOn(capabilitiesApi, "list").mockResolvedValue(ROWS);
    const onOpenTab = vi.fn();
    const seen: unknown[] = [];
    const on = (e: Event) => seen.push((e as CustomEvent).detail);
    window.addEventListener(OPEN_SECTION_EVENT, on);
    render(<CapabilitySwitches onOpenTab={onOpenTab} />);
    fireEvent.click(await screen.findByTestId("cap-fix-web"));
    fireEvent.click(screen.getByTestId("cap-fix-mcp:3"));
    window.removeEventListener(OPEN_SECTION_EVENT, on);
    expect(seen).toEqual([{ section: "settings", sub: "connections" }]);
    expect(onOpenTab).toHaveBeenCalledWith("mcps");
  });

  it("filters: on, can turn on (off or one step away), all", async () => {
    vi.spyOn(capabilitiesApi, "list").mockResolvedValue(ROWS);
    render(<CapabilitySwitches />);
    await screen.findByTestId("cap-terminal");
    expect(screen.getByTestId("cap-filter-on")).toHaveTextContent("capabilityList.filterOn:9");
    expect(screen.getByTestId("cap-filter-canTurnOn")).toHaveTextContent("capabilityList.filterCanTurnOn:4");
    fireEvent.click(screen.getByTestId("cap-filter-canTurnOn"));
    expect(screen.queryByTestId("cap-terminal")).toBeNull();
    expect(screen.queryByTestId("cap-mcp:2")).toBeNull();          // can't is not "can turn on"
    expect(screen.getByTestId("cap-files")).toBeInTheDocument();
    expect(screen.getByTestId("cap-hands")).toBeInTheDocument();
  });

  it("a long group opens with its first six", async () => {
    vi.spyOn(capabilitiesApi, "list").mockResolvedValue(ROWS);
    render(<CapabilitySwitches />);
    const methods = await screen.findByTestId("cap-group-methods");
    expect(within(methods).getAllByRole("switch")).toHaveLength(6);
    fireEvent.click(screen.getByTestId("cap-more-methods"));
    expect(within(methods).getAllByRole("switch")).toHaveLength(8);
  });

  it("strings exist in six languages with the same placeholders", () => {
    const keys = Object.keys(capabilityListMessages.en).sort();
    for (const messages of Object.values(capabilityListMessages)) {
      expect(Object.keys(messages).sort()).toEqual(keys);
      for (const key of keys) {
        const text = messages[key as keyof typeof messages];
        expect(text.trim()).not.toBe("");
        expect(text.match(/\{\{[^}]+\}\}/g) ?? []).toEqual(capabilityListMessages.en[key as keyof typeof messages].match(/\{\{[^}]+\}\}/g) ?? []);
      }
    }
    // Every built-in row the server can send has a name and a line.
    for (const key of ["files", "terminal", "browser", "shortcuts", "hands", "web", "charts", "schedule", "lan", "ssh"]) {
      expect(capabilityListMessages.en).toHaveProperty(`${key}_name`);
      expect(capabilityListMessages.en).toHaveProperty(`${key}_what`);
    }
  });
});
