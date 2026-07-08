import { render, screen, fireEvent } from "@testing-library/react";
import { describe, test, expect, vi } from "vitest";
import ClarifyOptionsCard from "./ClarifyOptionsCard";
import "../i18n";

const OPTIONS = [
  { label: "先出大纲", hint: "快速对齐结构" },
  { label: "直接生成整页 HTML", hint: "暗色磨砂玻璃风格" },
];

describe("ClarifyOptionsCard (PA-3)", () => {
  test("renders question + options with hints; a click fires onPick with the label", () => {
    const onPick = vi.fn();
    render(
      <ClarifyOptionsCard
        question="接下来往哪个方向推进?"
        options={OPTIONS}
        onPick={onPick}
      />,
    );
    expect(screen.getByText("接下来往哪个方向推进?")).toBeInTheDocument();
    expect(screen.getByText("先出大纲")).toBeInTheDocument();
    expect(screen.getByText("快速对齐结构")).toBeInTheDocument();
    expect(screen.getByText("暗色磨砂玻璃风格")).toBeInTheDocument();

    const buttons = screen.getAllByTestId("clarify-option");
    expect(buttons).toHaveLength(2);
    fireEvent.click(buttons[1]);
    expect(onPick).toHaveBeenCalledWith("直接生成整页 HTML");
  });

  test("answered state disables all options and blocks further picks", () => {
    const onPick = vi.fn();
    render(
      <ClarifyOptionsCard
        question="选一个方向"
        options={OPTIONS}
        answered
        onPick={onPick}
      />,
    );
    const buttons = screen.getAllByTestId("clarify-option");
    buttons.forEach((b) => expect(b).toBeDisabled());
    fireEvent.click(buttons[0]);
    expect(onPick).not.toHaveBeenCalled();
    expect(screen.getByTestId("clarify-answered")).toBeInTheDocument();
  });
});
