import { describe, expect, it } from "vitest";
import { toUiMessages } from "../api/adapters";
import type { ArslanThreadItem } from "../api/client.types";

describe("run replay entry", () => {
  it("toUiMessages carries runId onto spawn deliverables", () => {
    const items: ArslanThreadItem[] = [{
      id: 1, kind: "message", role: "spawn", content: "done",
      spawnId: 1, spawnName: "Mermer", spawnMessageId: 5, runId: 7,
    }];
    const msgs = toUiMessages(items);
    expect(msgs[0].runId).toBe(7);
  });
});
