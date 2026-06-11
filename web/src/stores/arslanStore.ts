import { create } from "zustand";
import type { ArslanServerMessage, ArslanThreadItem, SuggestDraft, ToolStep } from "../types";

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
  suggestionOverlaps: import("../types").OverlapInfo | null;
  // spawn_meta frames can arrive BEFORE the stream_end that creates the item
  // (production order). Stash them here keyed by arslan_message_id and apply on
  // stream_end. Cleared per-key once applied.
  pendingSpawnMeta: Record<number, { assistant_message_id: number; task_brief: string }>;
  // Live tool-loop steps for the in-flight spawn turn, paired from
  // tool_call/tool_result frames; folded into the reply item on stream_end.
  activitySteps: ToolStep[];

  setSpawnNames: (map: Record<number, string>) => void;
  addUserMessage: (content: string) => void;
  handleFrame: (frame: ArslanServerMessage) => void;
  dismissSuggestion: () => void;
  clearError: () => void;
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
    suggestionOverlaps: null as import("../types").OverlapInfo | null,
    pendingSpawnMeta: {} as Record<number, { assistant_message_id: number; task_brief: string }>,
    activitySteps: [] as ToolStep[],
  };
}

type SetState = (partial: Partial<ArslanState>) => void;
type GetState = () => ArslanState;

function makeActions(set: SetState, get: GetState) {
  return {
    setSpawnNames: (map: Record<number, string>) =>
      set({ spawnNames: { ...get().spawnNames, ...map } }),

    addUserMessage: (content: string) =>
      set({
        items: [...get().items, { id: nextClientId(), kind: "message", role: "user", content }],
        pending: true,
      }),

    dismissSuggestion: () => set({ suggestion: null }),
    clearError: () => set({ error: null }),

    handleFrame: (frame: ArslanServerMessage) => {
      const state = get();
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
          set({ streamingText: state.streamingText + frame.content });
          break;
        case "stream_end": {
          if (!state.streaming) break;
          // A spawn_meta for this message may have arrived earlier (production
          // order). Apply it now and drop the stashed entry.
          const meta = state.pendingSpawnMeta[frame.message_id];
          const item: ArslanThreadItem = {
            id: frame.message_id,
            kind: "message",
            role: state.streamSource === "spawn" ? "spawn" : "arslan",
            content: state.streamingText,
            spawnId: state.streamSpawnId,
            spawnName: state.streamSpawnName,
            spawnMessageId: meta?.assistant_message_id ?? null,
            taskBrief: meta?.task_brief ?? null,
            toolSteps: state.activitySteps.length > 0 ? state.activitySteps : undefined,
          };
          const nextPendingSpawnMeta = { ...state.pendingSpawnMeta };
          delete nextPendingSpawnMeta[frame.message_id];
          set({
            items: [...state.items, item],
            streaming: false,
            streamingText: "",
            streamSource: null,
            streamSpawnId: null,
            streamSpawnName: null,
            pendingRoute: null,
            pendingSpawnMeta: nextPendingSpawnMeta,
            lastMessageId: Math.max(state.lastMessageId, frame.message_id),
            activitySteps: [],
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
              };
              break;
            }
          }
          set({ activitySteps: steps });
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
                  ? { ...it, spawnMessageId: frame.assistant_message_id, taskBrief: frame.task_brief }
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
