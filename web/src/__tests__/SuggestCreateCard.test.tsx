import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import SuggestCreateCard from "../components/SuggestCreateCard";
import type { SuggestDraft, OverlapInfo } from "../api/client.types";

const baseDraft: SuggestDraft = {
  name: "ResearchBot",
  domain: "academic research",
  capabilities: ["literature review", "citation analysis"],
  persona_role: "Research Assistant",
  persona_tone: "formal",
  reason: "User needs in-depth paper analysis",
};

describe("SuggestCreateCard", () => {
  it("renders name and domain", () => {
    render(
      <SuggestCreateCard
        draft={baseDraft}
        taskBrief={null}
        overlaps={null}
        onCreate={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );
    expect(screen.getByText("ResearchBot")).toBeInTheDocument();
    expect(screen.getByText("academic research")).toBeInTheDocument();
  });

  it("renders capabilities joined", () => {
    render(
      <SuggestCreateCard
        draft={baseDraft}
        taskBrief={null}
        overlaps={null}
        onCreate={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );
    expect(screen.getByText("literature review、citation analysis")).toBeInTheDocument();
  });

  it("calls onCreate when 创建 is clicked", () => {
    const onCreate = vi.fn();
    render(
      <SuggestCreateCard
        draft={baseDraft}
        taskBrief={null}
        overlaps={null}
        onCreate={onCreate}
        onDismiss={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("btn-create"));
    expect(onCreate).toHaveBeenCalledOnce();
  });

  it("calls onDismiss when 忽略 is clicked", () => {
    const onDismiss = vi.fn();
    render(
      <SuggestCreateCard
        draft={baseDraft}
        taskBrief={null}
        overlaps={null}
        onCreate={vi.fn()}
        onDismiss={onDismiss}
      />,
    );
    fireEvent.click(screen.getByTestId("btn-dismiss"));
    expect(onDismiss).toHaveBeenCalledOnce();
  });

  it("shows overlap warning when overlaps provided", () => {
    const overlaps: OverlapInfo = {
      spawn_id: 42,
      name: "DataAnalyst",
      axes: ["data processing", "statistics"],
    };
    render(
      <SuggestCreateCard
        draft={baseDraft}
        taskBrief={null}
        overlaps={overlaps}
        onCreate={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );
    const warning = screen.getByTestId("overlap-warning");
    expect(warning).toBeInTheDocument();
    expect(warning.textContent).toContain("DataAnalyst");
  });

  it("does not show overlap warning when overlaps is null", () => {
    render(
      <SuggestCreateCard
        draft={baseDraft}
        taskBrief={null}
        overlaps={null}
        onCreate={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );
    expect(screen.queryByTestId("overlap-warning")).not.toBeInTheDocument();
  });

  it("renders optional persona_role and persona_tone", () => {
    render(
      <SuggestCreateCard
        draft={baseDraft}
        taskBrief="Analyze papers on NLP"
        overlaps={null}
        onCreate={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );
    expect(screen.getByText("Research Assistant")).toBeInTheDocument();
    expect(screen.getByText("formal")).toBeInTheDocument();
    expect(screen.getByText("Analyze papers on NLP")).toBeInTheDocument();
  });
});
