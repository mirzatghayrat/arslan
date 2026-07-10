/**
 * AccessTokenSettings — the token-entry / copy / reset section of Settings.
 *
 * Uses the REAL auth store (zustand) so setToken re-renders reactively, and
 * mocks the two api calls it makes.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { changeLanguage: vi.fn() },
  }),
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}));

const mockGetAccessToken = vi.fn();
const mockResetAccessToken = vi.fn();

vi.mock("../api/client", () => ({
  api: {
    getAccessToken: (...a: unknown[]) => mockGetAccessToken(...a),
    resetAccessToken: (...a: unknown[]) => mockResetAccessToken(...a),
  },
}));

import AccessTokenSettings from "../components/AccessTokenSettings";
import { useAuthStore } from "../stores/authStore";

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  useAuthStore.setState({ token: "" });
});

describe("AccessTokenSettings", () => {
  it("shows a non-nagging note when no token is required (dev)", async () => {
    mockGetAccessToken.mockResolvedValue({ token_required: false, token: null });
    render(<AccessTokenSettings backendStatus="online" />);
    expect(await screen.findByText("settings.accessToken.notRequired")).toBeInTheDocument();
  });

  it("shows + hydrates the store with the localhost-returned token", async () => {
    mockGetAccessToken.mockResolvedValue({ token_required: true, token: "srv-123" });
    render(<AccessTokenSettings backendStatus="online" />);

    const input = (await screen.findByTestId("access-token-value")) as HTMLInputElement;
    expect(input.value).toBe("srv-123");
    // The store is hydrated so API/WS auth works immediately.
    await waitFor(() => expect(useAuthStore.getState().token).toBe("srv-123"));
    expect(screen.getByTestId("access-token-copy")).toBeInTheDocument();
  });

  it("prompts for a token when required and none is known, writing it to the store", async () => {
    mockGetAccessToken.mockResolvedValue({ token_required: true, token: null });
    const user = userEvent.setup();
    render(<AccessTokenSettings backendStatus="online" />);

    const paste = (await screen.findByTestId("access-token-paste")) as HTMLInputElement;
    await user.type(paste, "pasted-tok");
    fireEvent.click(screen.getByTestId("access-token-save"));

    await waitFor(() => expect(useAuthStore.getState().token).toBe("pasted-tok"));
  });

  it("resets the token and updates both the display and the store", async () => {
    mockGetAccessToken.mockResolvedValue({ token_required: true, token: "srv-1" });
    mockResetAccessToken.mockResolvedValue({ token: "rotated-9" });
    render(<AccessTokenSettings backendStatus="online" />);

    await screen.findByTestId("access-token-value");
    fireEvent.click(screen.getByTestId("access-token-reset"));

    await waitFor(() => {
      expect(mockResetAccessToken).toHaveBeenCalledTimes(1);
      expect(useAuthStore.getState().token).toBe("rotated-9");
    });
    const input = screen.getByTestId("access-token-value") as HTMLInputElement;
    expect(input.value).toBe("rotated-9");
  });

  it("disables Reset when the backend is offline", async () => {
    mockGetAccessToken.mockResolvedValue({ token_required: true, token: "srv-1" });
    render(<AccessTokenSettings backendStatus="offline" />);
    await screen.findByTestId("access-token-value");
    expect(screen.getByTestId("access-token-reset")).toBeDisabled();
  });
});
