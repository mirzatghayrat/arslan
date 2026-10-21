/**
 * 0.1.63 K4b: the context ring opens a breakdown (master plan K4 ⑦, ⓪Plan Q8).
 * The total is the provider's last input; the server's five estimated parts are scaled to it
 * (marked "about"), so the rows add up to the total shown.
 */
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k),
    i18n: { resolvedLanguage: "en", language: "en" } }),
}));
const { client, conv } = vi.hoisted(() => ({
  client: { fetchProviderModels: vi.fn(), updateProviderConfig: vi.fn() },
  conv: { get: vi.fn(), set: vi.fn(), clear: vi.fn() },
}));
vi.mock("../api/client", async (orig) => ({ ...(await orig<object>()), ...client }));
vi.mock("../api/conversationModel", () => ({ conversationModelApi: conv }));

import type { ProviderConfig } from "../api/client.types";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";
import ConversationModelChip, { _resetChipCatalogs, ringRows } from "../components/models/ConversationModelChip";

const PARTS = { system: 1000, tools: 3000, context: 500, history: 4000, turn: 1500 };
const cfg = { id: 1, provider: "deepseek", model: "deepseek-chat", is_primary: true, label: "DeepSeek" } as ProviderConfig;

function chip(usage: Record<string, unknown>) {
  useArslanStore.setState({ items: [{ kind: "message", id: "a", role: "arslan", text: "hi", usage }] } as never);
  render(<ConversationModelChip conversationId="c1" llmProviders={[]} onSetDefault={vi.fn()} configs={[cfg]} />);
}

beforeEach(() => {
  _resetChipCatalogs();
  useArslanStore.setState(initialArslanState as never);
  client.fetchProviderModels.mockResolvedValue({ models: [{ id: "deepseek-chat", context_window: 64000, capabilities: ["tools"] }] });
  conv.get.mockResolvedValue({ choice: null });
});
afterEach(cleanup);

describe("ringRows", () => {
  it("scales the estimated parts to the provider's total, in a fixed order", () => {
    const rows = ringRows(PARTS, 48000);
    expect(rows.map((r) => r.key)).toEqual(["system", "tools", "context", "history", "turn"]);
    expect(rows.map((r) => r.tokens)).toEqual([4800, 14400, 2400, 19200, 7200]);
    expect(rows.map((r) => r.pct)).toEqual([10, 30, 5, 40, 15]);
  });

  it("rows always add up to the total, rounding included", () => {
    const rows = ringRows({ system: 1, tools: 1, context: 1, history: 0, turn: 0 }, 100);
    expect(rows.reduce((sum, r) => sum + r.tokens, 0)).toBe(100);
  });

  it("nothing to show without parts or a total", () => {
    expect(ringRows(null, 48000)).toEqual([]);
    expect(ringRows({ system: 0, tools: 0, context: 0, history: 0, turn: 0 }, 48000)).toEqual([]);
    expect(ringRows(PARTS, null)).toEqual([]);
  });
});

describe("the ring", () => {
  it("opens the breakdown: the provider's total, five rows, and a note that the split is estimated", async () => {
    chip({ last_input: 48000, context_parts: PARTS });
    const ring = await screen.findByTestId("context-ring");
    expect(ring.textContent).toBe("75%");
    expect(ring.getAttribute("aria-expanded")).toBe("false");
    await act(async () => { fireEvent.click(ring); });
    const box = screen.getByTestId("context-breakdown");
    expect(box.textContent).toContain('models.contextTotal:{"tokens":"48,000"}');
    expect(box.textContent).toContain("models.contextEstimated");
    expect(screen.getByTestId("context-part-history").textContent).toContain("models.partHistory");
    expect(screen.getByTestId("context-part-history").textContent).toContain('models.about:{"value":"19,200"}');
    expect(screen.getByTestId("context-part-history").textContent).toContain("40%");
    expect(screen.getByTestId("context-part-turn").textContent).toContain("models.partTurn");
  });

  it("without parts it stays the plain ring of before", async () => {
    chip({ last_input: 48000 });
    const ring = await screen.findByTestId("context-ring");
    expect(ring.getAttribute("aria-expanded")).toBeNull();
    fireEvent.click(ring);
    expect(screen.queryByTestId("context-breakdown")).toBeNull();
  });
});

describe("the breakdown's words", () => {
  it("exist in all six languages with their placeholders", async () => {
    const { modelsMessages } = await import("../locales/models");
    const keys = ["contextParts", "contextTotal", "contextEstimated", "about",
                  "partSystem", "partTools", "partContext", "partHistory", "partTurn"];
    for (const locale of ["en", "zh", "ja", "es", "de", "fr"] as const) {
      const messages = modelsMessages[locale] as Record<string, string>;
      for (const key of keys) expect(messages[key]?.trim(), `${locale}.${key}`).toBeTruthy();
      expect(messages.contextTotal).toContain("{{tokens}}");
      expect(messages.about).toContain("{{value}}");
    }
  });
});
