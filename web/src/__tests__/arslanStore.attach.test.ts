import { describe, it, expect, beforeEach } from "vitest";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";

beforeEach(() => useArslanStore.setState(initialArslanState(), true));

describe("attachment_stored frame", () => {
  it("appends a system note with spawn name and chunk count", () => {
    useArslanStore.getState().handleFrame({
      type: "attachment_stored",
      spawn_name: "小美",
      chunks: 3,
    } as any);

    const items = useArslanStore.getState().items;
    expect(items.length).toBe(1);
    const note = items[items.length - 1];
    expect(note.kind).toBe("system");
    // The store keeps an i18n-free sentinel; App translates it at render time.
    expect(note.content.startsWith("__ATTACHMENT_STORED__:")).toBe(true);
    const payload = JSON.parse(note.content.slice("__ATTACHMENT_STORED__:".length));
    expect(payload.name).toBe("小美");
    expect(payload.chunks).toBe(3);
  });

  it("carries a null name when spawn_name is null (generic wording at render)", () => {
    useArslanStore.getState().handleFrame({
      type: "attachment_stored",
      spawn_name: null,
      chunks: 1,
    } as any);

    const items = useArslanStore.getState().items;
    const payload = JSON.parse(
      items[items.length - 1].content.slice("__ATTACHMENT_STORED__:".length),
    );
    expect(payload.name).toBeNull();
    expect(payload.chunks).toBe(1);
  });
});
