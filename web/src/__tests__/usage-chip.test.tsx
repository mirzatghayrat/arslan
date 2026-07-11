import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import UsageChip from "../components/UsageChip";
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

describe("UsageChip (bubble corner usage)", () => {
  it("renders tokens + usd when both are known", () => {
    render(
      <UsageChip
        usage={{ tokens_in: 100, tokens_out: 50, tokens_total: 1234, estimated: false, usd: 0.003 }}
      />,
    );
    const chip = screen.getByTestId("usage-chip");
    expect(chip.textContent).toContain("1.2k tok");
    expect(chip.textContent).toContain("$0.003");
    expect(chip.textContent).not.toContain("≈");
  });

  it("usd null → tokens only (unknown ≠ free: never invent a $ figure)", () => {
    render(
      <UsageChip
        usage={{ tokens_in: 10, tokens_out: 5, tokens_total: 500, estimated: false, usd: null }}
      />,
    );
    const chip = screen.getByTestId("usage-chip");
    expect(chip.textContent).toContain("500 tok");
    expect(chip.textContent).not.toContain("$");
  });

  it("estimated → ≈ prefix", () => {
    render(
      <UsageChip
        usage={{ tokens_in: null, tokens_out: null, tokens_total: 2000, estimated: true, usd: null }}
      />,
    );
    const chip = screen.getByTestId("usage-chip");
    expect(chip.textContent).toContain("≈");
    expect(chip.textContent).toContain("2k tok");
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
