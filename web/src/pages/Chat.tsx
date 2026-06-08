import { useCallback, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import ChatInput from "../components/chat/ChatInput";
import FeedbackBar from "../components/chat/FeedbackBar";
import MessageBubble from "../components/chat/MessageBubble";
import { useWebSocket } from "../hooks/useWebSocket";
import { useChatStore } from "../stores/chatStore";
import type { ChatMessage, ServerMessage } from "../types";

export default function Chat() {
  const { t } = useTranslation();
  const { spawnId } = useParams();
  const id = Number(spawnId);
  const {
    messages,
    streaming,
    streamingText,
    setHistory,
    addMessage,
    startStreaming,
    appendChunk,
    finalizeStreaming,
  } = useChatStore();

  const onMessage = useCallback(
    (raw: unknown) => {
      const msg = raw as ServerMessage;
      switch (msg.type) {
        case "history":
          setHistory(
            msg.messages.map((m) => ({
              id: m.message_id,
              role: m.role as ChatMessage["role"],
              content: m.content,
            })),
          );
          break;
        case "stream_start":
          startStreaming();
          break;
        case "stream_chunk":
          appendChunk(msg.content);
          break;
        case "stream_end":
          finalizeStreaming(msg.message_id);
          break;
        case "message":
          addMessage({
            id: msg.message_id,
            role: msg.role as ChatMessage["role"],
            content: msg.content,
          });
          break;
        default:
          break;
      }
    },
    [setHistory, startStreaming, appendChunk, finalizeStreaming, addMessage],
  );

  const { send, reconnecting } = useWebSocket(`/ws/chat/${id}`, onMessage);

  useEffect(() => {
    // Reset store when switching spawns.
    setHistory([]);
  }, [id, setHistory]);

  const sendFeedback = (messageId: number, action: "thumbs_up" | "thumbs_down") => {
    void api.sendFeedback(id, { message_id: messageId, user_action: action, edits: {} });
  };

  const editMessage = (messageId: number, current: string) => {
    const edited = window.prompt(t("chat.edit"), current);
    if (edited != null && edited !== current) {
      void api.sendFeedback(id, {
        message_id: messageId,
        user_action: "edit",
        edits: { content: edited },
      });
    }
  };

  return (
    <div className="flex h-[70vh] flex-col">
      <h1 className="mb-2 text-xl font-semibold">{t("chat.title", { name: id })}</h1>
      {reconnecting && <p className="mb-2 text-sm text-amber">{t("chat.reconnecting")}</p>}

      <div className="flex-1 space-y-3 overflow-y-auto pb-4">
        {messages.map((m) => (
          <MessageBubble key={m.id} message={m}>
            {m.role === "assistant" && (
              <FeedbackBar
                onFeedback={(action) => sendFeedback(m.id, action)}
                onEdit={() => editMessage(m.id, m.content)}
              />
            )}
          </MessageBubble>
        ))}
        {streaming && (
          <MessageBubble message={{ id: -1, role: "assistant", content: streamingText || "…" }} />
        )}
      </div>

      <ChatInput onSend={(text) => send({ type: "user_message", content: text })} />
    </div>
  );
}
