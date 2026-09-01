/**
 * Push-to-talk's two pure pieces.
 *
 * The helper speaks in JSON lines over a pipe, which means the frontend has to
 * survive a partial write and a stray log line without taking the button down
 * with it — and it has to turn a refusal code into a sentence, because the
 * failure mode this replaces was silence that reads like broken hardware.
 */
import { describe, test, expect } from "vitest";
import { parseLine, errorMessage } from "../components/PushToTalk";

const t = (k: string) => k;   // identity: assert on the KEY, not on wording

describe("parseLine", () => {
  test("reads the four line kinds", () => {
    expect(parseLine('{"t":"ready"}')).toEqual({ t: "ready" });
    expect(parseLine('{"t":"partial","text":"你好"}')).toEqual({ t: "partial", text: "你好" });
    expect(parseLine('{"t":"final","text":"你好世界"}')).toEqual({ t: "final", text: "你好世界" });
    expect(parseLine('{"t":"error","code":"mic-denied","msg":"x"}'))
      .toEqual({ t: "error", code: "mic-denied", msg: "x" });
  });

  test("a half-written line is ignored, not thrown", () => {
    // The pipe can hand us a fragment; throwing here would kill the listener.
    expect(parseLine('{"t":"partial","te')).toBeNull();
  });

  test("a stray non-JSON line is ignored", () => {
    expect(parseLine("some framework logged this")).toBeNull();
  });

  test("valid JSON that is not one of our lines is rejected", () => {
    // Discriminates: parsing successfully is not the same as being ours.
    expect(parseLine('{"hello":"world"}')).toBeNull();
    expect(parseLine('"just a string"')).toBeNull();
    expect(parseLine("42")).toBeNull();
  });
});

describe("errorMessage", () => {
  test.each([
    ["mic-denied", "voice.errDenied"],
    ["speech-denied", "voice.errDenied"],
    ["mic-auth-timeout", "voice.errNoAnswer"],
    ["speech-auth-timeout", "voice.errNoAnswer"],
    ["locale-unsupported", "voice.errLocale"],
    ["no-input", "voice.errNoInput"],
  ])("%s becomes a sentence the user can act on", (code, key) => {
    expect(errorMessage(code, "raw", t)).toBe(key);
  });

  test("an unknown code falls back to what the helper said, not to silence", () => {
    // A code we have not seen yet must still surface SOMETHING — the whole
    // point is that a refusal never looks like broken hardware.
    expect(errorMessage("engine-failed", "the audio engine would not start", t))
      .toBe("the audio engine would not start");
  });
});
