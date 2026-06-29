import { describe, it, expect, beforeEach } from "vitest";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";
import type { ArslanServerMessage, SuggestDraft } from "../api/client.types";

beforeEach(() => useArslanStore.setState(initialArslanState(), true));

describe("suggest_create draft carries equipment / gaps / seed_refs", () => {
  it("survives the new fields into the stored suggestion (typed, no `as any`)", () => {
    const store = () => useArslanStore.getState();

    // Typed frame — this is also a compile-time guard that SuggestDraft carries
    // tools/skills/mcps/gaps/seed_refs and that suggest_create accepts them.
    const frame: ArslanServerMessage = {
      type: "suggest_create",
      draft: {
        name: "Researcher",
        domain: "research",
        capabilities: ["search", "summarize"],
        persona_role: "analyst",
        persona_tone: "concise",
        reason: "needs web research",
        tools: ["web_search"],
        skills: ["deep-research"],
        mcps: ["github"],
        gaps: ["no notion access"],
        seed_refs: ["seed:researcher"],
      },
      task_brief: "research the market",
      overlaps: null,
    };

    store().handleFrame(frame);

    const s = store().suggestion;
    expect(s).not.toBeNull();
    const draft = s as SuggestDraft;
    expect(draft.tools).toEqual(["web_search"]);
    expect(draft.skills).toEqual(["deep-research"]);
    expect(draft.mcps).toEqual(["github"]);
    expect(draft.gaps).toEqual(["no notion access"]);
    expect(draft.seed_refs).toEqual(["seed:researcher"]);
    // existing fields still present
    expect(draft.name).toBe("Researcher");
    expect(draft.capabilities).toEqual(["search", "summarize"]);
    expect(store().suggestionTaskBrief).toBe("research the market");
  });

  it("accepts a propose_invite frame as a typed member of the server-message union", () => {
    // Compile-time check: this object must be assignable to ArslanServerMessage.
    const invite: ArslanServerMessage = {
      type: "propose_invite",
      spawn_id: 7,
      reason: "domain expert needed",
    };
    expect(invite.type).toBe("propose_invite");
    // store handling of propose_invite is F3's job — F1 only guarantees the type.
  });
});
