/**
 * The Settings notice that says WHY stored secrets cannot be read.
 *
 * This replaces a single hard-coded sentence. `settings.keyUndecryptableReason` used
 * to say the key could not be decrypted "because ARSLAN_SECRET_KEY changed" — and in
 * the incident that produced this whole change, ARSLAN_SECRET_KEY had not changed.
 * The salt had. A specific, credible, WRONG cause costs more than no cause, because
 * the reader goes and solves a different problem; that is where a month went.
 *
 * So the backend computes a verdict and the frontend localizes it. Two properties
 * matter here and both are asserted:
 *
 *   1. Distinct verdicts produce DISTINCT words. A component that renders the same
 *      paragraph for every state would pass a "it rendered something" test while
 *      reintroducing exactly the defect being fixed.
 *   2. No copy, in any language, names ARSLAN_SECRET_KEY as the cause of a salt
 *      problem. That is asserted as an ABSENCE over the locale files, which is the
 *      one thing a source-level check is right for.
 *
 * The mock resolves the REAL shipped English, not echoed keys: the words are the
 * deliverable here, and echoing keys would let it ship with empty or wrong copy
 * while every assertion below still passed.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import en from "../locales/en.json";

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

import CryptoHealthNotice from "../components/settings/CryptoHealthNotice";
import { VERDICT_COPY_KEY, type CryptoHealth } from "../lib/cryptoHealth";

const LANGS = ["de", "en", "es", "fr", "ja", "zh"] as const;

const health = (over: Partial<CryptoHealth>): CryptoHealth => ({
  verdict: "healthy",
  undecryptable: 0,
  recoverable: 0,
  salt_provenance: "database",
  ...over,
});

describe("<CryptoHealthNotice>", () => {
  it("renders nothing when everything is readable", () => {
    // The other side. A permanent banner would be noise, and noise is how a real
    // warning stops being read.
    render(<CryptoHealthNotice health={health({ verdict: "healthy" })} />);
    expect(screen.queryByTestId("crypto-health-notice")).toBeNull();
  });

  it("renders nothing before the diagnosis has arrived", () => {
    // null = not fetched yet. Guessing a verdict while loading would show a scary
    // message on every cold start of a perfectly healthy install.
    render(<CryptoHealthNotice health={null} />);
    expect(screen.queryByTestId("crypto-health-notice")).toBeNull();
  });

  it("blames the salt, not the secret, when the salt was lost", () => {
    // 🔴 THE case. This is the exact scenario the old sentence got backwards.
    render(<CryptoHealthNotice health={health({ verdict: "salt-lost", undecryptable: 2 })} />);
    const el = screen.getByTestId("crypto-health-notice");

    expect(el.dataset.verdict).toBe("salt-lost");
    expect(el.textContent).toMatch(/salt/i);
    expect(el.textContent).not.toMatch(/ARSLAN_SECRET_KEY/);
  });

  it("names the secret only when the secret really is the missing half", () => {
    render(<CryptoHealthNotice health={health({ verdict: "secret-missing", undecryptable: 1 })} />);
    const el = screen.getByTestId("crypto-health-notice");

    expect(el.dataset.verdict).toBe("secret-missing");
    expect(el.textContent).toMatch(/ARSLAN_SECRET_KEY/);
  });

  it("says a way back exists when something is recoverable", () => {
    render(
      <CryptoHealthNotice health={health({ verdict: "recoverable", undecryptable: 1, recoverable: 1 })} />,
    );
    const el = screen.getByTestId("crypto-health-notice");

    expect(el.dataset.verdict).toBe("recoverable");
    expect(el.textContent).toMatch(/recover/i);
  });

  it("gives every verdict its own words", () => {
    // The property that makes the whole thing worth having. If two verdicts render
    // the same paragraph, the diagnosis is decoration.
    const seen = new Map<string, string>();
    for (const verdict of ["secret-missing", "recoverable", "salt-lost", "secret-does-not-match"] as const) {
      cleanup();   // each iteration renders fresh; without this getByTestId sees them all
      render(<CryptoHealthNotice health={health({ verdict, undecryptable: 1 })} />);
      const text = screen.getByTestId("crypto-health-notice").textContent ?? "";
      for (const [other, otherText] of seen) {
        expect(text, `${verdict} reads identically to ${other}`).not.toBe(otherText);
      }
      seen.set(verdict, text);
    }
    expect(seen.size).toBe(4);
  });

  it("tells the user how many values are affected", () => {
    render(<CryptoHealthNotice health={health({ verdict: "salt-lost", undecryptable: 3 })} />);
    expect(screen.getByTestId("crypto-health-notice").textContent).toContain("3");
  });

  it("announces as status rather than interrupting as an alert", () => {
    render(<CryptoHealthNotice health={health({ verdict: "salt-lost", undecryptable: 1 })} />);
    expect(screen.getByTestId("crypto-health-notice").getAttribute("role")).toBe("status");
  });
});

describe("locale coverage", () => {
  it("ships every verdict string in all six languages, none blank", async () => {
    for (const lang of LANGS) {
      const mod = await import(`../locales/${lang}.json`);
      const settings = (mod.default as Record<string, Record<string, string>>).settings;
      for (const verdict of Object.keys(VERDICT_COPY_KEY)) {
        if (verdict === "healthy") continue;
        const k = VERDICT_COPY_KEY[verdict as keyof typeof VERDICT_COPY_KEY];
        expect(typeof settings[k], `${lang}.${k}`).toBe("string");
        expect(settings[k].trim().length, `${lang}.${k}`).toBeGreaterThan(0);
      }
      expect(settings.cryptoHealthTitle?.trim().length, `${lang}.cryptoHealthTitle`).toBeGreaterThan(0);
    }
  });

  it("no language still blames ARSLAN_SECRET_KEY for a salt problem", async () => {
    // Asserting an ABSENCE, which is the case where reading the source is correct:
    // a sentence that is gone has no behaviour left to observe. The old copy lives
    // at settings.keyUndecryptableReason; it may still exist, but it must no longer
    // assert a cause it cannot know.
    for (const lang of LANGS) {
      const mod = await import(`../locales/${lang}.json`);
      const settings = (mod.default as Record<string, Record<string, string>>).settings;
      const reason = settings.keyUndecryptableReason ?? "";
      expect(reason, `${lang} still names the wrong cause`).not.toMatch(/ARSLAN_SECRET_KEY/);
      // And the salt-lost verdict must not blame the secret either.
      expect(settings[VERDICT_COPY_KEY["salt-lost"]], lang).not.toMatch(/ARSLAN_SECRET_KEY/);
    }
  });
});


describe("it is actually wired into the settings section", () => {
  /**
   * 🔴 The `containment` lesson, applied. server/mcp/catalog.py grew a `containment`
   * field, shipped it on the API, and NOTHING ever rendered it — adding the piece is
   * free, wiring it is the whole job. So this asserts the notice reaches the screen
   * through SearchToolsSection, not merely that the component can render alone.
   */
  it("shows the diagnosis inside Search & Tools", async () => {
    const { default: SearchToolsSection } = await import(
      "../components/settings/SearchToolsSection"
    );

    cleanup();
    render(
      <SearchToolsSection
        cryptoHealth={health({ verdict: "salt-lost", undecryptable: 1 })}
        searchProvider="tavily"
        searchProviders={["tavily"]}
        onSearchProviderChange={() => {}}
        searchKey=""
        onSearchKeyChange={() => {}}
        githubToken=""
        onGithubTokenChange={() => {}}
      />,
    );

    expect(screen.getByTestId("crypto-health-notice").dataset.verdict).toBe("salt-lost");
  });

  it("shows nothing there when the diagnosis is absent", async () => {
    const { default: SearchToolsSection } = await import(
      "../components/settings/SearchToolsSection"
    );

    cleanup();
    render(
      <SearchToolsSection
        searchProvider="tavily"
        searchProviders={["tavily"]}
        onSearchProviderChange={() => {}}
        searchKey=""
        onSearchKeyChange={() => {}}
        githubToken=""
        onGithubTokenChange={() => {}}
      />,
    );

    expect(screen.queryByTestId("crypto-health-notice")).toBeNull();
  });
});
