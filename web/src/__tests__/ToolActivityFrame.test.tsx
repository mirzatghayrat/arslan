import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import "../i18n";
import ToolActivityFrame from "../components/arslan/ToolActivityFrame";
import type { ToolStep } from "../types";

const steps: ToolStep[] = [
  { tool: "web_search", argsSummary: '{"q":"a"}', status: "ok", resultSummary: "5 hits" },
  { tool: "web_search", argsSummary: '{"q":"b"}', status: "error", resultSummary: "timeout" },
];

describe("ToolActivityFrame", () => {
  it("renders an aggregated summary for repeated tools", () => {
    render(<ToolActivityFrame steps={steps} />);
    expect(screen.getByText(/web_search ×2/)).toBeInTheDocument();
  });

  it("starts open when live — result summaries visible", () => {
    render(<ToolActivityFrame steps={steps} live />);
    expect(screen.getByText(/5 hits/)).toBeInTheDocument();
    expect(screen.getByText(/timeout/)).toBeInTheDocument();
  });

  it("starts collapsed when not live and expands on click", async () => {
    render(<ToolActivityFrame steps={steps} />);
    expect(screen.queryByText(/5 hits/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button"));
    expect(screen.getByText(/5 hits/)).toBeInTheDocument();
  });

  it("renders nothing for empty steps", () => {
    const { container } = render(<ToolActivityFrame steps={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
