import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import "../i18n";
import SpawnFeedbackBar from "../components/arslan/SpawnFeedbackBar";

describe("SpawnFeedbackBar", () => {
  it("fires the right callbacks", async () => {
    const cb = { onThumbUp: vi.fn(), onThumbDown: vi.fn(), onRedo: vi.fn(), onTweak: vi.fn() };
    render(<SpawnFeedbackBar {...cb} />);
    await userEvent.click(screen.getByRole("button", { name: /good/i }));
    await userEvent.click(screen.getByRole("button", { name: /bad/i }));
    await userEvent.click(screen.getByRole("button", { name: /redo/i }));
    await userEvent.click(screen.getByRole("button", { name: /tweak/i }));
    // Guard: i18n actually resolved the keys (no raw key paths leaked as labels).
    expect(screen.queryByLabelText(/feedback\.redo/)).toBeNull();
    expect(screen.queryByLabelText(/feedback\.tweak/)).toBeNull();
    expect(cb.onThumbUp).toHaveBeenCalled();
    expect(cb.onThumbDown).toHaveBeenCalled();
    expect(cb.onRedo).toHaveBeenCalled();
    expect(cb.onTweak).toHaveBeenCalled();
  });
});
