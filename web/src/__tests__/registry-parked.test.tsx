// CAP4a-3d's web half (the board the user OK'd, 2026-11-02): a connection its Registry entry stopped, and the button
// that keeps it. The row reads the server's `registry_parked`; the keep posts the `seen` it showed.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k} ${JSON.stringify(o)}` : k) }),
}));

const api = vi.hoisted(() => ({ source: vi.fn(), acceptSource: vi.fn() }));
vi.mock("../api/capabilities", async (orig) => ({ ...(await orig<object>()), capabilitiesApi: api }));

vi.mock("../components/McpServers", () => ({ default: () => null }));

import { ApiError } from "../api/client";
import { RegistryParked } from "../components/capabilities/RegistryParked";
import CapabilitySheet from "../components/CapabilitySheet";
import { formatUiDate } from "../lib/localeFormatting";
import type { CapabilitySource, RegistryParked as Parked } from "../api/capabilities";

const INSTALLED = { registry_type: "pypi", identifier: "notes-mcp", version: "1.2.0" };

function source(parked: Partial<Parked> | null): CapabilitySource {
  return { id: "src1", kind: "mcp", name: "notes", registry_parked: parked && {
    why: "withdrawn", seen: "a".repeat(64), checked_at: new Date().toISOString(), installed: INSTALLED, now: null,
    hidden: { installed: 0, now: 0 }, looks_same: false, ...parked } } as CapabilitySource;
}

beforeEach(() => { api.source.mockReset(); api.acceptSource.mockReset(); });
afterEach(cleanup);

