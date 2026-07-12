/**
 * Provider P2 — ModelCombobox: free-text model input with a filtered
 * suggestion dropdown (dynamic model catalog), capability chips, and an
 * always-present "use custom id" escape hatch so a rotten catalog can never
 * lock the user out.
 */

import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// ── i18n mock ────────────────────────────────────────────────────────────────
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { changeLanguage: vi.fn() },
  }),
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}));

import ModelCombobox from "../components/ModelCombobox";
import type { ModelInfo } from "../api/client.types";

const OPTIONS: ModelInfo[] = [
  {
    id: "deepseek-chat",
    display_name: "DeepSeek Chat",
    context_window: 128000,
    capabilities: ["tools"],
    source: "api",
  },
  {
    id: "deepseek-reasoner",
    display_name: null,
    context_window: 64000,
    capabilities: ["tools", "reasoning"],
    source: "api",
  },
  {
    id: "qwen-vl-max",
    display_name: "Qwen VL Max",
    context_window: null,
    capabilities: ["vision"],
    source: "api",
  },
];

describe("ModelCombobox", () => {
  it("renders the stored value as-is even when absent from options", () => {
    render(
      <ModelCombobox
        value="my-weird-custom-model"
        onChange={vi.fn()}
        options={OPTIONS}
        data-testid="model-combobox"
      />,
    );
    const input = screen.getByTestId("model-combobox") as HTMLInputElement;
    expect(input.value).toBe("my-weird-custom-model");
  });

  it("opens on focus and shows all options plus the custom-id row", async () => {
    const user = userEvent.setup();
    render(
      <ModelCombobox
        value="deepseek-chat"
        onChange={vi.fn()}
        options={OPTIONS}
        data-testid="model-combobox"
      />,
    );
    await user.click(screen.getByTestId("model-combobox"));
    const opts = screen.getAllByRole("option").map((o) => o.textContent ?? "");
    expect(opts.some((t) => t.includes("deepseek-chat"))).toBe(true);
    expect(opts.some((t) => t.includes("deepseek-reasoner"))).toBe(true);
    expect(opts.some((t) => t.includes("qwen-vl-max"))).toBe(true);
    // Fixed last row: use custom id
    expect(screen.getByTestId("model-custom-id-row")).toBeInTheDocument();
  });

  it("typing filters options case-insensitively on id and display_name", async () => {
    const user = userEvent.setup();
    render(
      <ModelCombobox
        value=""
        onChange={vi.fn()}
        options={OPTIONS}
        data-testid="model-combobox"
      />,
    );
    const input = screen.getByTestId("model-combobox");
    await user.click(input);
    await user.type(input, "QWEN");
    const opts = screen.getAllByRole("option").map((o) => o.textContent ?? "");
    expect(opts.some((t) => t.includes("qwen-vl-max"))).toBe(true);
    expect(opts.some((t) => t.includes("deepseek-chat"))).toBe(false);
    // display_name substring also matches
    await user.clear(input);
    await user.type(input, "DeepSeek Ch");
    const opts2 = screen.getAllByRole("option").map((o) => o.textContent ?? "");
    expect(opts2.some((t) => t.includes("deepseek-chat"))).toBe(true);
    expect(opts2.some((t) => t.includes("qwen-vl-max"))).toBe(false);
  });

  it("ArrowDown + Enter commits the highlighted option id", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <ModelCombobox
        value=""
        onChange={onChange}
        options={OPTIONS}
        data-testid="model-combobox"
      />,
    );
    const input = screen.getByTestId("model-combobox");
    await user.click(input);
    await user.keyboard("{ArrowDown}{Enter}");
    expect(onChange).toHaveBeenCalledWith("deepseek-chat");
  });

  it("free text + Enter commits the raw input", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <ModelCombobox
        value=""
        onChange={onChange}
        options={OPTIONS}
        data-testid="model-combobox"
      />,
    );
    const input = screen.getByTestId("model-combobox");
    await user.click(input);
    await user.type(input, "totally-new-model{Enter}");
    expect(onChange).toHaveBeenCalledWith("totally-new-model");
  });

  it("clicking the custom-id row commits the raw input", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <ModelCombobox
        value=""
        onChange={onChange}
        options={OPTIONS}
        data-testid="model-combobox"
      />,
    );
    const input = screen.getByTestId("model-combobox");
    await user.click(input);
    await user.type(input, "hand-typed-id");
    await user.click(screen.getByTestId("model-custom-id-row"));
    expect(onChange).toHaveBeenCalledWith("hand-typed-id");
  });

  it("renders capability chips and compact context window", async () => {
    const user = userEvent.setup();
    render(
      <ModelCombobox
        value=""
        onChange={vi.fn()}
        options={OPTIONS}
        data-testid="model-combobox"
      />,
    );
    await user.click(screen.getByTestId("model-combobox"));
    // Chips (i18n mock returns the key)
    expect(screen.getAllByText("settings.modelCapTools").length).toBeGreaterThan(0);
    expect(screen.getAllByText("settings.modelCapReasoning").length).toBeGreaterThan(0);
    expect(screen.getAllByText("settings.modelCapVision").length).toBeGreaterThan(0);
    // 128000 → "128k"
    expect(screen.getByText("128k")).toBeInTheDocument();
  });

  it("Escape closes the dropdown", async () => {
    const user = userEvent.setup();
    render(
      <ModelCombobox
        value=""
        onChange={vi.fn()}
        options={OPTIONS}
        data-testid="model-combobox"
      />,
    );
    const input = screen.getByTestId("model-combobox");
    await user.click(input);
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("renders a refresh button that fires onRefresh when provided", async () => {
    const user = userEvent.setup();
    const onRefresh = vi.fn();
    render(
      <ModelCombobox
        value=""
        onChange={vi.fn()}
        options={OPTIONS}
        onRefresh={onRefresh}
        data-testid="model-combobox"
      />,
    );
    const btn = screen.getByRole("button", { name: "settings.modelRefresh" });
    await user.click(btn);
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });

  it("shows the stale hint under the field when provided", () => {
    render(
      <ModelCombobox
        value=""
        onChange={vi.fn()}
        options={OPTIONS}
        staleHint="last updated 5m ago · refresh failed"
        data-testid="model-combobox"
      />,
    );
    expect(
      screen.getByText("last updated 5m ago · refresh failed"),
    ).toBeInTheDocument();
  });
});

