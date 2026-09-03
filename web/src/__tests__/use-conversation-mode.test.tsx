/**
 * Conversation mode's session, against a fake Tauri.
 *
 * What must be true: enabling starts the helper with the locale and the
 * silence setting; a final is SENT (not put in a text box); the microphone
 * is muted exactly while the speaker is active; disabling stops the helper.
 */
import { describe, test, expect, beforeEach, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { changeLanguage: vi.fn(), language: "en" },
  }),
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}));

import { useConversationMode } from "../hooks/useConversationMode";
import { useArslanStore } from "../stores/arslanStore";

let listeners: Array<(e: { payload: string }) => void>;
let invokes: Array<[string, unknown]>;
beforeEach(() => {
  listeners = []; invokes = [];
  (window as any).__TAURI__ = {
    core: { invoke: vi.fn(async (cmd: string, args?: unknown) => { invokes.push([cmd, args]); }) },
    event: { listen: vi.fn(async (_name: string, cb: any) => { listeners.push(cb); return () => { listeners = listeners.filter((l) => l !== cb); }; }) },
  };
  useArslanStore.setState({ speaking: false });
});
const emit = (line: string) => listeners.forEach((l) => l({ payload: line }));
const flush = () => act(async () => { await Promise.resolve(); await Promise.resolve(); });

describe("useConversationMode", () => {
  test("enabling starts the helper with locale and silence; a final is sent", async () => {
    const onFinal = vi.fn();
    const { result } = renderHook(() => useConversationMode({ enabled: true, locale: "zh-CN", silenceMs: 1200, onFinal, onError: vi.fn() }));
    await flush();
    expect(invokes).toContainEqual(["voice_conversation_start", { locale: "zh-CN", silenceMs: 1200 }]);
    expect(result.current.phase).toBe("arming");
    act(() => emit('{"t":"ready"}'));
    expect(result.current.phase).toBe("listening");
    // The helper comes up unmuted. Telling it to unmute because a phase change
    // re-ran the gate is a command about nothing — and the reason to care is
    // that it is written down the pipe the recogniser is reading.
    expect(invokes.map(([c]) => c)).not.toContain("voice_unmute");
    act(() => emit('{"t":"partial","text":"打开"}'));
    expect(result.current.partial).toBe("打开");
    act(() => emit('{"t":"final","text":"打开桌面"}'));
    expect(onFinal).toHaveBeenCalledWith("打开桌面");
    expect(result.current.partial).toBe("");
  });

  test("an empty final is not sent", async () => {
    const onFinal = vi.fn();
    renderHook(() => useConversationMode({ enabled: true, locale: "en-US", silenceMs: 900, onFinal, onError: vi.fn() }));
    await flush();
    act(() => emit('{"t":"final","text":"   "}'));
    expect(onFinal).not.toHaveBeenCalled();
  });

  test("the microphone is muted exactly while the speaker is active", async () => {
    const { result } = renderHook(() => useConversationMode({ enabled: true, locale: "en-US", silenceMs: 900, onFinal: vi.fn(), onError: vi.fn() }));
    await flush();
    act(() => emit('{"t":"ready"}'));
    act(() => useArslanStore.setState({ speaking: true }));
    await flush();
    expect(invokes.map(([c]) => c)).toContain("voice_mute");
    expect(result.current.phase).toBe("muted");
    act(() => useArslanStore.setState({ speaking: false }));
    await flush();
    expect(invokes.map(([c]) => c)).toContain("voice_unmute");
    expect(result.current.phase).toBe("listening");
  });

  test("disabling stops the helper; an error line surfaces as a sentence", async () => {
    const onError = vi.fn();
    const { rerender } = renderHook(({ enabled }) => useConversationMode({ enabled, locale: "en-US", silenceMs: 900, onFinal: vi.fn(), onError }), { initialProps: { enabled: true } });
    await flush();
    act(() => emit('{"t":"error","code":"mic-denied","msg":"x"}'));
    expect(onError).toHaveBeenCalledWith("voice.errDenied");
    rerender({ enabled: false });
    await flush();
    expect(invokes.map(([c]) => c)).toContain("voice_conversation_stop");
  });

  test("the helper ending reaches the caller, once", async () => {
    // `ended` is the shell saying the helper process is gone. The hook knew;
    // the caller did not, so its toggle stayed lit over a dead session and
    // the only way back was to press it twice.
    const onEnded = vi.fn();
    renderHook(() => useConversationMode({ enabled: true, locale: "en-US", silenceMs: 900, onFinal: vi.fn(), onError: vi.fn(), onEnded }));
    await flush();
    act(() => emit('{"t":"ended"}'));
    expect(onEnded).toHaveBeenCalledTimes(1);
  });

  test("a stop that races the start invoke still stops the helper", async () => {
    // The window: cleanup runs while `voice_conversation_start` is still in
    // flight. Its `voice_conversation_stop` reaches a shell that has not
    // spawned anything yet, and the helper that appears a moment later belongs
    // to nobody — holding the microphone until the app quits.
    let resolveStart: () => void = () => {};
    const inFlight = new Promise<void>((r) => { resolveStart = r; });
    (window as any).__TAURI__.core.invoke = vi.fn(async (cmd: string, args?: unknown) => {
      invokes.push([cmd, args]);
      if (cmd === "voice_conversation_start") await inFlight;
    });
    const { unmount } = renderHook(() => useConversationMode({ enabled: true, locale: "en-US", silenceMs: 900, onFinal: vi.fn(), onError: vi.fn() }));
    await flush();
    expect(invokes.map(([c]) => c)).toContain("voice_conversation_start");
    unmount();
    await flush();
    const stopsBefore = invokes.filter(([c]) => c === "voice_conversation_stop").length;
    resolveStart();
    await flush();
    const stopsAfter = invokes.filter(([c]) => c === "voice_conversation_stop").length;
    expect(stopsAfter).toBe(stopsBefore + 1);
  });

  test("no Tauri at all: stays off and never throws", async () => {
    (window as any).__TAURI__ = undefined;
    const { result } = renderHook(() => useConversationMode({ enabled: true, locale: "en-US", silenceMs: 900, onFinal: vi.fn(), onError: vi.fn() }));
    await flush();
    expect(result.current.phase).toBe("off");
  });
});
