import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

// t mock with naive {{var}} interpolation against the defaultValue template
// (same pattern as live-activity.test.tsx / tool-activity-card.test.tsx).
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (k: string, o?: Record<string, unknown>) => {
      let s = (o?.defaultValue as string) ?? k;
      for (const [key, v] of Object.entries(o ?? {})) {
        if (key === "defaultValue") continue;
        s = s.replace(`{{${key}}}`, String(v));
      }
      return s;
    },
  }),
}));
vi.mock("../api/client", () => ({
  api: {
    listCollections: vi.fn().mockResolvedValue([
      { id: 1, name: "保险资料", description: null, chunks: 12, sources: 3, spawn_ids: [2] },
    ]),
    listSpawns: vi.fn().mockResolvedValue([{ id: 2, name: "小保" }]),
    getCollectionKnowledge: vi.fn().mockResolvedValue([]),
  },
}));

import CollectionsPanel from "./CollectionsPanel";

describe("CollectionsPanel", () => {
  it("renders collections with stats", async () => {
    render(<CollectionsPanel />);
    await waitFor(() => expect(screen.getByText("保险资料")).toBeDefined());
    expect(screen.getByText(/12/)).toBeDefined();
  });

  it("renders empty state without crashing", async () => {
    const { api } = await import("../api/client");
    (api.listCollections as ReturnType<typeof vi.fn>).mockResolvedValueOnce([]);
    render(<CollectionsPanel />);
    await waitFor(() => expect(screen.queryByText("保险资料")).toBeNull());
  });
});
