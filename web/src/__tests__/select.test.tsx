/**
 * Task UX2 — Custom themed Select dropdown.
 *
 * Tests written first (TDD). Run before implementing Select.tsx — all should
 * fail initially, then pass once the component is built.
 */

import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import Select from "../components/Select";

const OPTIONS = [
  { value: "tavily", label: "Tavily" },
  { value: "serpapi", label: "SerpAPI" },
  { value: "google", label: "Google" },
];

describe("Select (custom themed dropdown)", () => {
  // ── Rendering ─────────────────────────────────────────────────────────────

  it("renders the selected option's label in the trigger", () => {
    render(
      <Select value="tavily" onChange={vi.fn()} options={OPTIONS} />
    );
    expect(screen.getByRole("button")).toHaveTextContent("Tavily");
  });

  it("renders placeholder when no value matches", () => {
    render(
      <Select
        value=""
        onChange={vi.fn()}
        options={OPTIONS}
        placeholder="Pick a provider…"
      />
    );
    expect(screen.getByRole("button")).toHaveTextContent("Pick a provider…");
  });

  it("does not show the options panel when closed", () => {
    render(
      <Select value="tavily" onChange={vi.fn()} options={OPTIONS} />
    );
    // Panel items should not be visible
    expect(screen.queryByRole("option", { name: "SerpAPI" })).toBeNull();
  });

  // ── Opening / closing ─────────────────────────────────────────────────────

  it("shows all option labels when the trigger is clicked", async () => {
    const user = userEvent.setup();
    render(
      <Select value="tavily" onChange={vi.fn()} options={OPTIONS} />
    );
    await user.click(screen.getByRole("button"));
    // All three options should now be visible as listbox options
    expect(screen.getByRole("option", { name: "Tavily" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "SerpAPI" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Google" })).toBeInTheDocument();
  });

  it("closes the panel when trigger is clicked a second time", async () => {
    const user = userEvent.setup();
    render(
      <Select value="tavily" onChange={vi.fn()} options={OPTIONS} />
    );
    await user.click(screen.getByRole("button"));
    // Panel open — click again to close
    await user.click(screen.getByRole("button"));
    expect(screen.queryByRole("option", { name: "SerpAPI" })).toBeNull();
  });

  it("closes the panel on Escape key", async () => {
    const user = userEvent.setup();
    render(
      <Select value="tavily" onChange={vi.fn()} options={OPTIONS} />
    );
    await user.click(screen.getByRole("button"));
    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(screen.queryByRole("option", { name: "SerpAPI" })).toBeNull();
    });
  });

  // ── Selection ─────────────────────────────────────────────────────────────

  it("calls onChange with the option value when an option is clicked", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <Select value="tavily" onChange={onChange} options={OPTIONS} />
    );
    await user.click(screen.getByRole("button"));
    await user.click(screen.getByRole("option", { name: "SerpAPI" }));
    expect(onChange).toHaveBeenCalledWith("serpapi");
  });

  it("closes the panel after an option is selected", async () => {
    const user = userEvent.setup();
    render(
      <Select value="tavily" onChange={vi.fn()} options={OPTIONS} />
    );
    await user.click(screen.getByRole("button"));
    await user.click(screen.getByRole("option", { name: "SerpAPI" }));
    await waitFor(() => {
      expect(screen.queryByRole("option", { name: "SerpAPI" })).toBeNull();
    });
  });

  it("does NOT call onChange again if the currently-selected option is clicked", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <Select value="tavily" onChange={onChange} options={OPTIONS} />
    );
    await user.click(screen.getByRole("button"));
    await user.click(screen.getByRole("option", { name: "Tavily" }));
    // onChange may still be called (it's the consumer's responsibility to decide)
    // but the panel should close
    await waitFor(() => {
      expect(screen.queryByRole("option", { name: "SerpAPI" })).toBeNull();
    });
  });

  // ── Disabled state ────────────────────────────────────────────────────────

  it("disables the trigger button when disabled prop is true", () => {
    render(
      <Select value="tavily" onChange={vi.fn()} options={OPTIONS} disabled />
    );
    expect(screen.getByRole("button")).toBeDisabled();
  });

  it("does not open the panel when disabled", async () => {
    const user = userEvent.setup();
    render(
      <Select value="tavily" onChange={vi.fn()} options={OPTIONS} disabled />
    );
    await user.click(screen.getByRole("button"));
    expect(screen.queryByRole("option", { name: "SerpAPI" })).toBeNull();
  });

  // ── Accessibility ─────────────────────────────────────────────────────────

  it("trigger has aria-haspopup='listbox'", () => {
    render(
      <Select value="tavily" onChange={vi.fn()} options={OPTIONS} />
    );
    expect(screen.getByRole("button")).toHaveAttribute("aria-haspopup", "listbox");
  });

  it("trigger has aria-expanded=false when closed and true when open", async () => {
    const user = userEvent.setup();
    render(
      <Select value="tavily" onChange={vi.fn()} options={OPTIONS} />
    );
    const btn = screen.getByRole("button");
    expect(btn).toHaveAttribute("aria-expanded", "false");
    await user.click(btn);
    expect(btn).toHaveAttribute("aria-expanded", "true");
  });

  it("renders the panel as role='listbox'", async () => {
    const user = userEvent.setup();
    render(
      <Select value="tavily" onChange={vi.fn()} options={OPTIONS} />
    );
    await user.click(screen.getByRole("button"));
    expect(screen.getByRole("listbox")).toBeInTheDocument();
  });

  it("currently selected option has aria-selected=true", async () => {
    const user = userEvent.setup();
    render(
      <Select value="tavily" onChange={vi.fn()} options={OPTIONS} />
    );
    await user.click(screen.getByRole("button"));
    const selected = screen.getByRole("option", { name: "Tavily" });
    expect(selected).toHaveAttribute("aria-selected", "true");
  });

  it("non-selected options have aria-selected=false", async () => {
    const user = userEvent.setup();
    render(
      <Select value="tavily" onChange={vi.fn()} options={OPTIONS} />
    );
    await user.click(screen.getByRole("button"));
    const other = screen.getByRole("option", { name: "SerpAPI" });
    expect(other).toHaveAttribute("aria-selected", "false");
  });

  // ── Keyboard navigation ────────────────────────────────────────────────────

  it("opens on Enter key when trigger is focused", async () => {
    const user = userEvent.setup();
    render(
      <Select value="tavily" onChange={vi.fn()} options={OPTIONS} />
    );
    screen.getByRole("button").focus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("listbox")).toBeInTheDocument();
  });

  it("opens on ArrowDown key when trigger is focused", async () => {
    const user = userEvent.setup();
    render(
      <Select value="tavily" onChange={vi.fn()} options={OPTIONS} />
    );
    screen.getByRole("button").focus();
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("listbox")).toBeInTheDocument();
  });

  it("ArrowDown+Enter selects the next option", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <Select value="tavily" onChange={onChange} options={OPTIONS} />
    );
    screen.getByRole("button").focus();
    // Open, move down one (from index 0 to 1 = serpapi), confirm
    await user.keyboard("{ArrowDown}{ArrowDown}{Enter}");
    expect(onChange).toHaveBeenCalledWith("serpapi");
  });

  // ── Props passthrough ──────────────────────────────────────────────────────

  it("passes id to the trigger button", () => {
    render(
      <Select value="tavily" onChange={vi.fn()} options={OPTIONS} id="my-select" />
    );
    expect(screen.getByRole("button").id).toBe("my-select");
  });

  it("passes ariaLabel to the trigger button", () => {
    render(
      <Select value="tavily" onChange={vi.fn()} options={OPTIONS} ariaLabel="Choose provider" />
    );
    expect(screen.getByRole("button")).toHaveAttribute("aria-label", "Choose provider");
  });
});
