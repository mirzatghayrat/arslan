/**
 * SB1-1 (⓪Plan's review of PR 543): the server's `last_at` is naive UTC ("2026-10-30T07:00:00", no offset),
 * which Date.parse reads as local time. Run under UTC+8, where 07:00 UTC today read as yesterday.
 */
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { metaFrom, utcIso } from "../lib/conversationMeta";
import { groupByDay } from "../lib/sidebarOrder";

const TZ = process.env.TZ;
beforeAll(() => { process.env.TZ = "Asia/Shanghai"; });       // Node reads TZ again when it is set
afterAll(() => { if (TZ === undefined) delete process.env.TZ; else process.env.TZ = TZ; });

describe("the server's naive UTC times", () => {
  it("are read as UTC, whatever the Mac's time zone", () => {
    expect(new Date(2026, 9, 30).getTimezoneOffset()).toBe(-480);   // the test really runs in UTC+8
    const meta = metaFrom([{ conversation_id: "a", title: "a", message_count: 1, last_at: "2026-10-30T07:00:00" }]);
    expect(Date.parse(meta.a.lastAt!)).toBe(Date.UTC(2026, 9, 30, 7, 0));
  });

  it("put 07:30 this morning in UTC+8 (23:30 UTC the day before) under Today, not Yesterday", () => {
    const meta = metaFrom([{ conversation_id: "a", title: "a", message_count: 1, last_at: "2026-10-29T23:30:00.123456" }]);
    const now = new Date(2026, 9, 30, 18, 0);                  // 18:00 in Shanghai, 10:00 UTC
    const g = groupByDay([{ id: "a" }], () => Date.parse(meta.a.lastAt!), now, "en");
    expect(g.today.map((r) => r.id)).toEqual(["a"]);
  });

  it("keeps a time that already says where it is", () => {
    expect(utcIso("2026-10-30T07:00:00Z")).toBe("2026-10-30T07:00:00Z");
    expect(utcIso("2026-10-30T07:00:00+08:00")).toBe("2026-10-30T07:00:00+08:00");
    expect(utcIso("2026-10-30T07:00:00-0500")).toBe("2026-10-30T07:00:00-0500");
  });
});
