import { describe, expect, it } from "vitest";
import i18n from "../i18n";

describe("i18n", () => {
  it("resolves an english key", () => {
    expect(i18n.t("app.name")).toBe("Arslan");
  });
  it("interpolates variables", () => {
    expect(i18n.t("build.step", { current: 2, total: 5 })).toBe("Step 2 of 5");
  });
  it("has all six languages loaded", () => {
    for (const lng of ["en", "zh", "ja", "es", "de", "fr"]) {
      expect(i18n.hasResourceBundle(lng, "translation")).toBe(true);
    }
  });
});
