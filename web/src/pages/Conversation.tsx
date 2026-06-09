import { useCallback, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import ChatInput from "../components/chat/ChatInput";
import ConversationBubble from "../components/arslan/ConversationBubble";
import CreateSpawnCard from "../components/arslan/CreateSpawnCard";
import { useWebSocket } from "../hooks/useWebSocket";
import { useArslanStore } from "../stores/arslanStore";
import type { ArslanServerMessage, SuggestDraft } from "../types";

const CONVERSATION_ID = "main";

export default function Conversation() {
  const { t } = useTranslation();
  const {
    items,
    streaming,
    streamingText,
    streamSource,
    streamSpawnName,
    suggestion,
    error,
    setSpawnNames,
    addUserMessage,
    handleFrame,
    dismissSuggestion,
    clearError,
  } = useArslanStore();

  // Resolve spawn names for history captions (history frame carries only spawn_id).
  useEffect(() => {
    void api.listSpawns().then((spawns) => {
      setSpawnNames(Object.fromEntries(spawns.map((s) => [s.id, s.name])));
    });
  }, [setSpawnNames]);

  const onMessage = useCallback(
    (raw: unknown) => handleFrame(raw as ArslanServerMessage),
    [handleFrame],
  );

  const { send, reconnecting } = useWebSocket(`/ws/arslan/${CONVERSATION_ID}`, onMessage);

  const sendMessage = (text: string) => {
    addUserMessage(text);
    send({ type: "user_message", content: text });
  };

  const confirmCreate = (draft: SuggestDraft) => {
    send({ type: "confirm_create", draft });
    dismissSuggestion();
  };

  return (
    <div className="flex h-[75vh] flex-col">
      <h1 className="mb-2 flex items-center gap-2 text-xl font-semibold">
        <span aria-hidden>🐆</span> {t("conversation.title")}
      </h1>

      {error && (
        <div className="mb-3 flex items-center justify-between rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-2 text-sm text-red-300">
          <span>{error}</span>
          <button onClick={clearError} className="text-red-300/70 hover:text-red-200">
            {t("errors.dismiss")}
          </button>
        </div>
      )}
      {reconnecting && <p className="mb-2 text-sm text-amber">{t("conversation.reconnecting")}</p>}

      <div className="flex-1 space-y-3 overflow-y-auto pb-4">
        {items.length === 0 && !streaming && (
          <p className="text-center text-white/40">{t("conversation.empty")}</p>
        )}
        {items.map((it) => (
          <ConversationBubble key={it.id} item={it} />
        ))}
        {streaming && (
          <ConversationBubble
            item={{
              id: -999999,
              kind: "message",
              role: streamSource === "spawn" ? "spawn" : "arslan",
              content: streamingText || "…",
              spawnName: streamSpawnName,
            }}
          />
        )}
        {suggestion && (
          <CreateSpawnCard draft={suggestion} onCreate={confirmCreate} onDismiss={dismissSuggestion} />
        )}
      </div>

      <ChatInput onSend={sendMessage} placeholder={t("conversation.placeholder")} />
    </div>
  );
}
