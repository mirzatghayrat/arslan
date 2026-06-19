import { describe, it, expect } from "vitest";
import { toUiSpawn } from "../api/adapters";

describe("toUiSpawn", () => {
  it("maps a backend spawn to the UI Spawn shape", () => {
    const api = { id: 7, name: "Aletheia", domain: "finance", description: "d", status: "idle", tools: ["web_search"], skills: ["financial-res"], total_tasks: 42 };
    const ui = toUiSpawn(api as never);
    expect(ui).toMatchObject({ id: "7", name: "Aletheia", status: "idle", totalTasks: 42 });
    expect(ui.tools).toContain("web_search");
  });
});
