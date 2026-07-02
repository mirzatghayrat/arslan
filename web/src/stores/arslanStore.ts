import { create } from "zustand";
import type { ArslanServerMessage, ArslanThreadItem, SuggestDraft, ToolStep, OverlapInfo, RosterMember, StaffingCandidate, SpawnUpdateChanges, SpawnUpdateCurrent } from "../api/client.types";

interface ArslanState {
  items: ArslanThreadItem[];
  streaming: boolean;
  streamingText: string;
  streamSource: "arslan" | "spawn" | null;
  streamSpawnId: number | null;
  streamSpawnName: string | null;
  pendingRoute: { spawnId: number; spawnName: string | null } | null;
  suggestion: SuggestDraft | null;
  spawnNames: Record<number, string>;
  error: string | null;
  lastMessageId: number;
  pending: boolean;
  suggestionTaskBrief: string | null;
  suggestionOverlaps: OverlapInfo | null;
  // spawn_meta frames can arrive BEFORE the stream_end that creates the item
  // (production order). Stash them here keyed by arslan_message_id and apply on
  // stream_end. Cleared per-key once applied.
  pendingSpawnMeta: Record<number, { assistant_message_id: number; task_brief: string; run_id?: number }>;
  // Live tool-loop steps for the in-flight spawn turn, paired from
  // tool_call/tool_result frames; folded into the reply item on stream_end.
  activitySteps: ToolStep[];
  // Pending proposal: when a `proposal` frame arrives, the next spawn deliverable
  // created at stream_end for that spawn_id should be flagged isProposal: true.
  pendingProposalSpawnId: number | null;
  // Active conversation roster: spawns currently joined to this conversation thread.
  roster: RosterMember[];
  // Pending invite: set when a `propose_invite` frame arrives; cleared once the
  // user confirms (sends roster_invite) or cancels.
  pendingInvite: { spawnId: number; reason: string } | null;
  // Pending staffing decision: set when a `propose_staffing` frame arrives.
  // Candidates are mapped snake→camel. Cleared once the user picks or dismisses.
  pendingStaffing: { candidates: { spawnId: number; name: string | null; score: number; why: string }[]; createDraft: SuggestDraft | null } | null;
  // Pending conversational spawn edit: set by a `suggest_update` frame; cleared on
  // confirm (sends confirm_update) or dismiss. Applied ONLY by the backend on confirm.
  pendingUpdate: { spawnId: number; spawnName: string; current: SpawnUpdateCurrent; changes: SpawnUpdateChanges; reason?: string } | null;
  // True from the moment the user sends a message until the first response frame arrives.
  thinking: boolean;

  setSpawnNames: (map: Record<number, string>) => void;
  setThinking: (v: boolean) => void;
  addUserMessage: (content: string) => void;
  handleFrame: (frame: ArslanServerMessage) => void;
  dismissSuggestion: () => void;
  dismissUpdate: () => void;
  markProposalConfirmed: (spawnId: number) => void;
  clearPendingInvite: () => void;
  clearPendingStaffing: () => void;
  clearError: () => void;
  resetForNewConversation: () => void;
}

// Negative, decrementing ids for client-only items (user echoes, fact chips)
// so they never collide with server message ids.
let clientSeq = -1;
const nextClientId = () => clientSeq--;

// Data-only initial state. Actions are attached separately and merged in so a
// `setState(initialArslanState(), true)` full-replace (used by tests) keeps the
// action methods intact.
function initialData() {
  return {
    items: [] as ArslanThreadItem[],
    streaming: false,
    streamingText: "",
    streamSource: null as "arslan" | "spawn" | null,
    streamSpawnId: null as number | null,
    streamSpawnName: null as string | null,
    pendingRoute: null as { spawnId: number; spawnName: string | null } | null,
    suggestion: null as SuggestDraft | null,
    spawnNames: {} as Record<number, string>,
    error: null as string | null,
    lastMessageId: 0,
    pending: false,
    suggestionTaskBrief: null as string | null,
    suggestionOverlaps: null as OverlapInfo | null,
    pendingSpawnMeta: {} as Record<number, { assistant_message_id: number; task_brief: string; run_id?: number }>,
    activitySteps: [] as ToolStep[],
    pendingProposalSpawnId: null as number | null,
    roster: [] as RosterMember[],
    pendingInvite: null as { spawnId: number; reason: string } | null,
    pendingStaffing: null as { candidates: { spawnId: number; name: string | null; score: number; why: string }[]; createDraft: SuggestDraft | null } | null,
    pendingUpdate: null as { spawnId: number; spawnName: string; current: SpawnUpdateCurrent; changes: SpawnUpdateChanges; reason?: string } | null,
    thinking: false,
  };
}

