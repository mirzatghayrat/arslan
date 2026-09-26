import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import i18n, { SUPPORTED_LANGUAGES } from "../i18n";
import { designMessages } from "../locales/design";
import MemoryEditor from "../components/companion/MemoryEditor";
import StyleReferenceView from "../components/companion/StyleReferenceView";
import { companionApi, type Project } from "../api/companion";

vi.mock("../api/companion", () => ({ companionApi: { createMemory: vi.fn(async () => ({})), editMemory: vi.fn() } }));
const project: Project = { id: "p", name: "Project A", kind: "design", summary: "", workspace_ref: null,
  collection_ids: [], app_binding: null, version: 1, status: "active", updated_at: "2026-09-15T00:00:00Z" };
beforeEach(() => vi.clearAllMocks());
afterEach(() => { cleanup(); void i18n.changeLanguage("en"); });

it.each(SUPPORTED_LANGUAGES)("saves explicitly scoped evidence with translated controls in %s", async language => {
  await i18n.changeLanguage(language);
  const copy = designMessages[language];
  const saved = vi.fn();
  render(<MemoryEditor projects={[project]} onClose={vi.fn()} onSaved={saved} />);
  fireEvent.change(screen.getByLabelText(i18n.t("companion.content")), { target: { value: "Use blue headings" } });
  fireEvent.click(screen.getByLabelText(copy.addReference));
  expect(screen.getByLabelText(i18n.t("companion.scope"))).toHaveValue("project");
  fireEvent.change(screen.getByLabelText(i18n.t("companion.project")), { target: { value: "p" } });
  fireEvent.change(screen.getByLabelText(copy.sourceRef), { target: { value: "reference.png" } });
  fireEvent.change(screen.getByLabelText(copy.rationale), { target: { value: "Readable contrast" } });
  fireEvent.change(screen.getByLabelText(copy.polarity), { target: { value: "negative" } });
  expect(screen.getByLabelText(copy.interpretation)).toHaveValue("tentative");
  fireEvent.click(screen.getByRole("button", { name: i18n.t("companion.save") }));
  await waitFor(() => expect(saved).toHaveBeenCalled());
  expect(companionApi.createMemory).toHaveBeenCalledWith(expect.objectContaining({
    kind: "style_rule", scope: { kind: "project", id: "p" }, use_policy: "local_only",
    style_reference: { source_kind: "file", source_ref: "reference.png", rationale: "Readable contrast", polarity: "negative", interpretation: "tentative" },
  }));
});

it("shows source evidence as inert text, never a fetched image or executable link", async () => {
  await i18n.changeLanguage("en");
  const { container } = render(<StyleReferenceView reference={{ source_kind: "url", source_ref: "javascript:do_not_execute()",
    polarity: "negative", rationale: "Avoid this", interpretation: "tentative" }} />);
  expect(screen.getByText("javascript:do_not_execute()")).toBeInTheDocument();
  expect(container.querySelector("a,img,iframe")).toBeNull();
});

it("keeps the complete design dictionary in every language", () => {
  for (const language of SUPPORTED_LANGUAGES) {
    expect(Object.keys(designMessages[language]).sort()).toEqual(Object.keys(designMessages.en).sort());
    expect(Object.values(designMessages[language]).every(value => !!value.trim())).toBe(true);
  }
});
