import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import "../i18n";
import EquipmentChips from "../components/arslan/EquipmentChips";

const eq = {
  toolsets: [
    { key: "ws", name: "Web search", status: "wired", grant: "permanent" as const, granted_by: "create" as const },
    { key: "ds", name: "Discord", status: "registered", grant: "temporary" as const, granted_by: "escalation" as const, expires_turn: 9 },
  ],
  skills: [{ key: "sk", name: "Summarizing", status: "wired", grant: "permanent" as const }],
};

describe("EquipmentChips", () => {
  it("renders toolset and skill chips", () => {
    render(<EquipmentChips equipment={eq} />);
    expect(screen.getByText("Web search")).toBeInTheDocument();
    expect(screen.getByText("Summarizing")).toBeInTheDocument();
  });

  it("badges temporary grants", () => {
    render(<EquipmentChips equipment={eq} />);
    // "temp" is the equipment.temp_badge translation key value in English
    expect(screen.getByText("temp")).toBeInTheDocument();
  });

  it("collapses beyond 4 in compact mode", () => {
    const many = {
      toolsets: Array.from({ length: 6 }, (_, i) => ({
        key: `k${i}`,
        name: `T${i}`,
        status: "wired",
        grant: "permanent" as const,
      })),
      skills: [],
    };
    render(<EquipmentChips equipment={many} compact />);
    expect(screen.getByText("+2 more")).toBeInTheDocument();
    expect(screen.queryByText("T5")).not.toBeInTheDocument();
  });

  it("renders nothing when empty", () => {
    const { container } = render(<EquipmentChips equipment={{ toolsets: [], skills: [] }} />);
    expect(container).toBeEmptyDOMElement();
  });
});
