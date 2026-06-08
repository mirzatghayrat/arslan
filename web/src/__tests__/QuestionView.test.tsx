import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import QuestionView from "../components/build/QuestionView";

describe("QuestionView", () => {
  it("renders options and submits the chosen one (single-select)", async () => {
    const onSubmit = vi.fn();
    render(
      <QuestionView
        text="Pick a domain"
        options={["content-creator — Content", "translator — Translate"]}
        multiSelect={false}
        hint=""
        onSubmit={onSubmit}
      />,
    );
    await userEvent.click(screen.getByText("content-creator — Content"));
    await userEvent.click(screen.getByRole("button", { name: /next/i }));
    expect(onSubmit).toHaveBeenCalledWith("content-creator — Content");
  });

  it("supports multi-select and joins selections", async () => {
    const onSubmit = vi.fn();
    render(
      <QuestionView
        text="Pick capabilities"
        options={["A — gen", "B — qa"]}
        multiSelect
        hint=""
        onSubmit={onSubmit}
      />,
    );
    await userEvent.click(screen.getByText("A — gen"));
    await userEvent.click(screen.getByText("B — qa"));
    await userEvent.click(screen.getByRole("button", { name: /next/i }));
    expect(onSubmit).toHaveBeenCalledWith("A — gen, B — qa");
  });

  it("renders a free-text input when there are no options", async () => {
    const onSubmit = vi.fn();
    render(
      <QuestionView text="Name it" options={null} multiSelect={false} hint="" onSubmit={onSubmit} />,
    );
    await userEvent.type(screen.getByRole("textbox"), "beauty-guru");
    await userEvent.click(screen.getByRole("button", { name: /next/i }));
    expect(onSubmit).toHaveBeenCalledWith("beauty-guru");
  });
});
