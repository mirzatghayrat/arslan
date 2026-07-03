import { render, screen, fireEvent } from "@testing-library/react";
import { describe, test, expect, vi } from "vitest";
import RunCommandCard from "./RunCommandCard";
import "../i18n";

describe("RunCommandCard", () => {
  test("shows the full command and fires confirm with remember flag", () => {
    const onConfirm = vi.fn();
    render(
      <RunCommandCard
        callId="c1"
        pretty="git status"
        reason="check repo"
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.getByText("git status")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("runcmd-remember"));
    fireEvent.click(screen.getByTestId("runcmd-run"));
    expect(onConfirm).toHaveBeenCalledWith("c1", true);
  });

  test("cancel fires onCancel", () => {
    const onCancel = vi.fn();
    render(
      <RunCommandCard
        callId="c1"
        pretty="git status"
        reason=""
        onConfirm={vi.fn()}
        onCancel={onCancel}
      />,
    );
    fireEvent.click(screen.getByTestId("runcmd-cancel"));
    expect(onCancel).toHaveBeenCalledWith("c1");
  });
});
