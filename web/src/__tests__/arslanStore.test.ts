import { beforeEach, describe, expect, it } from "vitest";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";

const reset = () => useArslanStore.setState(initialArslanState(), true);

describe("arslanStore", () => {
  beforeEach(reset);

  it("maps a history frame, resolving spawn names from the roster", () => {
    useArslanStore.getState().setSpawnNames({ 7: "Beauty Guru" });
    useArslanStore.getState().handleFrame({
      type: "history",
      messages: [
        { message_id: 1, role: "user", content: "hi", spawn_id: null },
        { message_id: 2, role: "arslan", content: "hello", spawn_id: null },
        { message_id: 3, role: "spawn_summary", content: "Full post draft…", spawn_id: 7 },
      ],
    });
    const items = useArslanStore.getState().items;
    expect(items).toHaveLength(3);
    expect(items[1]).toMatchObject({ role: "arslan", content: "hello" });
    expect(items[2]).toMatchObject({ role: "spawn", spawnId: 7, spawnName: "Beauty Guru", content: "Full post draft…" });
  });

  it("optimistically adds a user message", () => {
    useArslanStore.getState().addUserMessage("draft me a post");
    const items = useArslanStore.getState().items;
    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({ role: "user", content: "draft me a post" });
  });

  it("streams an Arslan answer to a finalized message", () => {
    const s = useArslanStore.getState();
    s.handleFrame({ type: "stream_start", source: "arslan" });
    s.handleFrame({ type: "stream_chunk", content: "Hel" });
    s.handleFrame({ type: "stream_chunk", content: "lo" });
    expect(useArslanStore.getState().streamingText).toBe("Hello");
    expect(useArslanStore.getState().streamSource).toBe("arslan");
    s.handleFrame({ type: "stream_end", message_id: 10 });
    const st = useArslanStore.getState();
    expect(st.streaming).toBe(false);
    const last = st.items[st.items.length - 1];
    expect(last).toMatchObject({ id: 10, role: "arslan", content: "Hello" });
  });

  it("attributes a routed spawn stream using the preceding routing frame", () => {
    const s = useArslanStore.getState();
    s.handleFrame({ type: "routing", spawn_id: 7, spawn_name: "Beauty Guru" });
    s.handleFrame({ type: "stream_start", source: "spawn", spawn_id: 7 });
    s.handleFrame({ type: "stream_chunk", content: "Here are 3 posts" });
    s.handleFrame({ type: "stream_end", message_id: 11 });
    const st = useArslanStore.getState();
    const last = st.items[st.items.length - 1];
    expect(last).toMatchObject({ role: "spawn", spawnId: 7, spawnName: "Beauty Guru", content: "Here are 3 posts" });
    expect(st.pendingRoute).toBeNull();
  });

  it("stores a suggest_create draft and clears it on dismiss", () => {
    const s = useArslanStore.getState();
    const draft = { name: "beauty-guru", domain: "content-creator.xiaohongshu", capabilities: ["content-generation"] };
    s.handleFrame({ type: "suggest_create", draft });
    expect(useArslanStore.getState().suggestion).toEqual(draft);
    s.dismissSuggestion();
    expect(useArslanStore.getState().suggestion).toBeNull();
  });

  it("renders fact_saved as a fact item in the thread", () => {
    useArslanStore.getState().handleFrame({ type: "fact_saved", content: "posts on xiaohongshu", sensitive: false });
    const its = useArslanStore.getState().items;
    const last = its[its.length - 1];
    expect(last).toMatchObject({ kind: "fact", content: "posts on xiaohongshu", sensitive: false });
  });

  it("clears the suggestion and records the name on spawn_created", () => {
    const s = useArslanStore.getState();
    s.handleFrame({ type: "suggest_create", draft: { name: "x", domain: "d", capabilities: [] } });
    s.handleFrame({ type: "spawn_created", spawn_id: 9, spawn_name: "Beauty Guru" });
    expect(useArslanStore.getState().suggestion).toBeNull();
    expect(useArslanStore.getState().spawnNames[9]).toBe("Beauty Guru");
  });

  it("records the created spawn name for confirmation", () => {
    useArslanStore.getState().handleFrame({ type: "spawn_created", spawn_id: 9, spawn_name: "Beauty Guru" });
    expect(useArslanStore.getState().lastCreatedSpawn).toBe("Beauty Guru");
  });

  it("appends a replayed message frame (resume path)", () => {
    useArslanStore.getState().setSpawnNames({ 7: "Beauty Guru" });
    const s = useArslanStore.getState();
    s.handleFrame({ type: "message", message_id: 20, content: "welcome back", role: "arslan" });
    s.handleFrame({ type: "message", message_id: 21, content: "post draft", role: "spawn_summary" });
    const items = useArslanStore.getState().items;
    expect(items[items.length - 2]).toMatchObject({ id: 20, role: "arslan", content: "welcome back" });
    const last = items[items.length - 1];
    expect(last).toMatchObject({ id: 21, role: "spawn", content: "post draft", spawnName: "Beauty Guru" });
    expect(useArslanStore.getState().lastMessageId).toBe(21);
  });

  it("records a recoverable error and ends streaming", () => {
    const s = useArslanStore.getState();
    s.handleFrame({ type: "stream_start", source: "spawn", spawn_id: 7 });
    s.handleFrame({ type: "error", code: "SPAWN_ERROR", message: "couldn't complete", recoverable: true });
    const st = useArslanStore.getState();
    expect(st.error).toContain("couldn't complete");
    expect(st.streaming).toBe(false);
  });

  it("ignores a stream_end with no active stream (no empty bubble)", () => {
    const s = useArslanStore.getState();
    s.handleFrame({ type: "stream_end", message_id: 99 });
    expect(useArslanStore.getState().items).toHaveLength(0);
  });

  it("ignores stream chunks arriving after stream_end", () => {
    const s = useArslanStore.getState();
    s.handleFrame({ type: "stream_start", source: "arslan" });
    s.handleFrame({ type: "stream_chunk", content: "hi" });
    s.handleFrame({ type: "stream_end", message_id: 5 });
    s.handleFrame({ type: "stream_chunk", content: "orphan" });
    expect(useArslanStore.getState().streamingText).toBe("");
    s.handleFrame({ type: "stream_end", message_id: 6 });
    // the orphan chunk must NOT have produced a second message
    expect(useArslanStore.getState().items).toHaveLength(1);
  });

  it("clears spawn attribution when an error interrupts a routed stream", () => {
    const s = useArslanStore.getState();
    s.handleFrame({ type: "routing", spawn_id: 7, spawn_name: "Beauty Guru" });
    s.handleFrame({ type: "stream_start", source: "spawn", spawn_id: 7 });
    s.handleFrame({ type: "error", code: "SPAWN_ERROR", message: "boom" });
    const st = useArslanStore.getState();
    expect(st.streamSource).toBeNull();
    expect(st.streamSpawnId).toBeNull();
    expect(st.pendingRoute).toBeNull();
  });
});
