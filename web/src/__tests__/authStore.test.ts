import { beforeEach, describe, expect, it } from "vitest";
import { useAuthStore } from "../stores/authStore";

describe("authStore", () => {
  beforeEach(() => {
    localStorage.clear();
    useAuthStore.setState({ token: "" });
  });

  it("starts with empty token", () => {
    expect(useAuthStore.getState().token).toBe("");
  });

  it("sets and persists the token", () => {
    useAuthStore.getState().setToken("abc123");
    expect(useAuthStore.getState().token).toBe("abc123");
    expect(localStorage.getItem("arslan_token")).toBe("abc123");
  });

  it("clears the token", () => {
    useAuthStore.getState().setToken("abc");
    useAuthStore.getState().clearToken();
    expect(useAuthStore.getState().token).toBe("");
    expect(localStorage.getItem("arslan_token")).toBeNull();
  });
});
