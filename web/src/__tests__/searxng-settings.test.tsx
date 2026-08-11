/**
 * The SearXNG address field and its connection test.
 *
 * These assert what is ON SCREEN and what reaches the network, never that a string
 * exists in a file. A field that never renders and a button whose handler is never
 * wired both look exactly like working code from the source — this project has
 * shipped "a prop nobody passed" before, and 1150 green tests did not catch it.
 *
 * The four verdicts get four assertions because the four fixes differ. A test that
 * only checked "some message appeared" would pass against a single generic string,
 * which is the failure this whole feature exists to avoid.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import en from "../locales/en.json";

// The words ARE the deliverable here, so the real shipped English resolves through
// the mock and a blank or deleted key throws instead of silently rendering nothing.
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => {
      const hit = key.split(".").reduce<unknown>(
        (node, part) =>
          node && typeof node === "object" ? (node as Record<string, unknown>)[part] : undefined,
        en as unknown,
      );
      if (typeof hit !== "string" || !hit.trim()) throw new Error(`missing locale string: ${key}`);
      return hit;
    },
  }),
}));

const testSearchInstance = vi.fn();
vi.mock("../api/client", () => ({
  testSearchInstance: (...args: unknown[]) => testSearchInstance(...args),
}));

import SearchToolsSection from "../components/settings/SearchToolsSection";

const base = {
  searchProvider: "searxng",
  searchProviders: ["duckduckgo", "tavily", "searxng"],
  onSearchProviderChange: () => {},
  searchKey: "",
  onSearchKeyChange: () => {},
  githubToken: "",
  onGithubTokenChange: () => {},
  searchBaseUrl: "",
  onSearchBaseUrlChange: () => {},
};

beforeEach(() => {
  testSearchInstance.mockReset();
});

describe("the address field", () => {
  it("appears when SearXNG is the selected provider", () => {
    render(<SearchToolsSection {...base} />);
    expect(screen.getByTestId("searxng-base-url")).toBeTruthy();
  });

  it("is absent for a provider with a fixed destination", () => {
    // Rendering it for Tavily would invite someone to type an address that is
    // read by nothing — a control that looks live and is inert.
    render(<SearchToolsSection {...base} searchProvider="tavily" />);
    expect(screen.queryByTestId("searxng-base-url")).toBeNull();
  });

  it("reports what the user typed", async () => {
    const onChange = vi.fn();
    render(<SearchToolsSection {...base} onSearchBaseUrlChange={onChange} />);
    await userEvent.type(screen.getByTestId("searxng-base-url"), "http://a");
    expect(onChange).toHaveBeenCalled();
  });
});

describe("the connection test", () => {
  const clickTest = async () => {
    await userEvent.click(screen.getByTestId("searxng-test-button"));
  };

  it("sends the address the user typed", async () => {
    testSearchInstance.mockResolvedValue({ verdict: "ok", result_count: 3 });
    render(<SearchToolsSection {...base} searchBaseUrl="http://192.168.1.10:8080" />);
    await clickTest();
    await waitFor(() =>
      expect(testSearchInstance).toHaveBeenCalledWith({ base_url: "http://192.168.1.10:8080" }),
    );
  });

  it("renders a DIFFERENT message for each of the four verdicts", async () => {
    const seen = new Set<string>();
    for (const verdict of ["unreachable", "not_searxng", "json_disabled", "ok"]) {
      testSearchInstance.mockResolvedValue({ verdict, result_count: 0 });
      const { unmount } = render(
        <SearchToolsSection {...base} searchBaseUrl="http://x" />,
      );
      await clickTest();
      const el = await screen.findByTestId("searxng-test-result");
      const text = (el.textContent ?? "").trim();
      expect(text.length, verdict).toBeGreaterThan(0);
      seen.add(text);
      unmount();
    }
    expect(seen.size, "the four verdicts must not share wording").toBe(4);
  });

  it("names settings.yml and search.formats when json is disabled", async () => {
    // The most common failure, and the one most easily misread as a typo. A generic
    // message here sends the user to re-check an address that was never wrong.
    testSearchInstance.mockResolvedValue({ verdict: "json_disabled" });
    render(<SearchToolsSection {...base} searchBaseUrl="http://x" />);
    await clickTest();
    const text = (await screen.findByTestId("searxng-test-result")).textContent ?? "";
    expect(text).toMatch(/settings\.yml/);
    expect(text).toMatch(/search\.formats/);
  });

  it("says how many results came back when the instance works", async () => {
    testSearchInstance.mockResolvedValue({ verdict: "ok", result_count: 7 });
    render(<SearchToolsSection {...base} searchBaseUrl="http://x" />);
    await clickTest();
    const text = (await screen.findByTestId("searxng-test-result")).textContent ?? "";
    expect(text).toMatch(/7/);
  });

  it("surfaces a thrown request as a failure rather than a blank box", async () => {
    // A rejected promise must not leave the button spinning with nothing said.
    testSearchInstance.mockRejectedValue(new Error("network down"));
    render(<SearchToolsSection {...base} searchBaseUrl="http://x" />);
    await clickTest();
    const el = await screen.findByTestId("searxng-test-result");
    expect((el.textContent ?? "").trim().length).toBeGreaterThan(0);
  });

  it("does not call the endpoint with a blank address", async () => {
    render(<SearchToolsSection {...base} searchBaseUrl="   " />);
    await clickTest();
    expect(testSearchInstance).not.toHaveBeenCalled();
  });
});

describe("locale coverage", () => {
  const KEYS = [
    "labelSearchBaseUrl",
    "searxngTestButton",
    "searxngVerdictUnreachable",
    "searxngVerdictNotSearxng",
    "searxngVerdictJsonDisabled",
    "searxngVerdictOk",
  ] as const;

  it("ships every string in all six languages, none blank", async () => {
    for (const lang of ["de", "en", "es", "fr", "ja", "zh"]) {
      const mod = await import(`../locales/${lang}.json`);
      const settings = (mod.default as Record<string, Record<string, string>>).settings;
      for (const k of KEYS) {
        expect(typeof settings[k], `${lang}.${k}`).toBe("string");
        expect(settings[k].trim().length, `${lang}.${k}`).toBeGreaterThan(0);
      }
    }
  });

  it("names settings.yml in every language, since that is the actual fix", async () => {
    // A translated message that drops the filename leaves non-English users with
    // "something is wrong" — the exact state this verdict exists to end.
    for (const lang of ["de", "en", "es", "fr", "ja", "zh"]) {
      const mod = await import(`../locales/${lang}.json`);
      const text = (mod.default as Record<string, Record<string, string>>).settings
        .searxngVerdictJsonDisabled;
      expect(text, lang).toMatch(/settings\.yml/);
    }
  });
});


describe("the wiring from backend to screen and back", () => {
  // 🔴 A prop the host never passes is a feature nobody has. This repo shipped
  // exactly that once and 1150 green tests said nothing — the defect was found by
  // looking at the running app. These assertions walk the whole chain instead.

  it("carries search_base_url from the backend payload into UI settings", async () => {
    const { toUiSettings } = await import("../api/adapters");
    const ui = toUiSettings({ search_base_url: "http://192.168.1.10:8080" } as never);
    expect((ui as Record<string, unknown>).searchBaseUrl).toBe("http://192.168.1.10:8080");
  });

  it("sends searchBaseUrl back out on save", async () => {
    const { toBackendSettings } = await import("../api/adapters");
    const body = toBackendSettings({ searchBaseUrl: "http://a:8080" } as never);
    expect((body as Record<string, unknown>).search_base_url).toBe("http://a:8080");
  });

  it("passes the value and both handlers down from SettingsScreen", async () => {
    // Reading the call site is the only way to see an omitted prop: a missing one
    // is not a type error when the prop is optional, and nothing renders wrong
    // until a user types into a field that saves nowhere.
    const src = await import("../components/SettingsScreen?raw");
    const text = (src.default as string);
    const call = text.slice(text.indexOf("<SearchToolsSection"));
    const block = call.slice(0, call.indexOf("/>"));
    expect(block).toMatch(/searchBaseUrl=/);
    expect(block).toMatch(/onSearchBaseUrlChange=/);
  });
});
