/**
 * A page turn in an AskQueue is not undone by an effect that runs late.
 *
 * The queue picks its first card in an effect. That effect read `shown` from the render it closed over, so
 * when it ran after the person had already paged (‹ ›), it saw the old value (none), put the first card back,
 * and the next Allow answered that one. In the browser this needs a click between React's commit and its
 * passive effects; in CI it happened whenever React's scheduler task ran after Testing Library's drain
 * (inbox-v2.test.tsx "a choice made on one card is not carried…" answered k1, run 39568511999). Here the
 * scheduler task is delayed on purpose, so the order is the bad one every time.
 */
import { describe, it, expect, vi, afterEach } from "vitest";

vi.hoisted(() => {
  // React's scheduler runs passive effects on setImmediate in Node, captured when it loads: make it late.
  const g = globalThis as unknown as { setImmediate: (cb: (...a: unknown[]) => void, ...a: unknown[]) => unknown };
  g.setImmediate = (cb, ...a) => setTimeout(() => cb(...a), 80);
});

import { useEffect, useState } from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { AskQueue, type QueuedAsk } from "../components/kit/AskQueue";

afterEach(cleanup);

const card = (key: string): QueuedAsk => ({
  key,
  render: (queue) => <div data-testid={`card-${key}`}><button type="button" onClick={queue.onNext}>next</button></div>,
});

/** The Inbox's way in: the cards arrive from an async load, so the queue mounts outside act. */
function Late() {
  const [items, setItems] = useState<QueuedAsk[]>([]);
  useEffect(() => { void Promise.resolve().then(() => setItems([card("k1"), card("k2")])); }, []);
  return <AskQueue items={items} />;
}

describe("AskQueue", () => {
  it("keeps the card paged to when the effect that picks the first card runs late", async () => {
    render(<Late />);
    fireEvent.click(await screen.findByText("next", {}, { timeout: 2000 }));
    expect(screen.getByTestId("card-k2")).toBeInTheDocument();
    await act(async () => { await new Promise((r) => setTimeout(r, 200)); });     // the late effect has run by now
    expect(screen.getByTestId("card-k2")).toBeInTheDocument();
    expect(screen.queryByTestId("card-k1")).toBeNull();
  });
});
