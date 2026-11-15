import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import i18n from "../i18n";
import MemoryEditor from "../components/companion/MemoryEditor";
import type { MemoryEntry } from "../api/companion";

vi.mock("../api/companion", () => ({ companionApi: { createMemory: vi.fn(), editMemory: vi.fn() } }));
afterEach(() => cleanup());

const scopeOptions = () => Array.from((screen.getByLabelText(i18n.t("companion.scope")) as HTMLSelectElement).options)
  .map(option => ({ value: option.value, disabled: option.disabled }));

it("C7c-4: a new memory cannot be put in an expert's own scope", async () => {
  await i18n.changeLanguage("en");
  render(<MemoryEditor projects={[]} onClose={vi.fn()} onSaved={vi.fn()} />);
  expect(scopeOptions().map(option => option.value)).toEqual(["global", "project", "domain"]);
});

it("C7c-4: an old expert-scope entry shows its scope, but it cannot be chosen again", async () => {
  await i18n.changeLanguage("en");
  const entry = { id: "e1", version: 1, content: "Old expert note", kind: "preference",
    scope: { kind: "expert", id: "3" }, sensitivity: "normal", use_policy: "local_only", status: "quarantined" } as unknown as MemoryEntry;
  render(<MemoryEditor entry={entry} projects={[]} onClose={vi.fn()} onSaved={vi.fn()} />);
  expect(screen.getByLabelText(i18n.t("companion.scope"))).toHaveValue("expert");
  expect(scopeOptions()).toContainEqual({ value: "expert", disabled: true });
  expect(screen.queryByLabelText(i18n.t("companion.scopeId"))).toBeNull();
});