describe("a connection its Registry entry stopped", () => {
  it("shows nothing when nothing is parked", async () => {
    api.source.mockResolvedValue(source(null));
    const { container } = render(<RegistryParked sourceId="src1" onChanged={vi.fn()} />);
    await waitFor(() => expect(api.source).toHaveBeenCalledWith("src1"));
    expect(container.querySelector('[data-testid="registry-parked"]')).toBeNull();
  });

  it("a withdrawn entry: why, what was installed, the withdrawn mark, and the keep", async () => {
    api.source.mockResolvedValue(source({}));
    render(<RegistryParked sourceId="src1" onChanged={vi.fn()} />);
    expect(await screen.findByTestId("registry-parked-why")).toHaveTextContent(
      'capabilityList.parked_withdrawn {"when":"capabilityList.parked_today"}');
    expect(screen.getByTestId("registry-parked-installed")).toHaveTextContent("notes-mcp 1.2.0 (PyPI)");
    expect(screen.getByTestId("registry-parked-now")).toHaveTextContent("capabilityList.parked_nowWithdrawn");
    expect(screen.queryByTestId("registry-parked-looks-same")).toBeNull();
    expect(screen.getByTestId("registry-keep")).toHaveTextContent("capabilityList.parked_keep");
  });

  it("a changed entry: what it names now, and that keeping runs what was installed", async () => {
    api.source.mockResolvedValue(source({ why: "changed",
      now: { registry_type: "pypi", identifier: "notes-mcp-next", version: "1.2.0" } }));
    render(<RegistryParked sourceId="src1" onChanged={vi.fn()} />);
    expect(await screen.findByTestId("registry-parked-why")).toHaveTextContent("capabilityList.parked_changed");
    expect(screen.getByTestId("registry-parked-now")).toHaveTextContent("notes-mcp-next 1.2.0 (PyPI)");
    expect(screen.getByText("capabilityList.parked_keepRuns")).toBeInTheDocument();
  });

  it("a remote shows its URL on both sides", async () => {
    api.source.mockResolvedValue(source({ why: "changed", installed: { url: "https://mcp.example.com/notes" },
      now: { url: "https://elsewhere.example.net/notes" } }));
    render(<RegistryParked sourceId="src1" onChanged={vi.fn()} />);
    expect(await screen.findByTestId("registry-parked-installed")).toHaveTextContent("https://mcp.example.com/notes");
    expect(screen.getByTestId("registry-parked-now")).toHaveTextContent("https://elsewhere.example.net/notes");
  });

  it("a change that reads the same says so, and counts what shows nothing", async () => {
    api.source.mockResolvedValue(source({ why: "changed", now: INSTALLED, looks_same: true,
      hidden: { installed: 0, now: 2 } }));
    render(<RegistryParked sourceId="src1" onChanged={vi.fn()} />);
    expect(await screen.findByTestId("registry-parked-looks-same")).toHaveTextContent("capabilityList.parked_looksSame");
    expect(screen.getByTestId("registry-parked-hidden")).toHaveTextContent('capabilityList.parked_hidden {"count":2}');
  });

  it("the Registry's values are isolated from the words around them", async () => {
    api.source.mockResolvedValue(source({ why: "changed", now: { identifier: "notes-mcp-next", version: "1" } }));
    render(<RegistryParked sourceId="src1" onChanged={vi.fn()} />);
    const now = await screen.findByTestId("registry-parked-now");
    expect(now.querySelector("bdi")).not.toBeNull();
  });

  it("an older check shows its date, not today", async () => {
    api.source.mockResolvedValue(source({ checked_at: "2026-10-01T09:00:00Z" }));
    render(<RegistryParked sourceId="src1" onChanged={vi.fn()} />);
    const why = await screen.findByTestId("registry-parked-why");
    expect(why).not.toHaveTextContent("capabilityList.parked_today");
    expect(why).toHaveTextContent(formatUiDate("2026-10-01T09:00:00Z"));
  });

  it("keeping posts the answer it showed, then says it started again", async () => {
    const onChanged = vi.fn();
    api.source.mockResolvedValue(source({}));
    api.acceptSource.mockResolvedValue(source(null));
    render(<RegistryParked sourceId="src1" onChanged={onChanged} />);
    fireEvent.click(await screen.findByTestId("registry-keep"));
    expect(await screen.findByTestId("registry-kept")).toHaveTextContent("capabilityList.parked_kept");
    expect(api.acceptSource).toHaveBeenCalledWith("src1", "a".repeat(64));
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it("a newer answer (409) is shown again, never kept", async () => {
    const onChanged = vi.fn();
    const newer = source({ why: "changed", seen: "b".repeat(64),
      now: { registry_type: "pypi", identifier: "other", version: "9" } });
    api.source.mockResolvedValue(newer).mockResolvedValueOnce(source({}));
    api.acceptSource.mockRejectedValueOnce(new ApiError("moved", 409, { code: "source_answer_moved" }))
      .mockResolvedValueOnce(source(null));
    render(<RegistryParked sourceId="src1" onChanged={onChanged} />);
    fireEvent.click(await screen.findByTestId("registry-keep"));
    expect(await screen.findByTestId("registry-parked-error")).toHaveTextContent("capabilityList.parked_moved");
    expect(await screen.findByTestId("registry-parked-now")).toHaveTextContent("other 9 (PyPI)");
    expect(screen.queryByTestId("registry-kept")).toBeNull();
    expect(onChanged).not.toHaveBeenCalled();
    // The newer answer is shown, never kept by itself: one post so far, of the answer that was shown first.
    expect(api.acceptSource).toHaveBeenCalledTimes(1);
    expect(api.acceptSource).toHaveBeenNthCalledWith(1, "src1", "a".repeat(64));
    fireEvent.click(screen.getByTestId("registry-keep"));
    expect(await screen.findByTestId("registry-kept")).toBeInTheDocument();
    expect(api.acceptSource).toHaveBeenNthCalledWith(2, "src1", "b".repeat(64));
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it("a reload that fails after a 409 keeps the row it showed", async () => {
    api.source.mockResolvedValueOnce(source({})).mockRejectedValueOnce(new ApiError("down", 503));
    api.acceptSource.mockRejectedValue(new ApiError("moved", 409));
    render(<RegistryParked sourceId="src1" onChanged={vi.fn()} />);
    fireEvent.click(await screen.findByTestId("registry-keep"));
    expect(await screen.findByTestId("registry-parked-error")).toHaveTextContent("capabilityList.parked_moved");
    expect(screen.getByTestId("registry-parked-installed")).toHaveTextContent("notes-mcp 1.2.0 (PyPI)");
  });

  it("a first load that fails says so", async () => {
    api.source.mockRejectedValue(new ApiError("down", 503));
    render(<RegistryParked sourceId="src1" onChanged={vi.fn()} />);
    expect(await screen.findByTestId("registry-parked-load-failed")).toHaveTextContent("capabilityList.loadFailed");
  });

  it("a changed remote says keeping it keeps connecting to the address it was added with", async () => {
    api.source.mockResolvedValue(source({ why: "changed", installed: { url: "https://mcp.example.com/notes" },
      now: { url: "https://elsewhere.example.net/notes" } }));
    render(<RegistryParked sourceId="src1" onChanged={vi.fn()} />);
    expect(await screen.findByTestId("registry-parked-keep-runs")).toHaveTextContent("capabilityList.parked_keepRunsRemote");
  });

  it("another failure says so and keeps the row", async () => {
    api.source.mockResolvedValue(source({}));
    api.acceptSource.mockRejectedValue(new ApiError("boom", 500));
    render(<RegistryParked sourceId="src1" onChanged={vi.fn()} />);
    fireEvent.click(await screen.findByTestId("registry-keep"));
    expect(await screen.findByTestId("registry-parked-error")).toHaveTextContent("capabilityList.parked_failed");
    expect(screen.getByTestId("registry-parked")).toBeInTheDocument();
  });
});

describe("in a row's details sheet", () => {
  const row = (over: object) => ({ key: "mcp:1", section: "connections", origin: "installed", deletable: true,
    source_id: "src1", state: "off", switch: "mcp", tools: [], reason: null, fix: null, last_used: null, ...over }) as never;
  const sheet = (r: never) => render(<CapabilitySheet row={r} name="notes" what="" used="" onClose={() => {}}
    onDelete={() => {}} onChanged={() => {}} />);

  it("a connection installed from a card shows the parked row above its card", async () => {
    api.source.mockResolvedValue(source({}));
    sheet(row({}));
    expect(await screen.findByTestId("registry-parked")).toBeInTheDocument();
    expect(api.source).toHaveBeenCalledWith("src1");
  });

  it("a connection added by hand, or a skill, asks nothing", async () => {
    sheet(row({ source_id: null, origin: "manual" }));
    cleanup();
    sheet(row({ key: "skill:weekly", section: "skills" }));
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(api.source).not.toHaveBeenCalled();
    expect(screen.queryByTestId("registry-parked")).toBeNull();
  });
});

// #604 max review (0396a90d): two rows must never read the same without a word, and a lookalike never pass.
describe("values that could pass for each other", () => {
  const NBSP = String.fromCodePoint(0xa0);
  const rows = async () => ({ installed: await screen.findByTestId("registry-parked-installed"),
                              now: screen.getByTestId("registry-parked-now") });

  it("spacing moved between the name and the version reads the same: the note says so, the odd space is marked", async () => {
    api.source.mockResolvedValue(source({ why: "changed", looks_same: false,
      installed: { registry_type: "pypi", identifier: "notes-mcp 1.2.0", version: " " },
      now: { registry_type: "pypi", identifier: NBSP, version: "notes-mcp 1.2.0" } }));
    render(<RegistryParked sourceId="src1" onChanged={vi.fn()} />);
    const { now } = await rows();
    expect(screen.getByTestId("registry-parked-looks-same")).toBeInTheDocument();
    expect(within(now).getByTestId("non-ascii")).toHaveTextContent("U+00A0");
  });

  it.each([["a Cyrillic р", "notes-mc" + String.fromCodePoint(0x440), "U+0440"],
           ["a Cyrillic о", "n" + String.fromCodePoint(0x43e) + "tes-mcp", "U+043E"],
           ["U+2010 for a hyphen", "notes" + String.fromCodePoint(0x2010) + "mcp", "U+2010"]])(
    "%s in a name is marked by its code point", async (_what, identifier, code) => {
      api.source.mockResolvedValue(source({ why: "changed", now: { registry_type: "pypi", identifier, version: "1.2.0" } }));
      render(<RegistryParked sourceId="src1" onChanged={vi.fn()} />);
      const { now } = await rows();
      expect(within(now).getByTestId("non-ascii")).toHaveTextContent(code);
    });

  it("a non-ASCII address is marked too", async () => {
    api.source.mockResolvedValue(source({ why: "changed", installed: { url: "https://example.com/mcp" },
      now: { url: "https://ex" + String.fromCodePoint(0x430) + "mple.com/mcp" } }));
    render(<RegistryParked sourceId="src1" onChanged={vi.fn()} />);
    const { now } = await rows();
    expect(within(now).getByTestId("non-ascii")).toHaveTextContent("U+0430");
  });

  it("an empty value reads as a dash, on either side", async () => {
    api.source.mockResolvedValue(source({ why: "changed", installed: { identifier: "", version: "" }, now: {} }));
    render(<RegistryParked sourceId="src1" onChanged={vi.fn()} />);
    const { installed, now } = await rows();
    expect(installed).toHaveTextContent(/^—$/);
    expect(now).toHaveTextContent(/^—$/);
  });

  it("plain ASCII is shown as it is, with no marks", async () => {
    api.source.mockResolvedValue(source({ why: "changed", now: { registry_type: "pypi", identifier: "notes-mcp-next", version: "1.2.0" } }));
    render(<RegistryParked sourceId="src1" onChanged={vi.fn()} />);
    await rows();
    expect(screen.queryByTestId("non-ascii")).toBeNull();
    expect(screen.queryByTestId("registry-parked-looks-same")).toBeNull();
  });
});