type SetState = (partial: Partial<ArslanState>) => void;
type GetState = () => ArslanState;

function makeActions(set: SetState, get: GetState) {
  return {
    setThinking: (v: boolean) => set({ thinking: v }),

    setSpawnNames: (map: Record<number, string>) =>
      set({ spawnNames: { ...get().spawnNames, ...map } }),

    addUserMessage: (content: string) =>
      set({
        items: [...get().items, { id: nextClientId(), kind: "message", role: "user", content }],
        pending: true,
      }),

    dismissSuggestion: () => set({ suggestion: null, suggestionTaskBrief: null, suggestionOverlaps: null }),
    dismissUpdate: () => set({ pendingUpdate: null }),
    // One-shot confirm (doom-loop guard, frontend half): flipping isProposal off disables the
    // confirm button immediately so a stale re-click can never re-fire execute_confirmed.
    markProposalConfirmed: (spawnId: number) =>
      set({
        items: get().items.map((it) =>
          it.isProposal && Number(it.spawnId) === spawnId ? { ...it, isProposal: false } : it),
      }),
    clearPendingInvite: () => set({ pendingInvite: null }),
    clearPendingStaffing: () => set({ pendingStaffing: null }),
    clearError: () => set({ error: null }),

    // Clear all conversation state so the incoming `history` frame for the new
    // conversation_id repopulates from scratch with no stale carry-over.
    resetForNewConversation: () => set({ ...initialData() }),

    handleFrame: (frame: ArslanServerMessage) => {
      const state = get();
      // Clear thinking on the first frame that signals Arslan is responding with
      // real content or a card. Intermediate dispatch frames ("routing",
      // "roster_event", "spawn_meta") are NOT included here — they fire during
      // the Arslan→spawn handoff before the spawn has streamed anything, so
      // clearing thinking on them creates a dead-air gap. Instead, thinking
      // persists through routing/dispatch and clears in stream_chunk (first real
      // token) or on card frames below.
      // NOTE: "stream_start" is intentionally excluded — it starts streaming but
      // delivers no content yet. Slow models (e.g. Gemini 2.5 Pro) have a long
      // delay between stream_start and the first token, so we keep the thinking
      // indicator alive until stream_chunk (first real content) clears it.
      const RESPONDING_TYPES = new Set(["suggest_create", "message", "error", "fact_saved", "proposal", "propose_invite", "propose_staffing", "suggest_update", "spawn_updated"]);
      if (RESPONDING_TYPES.has(frame.type)) {
        set({ thinking: false });
      }
      // Maps a server row (history row or `message` frame — same field names,
      // `spawn_id` optional) to a renderable thread item, resolving spawn names.
      const rowToItem = (row: {
        message_id: number;
        role: string;
        content: string;
        spawn_id?: number | null;
      }): ArslanThreadItem => {
        if (row.role === "spawn_summary") {
          // Resolve the spawn name ONLY from an explicit spawn_id. History rows
          // always carry one; the resume `message` frame does not (server
          // contract), in which case spawnId/spawnName degrade to null and the
          // bubble falls back to the conversation title. Never guess from the
          // roster.
          const spawnId = row.spawn_id ?? null;
          return {
            id: row.message_id,
            kind: "message",
            role: "spawn",
            content: row.content,
            spawnId,
            spawnName: spawnId != null ? state.spawnNames[spawnId] ?? null : null,
          };
        }
        return {
          id: row.message_id,
          kind: "message",
          role: row.role === "arslan" ? "arslan" : "user",
          content: row.content,
        };
      };
      switch (frame.type) {
        case "history": {
          const items: ArslanThreadItem[] = frame.messages.map(rowToItem);
          const lastId = items.reduce((max, it) => (it.id > max ? it.id : max), 0);
          set({ items, lastMessageId: lastId, activitySteps: [] });
          break;
        }
        case "message": {
          set({
            items: [...state.items, rowToItem(frame)],
            lastMessageId: Math.max(state.lastMessageId, frame.message_id),
          });
          break;
        }
        case "proposal":
          // Mark the spawn's next deliverable as a proposal. Cleared in stream_end.
          set({ pendingProposalSpawnId: frame.spawn_id });
          break;
        case "routing":
          set({
            pendingRoute: { spawnId: frame.spawn_id, spawnName: frame.spawn_name },
            spawnNames: frame.spawn_name
              ? { ...state.spawnNames, [frame.spawn_id]: frame.spawn_name }
              : state.spawnNames,
          });
          break;
        case "stream_start":
          set({
            pending: false,
            streaming: true,
            streamingText: "",
            streamSource: frame.source,
            streamSpawnId:
              frame.source === "spawn"
                ? state.pendingRoute?.spawnId ?? frame.spawn_id ?? null
                : null,
            streamSpawnName: frame.source === "spawn" ? state.pendingRoute?.spawnName ?? null : null,
          });
          break;
        case "stream_chunk":
          if (!state.streaming) break;
          // First real content arrived — clear thinking so the indicator hands
          // off seamlessly to the streaming bubble (no blank gap).
          set({ thinking: false, streamingText: state.streamingText + frame.content });
          break;
        case "stream_end": {
          if (!state.streaming) break;
          // A refused escalation ends the stream without persisting a message:
          // the server sends message_id: null and no reply text. With nothing
          // to show, just reset the streaming state — appending an item would
          // create a ghost entry with a null id (duplicate React keys).
          const hasContent = state.streamingText.length > 0;
          const hasSteps = state.activitySteps.length > 0;
          if (frame.message_id == null && !hasContent && !hasSteps) {
            set({
              thinking: false,
              streaming: false,
              streamingText: "",
              streamSource: null,
              streamSpawnId: null,
              streamSpawnName: null,
              pendingRoute: null,
              activitySteps: [],
              pendingProposalSpawnId: null,
            });
            break;
          }
          // A spawn_meta for this message may have arrived earlier (production
          // order). Apply it now and drop the stashed entry.
          const meta = frame.message_id != null ? state.pendingSpawnMeta[frame.message_id] : undefined;
          // If a proposal was pending for this spawn, mark the item as a proposal.
          const isProposal =
            state.streamSource === "spawn" &&
            state.pendingProposalSpawnId != null &&
            state.pendingProposalSpawnId === state.streamSpawnId;
          const item: ArslanThreadItem = {
            id: frame.message_id ?? nextClientId(),
            kind: "message",
            role: state.streamSource === "spawn" ? "spawn" : "arslan",
            content: state.streamingText,
            spawnId: state.streamSpawnId,
            spawnName: state.streamSpawnName,
            spawnMessageId: meta?.assistant_message_id ?? null,
            runId: meta?.run_id ?? null,
            taskBrief: meta?.task_brief ?? null,
            toolSteps: state.activitySteps.length > 0 ? state.activitySteps : undefined,
            ...(isProposal ? { isProposal: true } : {}),
          };
          const nextPendingSpawnMeta = { ...state.pendingSpawnMeta };
          if (frame.message_id != null) delete nextPendingSpawnMeta[frame.message_id];
          set({
            thinking: false,
            items: [...state.items, item],
            streaming: false,
            streamingText: "",
            streamSource: null,
            streamSpawnId: null,
            streamSpawnName: null,
            pendingRoute: null,
            pendingSpawnMeta: nextPendingSpawnMeta,
            lastMessageId:
              frame.message_id != null ? Math.max(state.lastMessageId, frame.message_id) : state.lastMessageId,
            activitySteps: [],
            // Clear the proposal flag once consumed
            pendingProposalSpawnId: isProposal ? null : state.pendingProposalSpawnId,
          });
          break;
        }
        case "tool_call":
          set({
            activitySteps: [
              ...state.activitySteps,
              { tool: frame.tool, argsSummary: frame.args_summary, status: "running" },
            ],
          });
          break;
        case "tool_result": {
          // The loop is sequential per tool: resolve the most recent unresolved
          // step with the same tool name.
          const steps = [...state.activitySteps];
          for (let i = steps.length - 1; i >= 0; i--) {
            if (steps[i].tool === frame.tool && steps[i].status === "running") {
              steps[i] = {
                ...steps[i],
                status: frame.ok ? "ok" : "error",
                resultSummary: frame.summary,
                // 🔒 SECURITY: artifactSvg / artifactChart / artifactPptx come ONLY from the backend
                // render_chart/render_deck tool_result frame's artifact, NEVER from LLM message text.
                ...(frame.artifact?.kind === "svg" ? { artifactSvg: frame.artifact.content } : {}),
                ...(frame.artifact?.kind === "echarts" ? { artifactChart: frame.artifact.spec } : {}),
                ...(frame.artifact?.kind === "pptx" ? { artifactPptx: {
                  filename: frame.artifact.filename ?? "deck.pptx",
                  bytesB64: frame.artifact.bytes_b64 ?? "",
                  slides: frame.artifact.slides ?? 0,
                } } : {}),
              };
              break;
            }
          }
          set({ activitySteps: steps, thinking: true });
          break;
        }
        case "suggest_create":
          set({
            pending: false,
            suggestion: frame.draft,
            suggestionTaskBrief: frame.task_brief ?? null,
            suggestionOverlaps: frame.overlaps ?? null,
          });
          break;
        case "spawn_meta": {
          // Production order is spawn_meta BEFORE stream_end, so the target item
          // usually doesn't exist yet — stash it for stream_end to apply. If the
          // item already exists (defensive / reverse order), attach directly.
          const exists = state.items.some((it) => it.id === frame.arslan_message_id);
          if (exists) {
            set({
              items: state.items.map((it) =>
                it.id === frame.arslan_message_id
                  ? { ...it, spawnMessageId: frame.assistant_message_id, taskBrief: frame.task_brief, runId: frame.run_id ?? null }
                  : it,
              ),
            });
          } else {
            set({
              pendingSpawnMeta: {
                ...state.pendingSpawnMeta,
                [frame.arslan_message_id]: {
                  assistant_message_id: frame.assistant_message_id,
                  task_brief: frame.task_brief,
                  run_id: frame.run_id,
                },
              },
            });
          }
          break;
        }
        case "fact_saved":
          set({
            items: [
              ...state.items,
              {
                id: nextClientId(),
                kind: "fact",
                role: "arslan",
                content: frame.content,
                sensitive: frame.sensitive,
              },
            ],
          });
          break;
        case "suggest_update":
          set({
            pending: false,
            pendingUpdate: {
              spawnId: frame.spawn_id,
              spawnName: frame.spawn_name,
              current: frame.current,
              changes: frame.changes,
              reason: frame.reason,
            },
          });
          break;
        case "spawn_updated":
          set({
            pendingUpdate: null,
            items: [
              ...state.items,
              {
                id: nextClientId(),
                kind: "system",
                role: "arslan",
                content: `__SPAWN_UPDATED__:${frame.spawn_name}`,
                equipment: frame.equipment ?? null,
              },
            ],
          });
          break;
        case "spawn_created":
          set({
            suggestion: null,
            suggestionTaskBrief: null,
            suggestionOverlaps: null,
            spawnNames: { ...state.spawnNames, [frame.spawn_id]: frame.spawn_name },
            items: [
              ...state.items,
              {
                id: nextClientId(),
                kind: "system",
                role: "arslan",
                content: `__SPAWN_CREATED__:${frame.spawn_name}`,
                equipment: frame.equipment ?? null,
                intro: frame.intro ?? null,
              },
            ],
          });
          break;
        case "escalation":
          set({
            items: [
              ...state.items,
              {
                id: nextClientId(),
                kind: "escalation",
                role: "spawn",
                content: "",
                spawnId: frame.spawn_id,
                spawnName: frame.spawn_name,
                escalation: {
                  spawnId: frame.spawn_id,
                  spawnName: frame.spawn_name,
                  kind: frame.kind,
                  need: frame.need,
                  status: "resolving",
                },
              },
            ],
          });
          break;
        case "escalation_resolved":
        case "escalation_refused": {
          // Update the most recent still-resolving escalation for this spawn.
          const items = [...state.items];
          for (let i = items.length - 1; i >= 0; i--) {
            const esc = items[i].escalation;
            if (esc && esc.spawnId === frame.spawn_id && esc.status === "resolving") {
              items[i] = {
                ...items[i],
                escalation:
                  frame.type === "escalation_resolved"
                    ? { ...esc, status: "resolved", how: frame.how, detail: frame.detail }
                    : { ...esc, status: "refused", why: frame.why },
              };
              break;
            }
          }
          set({ items });
          break;
        }
        case "verdict_recorded": {
          // Mark the most recent spawn deliverable (role==='spawn', !isProposal) for
          // this spawn_id with the verdict action so the UI can show confirmed state.
          const items = [...state.items];
          for (let i = items.length - 1; i >= 0; i--) {
            const it = items[i];
            if (it.role === "spawn" && !it.isProposal && it.spawnId === frame.spawn_id) {
              items[i] = { ...it, verdict: frame.action };
              break;
            }
          }
          set({ items });
          break;
        }
        case "deliverable_finalized": {
          // A refined spawn deliverable, posted back from the side chat into the
          // main thread. Append as a spawn item; the verdict_recorded that follows
          // marks it accepted via the existing case.
          const item: ArslanThreadItem = {
            id: frame.message_id ?? nextClientId(),
            kind: "message",
            role: "spawn",
            content: frame.content,
            spawnId: frame.spawn_id,
            spawnName: frame.spawn_name ?? state.spawnNames[frame.spawn_id] ?? null,
            refinedFrom: frame.refined_from ?? null,
          };
          set({
            items: [...state.items, item],
            lastMessageId:
              frame.message_id != null ? Math.max(state.lastMessageId, frame.message_id) : state.lastMessageId,
          });
          break;
        }
        case "roster_update":
          set({
            roster: frame.members.map((m) => ({
              spawnId: m.spawn_id,
              spawnName: m.spawn_name,
              joinedVia: m.joined_via,
              status: m.status,
            })),
          });
          break;
        case "propose_invite":
          set({ pendingInvite: { spawnId: frame.spawn_id, reason: frame.reason } });
          break;
        case "propose_staffing":
          set({
            pendingStaffing: {
              candidates: frame.candidates.map((c: StaffingCandidate) => ({
                spawnId: c.spawn_id,
                name: c.name,
                score: c.score,
                why: c.why,
              })),
              createDraft: frame.create_draft,
            },
          });
          break;
        case "roster_event":
          set({
            items: [
              ...state.items,
              {
                id: nextClientId(),
                kind: "system",
                role: "arslan",
                content: "",
                spawnId: frame.spawn_id,
                spawnName: frame.spawn_name,
                rosterAction: frame.action,
              },
            ],
          });
          break;
        case "attachment_stored":
          set({
            items: [
              ...state.items,
              {
                id: nextClientId(),
                kind: "system",
                role: "arslan",
                content: `📎 已记入 ${frame.spawn_name ?? "知识库"} 的知识库 · ${frame.chunks} 块`,
                spawnName: frame.spawn_name,
              },
            ],
          });
          break;
        case "error":
          set({
            error: frame.message,
            pending: false,
            streaming: false,
            streamingText: "",
            streamSource: null,
            streamSpawnId: null,
            streamSpawnName: null,
            pendingRoute: null,
            activitySteps: [],
          });
          break;
        default:
          break;
      }
    },
  };
}

export const useArslanStore = create<ArslanState>((set, get) => ({
  ...initialData(),
  ...makeActions(set, get),
}));

// Returns a full state object (data + actions) so it can be used with
// `setState(initialArslanState(), true)` without dropping the action methods.
export function initialArslanState(): ArslanState {
  return {
    ...initialData(),
    ...makeActions(
      (partial) => useArslanStore.setState(partial),
      () => useArslanStore.getState(),
    ),
  };
}
