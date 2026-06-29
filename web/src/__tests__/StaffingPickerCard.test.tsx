import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import StaffingPickerCard from "../components/StaffingPickerCard";
import type { SuggestDraft } from "../api/client.types";

// ── i18n mock: t returns the key so assertions are language-independent ──────
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts ? `${key}:${JSON.stringify(opts)}` : key,
    i18n: { changeLanguage: vi.fn() },
  }),
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}));

const candidates = [
  { spawnId: 7, name: "Mermer", score: 0.92, why: "Great at translation" },
  { spawnId: 12, name: "DataBot", score: 0.75, why: "Strong data skills" },
];

const createDraft: SuggestDraft = {
  name: "Hybrid",
  domain: "research",
  capabilities: ["search"],
  persona_role: "analyst",
  persona_tone: "concise",
  reason: "blend both",
  tools: ["web_search"],
  skills: [],
  mcps: [],
};

describe("StaffingPickerCard", () => {
  it("renders all candidate names and why strings", () => {
    render(
      <StaffingPickerCard
        candidates={candidates}
        createDraft={createDraft}
        onInvite={vi.fn()}
        onCreateNew={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );
    expect(screen.getByText("Mermer")).toBeInTheDocument();
    expect(screen.getByText("Great at translation")).toBeInTheDocument();
    expect(screen.getByText("DataBot")).toBeInTheDocument();
    expect(screen.getByText("Strong data skills")).toBeInTheDocument();
  });

  it("calls onInvite(spawnId) when the invite button for a candidate is clicked", () => {
    const onInvite = vi.fn();
    render(
      <StaffingPickerCard
        candidates={candidates}
        createDraft={createDraft}
        onInvite={onInvite}
        onCreateNew={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("staffing-invite-7"));
    expect(onInvite).toHaveBeenCalledWith(7);

    fireEvent.click(screen.getByTestId("staffing-invite-12"));
    expect(onInvite).toHaveBeenCalledWith(12);
  });

  it("calls onCreateNew(createDraft) when the build-new button is clicked", () => {
    const onCreateNew = vi.fn();
    render(
      <StaffingPickerCard
        candidates={candidates}
        createDraft={createDraft}
        onInvite={vi.fn()}
        onCreateNew={onCreateNew}
        onDismiss={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("staffing-build-new"));
    expect(onCreateNew).toHaveBeenCalledWith(createDraft);
  });

  it("calls onDismiss when the dismiss button is clicked", () => {
    const onDismiss = vi.fn();
    render(
      <StaffingPickerCard
        candidates={candidates}
        createDraft={createDraft}
        onInvite={vi.fn()}
        onCreateNew={vi.fn()}
        onDismiss={onDismiss}
      />,
    );
    fireEvent.click(screen.getByTestId("staffing-dismiss"));
    expect(onDismiss).toHaveBeenCalledOnce();
  });

  it("hides the build-new button when createDraft is null", () => {
    render(
      <StaffingPickerCard
        candidates={candidates}
        createDraft={null}
        onInvite={vi.fn()}
        onCreateNew={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );
    expect(screen.queryByTestId("staffing-build-new")).not.toBeInTheDocument();
  });

  it("falls back to #id when candidate name is null", () => {
    render(
      <StaffingPickerCard
        candidates={[{ spawnId: 99, name: null, score: 0.5, why: "some reason" }]}
        createDraft={null}
        onInvite={vi.fn()}
        onCreateNew={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );
    expect(screen.getByText("#99")).toBeInTheDocument();
  });
});
