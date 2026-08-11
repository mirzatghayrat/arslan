/**
 * The Settings notice for providers that cannot call tools.
 *
 * These assert what is ON SCREEN, not that the component exists or that a
 * string appears in a file. That distinction is the whole point here: the defect
 * being fixed is a silent one, and a warning that never renders looks exactly
 * like a provider that works. A source-level assertion would stay green through
 * the entire failure.
 *
 * Every case is two-sided. A notice stuck ON is as broken as one stuck OFF — it
 * trains people to ignore it, which is how the next real warning gets missed.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import en from "../locales/en.json";

// The house pattern mocks `t` to echo the key back. Not here: the words ARE the
// deliverable for this component, and echoing keys would let it ship with empty
// or wrong copy while every assertion below still passed. So the real shipped
// English resolves through the mock, and a deleted or blanked key throws.
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

import ToolTransportWarning from "../components/settings/ToolTransportWarning";
import {
  TOOL_TRANSPORT,
  needsToolTransportNotice,
  toolTransportState,
} from "../lib/toolTransport";

describe("toolTransportState", () => {
  it("reports the measured-broken provider as unsupported", () => {
    // Anthropic was here until G1 put tool schemas on its wire. Gemini still
    // builds no `tools`, so it is what this notice is now for.
    expect(toolTransportState("gemini")).toBe("unsupported");
  });

  it("reports Anthropic as supported now that G1 landed", () => {
    // The user-visible consequence of G1, asserted rather than assumed: the
    // provider that was the headline case for this warning must no longer be one.
    expect(toolTransportState("anthropic")).toBe("supported");
  });

  it("reports the OpenAI-compatible family as supported", () => {
    for (const p of ["openai", "custom", "ollama", "deepseek"]) {
      expect(toolTransportState(p), p).toBe("supported");
    }
  });

  it("treats an unknown provider as unverified, not as fine", () => {
    // The failure this area exists to correct began with assuming an unmeasured
    // path worked. A new provider must not inherit a green light.
    expect(toolTransportState("some-new-provider")).toBe("unverified");
    expect(toolTransportState("")).toBe("unverified");
    expect(toolTransportState(null)).toBe("unverified");
    expect(toolTransportState(undefined)).toBe("unverified");
  });

  it("is not fooled by casing or stray whitespace from a stored config", () => {
    expect(toolTransportState("  Gemini ")).toBe("unsupported");
    expect(toolTransportState("GEMINI")).toBe("unsupported");
    expect(toolTransportState(" Anthropic ")).toBe("supported");
  });

  it("asks for a notice on everything except a measured-good provider", () => {
    expect(needsToolTransportNotice("gemini")).toBe(true);
    expect(needsToolTransportNotice("whatever")).toBe(true);
    expect(needsToolTransportNotice("openai")).toBe(false);
    expect(needsToolTransportNotice("anthropic")).toBe(false);
  });
});

describe("<ToolTransportWarning>", () => {
  it("warns, in words, when Gemini is selected", () => {
    render(<ToolTransportWarning provider="gemini" />);
    const el = screen.getByTestId("tool-transport-warning");

    expect(el.dataset.state).toBe("unsupported");
    // The text has to actually say what will not happen. Asserting only that a
    // box appeared would pass on an empty box.
    expect(el.textContent).toMatch(/tool/i);
    expect(el.textContent).toMatch(/MCP/);
  });

  it("renders NOTHING for Anthropic now that G1 landed", () => {
    // This is what G1 looks like from the user's chair. The warning was correct
    // when it shipped and would be a lie now; a notice that outlives its defect
    // is the same failure as one that never appeared, pointed the other way.
    render(<ToolTransportWarning provider="anthropic" />);
    expect(screen.queryByTestId("tool-transport-warning")).toBeNull();
  });

  it("renders NOTHING for a provider whose tools work", () => {
    // The other side. A permanent banner on OpenAI would be noise, and noise is
    // how a real warning stops being read.
    render(<ToolTransportWarning provider="openai" />);
    expect(screen.queryByTestId("tool-transport-warning")).toBeNull();
  });

  it("says so quietly when nobody has measured the provider", () => {
    render(<ToolTransportWarning provider="brand-new-thing" />);
    const el = screen.getByTestId("tool-transport-warning");

    expect(el.dataset.state).toBe("unverified");
    // Distinguishable from the hard warning, so "unmeasured" cannot be read as
    // "broken" or as "fine".
    expect(el.textContent).not.toMatch(/MCP/);
  });

  it("does not claim skills are dead, because they are not", () => {
    // Skills never enter _native_tool_schemas, so the broken transport does not
    // carry them. Saying "skills will not run" would be untrue — and untrue in
    // the cautious direction is still untrue.
    render(<ToolTransportWarning provider="gemini" />);
    const text = screen.getByTestId("tool-transport-warning").textContent ?? "";

    expect(text).toMatch(/skill/i);
    expect(text).not.toMatch(/skills (are|will be) (inert|disabled)/i);
    expect(text).not.toMatch(/skills will not (run|work)/i);
  });

  it("announces as status rather than interrupting as an alert", () => {
    // The notice describes a standing property of the selection, not an event;
    // role="alert" would cut a screen reader off on every change of the select.
    render(<ToolTransportWarning provider="gemini" />);
    expect(screen.getByTestId("tool-transport-warning").getAttribute("role")).toBe("status");
  });

  it("covers every provider in the table with a defined verdict", () => {
    for (const [p, expected] of Object.entries(TOOL_TRANSPORT)) {
      expect(toolTransportState(p), p).toBe(expected);
    }
  });
});

describe("locale coverage", () => {
  const KEYS = [
    "tool_transport_title",
    "tool_transport_unsupported",
    "tool_transport_unverified",
  ] as const;

  it("ships all three strings in all six languages, none blank", async () => {
    // A warning that exists only in English is a silent failure for everyone
    // else — the same class of bug as having no warning at all.
    for (const lang of ["de", "en", "es", "fr", "ja", "zh"]) {
      const mod = await import(`../locales/${lang}.json`);
      const settings = (mod.default as Record<string, Record<string, string>>).settings;
      for (const k of KEYS) {
        expect(typeof settings[k], `${lang}.${k}`).toBe("string");
        expect(settings[k].trim().length, `${lang}.${k}`).toBeGreaterThan(0);
      }
    }
  });

  it("mentions MCP in every language, since that is half of what dies", async () => {
    for (const lang of ["de", "en", "es", "fr", "ja", "zh"]) {
      const mod = await import(`../locales/${lang}.json`);
      const text = (mod.default as Record<string, Record<string, string>>).settings
        .tool_transport_unsupported;
      expect(text, lang).toMatch(/MCP/);
    }
  });
});
