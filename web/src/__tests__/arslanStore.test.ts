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

  it("sets pending on addUserMessage and clears on first stream_start", () => {
    const s = useArslanStore.getState();
    s.addUserMessage("hi");
    expect(useArslanStore.getState().pending).toBe(true);
    s.handleFrame({ type: "stream_start", source: "arslan" });
    expect(useArslanStore.getState().pending).toBe(false);
  });

  it("renders spawn_created as an in-order system item (not a bottom chip)", () => {
    const s = useArslanStore.getState();
    s.addUserMessage("make me a spawn");
    s.handleFrame({ type: "spawn_created", spawn_id: 9, spawn_name: "Beauty Guru" });
    const items = useArslanStore.getState().items;
    const last = items[items.length - 1];
    expect(last.kind).toBe("system");
    expect(last.content).toContain("Beauty Guru");
    expect(useArslanStore.getState().suggestion).toBeNull();
  });

  it("stores task_brief + overlaps with the suggestion", () => {
    useArslanStore.getState().handleFrame({
      type: "suggest_create",
      draft: { name: "eq", domain: "finance.x", capabilities: [] },
      task_brief: "analyze TSLA",
      overlaps: { spawn_id: 3, name: "GuGu", axes: ["a"] },
    });
    const st = useArslanStore.getState();
    expect(st.suggestion).toMatchObject({ name: "eq" });
    expect(st.suggestionTaskBrief).toBe("analyze TSLA");
    expect(st.suggestionOverlaps).toMatchObject({ spawn_id: 3, name: "GuGu" });
  });

  it("attaches spawn_meta sent before stream_end (production order)", () => {
    const s = useArslanStore.getState();
    s.handleFrame({ type: "stream_start", source: "spawn", spawn_id: 7 });
    s.handleFrame({ type: "stream_chunk", content: "out" });
    s.handleFrame({ type: "spawn_meta", arslan_message_id: 11, spawn_id: 7, assistant_message_id: 42, task_brief: "do X" });
    s.handleFrame({ type: "stream_end", message_id: 11 });
    const item = useArslanStore.getState().items.find((i) => i.id === 11);
    expect(item).toMatchObject({ spawnMessageId: 42, taskBrief: "do X" });
  });

  it("also attaches spawn_meta sent after stream_end (defensive)", () => {
    const s = useArslanStore.getState();
    s.handleFrame({ type: "stream_start", source: "spawn", spawn_id: 7 });
    s.handleFrame({ type: "stream_chunk", content: "out" });
    s.handleFrame({ type: "stream_end", message_id: 11 });
    s.handleFrame({ type: "spawn_meta", arslan_message_id: 11, spawn_id: 7, assistant_message_id: 42, task_brief: "do X" });
    const item = useArslanStore.getState().items.find((i) => i.id === 11);
    expect(item).toMatchObject({ spawnMessageId: 42, taskBrief: "do X" });
  });

  it("stream_end with null message_id (refused escalation) creates no empty ghost item", () => {
    useArslanStore.setState(initialArslanState(), true);
    const h = useArslanStore.getState().handleFrame;
    h({ type: "stream_start", source: "spawn", spawn_id: 7 } as never);
    h({ type: "stream_end", message_id: null } as never);
    expect(useArslanStore.getState().items).toHaveLength(0);
    expect(useArslanStore.getState().streaming).toBe(false);
  });

  it("stream_end with null message_id still folds pending tool steps under a client id", () => {
    useArslanStore.setState(initialArslanState(), true);
    const h = useArslanStore.getState().handleFrame;
    h({ type: "tool_call", tool: "web_search", args_summary: "" } as never);
    h({ type: "tool_result", tool: "web_search", ok: true, summary: "hits" } as never);
    h({ type: "stream_start", source: "spawn", spawn_id: 7 } as never);
    h({ type: "stream_end", message_id: null } as never);
    const items = useArslanStore.getState().items;
    expect(items).toHaveLength(1);
    expect(items[0].id).toBeLessThan(0); // client id, not null
    expect(items[0].toolSteps).toHaveLength(1);
    expect(useArslanStore.getState().activitySteps).toEqual([]);
  });

  it("appends a replayed message frame (resume path)", () => {
    useArslanStore.getState().setSpawnNames({ 7: "Beauty Guru" });
    const s = useArslanStore.getState();
    s.handleFrame({ type: "message", message_id: 20, content: "welcome back", role: "arslan" });
    s.handleFrame({ type: "message", message_id: 21, content: "post draft", role: "spawn_summary" });
    const items = useArslanStore.getState().items;
    expect(items[items.length - 2]).toMatchObject({ id: 20, role: "arslan", content: "welcome back" });
    const last = items[items.length - 1];
    // A replayed message frame carries no spawn_id, so the name cannot be resolved — degrades to null.
    expect(last).toMatchObject({ id: 21, role: "spawn", content: "post draft", spawnId: null, spawnName: null });
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

  it("spawn_created stores equipment and intro on the system item", () => {
    useArslanStore.setState(initialArslanState(), true);
    useArslanStore.getState().handleFrame({
      type: "spawn_created", spawn_id: 7, spawn_name: "Scout",
      equipment: { toolsets: [{ key: "ws", name: "Web search", status: "wired", grant: "permanent" }], skills: [] },
      intro: "Hi, I'm Scout.",
    } as never);
    const items = useArslanStore.getState().items;
    const item = items[items.length - 1];
    expect(item.kind).toBe("system");
    expect(item.intro).toBe("Hi, I'm Scout.");
    expect(item.equipment?.toolsets[0].key).toBe("ws");
  });

  it("pairs tool_call/tool_result and folds steps into the reply on stream_end", () => {
    useArslanStore.setState(initialArslanState(), true);
    const h = useArslanStore.getState().handleFrame;
    h({ type: "tool_call", tool: "web_search", args_summary: '{"q":"a"}' } as never);
    h({ type: "tool_call", tool: "web_search", args_summary: '{"q":"b"}' } as never);
    h({ type: "tool_result", tool: "web_search", ok: true, summary: "5 hits" } as never);
    const steps = useArslanStore.getState().activitySteps;
    // most recent unresolved same-tool step resolves first
    expect(steps[1]).toMatchObject({ status: "ok", resultSummary: "5 hits" });
    expect(steps[0].status).toBe("running");
    h({ type: "tool_result", tool: "web_search", ok: false, summary: "timeout" } as never);
    expect(useArslanStore.getState().activitySteps[0].status).toBe("error");

    h({ type: "stream_start", source: "spawn", spawn_id: 7 } as never);
    h({ type: "stream_chunk", content: "answer" } as never);
    h({ type: "stream_end", message_id: 42 } as never);
    const its = useArslanStore.getState().items;
    const item = its[its.length - 1];
    expect(item.toolSteps).toHaveLength(2);
    expect(useArslanStore.getState().activitySteps).toEqual([]);
  });

  it("clears activity on error frame", () => {
    useArslanStore.setState(initialArslanState(), true);
    const h = useArslanStore.getState().handleFrame;
    h({ type: "tool_call", tool: "web_extract", args_summary: "" } as never);
    h({ type: "error", code: "X", message: "boom" } as never);
    expect(useArslanStore.getState().activitySteps).toEqual([]);
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

  it("escalation frames drive a resolving→resolved item state machine", () => {
    useArslanStore.setState(initialArslanState(), true);
    const h = useArslanStore.getState().handleFrame;
    h({ type: "escalation", spawn_id: 7, spawn_name: "Scout", kind: "capability", need: "discord access" } as never);
    let item = useArslanStore.getState().items[useArslanStore.getState().items.length - 1];
    expect(item.kind).toBe("escalation");
    expect(item.escalation).toMatchObject({ status: "resolving", need: "discord access" });
    h({ type: "escalation_resolved", spawn_id: 7, how: "granted", detail: "discord toolset, 3 turns" } as never);
    item = useArslanStore.getState().items[useArslanStore.getState().items.length - 1];
    expect(item.escalation).toMatchObject({ status: "resolved", how: "granted" });
  });

  it("escalation_refused marks the item refused with why", () => {
    useArslanStore.setState(initialArslanState(), true);
    const h = useArslanStore.getState().handleFrame;
    h({ type: "escalation", spawn_id: 7, spawn_name: "Scout", kind: "data", need: "run code" } as never);
    h({ type: "escalation_refused", spawn_id: 7, why: "action, not a need" } as never);
    const item = useArslanStore.getState().items[useArslanStore.getState().items.length - 1];
    expect(item.escalation).toMatchObject({ status: "refused", why: "action, not a need" });
  });
});
