/**
 * The catalog's third kind of connector: needs OAuth, not supported yet.
 *
 * 🔴 What the old two-way split would have done with such an entry: no env vars
 * ⇒ one_click ⇒ a green Connect button whose click can only fail — or, keyed
 * the other way, a needs-key prefill collecting a key no service will issue.
 * Both are traps dressed as features. The section exists BEFORE any oauth entry
 * does (ruling ②), so the entry here is a TEST STUB, never a catalog addition.
 */
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const catalog = vi.fn();
vi.mock("../api/catalog", () => ({
  getMcpCatalog: (...a: unknown[]) => catalog(...a),
}));
vi.mock("../api/mcp", () => ({
  listMcpServers: vi.fn(async () => []),
  addMcpServer: vi.fn(),
  connectMcpServer: vi.fn(),
}));

import RecommendedMcp from "../components/RecommendedMcp";

const base = {
  key: "x", label: "X", transport: "stdio", command: "npx", args: [],
  url: null, runtime: "node", env: [], requires_path: false,
  path_placeholder: null, description: "d",
};

afterEach(cleanup);

describe("the oauth section", () => {
  it("renders oauth connectors in their own section, with no action button", async () => {
    catalog.mockResolvedValue([
      { ...base, key: "free", label: "Free", auth: "none", one_click: true },
      { ...base, key: "linear", label: "Linear", auth: "oauth", one_click: true, env: [] },
    ]);
    render(<RecommendedMcp />);
    await waitFor(() => expect(screen.getByText("Linear")).toBeTruthy());

    const card = screen.getByText("Linear").closest("div[data-auth]") as HTMLElement;
    expect(card?.dataset.auth).toBe("oauth");
    // The honesty line, and the absence of every action the card cannot honour.
    expect(card.textContent).toMatch(/OAuth/);
    expect(card.textContent).toMatch(/not supported yet/i);
    expect(card.querySelector("button")).toBeNull();
  });

  it("does NOT let an oauth entry fall into the one-click section", async () => {
    // The trap the explicit field replaces: an oauth service has no env vars, so
    // the derived one_click is TRUE for it — a green Connect that can only fail.
    catalog.mockResolvedValue([
      { ...base, key: "linear", label: "Linear", auth: "oauth", one_click: true },
    ]);
    render(<RecommendedMcp />);
    await waitFor(() => expect(screen.getByText("Linear")).toBeTruthy());
    expect(screen.queryByText("Connect")).toBeNull();
  });

  it("hides the whole section while no oauth connector exists", async () => {
    // Today's catalog. An empty section with a heading would be a placeholder,
    // and this repo deleted its placeholder tabs for a reason.
    catalog.mockResolvedValue([
      { ...base, key: "free", label: "Free", auth: "none", one_click: true },
    ]);
    render(<RecommendedMcp />);
    await waitFor(() => expect(screen.getByText("Free")).toBeTruthy());
    expect(screen.queryByTestId("mcp-oauth-section")).toBeNull();
  });

  it("still sections none and static_key exactly as before", async () => {
    catalog.mockResolvedValue([
      { ...base, key: "free", label: "Free", auth: "none", one_click: true },
      { ...base, key: "keyed", label: "Keyed", auth: "static_key", one_click: false,
        env: [{ name: "K", description: "", get_it_url: "", paid: false }] },
    ]);
    render(<RecommendedMcp />);
    await waitFor(() => expect(screen.getByText("Keyed")).toBeTruthy());
    expect(screen.getByText("Connect")).toBeTruthy();
    expect(screen.getByText("Set up")).toBeTruthy();
  });
});
