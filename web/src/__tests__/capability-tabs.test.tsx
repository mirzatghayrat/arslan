import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import CapabilityTabs from "../components/CapabilityTabs";

describe("CapabilityTabs", () => {
  it("renders tabs and switches active on click", () => {
    const onChange = vi.fn();
    render(<CapabilityTabs active="tools" onChange={onChange} tabs={[
      { id: "tools", label: "Tools" }, { id: "skills", label: "Skills" }, { id: "mcps", label: "MCPs" }]} />);
    expect(screen.getByRole("tab", { name: "Tools" })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(screen.getByRole("tab", { name: "MCPs" }));
    expect(onChange).toHaveBeenCalledWith("mcps");
  });
});
