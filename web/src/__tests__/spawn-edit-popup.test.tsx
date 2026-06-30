import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SpawnEditPopup from "../components/SpawnEditPopup";

vi.mock("../api/client", () => ({
  api: {
    getRegistry: vi.fn(),
    getSpawn: vi.fn(),
    updateEquipment: vi.fn(),
  },
}));
import { api } from "../api/client";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

const REGISTRY = {
  toolsets: [
    { key: "web_search", name: "Web Search", description: "search the web", tier: "tier-1", status: "ok", assignable: true, tools: [] },
    { key: "mcp_5", name: "Notion MCP", description: "notion server", tier: "tier-2", status: "ok", assignable: true, tools: [] },
    { key: "locked_tool", name: "Locked", description: "no", tier: "tier-3", status: "ok", assignable: false, tools: [] },
  ],
  skills: [
    { key: "seo-opt", name: "SEO", category: "writing", description: "seo skill", tier: "tier-1", status: "ok", assignable: true },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  m.getRegistry.mockResolvedValue(REGISTRY);
  m.getSpawn.mockResolvedValue({
    id: 7,
    name: "小美",
    domain: "marketing",
    capabilities: [],
    template_used: null,
    generation_level: 1,
    created_at: "",
    updated_at: "",
    persona_role: null,
    persona_tone: null,
    system_prompt: "",
    messages: [],
    // already equipped: the web_search tool
    equipment: { toolsets: [{ key: "web_search", name: "Web Search", status: "ok", grant: "permanent" }], skills: [] },
  });
});

describe("SpawnEditPopup", () => {
  it("renders three panels with pre-checked equipped items", async () => {
    render(<SpawnEditPopup spawnId={7} spawnName="小美" spawnDomain="marketing" onClose={() => {}} />);
    await screen.findByTestId("spawn-edit-panel-skill");
    expect(screen.getByTestId("spawn-edit-panel-tool")).toBeTruthy();
    expect(screen.getByTestId("spawn-edit-panel-mcp")).toBeTruthy();
    // The equipped web_search tool is pre-selected (aria-pressed true).
    await waitFor(() =>
      expect(screen.getByTestId("spawn-edit-item-web_search").getAttribute("aria-pressed")).toBe("true"),
    );
    // MCP appears in its own panel.
    expect(screen.getByTestId("spawn-edit-item-mcp_5")).toBeTruthy();
  });

  it("non-assignable items are disabled", async () => {
    render(<SpawnEditPopup spawnId={7} spawnName="小美" spawnDomain="marketing" onClose={() => {}} />);
    const locked = await screen.findByTestId("spawn-edit-item-locked_tool");
    expect((locked as HTMLButtonElement).disabled).toBe(true);
  });

  it("toggles a skill + an MCP and saves the merged toolsets+skills", async () => {
    m.updateEquipment.mockResolvedValue({});
    const onSaved = vi.fn();
    render(<SpawnEditPopup spawnId={7} spawnName="小美" spawnDomain="marketing" onClose={() => {}} onSaved={onSaved} />);

    // add the skill and the MCP (web_search already on)
    fireEvent.click(await screen.findByTestId("spawn-edit-item-seo-opt"));
    fireEvent.click(screen.getByTestId("spawn-edit-item-mcp_5"));
    fireEvent.click(screen.getByTestId("spawn-edit-save"));

    await waitFor(() => expect(m.updateEquipment).toHaveBeenCalledTimes(1));
    const [id, body] = m.updateEquipment.mock.calls[0];
    expect(id).toBe(7);
    // MCP folds into toolsets along with the existing tool.
    expect(new Set(body.toolsets)).toEqual(new Set(["web_search", "mcp_5"]));
    expect(body.skills).toEqual(["seo-opt"]);
    expect(onSaved).toHaveBeenCalled();
  });
});
