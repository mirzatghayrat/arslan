/** NET-b: Settings > Sandbox > Sites edits `sandbox_allowed_sites` (a JSON list string) through PUT /settings. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, o?: Record<string, unknown>) => (o ? `${key}:${JSON.stringify(o)}` : key) }),
}));
const request = vi.fn();
vi.mock("../api/client", async (original) => ({
  ...(await original<typeof import("../api/client")>()),
  request: (...args: unknown[]) => request(...args),
}));

import { ApiError } from "../api/client";
import SandboxNetworkPanel from "../components/settings/SandboxNetworkPanel";

const puts = () => request.mock.calls.filter(([, init]) => init?.method === "PUT");
function serve(sites: string[], put: () => unknown = () => ({})) {
  request.mockImplementation(async (path: string, init?: RequestInit) => {
    if (init?.method === "PUT") return put();
    if (path === "/settings") return { sandbox_allowed_sites: JSON.stringify(sites) };
    return { devices: [] };
  });
}

beforeEach(() => request.mockReset());

describe("Settings > Sandbox > Sites", () => {
  it("lists the saved sites", async () => {
    serve(["example.com", "api.test.dev"]);
    render(<SandboxNetworkPanel systemCertificates={false} />);
    const rows = await screen.findAllByTestId("allowed-site");
    expect(rows.map((r) => r.textContent)).toEqual(["example.comsandboxNet.remove", "api.test.devsandboxNet.remove"]);
  });

  it("adds a site, trimmed and lower-cased, with a PUT of the whole list", async () => {
    serve(["example.com"]);
    render(<SandboxNetworkPanel systemCertificates={false} />);
    await screen.findByTestId("allowed-site");
    fireEvent.change(screen.getByTestId("allowed-site-input"), { target: { value: "  Docs.Example.ORG " } });
    fireEvent.click(screen.getByTestId("allowed-site-add"));
    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()[0]).toEqual(["/settings", { method: "PUT",
      body: JSON.stringify({ sandbox_allowed_sites: JSON.stringify(["example.com", "docs.example.org"]) }) }]);
    expect(await screen.findAllByTestId("allowed-site")).toHaveLength(2);
  });

  it("removes a site with a PUT without it", async () => {
    serve(["example.com", "api.test.dev"]);
    render(<SandboxNetworkPanel systemCertificates={false} />);
    fireEvent.click(await screen.findByTestId("allowed-site-remove-example.com"));
    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()[0][1].body).toBe(JSON.stringify({ sandbox_allowed_sites: JSON.stringify(["api.test.dev"]) }));
    await waitFor(() => expect(screen.getAllByTestId("allowed-site")).toHaveLength(1));
  });

  it("never PUTs a list it couldn't read first: add and remove stay off", async () => {
    request.mockImplementation(async (path: string, init?: RequestInit) => {
      if (init?.method === "PUT") return {};
      if (path === "/settings") throw new ApiError("HTTP 500", 500, "boom");
      return { devices: [] };
    });
    render(<SandboxNetworkPanel systemCertificates={false} />);
    expect(await screen.findByTestId("allowed-site-error")).toHaveTextContent("sandboxNet.failed");
    const add = screen.getByTestId("allowed-site-add");
    expect(add).toBeDisabled();
    fireEvent.change(screen.getByTestId("allowed-site-input"), { target: { value: "docs.example.org" } });
    fireEvent.click(add);
    fireEvent.keyDown(screen.getByTestId("allowed-site-input"), { key: "Enter" });
    await new Promise((r) => setTimeout(r, 20));
    expect(puts()).toHaveLength(0);
  });

  it("shows the server's refusal and keeps the list as it was", async () => {
    serve(["example.com"], () => { throw new ApiError("HTTP 422", 422, [{ msg: "Value error, not a site Arslan can list: com" }]); });
    render(<SandboxNetworkPanel systemCertificates={false} />);
    await screen.findByTestId("allowed-site");
    fireEvent.change(screen.getByTestId("allowed-site-input"), { target: { value: "com" } });
    fireEvent.click(screen.getByTestId("allowed-site-add"));
    expect(await screen.findByTestId("allowed-site-error")).toHaveTextContent('sandboxNet.sitesRefused:{"value":"com"}');
    expect(screen.getAllByTestId("allowed-site")).toHaveLength(1);
  });
});
