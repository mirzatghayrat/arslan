import { afterEach, expect, it } from "vitest";

afterEach(() => { localStorage.clear(); sessionStorage.clear(); });

it("uses real isolated browser storage rather than Node process storage", () => {
  const browser = (globalThis as unknown as { jsdom: { window: Window } }).jsdom.window;
  expect(localStorage).toBe(browser.localStorage);
  expect(sessionStorage).toBe(browser.sessionStorage);
  expect(localStorage).toBeInstanceOf(Storage);
  expect(sessionStorage).toBeInstanceOf(Storage);
  expect(localStorage).not.toBe(sessionStorage);
  expect(localStorage.length).toBe(0);
  expect(sessionStorage.length).toBe(0);
  localStorage.setItem("browser-only", "persistent");
  sessionStorage.setItem("browser-only", "session");
  expect(window.localStorage.getItem("browser-only")).toBe("persistent");
  expect(window.sessionStorage.getItem("browser-only")).toBe("session");
  localStorage.removeItem("browser-only");
  expect(localStorage.getItem("browser-only")).toBeNull();
  expect(sessionStorage.key(0)).toBe("browser-only");
});
