import { describe, it, expect, beforeEach } from "vitest";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";
import { toUiMessages } from "../api/adapters";

beforeEach(() => useArslanStore.setState(initialArslanState(), true));

// 🔒 SECURITY invariant under test: artifactHtml is populated ONLY from the backend
// stream_end frame's artifact (HX-2 HTML deliverable channel), never from LLM text.
const HTML_ARTIFACT = {
  kind: "html",
  filename: "run_68_okx-deck.html",
  title: "OKX 演示",
  bytes: 21628,
  complete: false,
  content: "<!DOCTYPE html><html><head><title>OKX 演示</title></head><body>deck",
};

describe("stream_end html artifact (HX-3)", () => {
  it("captures a kind:html artifact from the stream_end frame onto the message item", () => {
    const store = () => useArslanStore.getState();
    store().handleFrame({ type: "stream_start", source: "spawn", spawn_id: 6 } as any);
    store().handleFrame({ type: "stream_chunk", content: "已生成 HTML 文档《OKX 演示》" } as any);
    store().handleFrame({ type: "stream_end", message_id: 465, artifact: HTML_ARTIFACT } as any);

    const item = store().items[store().items.length - 1];
    expect(item.artifactHtml).toEqual({
      title: "OKX 演示",
      filename: "run_68_okx-deck.html",
      content: HTML_ARTIFACT.content,
      complete: false,
      bytes: 21628,
    });
  });

  it("leaves artifactHtml undefined when the stream_end frame carries no artifact", () => {
    const store = () => useArslanStore.getState();
    store().handleFrame({ type: "stream_start", source: "spawn", spawn_id: 6 } as any);
    store().handleFrame({ type: "stream_chunk", content: "普通回复" } as any);
    store().handleFrame({ type: "stream_end", message_id: 1 } as any);

    const item = store().items[store().items.length - 1];
    expect(item.artifactHtml).toBeUndefined();
  });

  it("ignores non-html artifact kinds on stream_end (channel is kind-gated)", () => {
    const store = () => useArslanStore.getState();
    store().handleFrame({ type: "stream_start", source: "spawn", spawn_id: 6 } as any);
    store().handleFrame({ type: "stream_chunk", content: "x" } as any);
    store().handleFrame({
      type: "stream_end",
      message_id: 2,
      artifact: { kind: "pptx", filename: "deck.pptx" },
    } as any);

    const item = store().items[store().items.length - 1];
    expect(item.artifactHtml).toBeUndefined();
  });

  it("toUiMessages passes artifactHtml through to the UI Message", () => {
    const store = () => useArslanStore.getState();
    store().handleFrame({ type: "stream_start", source: "spawn", spawn_id: 6 } as any);
    store().handleFrame({ type: "stream_chunk", content: "已生成" } as any);
    store().handleFrame({ type: "stream_end", message_id: 465, artifact: HTML_ARTIFACT } as any);

    const ui = toUiMessages(store().items);
    const msg = ui[ui.length - 1];
    expect(msg.sender).toBe("spawn");
    expect(msg.artifactHtml?.title).toBe("OKX 演示");
    expect(msg.artifactHtml?.complete).toBe(false);
    expect(msg.artifactHtml?.filename).toBe("run_68_okx-deck.html");
  });
});
