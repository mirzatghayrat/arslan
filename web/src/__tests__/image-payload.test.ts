import { describe, expect, it } from "vitest";
import { base64Bytes, computeTargetSize, MAX_EDGE } from "../lib/imagePayload";

describe("computeTargetSize", () => {
  it("leaves small images alone", () => {
    expect(computeTargetSize(800, 600)).toEqual({ width: 800, height: 600 });
  });

  it("scales the LONG edge to the cap, preserving aspect ratio", () => {
    const out = computeTargetSize(4000, 3000);
    expect(Math.max(out.width, out.height)).toBe(MAX_EDGE);
    // 4:3 in, 4:3 out — a fix that clamped both edges would square the image.
    expect(out.width / out.height).toBeCloseTo(4 / 3, 2);
  });

  it("handles portrait as well as landscape", () => {
    const out = computeTargetSize(1000, 5000);
    expect(out.height).toBe(MAX_EDGE);
    expect(out.width).toBeLessThan(out.height);
  });

  it("never collapses a dimension to zero", () => {
    // A 10000x3 banner scaled by 1568/10000 gives 0.47px of height.
    expect(computeTargetSize(10000, 3).height).toBeGreaterThanOrEqual(1);
  });

  it("is a no-op at exactly the cap", () => {
    expect(computeTargetSize(MAX_EDGE, 900)).toEqual({ width: MAX_EDGE, height: 900 });
  });
});

describe("base64Bytes", () => {
  it("accounts for padding", () => {
    // "QUJD" = "ABC" (3 bytes, no padding); "QQ==" = "A" (1 byte, 2 pad)
    expect(base64Bytes("QUJD")).toBe(3);
    expect(base64Bytes("QQ==")).toBe(1);
    expect(base64Bytes("QUI=")).toBe(2);
  });

  it("is close enough to reject a frame that would not fit", () => {
    // 16 MiB of base64 decodes to 12 MiB — the guard must see it as over 12 MiB
    // of PAYLOAD, not under it, or an oversized frame slips through.
    const b64 = "A".repeat(16 * 1024 * 1024);
    expect(base64Bytes(b64)).toBeCloseTo(12 * 1024 * 1024, -3);
  });
});
