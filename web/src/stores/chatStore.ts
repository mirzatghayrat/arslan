import { create } from "zustand";
import type { ChatMessage } from "../api/client.types";

interface ChatState {
  messages: ChatMessage[];
  streaming: boolean;
  streamingText: string;
  setHistory: (messages: ChatMessage[]) => void;
  addMessage: (message: ChatMessage) => void;
  startStreaming: () => void;
  appendChunk: (chunk: string) => void;
  finalizeStreaming: (id: number) => void;
}

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  streaming: false,
  streamingText: "",
  setHistory: (messages) => set({ messages }),
  addMessage: (message) => set({ messages: [...get().messages, message] }),
  startStreaming: () => set({ streaming: true, streamingText: "" }),
  appendChunk: (chunk) => set({ streamingText: get().streamingText + chunk }),
  finalizeStreaming: (id) =>
    set({
      streaming: false,
      streamingText: "",
      messages: [
        ...get().messages,
        { id, role: "assistant", content: get().streamingText },
      ],
    }),
}));
