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
    expect(note.content).toContain("已记入");
    expect(note.content).toContain("小美");
    expect(note.content).toContain("3");
  });

  it("falls back to 知识库 when spawn_name is null", () => {
    useArslanStore.getState().handleFrame({
      type: "attachment_stored",
      spawn_name: null,
      chunks: 1,
    } as any);

    const items = useArslanStore.getState().items;
    expect(items[items.length - 1].content).toContain("知识库");
  });
});
