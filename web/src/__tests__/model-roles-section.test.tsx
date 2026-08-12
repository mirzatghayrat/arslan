/**
 * The model-roles section — asserted as RENDERED TEXT, not as i18n keys.
 *
 * A key that exists while no component renders it looks exactly like one that was
 * never written, and this project has shipped a prop nobody passed while 1150 tests
 * stayed green. So every assertion here reads the screen.
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import en from "../locales/en.json";

// The words are the deliverable, so the real shipped English resolves through the
// mock and a blank or missing key throws instead of quietly rendering nothing.
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => {
      const hit = key.split(".").reduce<unknown>(
        (n, p) => (n && typeof n === "object" ? (n as Record<string, unknown>)[p] : undefined),
        en as unknown,
      );
      if (typeof hit !== "string" || !hit.trim()) throw new Error(`missing locale string: ${key}`);
      return hit;
    },
  }),
}));

import ModelRolesSection from "../components/settings/ModelRolesSection";
import { MODEL_SLOTS } from "../lib/modelSlots";

const cfg = (id: number, label: string, primary = false) => ({
  id,
  label,
  provider: "deepseek",
  model: "deepseek-chat",
  is_primary: primary,
});

const base = {
  values: {},
  onChange: () => {},
  providerConfigs: [cfg(1, "Main", true), cfg(2, "Cheap")],
  strategy: "single",
};

describe("the five dropdowns", () => {
  it("renders one per slot", () => {
    render(<ModelRolesSection {...base} />);
    for (const s of MODEL_SLOTS) {
      expect(screen.getByTestId(`slot-${s.id}`), s.id).toBeTruthy();
    }
  });

  it("renders a NON-EMPTY purpose line for every slot", () => {
    // Ruling ④, and the criterion that pins it. Five unexplained dropdowns pass
    // every other test in this file.
    render(<ModelRolesSection {...base} />);
    for (const s of MODEL_SLOTS) {
      const el = screen.getByTestId(`slot-purpose-${s.id}`);
      expect((el.textContent ?? "").trim().length, s.id).toBeGreaterThan(0);
    }
  });

  it("gives the five purposes five DIFFERENT texts", () => {
    // One sentence reused five times is not an explanation; it would pass a
    // non-empty check while telling the user nothing.
    render(<ModelRolesSection {...base} />);
    const texts = MODEL_SLOTS.map((s) =>
      (screen.getByTestId(`slot-purpose-${s.id}`).textContent ?? "").trim(),
    );
    expect(new Set(texts).size).toBe(5);
  });
});

describe("the empty-slot sentence is true", () => {
  it("says the router is pinned, not following", () => {
    render(<ModelRolesSection {...base} strategy="balanced" />);
    const el = screen.getByTestId("slot-fallback-router");
    expect(el.dataset.kind).toBe("pinned-primary");
    expect(el.textContent).toMatch(/Main/);
  });

  it("says synthesis follows the conversation", () => {
    render(<ModelRolesSection {...base} />);
    expect(screen.getByTestId("slot-fallback-synthesis").dataset.kind).toBe(
      "follows-conversation",
    );
  });

  it("gives router and synthesis different sentences from the routable three", () => {
    render(<ModelRolesSection {...base} />);
    const text = (id: string) =>
      (screen.getByTestId(`slot-fallback-${id}`).textContent ?? "").trim();
    expect(text("router")).not.toBe(text("title"));
    expect(text("synthesis")).not.toBe(text("title"));
    expect(text("router")).not.toBe(text("synthesis"));
  });

  it("mentions the image condition on the vision slot", () => {
    // Without it, someone who sets a vision model expects every turn to use it and
    // reads the unchanged behaviour as the setting not working.
    render(<ModelRolesSection {...base} />);
    const text = screen.getByTestId("slot-purpose-vision").textContent ?? "";
    expect(text).toMatch(/image/i);
  });

  it("says 'assigned by the routing strategy' WITHOUT naming the primary", () => {
    // Naming the primary here re-implies "the primary is doing the work", which is
    // exactly what this wording exists to stop implying.
    render(<ModelRolesSection {...base} strategy="balanced" />);
    const el = screen.getByTestId("slot-fallback-title");
    expect(el.dataset.kind).toBe("routed");
    expect(el.textContent).not.toMatch(/Main/);
  });

  it("still follows the primary with ONE config under a routing strategy", () => {
    render(
      <ModelRolesSection {...base} strategy="balanced" providerConfigs={[cfg(1, "Main", true)]} />,
    );
    const el = screen.getByTestId("slot-fallback-title");
    expect(el.dataset.kind).toBe("follows-primary");
    expect(el.textContent).toMatch(/Main/);
  });
});

describe("nothing configured yet", () => {
  it("points at the provider section instead of rendering empty brackets", () => {
    render(<ModelRolesSection {...base} providerConfigs={[]} />);
    const el = screen.getByTestId("slot-fallback-title");
    expect(el.dataset.kind).toBe("no-configs");
    expect(el.textContent).not.toMatch(/\(\s*\)/);
  });

  it("offers a way OUT of the dead end, and it works", () => {
    // 🔴 Found by running the app, not by these tests. The link is rendered only
    // when a handler is supplied, and SettingsScreen supplied none — so the
    // section said "no models configured yet" and gave the user nowhere to go.
    // The earlier version of this describe asserted the sentence and stopped
    // there, which is why half a feature shipped.
    const go = vi.fn();
    render(<ModelRolesSection {...base} providerConfigs={[]} onGoToProviders={go} />);
    const link = screen.getByTestId("slot-goto-providers");
    expect((link.textContent ?? "").trim().length).toBeGreaterThan(0);
    link.click();
    expect(go).toHaveBeenCalled();
  });

  it("does not offer the link once models exist", () => {
    // The other side: a permanent "add a model" link beside a configured slot is
    // noise, and noise is how a real prompt stops being read.
    render(<ModelRolesSection {...base} onGoToProviders={() => {}} />);
    expect(screen.queryByTestId("slot-goto-providers")).toBeNull();
  });
});

describe("the embedding pointer", () => {
  it("names the section embeddings actually live in", () => {
    // Without this line the new section silently has a sixth slot the user cannot
    // see, and the promise was one screen showing which model does what.
    render(<ModelRolesSection {...base} />);
    const el = screen.getByTestId("embedding-pointer");
    expect((el.textContent ?? "").trim().length).toBeGreaterThan(0);
  });
});

describe("locale coverage", () => {
  it("ships every slot label and purpose in all six languages, none blank", async () => {
    for (const lang of ["de", "en", "es", "fr", "ja", "zh"]) {
      const mod = await import(`../locales/${lang}.json`);
      const settings = (mod.default as Record<string, Record<string, string>>).settings;
      for (const s of MODEL_SLOTS) {
        for (const key of [s.labelKey, s.purposeKey]) {
          const leaf = key.replace(/^settings\./, "");
          expect(typeof settings[leaf], `${lang}.${key}`).toBe("string");
          expect(settings[leaf].trim().length, `${lang}.${key}`).toBeGreaterThan(0);
        }
      }
    }
  });

  it("ships the fallback sentences and the pointer in all six languages", async () => {
    const KEYS = [
      "slotFallbackPinnedPrimary",
      "slotFallbackFollowsPrimary",
      "slotFallbackRouted",
      "slotFallbackFollowsConversation",
      "slotFallbackNoConfigs",
      "modelRolesEmbeddingPointer",
      "modelRolesLede",
      "slotUnset",
      "slotGoToProviders",
      "navModelRoles",
    ];
    for (const lang of ["de", "en", "es", "fr", "ja", "zh"]) {
      const mod = await import(`../locales/${lang}.json`);
      const settings = (mod.default as Record<string, Record<string, string>>).settings;
      for (const k of KEYS) {
        expect(typeof settings[k], `${lang}.${k}`).toBe("string");
        expect(settings[k].trim().length, `${lang}.${k}`).toBeGreaterThan(0);
      }
    }
  });

  it("keeps the {model} placeholder in the two sentences that name a model", async () => {
    // A translation that drops it renders "follows your main model ." with the name
    // silently gone — which is the empty-bracket failure in another shape.
    for (const lang of ["de", "en", "es", "fr", "ja", "zh"]) {
      const mod = await import(`../locales/${lang}.json`);
      const settings = (mod.default as Record<string, Record<string, string>>).settings;
      for (const k of ["slotFallbackPinnedPrimary", "slotFallbackFollowsPrimary"]) {
        expect(settings[k], `${lang}.${k}`).toMatch(/\{model\}/);
      }
    }
  });
});


describe("the section is wired into Settings", () => {
  it("registers a nav entry", async () => {
    const { SETTINGS_SECTIONS } = await import("../components/settings/sectionRegistry");
    expect(SETTINGS_SECTIONS.some((s) => s.id === "modelroles")).toBe(true);
  });

  it("gives every slot a home in FIELD_HOMES", async () => {
    // A section with no fields behind it is exactly what the deleted `scheduled`
    // and `usage` placeholder tabs were, and the existing field-homes guard fails
    // on one. Five entries, one per slot.
    const { FIELD_HOMES } = await import("../components/settings/sectionRegistry");
    const homed = Object.entries(FIELD_HOMES).filter(([, v]) => v === "modelroles");
    expect(homed).toHaveLength(5);
  });

  it("is rendered by SettingsScreen with values, a handler, configs and the strategy", async () => {
    // Reading the call site is the only way to see an omitted prop: with optional
    // props a missing one is not a type error, and nothing looks wrong until a user
    // changes a dropdown that saves nowhere.
    const src = await import("../components/SettingsScreen?raw");
    const block = (src.default as string).split("<ModelRolesSection")[1]?.split("/>")[0] ?? "";

    // 🔴 DERIVED, NOT ENUMERATED. The hand-written version listed four props and
    // the fifth — onGoToProviders — was the one nobody passed, so the "no models
    // configured" state had no way out and this test said nothing. A hand list is
    // the thing that rots: the same lesson as the macOS marker round, where a
    // hand-maintained file list quietly stopped covering new files.
    //
    // The required set comes from the component's own prop type, so a prop added
    // there and not passed here fails without anyone remembering to edit a list.
    const propsSrc = await import("../components/settings/ModelRolesSection?raw");
    const iface = (propsSrc.default as string)
      .split("export interface ModelRolesSectionProps")[1]
      .split("}")[0];
    const required = [...iface.matchAll(/^\s*(\w+)\??:/gm)].map((m) => m[1]);
    expect(required.length, "the prop interface could not be parsed").toBeGreaterThanOrEqual(5);

    const missing = required.filter((prop) => !new RegExp(`\\b${prop}=`).test(block));
    expect(missing, `SettingsScreen never passes: ${missing.join(", ")}`).toEqual([]);
  });
});
