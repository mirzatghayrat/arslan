/**
 * One parser for both helpers. Conversation mode adds three line kinds the
 * hold-to-talk helper never sends; the shape check must still reject JSON
 * that is not ours.
 */
import { describe, test, expect } from "vitest";
import { parseLine } from "../lib/voiceLine";

describe("parseLine (shared)", () => {
  test("reads the conversation-only kinds", () => {
    expect(parseLine('{"t":"level","peak":0.2}')).toEqual({ t: "level", peak: 0.2 });
    expect(parseLine('{"t":"state","muted":true}')).toEqual({ t: "state", muted: true });
    expect(parseLine('{"t":"ended"}')).toEqual({ t: "ended" });
  });
  test("still rejects foreign JSON and fragments", () => {
    expect(parseLine('{"hello":"world"}')).toBeNull();
    expect(parseLine('{"t":"lev')).toBeNull();
  });
});
