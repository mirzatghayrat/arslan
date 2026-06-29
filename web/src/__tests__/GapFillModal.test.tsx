import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

// ── i18n mock: t returns the key so assertions are language-independent ──────────
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts ? `${key}:${JSON.stringify(opts)}` : key,
    i18n: { changeLanguage: vi.fn() },
  }),
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}));

// ── api mocks: the acquisition clients are never reached on the cancel path ──────
vi.mock("../api/discovery", () => ({
  evaluateRepo: vi.fn(),
  generateSkill: vi.fn(),
  createSkill: vi.fn(),
}));
vi.mock("../api/mcp", () => ({
  addMcpServer: vi.fn(),
  connectMcpServer: vi.fn(),
  exposeMcpServer: vi.fn(),
}));

import GapFillModal from "../components/GapFillModal";

describe("GapFillModal (gated gap-fill)", () => {
  it("cancel (✕) resolves onDone(null) — nothing gets stuck", () => {
    const onDone = vi.fn();
    render(<GapFillModal kind="discover_mcp" gap="no notion access" onDone={onDone} />);
    fireEvent.click(screen.getByTestId("gap-fill-cancel"));
    expect(onDone).toHaveBeenCalledOnce();
    expect(onDone).toHaveBeenCalledWith(null);
  });

  it("renders the gap context and the read-only first step for distill_skill", () => {
    const onDone = vi.fn();
    render(<GapFillModal kind="distill_skill" gap="no notion access" onDone={onDone} />);
    expect(screen.getByTestId("gap-fill-modal")).toBeInTheDocument();
    expect(screen.getByTestId("gap-fill-ref")).toBeInTheDocument();
    // No acquisition has happened — no draft panel yet.
    expect(screen.queryByTestId("gap-fill-skill-draft")).not.toBeInTheDocument();
  });
});
