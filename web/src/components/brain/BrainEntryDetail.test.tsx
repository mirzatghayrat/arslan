import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/client", () => {
  class ApiError extends Error {
    status: number;
    constructor(m: string, s: number) { super(m); this.status = s; }
  }
  return { ApiError, api: { getBrainEntry: vi.fn(), undoSupersede: vi.fn() } };
});

import BrainEntryDetail from "./BrainEntryDetail";
import { api } from "../../api/client";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

const LEAF = (kind: string, ref: string) => ({
  kind, ref, label: "北京", provenance: null, confidence: null,
  usage_count: 0, last_used_at: null, last_used_ref: null, value: 1,
}) as never;

const ENTRY = (over: Record<string, unknown> = {}) => ({
  kind: "profile", ref: "fact:1", label: "北京", provenance: "identity · auto",
  confidence: 0.8, excerpt: "住在北京", usage_count: 3, last_used_at: null,
  last_used_ref: null, valid_from: null, superseded_by: null,
  provenance_record: null, ...over,
});

beforeEach(() => { vi.clearAllMocks(); m.getBrainEntry.mockResolvedValue(ENTRY()); });

describe("BrainEntryDetail", () => {
  it("🔴 offers undo ONLY when the entry is actually superseded", async () => {
    // The gate is superseded_by != null, NOT the kind. Gating on kind alone would put the
    // button on every active profile/learning entry, where the server answers 409
    // "already active" — an affordance whose only possible outcome is an error. A test
    // that just asserted "the button exists for a profile entry" would pass under that
    // bug, so both directions are asserted.
    render(<BrainEntryDetail leaf={LEAF("profile", "fact:1")} onClose={() => {}} />);
    await screen.findByText("住在北京");
    expect(screen.queryByTestId("undo-supersede")).toBeNull();

    m.getBrainEntry.mockResolvedValue(ENTRY({ superseded_by: 9 }));
    render(<BrainEntryDetail leaf={LEAF("profile", "fact:2")} onClose={() => {}} />);
    expect(await screen.findByTestId("undo-supersede")).toBeTruthy();
  });

  it("does not offer undo for material — the server refuses that kind outright", async () => {
    m.getBrainEntry.mockResolvedValue(ENTRY({ kind: "material", superseded_by: 9 }));
    render(<BrainEntryDetail leaf={LEAF("material", "material:coll:1:x.pdf")} onClose={() => {}} />);
    await screen.findByText("住在北京");
    expect(screen.queryByTestId("undo-supersede")).toBeNull();
  });

  it("🔴 refetches after a successful undo instead of leaving the panel frozen", async () => {
    // "I clicked and nothing moved" is the exact failure the evolution panel just shipped.
    // Asserting only that undoSupersede was called would pass with a frozen panel.
    m.getBrainEntry.mockResolvedValueOnce(ENTRY({ superseded_by: 9 }))
      .mockResolvedValue(ENTRY({ superseded_by: null }));
    m.undoSupersede.mockResolvedValue({ superseded_by: null });
    const onChanged = vi.fn();

    render(<BrainEntryDetail leaf={LEAF("profile", "fact:2")} onClose={() => {}} onChanged={onChanged} />);
    fireEvent.click(await screen.findByTestId("undo-supersede"));

    await waitFor(() => expect(m.undoSupersede).toHaveBeenCalledWith("profile", "fact:2"));
    // the panel must reflect the new state, and the rest of the view must be told
    await waitFor(() => expect(screen.queryByTestId("entry-superseded")).toBeNull());
    expect(onChanged).toHaveBeenCalled();
  });

  it("surfaces an undo failure instead of silently doing nothing", async () => {
    m.getBrainEntry.mockResolvedValue(ENTRY({ superseded_by: 9 }));
    m.undoSupersede.mockRejectedValue(new Error("409 already active"));
    render(<BrainEntryDetail leaf={LEAF("profile", "fact:2")} onClose={() => {}} />);
    fireEvent.click(await screen.findByTestId("undo-supersede"));
    expect((await screen.findByRole("alert")).textContent).toContain("409");
  });

  it("🔴 says a fact is stale, in BOTH directions", async () => {
    // A stale fact is still here in full — the backend just stopped injecting it
    // (memory.list_facts). Without this line the only visible effect of mark_stale is
    // that answers quietly stop mentioning something the graph still shows, which reads
    // as the model forgetting. The negative direction matters as much: a note on every
    // entry would make the mark meaningless.
    render(<BrainEntryDetail leaf={LEAF("profile", "fact:1")} onClose={() => {}} />);
    await screen.findByText("住在北京");
    expect(screen.queryByTestId("stale-note")).toBeNull();

    m.getBrainEntry.mockResolvedValue(ENTRY({ provenance_record: { stale: true } }));
    render(<BrainEntryDetail leaf={LEAF("profile", "fact:2")} onClose={() => {}} />);
    expect(await screen.findByTestId("stale-note")).toBeTruthy();
  });

  it("🔴 does not read stale off a provenance record that has no such key", async () => {
    // provenance_record is whatever JSON the row carries — a marked_at without stale, or
    // a non-object, must not light the note up.
    m.getBrainEntry.mockResolvedValue(
      ENTRY({ provenance_record: { source_kind: "manual", marked_at: "2026-01-01" } }));
    render(<BrainEntryDetail leaf={LEAF("profile", "fact:3")} onClose={() => {}} />);
    await screen.findByText("住在北京");
    expect(screen.queryByTestId("stale-note")).toBeNull();
  });

  it("🔴 marks sensitive WITHOUT claiming the content is withheld", async () => {
    // D2 established this is a rendering hint: the excerpt is still returned in full.
    // Copy that implied isolation would be a lie the payload itself contradicts.
    m.getBrainEntry.mockResolvedValue(ENTRY({ sensitive: true }));
    render(<BrainEntryDetail leaf={LEAF("profile", "fact:1")} onClose={() => {}} />);
    expect(await screen.findByTestId("entry-sensitive")).toBeTruthy();
    const note = screen.getByTestId("sensitive-note").textContent ?? "";
    expect(note).toContain("brain.sensitive_note");
    expect(screen.getByText("住在北京")).toBeTruthy();   // content IS still shown
  });

  it("translates the category half of the provenance line (S4.2-d stable keys)", async () => {
    // Server ships "identity · auto"; the UI must show the translated label for
    // the key half and keep the source half verbatim. i18n is uninitialised in
    // tests, so t() echoes the key: "brain.cat.identity · auto".
    m.getBrainEntry.mockResolvedValue(ENTRY({}));
    render(<BrainEntryDetail leaf={LEAF("profile", "fact:1")} onClose={() => {}} />);
    expect((await screen.findByText(/brain\.cat\.identity · auto/)).textContent
      ).toContain("brain.cat.identity · auto");
  });

  it("shows the audit provenance record, not just the legacy display string", async () => {
    m.getBrainEntry.mockResolvedValue(
      ENTRY({ provenance_record: { source_kind: "distill", source_ref: { conversation_id: "c1" } } }));
    render(<BrainEntryDetail leaf={LEAF("profile", "fact:1")} onClose={() => {}} />);
    const rec = await screen.findByTestId("provenance-record");
    expect(rec.textContent).toContain("distill");
  });

  it("🔴 a deleted entry says so instead of loading forever", async () => {
    // Reachable now: the activity strip is built from an event log that nothing purges
    // on delete, so a row can outlive its entity. Before this, both "still loading" and
    // "gone" were the same null state and the panel showed loading… indefinitely.
    const { ApiError } = await import("../../api/client");
    m.getBrainEntry.mockRejectedValue(
      new (ApiError as unknown as new (m: string, s: number) => Error)("not found", 404));
    render(<BrainEntryDetail leaf={LEAF("profile", "fact:404")} onClose={() => {}} />);
    expect((await screen.findByTestId("entry-load-error")).textContent).toContain("brain.entry_gone");
  });
});
