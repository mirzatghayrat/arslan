import { useCallback, useEffect, useState } from "react";
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
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [spawnName, setSpawnName] = useState<string | null>(null);

  useEffect(() => {
    void api.getSpawn(id).then((s) => setSpawnName(s.name)).catch(() => setSpawnName(null));
  }, [id]);

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
        case "error":
          setErrorMsg(`${t("errors.server_error")}: ${msg.message}`);
          break;
        default:
          break;
      }
    },
    [setHistory, startStreaming, appendChunk, finalizeStreaming, addMessage, t],
  );

  const handleAuthFail = useCallback(() => setErrorMsg(t("errors.auth_failed")), [t]);

  const { send, reconnecting } = useWebSocket(`/ws/chat/${id}`, onMessage, {
    onAuthFail: handleAuthFail,
  });

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
      <h1 className="mb-2 text-xl font-semibold">{t("chat.title", { name: spawnName ?? id })}</h1>
      {errorMsg && (
        <div className="mb-3 flex items-center justify-between rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-2 text-sm text-red-300">
          <span>{errorMsg}</span>
          <button onClick={() => setErrorMsg(null)} className="text-red-300/70 hover:text-red-200">
            {t("errors.dismiss")}
          </button>
        </div>
      )}
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
