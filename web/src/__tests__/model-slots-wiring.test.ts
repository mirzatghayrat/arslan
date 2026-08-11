/**
 * A slot the frontend declares and the adapter forgets looks exactly like a working one.
 *
 * github_token broke this way: registered in one place, missing in another, so the
 * frontend sent it, the API accepted it, nothing stored it, and every layer reported
 * success. These iterate MODEL_SLOTS rather than naming five keys, so a sixth slot
 * cannot be added without someone remembering to come back here.
 */
import { describe, expect, it } from "vitest";

import { toUiSettings, toBackendSettings } from "../api/adapters";
import { MODEL_SLOTS } from "../lib/modelSlots";

/** camelCase settings key -> the snake_case name the backend uses. */
const backendKey = (k: string) => k.replace(/[A-Z]/g, (c) => `_${c.toLowerCase()}`);

describe("every slot survives the round trip", () => {
  it.each(MODEL_SLOTS)("$id arrives from the backend", (slot) => {
    const ui = toUiSettings({ [backendKey(slot.settingsKey)]: "7" } as never);
    expect((ui as Record<string, unknown>)[slot.settingsKey]).toBe("7");
  });

  it.each(MODEL_SLOTS)("$id is sent back on save", (slot) => {
    const body = toBackendSettings({ [slot.settingsKey]: "7" } as never);
    expect((body as Record<string, unknown>)[backendKey(slot.settingsKey)]).toBe("7");
  });

  it.each(MODEL_SLOTS)("$id sends an empty value as empty, not as undefined", (slot) => {
    // "" is how a user CLEARS a slot. Dropping it from the body would make clearing
    // a no-op that looks like it worked — the field would still show the old model
    // after a reload, and nothing would say why.
    const body = toBackendSettings({ [slot.settingsKey]: "" } as never);
    expect((body as Record<string, unknown>)[backendKey(slot.settingsKey)]).toBe("");
  });

  it.each(MODEL_SLOTS)("$id defaults to empty when the backend omits it", (slot) => {
    const ui = toUiSettings({} as never);
    expect((ui as Record<string, unknown>)[slot.settingsKey]).toBe("");
  });
});
