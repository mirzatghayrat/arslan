/**
 * Smoke render test — guards against import/runtime breakage in key components.
 * Renders SpawnsDashboard with minimal props and asserts it doesn't throw.
 */

import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { changeLanguage: vi.fn() },
  }),
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}));

vi.mock("../api/client", () => ({
  api: {
    listSpawns: vi.fn().mockResolvedValue([]),
    getSettings: vi.fn().mockResolvedValue({}),
  },
  API_BASE: "",
}));

vi.mock("../stores/authStore", () => ({
  useAuthStore: { getState: () => ({ token: null }) },
}));

// motion/react: passthrough (avoids JSDOM animation issues)
vi.mock("motion/react", () => ({
  motion: {
    div: ({ children, ...props }: React.HTMLAttributes<HTMLDivElement>) => <div {...props}>{children}</div>,
    button: ({ children, ...props }: React.HTMLAttributes<HTMLButtonElement>) => <button {...(props as React.ButtonHTMLAttributes<HTMLButtonElement>)}>{children}</button>,
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

import SpawnsDashboard from "../components/SpawnsDashboard";
import type { Spawn } from "../types";

const mockSpawns: Spawn[] = [
  { id: "1", name: "Aletheia", domain: "finance", description: "Finance spawn", status: "idle", avatarEmoji: "🤖", tools: ["web_search"], skills: [], totalTasks: 5 },
];

describe("SpawnsDashboard smoke render", () => {
  it("renders without throwing given mocked spawns", () => {
    expect(() =>
      render(
        <SpawnsDashboard
          spawns={mockSpawns}
          selectedSpawnId={null}
          setSelectedSpawnId={vi.fn()}
          cardStyle="compact"
          setCardStyle={vi.fn()}
          onEditEquipment={vi.fn()}
          onCreateSpawnClick={vi.fn()}
          backendStatus="online"
        />
      )
    ).not.toThrow();
  });

  it("renders spawn name in the list", () => {
    render(
      <SpawnsDashboard
        spawns={mockSpawns}
        selectedSpawnId={null}
        setSelectedSpawnId={vi.fn()}
        cardStyle="compact"
        setCardStyle={vi.fn()}
        onEditEquipment={vi.fn()}
        onCreateSpawnClick={vi.fn()}
        backendStatus="online"
      />
    );
    expect(screen.getByText("Aletheia")).toBeInTheDocument();
  });

  it("renders empty state when spawns list is empty", () => {
    render(
      <SpawnsDashboard
        spawns={[]}
        selectedSpawnId={null}
        setSelectedSpawnId={vi.fn()}
        cardStyle="compact"
        setCardStyle={vi.fn()}
        onEditEquipment={vi.fn()}
        onCreateSpawnClick={vi.fn()}
        backendStatus="online"
      />
    );
    // The empty state renders the i18n key (mocked as passthrough)
    expect(screen.getByText("ledger.empty_no_spawns")).toBeInTheDocument();
  });
});
