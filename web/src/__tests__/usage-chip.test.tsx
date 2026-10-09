import { describe, it, expect } from "vitest";
import { fmtTok, fmtUsd } from "../lib/usageFormat";
import { toUiMessages } from "../api/adapters";
import type { ArslanThreadItem } from "../api/client.types";

describe("fmtTok / fmtUsd (S3-M3)", () => {
  it("formats token counts: <1000 raw, then k, then M", () => {
    expect(fmtTok(0)).toBe("0");
    expect(fmtTok(999)).toBe("999");
    expect(fmtTok(1234)).toBe("1.2k");
    expect(fmtTok(12000)).toBe("12k");
    expect(fmtTok(8_690_000)).toBe("8.7M");
  });

  it("formats usd honestly: $0 only for genuinely free, micro-costs keep precision", () => {
    expect(fmtUsd(0)).toBe("$0");
    expect(fmtUsd(0.003)).toBe("$0.003");
    expect(fmtUsd(1.5)).toBe("$1.50");
  });
});

describe("adapter passes item.usage through to the UI Message", () => {
  it("arslan and spawn items keep usage; user items never carry one", () => {
    const usage = { tokens_in: 1, tokens_out: 2, tokens_total: 3, estimated: false, usd: null };
    const items: ArslanThreadItem[] = [
      { id: 1, kind: "message", role: "user", content: "hi" },
      { id: 2, kind: "message", role: "arslan", content: "yo", usage },
      { id: 3, kind: "message", role: "spawn", content: "done", spawnName: "S", usage },
    ];
    const msgs = toUiMessages(items);
    expect(msgs[0].usage).toBeUndefined();
    expect(msgs[1].usage).toEqual(usage);
    expect(msgs[2].usage).toEqual(usage);
  });
});