// ── Review fixes: guarded commits + all four exits behave identically ─────────

describe("ModelCombobox guarded commits (review fixes)", () => {
  it("Enter without editing does not fire onChange (no-op commit)", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <ModelCombobox
        value="deepseek-chat"
        onChange={onChange}
        options={OPTIONS}
        data-testid="model-combobox"
      />,
    );
    await user.click(screen.getByTestId("model-combobox"));
    await user.keyboard("{Enter}");
    expect(onChange).not.toHaveBeenCalled();
    // Commit still closes the dropdown
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("clicking the option equal to the current value does not fire onChange", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <ModelCombobox
        value="deepseek-chat"
        onChange={onChange}
        options={OPTIONS}
        data-testid="model-combobox"
      />,
    );
    await user.click(screen.getByTestId("model-combobox"));
    const same = screen
      .getAllByRole("option")
      .find((o) => (o.textContent ?? "").includes("deepseek-chat"));
    await user.click(same!);
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("clearing the input then Enter reverts to the stored value without onChange", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <ModelCombobox
        value="deepseek-chat"
        onChange={onChange}
        options={OPTIONS}
        data-testid="model-combobox"
      />,
    );
    const input = screen.getByTestId("model-combobox") as HTMLInputElement;
    await user.click(input);
    await user.clear(input);
    await user.keyboard("{Enter}");
    expect(onChange).not.toHaveBeenCalled();
    expect(input.value).toBe("deepseek-chat");
  });

  it("resets the highlight when options swap under an open dropdown", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { rerender } = render(
      <ModelCombobox
        value=""
        onChange={onChange}
        options={OPTIONS}
        data-testid="model-combobox"
      />,
    );
    const input = screen.getByTestId("model-combobox");
    await user.click(input);
    // Highlight the 3rd option (index 2)
    await user.keyboard("{ArrowDown}{ArrowDown}{ArrowDown}");
    // Options swap (e.g. the lazy fetch resolving) to a 1-item list
    const single: ModelInfo[] = [OPTIONS[1]];
    rerender(
      <ModelCombobox
        value=""
        onChange={onChange}
        options={single}
        data-testid="model-combobox"
      />,
    );
    // Highlight was reset — Enter must NOT commit an out-of-range surprise;
    // the empty raw input reverts, so nothing fires.
    await user.keyboard("{Enter}");
    expect(onChange).not.toHaveBeenCalled();
    // Re-open and pick predictably from the new list
    await user.click(input);
    await user.keyboard("{ArrowDown}{Enter}");
    expect(onChange).toHaveBeenCalledWith("deepseek-reasoner");
  });

  it("Tab-away commits pending text like outside-click", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <ModelCombobox
        value="deepseek-chat"
        onChange={onChange}
        options={OPTIONS}
        data-testid="model-combobox"
      />,
    );
    const input = screen.getByTestId("model-combobox") as HTMLInputElement;
    await user.click(input);
    await user.clear(input);
    await user.type(input, "typed-then-tabbed");
    await user.tab();
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("typed-then-tabbed");
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("Tab-away without an edit closes without firing onChange", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <ModelCombobox
        value="deepseek-chat"
        onChange={onChange}
        options={OPTIONS}
        data-testid="model-combobox"
      />,
    );
    await user.click(screen.getByTestId("model-combobox"));
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    await user.tab();
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("Escape reverts the draft and closes; a later Tab does not commit it", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <ModelCombobox
        value="deepseek-chat"
        onChange={onChange}
        options={OPTIONS}
        data-testid="model-combobox"
      />,
    );
    const input = screen.getByTestId("model-combobox") as HTMLInputElement;
    await user.click(input);
    await user.clear(input);
    await user.type(input, "zzz-discard-me");
    await user.keyboard("{Escape}");
    expect(input.value).toBe("deepseek-chat");
    expect(screen.queryByRole("listbox")).toBeNull();
    // The reverted draft must be gone for good — Tab-away commits nothing
    await user.tab();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("outside-click commits changed text (blur-save semantics)", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <div>
        <ModelCombobox
          value="deepseek-chat"
          onChange={onChange}
          options={OPTIONS}
          data-testid="model-combobox"
        />
        <button type="button" data-testid="outside-target">out</button>
      </div>,
    );
    const input = screen.getByTestId("model-combobox") as HTMLInputElement;
    await user.click(input);
    await user.clear(input);
    await user.type(input, "clicked-away-model");
    await user.click(screen.getByTestId("outside-target"));
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("clicked-away-model");
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("outside-click without an edit does not fire onChange", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <div>
        <ModelCombobox
          value="deepseek-chat"
          onChange={onChange}
          options={OPTIONS}
          data-testid="model-combobox"
        />
        <button type="button" data-testid="outside-target">out</button>
      </div>,
    );
    await user.click(screen.getByTestId("model-combobox"));
    await user.click(screen.getByTestId("outside-target"));
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.queryByRole("listbox")).toBeNull();
  });
});
