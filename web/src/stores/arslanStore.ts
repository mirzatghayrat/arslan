import { create } from "zustand";
import type { ArslanServerMessage, ArslanThreadItem, SuggestDraft } from "../types";

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
      }),

    dismissSuggestion: () => set({ suggestion: null }),
    clearError: () => set({ error: null }),

    handleFrame: (frame: ArslanServerMessage) => {
      const state = get();
      switch (frame.type) {
        case "history": {
          const items: ArslanThreadItem[] = frame.messages.map((m) => {
            if (m.role === "spawn_summary") {
              return {
                id: m.message_id,
                kind: "message",
                role: "spawn",
                content: m.content,
                spawnId: m.spawn_id,
                spawnName: m.spawn_id != null ? state.spawnNames[m.spawn_id] ?? null : null,
              };
            }
            return {
              id: m.message_id,
              kind: "message",
              role: m.role === "arslan" ? "arslan" : "user",
              content: m.content,
            };
          });
          const lastId = items.reduce((max, it) => (it.id > max ? it.id : max), 0);
          set({ items, lastMessageId: lastId });
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
          const item: ArslanThreadItem = {
            id: frame.message_id,
            kind: "message",
            role: state.streamSource === "spawn" ? "spawn" : "arslan",
            content: state.streamingText,
            spawnId: state.streamSpawnId,
            spawnName: state.streamSpawnName,
          };
          set({
            items: [...state.items, item],
            streaming: false,
            streamingText: "",
            streamSource: null,
            streamSpawnId: null,
            streamSpawnName: null,
            pendingRoute: null,
            lastMessageId: Math.max(state.lastMessageId, frame.message_id),
          });
          break;
        }
        case "suggest_create":
          set({ suggestion: frame.draft });
          break;
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
            spawnNames: { ...state.spawnNames, [frame.spawn_id]: frame.spawn_name },
          });
          break;
        case "error":
          set({
            error: frame.message,
            streaming: false,
            streamingText: "",
            streamSource: null,
            streamSpawnId: null,
            streamSpawnName: null,
            pendingRoute: null,
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
