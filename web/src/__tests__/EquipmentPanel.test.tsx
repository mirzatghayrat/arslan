import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import "../i18n";
import { ApiError } from "../api/client";
import { api } from "../api/client";
import EquipmentPanel from "../components/spawn/EquipmentPanel";
import type { RegistryCatalog, SpawnDetail } from "../types";

const registryFixture: RegistryCatalog = {
  toolsets: [
    {
      key: "web_search_scraping",
      name: "Web search & scraping",
      description: "Search the web",
      tier: "standard",
      status: "enabled",
      assignable: true,
      tools: [],
    },
    {
      key: "browser_automation",
      name: "Browser automation",
      description: "Automate browser interactions",
      tier: "standard",
      status: "enabled",
      assignable: false,
      tools: [],
    },
  ],
  skills: [
    {
      key: "summarizing",
      name: "Summarizing",
      category: "text",
      description: "Summarize content",
      tier: "standard",
      status: "enabled",
      assignable: true,
    },
  ],
};

const spawnFixture: SpawnDetail = {
  id: 42,
  name: "TestSpawn",
  domain: "general",
  capabilities: [],
  template_used: null,
  generation_level: 1,
  created_at: "",
  updated_at: "",
  persona_role: null,
  persona_tone: null,
  system_prompt: "",
  messages: [],
  equipment: {
    toolsets: [
      {
        key: "web_search_scraping",
        name: "Web search & scraping",
        status: "wired",
        grant: "permanent",
        granted_by: "create",
      },
      {
        key: "discord",
        name: "Discord",
        status: "registered",
        grant: "temporary",
        granted_by: "escalation",
        expires_turn: 9,
      },
    ],
    skills: [],
  },
};

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "getRegistry").mockResolvedValue(registryFixture);
  vi.spyOn(api, "updateEquipment").mockResolvedValue(spawnFixture);
});

describe("EquipmentPanel", () => {
  it("renders current chips from spawn.equipment", () => {
    render(<EquipmentPanel spawn={spawnFixture} onUpdated={vi.fn()} />);
    expect(screen.getByText("Web search & scraping")).toBeInTheDocument();
  });

  it("clicking the edit button loads the registry and shows checkboxes; non-assignable checkbox is disabled", async () => {
    render(<EquipmentPanel spawn={spawnFixture} onUpdated={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: /edit equipment/i }));
    await waitFor(() => expect(api.getRegistry).toHaveBeenCalled());

    // Assignable checkbox is enabled
    const assignableCheckbox = screen.getByRole("checkbox", { name: /web search & scraping/i });
    expect(assignableCheckbox).not.toBeDisabled();

    // Non-assignable checkbox is disabled
    const lockedCheckbox = screen.getByRole("checkbox", { name: /browser automation/i });
    expect(lockedCheckbox).toBeDisabled();
  });

  it("temporary grants are listed read-only in the temporary section (Discord appears as text, not a checkbox)", async () => {
    render(<EquipmentPanel spawn={spawnFixture} onUpdated={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: /edit equipment/i }));
    await waitFor(() => expect(api.getRegistry).toHaveBeenCalled());

    // Discord should appear as text, not a checkbox
    expect(screen.getByText(/Discord/)).toBeInTheDocument();
    // No checkbox for Discord
    const checkboxes = screen.getAllByRole("checkbox");
    const checkboxLabels = checkboxes.map((cb) => cb.closest("label")?.textContent ?? "");
    expect(checkboxLabels.some((l) => /Discord/i.test(l))).toBe(false);
  });

  it("Save calls api.updateEquipment with the selected keys and calls onUpdated with the response", async () => {
    const onUpdated = vi.fn();
    render(<EquipmentPanel spawn={spawnFixture} onUpdated={onUpdated} />);
    await userEvent.click(screen.getByRole("button", { name: /edit equipment/i }));
    await waitFor(() => expect(api.getRegistry).toHaveBeenCalled());

    await userEvent.click(screen.getByRole("button", { name: /save/i }));
    await waitFor(() =>
      expect(api.updateEquipment).toHaveBeenCalledWith(42, {
        toolsets: ["web_search_scraping"],
        skills: [],
      }),
    );
    expect(onUpdated).toHaveBeenCalledWith(spawnFixture);
  });

  it("shows inline error when updateEquipment rejects with ApiError 422", async () => {
    vi.spyOn(api, "updateEquipment").mockRejectedValue(
      new ApiError("toolset browser_automation is not spawn-assignable", 422),
    );
    render(<EquipmentPanel spawn={spawnFixture} onUpdated={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: /edit equipment/i }));
    await waitFor(() => expect(api.getRegistry).toHaveBeenCalled());

    await userEvent.click(screen.getByRole("button", { name: /save/i }));
    await waitFor(() =>
      expect(
        screen.getByText("toolset browser_automation is not spawn-assignable"),
      ).toBeInTheDocument(),
    );
  });
});
