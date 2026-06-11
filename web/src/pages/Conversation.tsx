import { useCallback, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import ChatInput from "../components/chat/ChatInput";
import ConversationBubble from "../components/arslan/ConversationBubble";
import ArslanMark from "../components/brand/ArslanMark";
import ErrorBoundary from "../components/layout/ErrorBoundary";
import CreateSpawnCard from "../components/arslan/CreateSpawnCard";
import SpawnFeedbackBar from "../components/arslan/SpawnFeedbackBar";
import ThinkingIndicator from "../components/arslan/ThinkingIndicator";
import ToolActivityFrame from "../components/arslan/ToolActivityFrame";
import { useWebSocket } from "../hooks/useWebSocket";
import { useArslanStore } from "../stores/arslanStore";
import type { ArslanServerMessage, ArslanThreadItem, SuggestDraft } from "../types";

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
    pending,
    pendingRoute,
    suggestionTaskBrief,
    suggestionOverlaps,
    activitySteps,
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

  const confirmCreate = (d: SuggestDraft, differentiation?: string) => {
    send({ type: "confirm_create", draft: d, task_brief: suggestionTaskBrief ?? "", differentiation });
    dismissSuggestion();
  };
  const refineDraft = (instruction: string) =>
    send({ type: "refine_draft", description: instruction, previous_draft: suggestion });
  const routeToExisting = (spawnId: number) => {
    send({ type: "route_to", spawn_id: spawnId, task_brief: suggestionTaskBrief ?? "" });
    dismissSuggestion();
  };
  const sendFeedback = (spawnId: number, messageId: number | null | undefined, action: string) =>
    void api.sendFeedback(spawnId, { message_id: messageId ?? undefined, user_action: action, edits: {} });
  const redo = (it: ArslanThreadItem) =>
    it.spawnId && send({ type: "redo", spawn_id: it.spawnId, message_id: it.spawnMessageId, task_brief: it.taskBrief ?? "" });
  const tweak = (it: ArslanThreadItem, instruction: string) =>
    it.spawnId && send({ type: "refine", spawn_id: it.spawnId, message_id: it.spawnMessageId, task_brief: it.taskBrief ?? "", instruction });

  const renderError = (
    <div className="flex justify-center">
      <span className="rounded-full border border-red-500/40 bg-red-500/10 px-3 py-1 text-xs text-red-300">
        {t("errors.render_failed")}
      </span>
    </div>
  );

  return (
    <div className="flex h-[75vh] flex-col">
      <h1 className="mb-2 flex items-center gap-2 text-xl font-semibold">
        <ArslanMark className="h-6 w-6 text-brand" /> {t("conversation.title")}
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
          // Per-item boundary: a single malformed turn degrades to an inline
          // notice instead of white-screening the whole app.
          <ErrorBoundary key={it.id} fallback={renderError}>
            <div>
              {it.toolSteps && <ToolActivityFrame steps={it.toolSteps} />}
              <ConversationBubble item={it}>
                {it.role === "spawn" && it.kind === "message" && (
                  <SpawnFeedbackBar
                    onThumbUp={() => { sendFeedback(it.spawnId!, it.spawnMessageId, "thumbs_up"); }}
                    onThumbDown={() => { sendFeedback(it.spawnId!, it.spawnMessageId, "thumbs_down"); }}
                    onRedo={() => { sendFeedback(it.spawnId!, it.spawnMessageId, "redo"); redo(it); }}
                    onTweak={() => { const v = window.prompt(t("create_card.refine_placeholder")); if (v) { sendFeedback(it.spawnId!, it.spawnMessageId, "refine"); tweak(it, v); } }}
                  />
                )}
              </ConversationBubble>
            </div>
          </ErrorBoundary>
        ))}
        {activitySteps.length > 0 && <ToolActivityFrame steps={activitySteps} live />}
        {pending && !streaming && (
          <ThinkingIndicator spawnName={pendingRoute?.spawnName ?? null} />
        )}
        {streaming && (
          <ConversationBubble
            live
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
          <ErrorBoundary fallback={renderError}>
            <CreateSpawnCard
              draft={suggestion}
              overlaps={suggestionOverlaps}
              onCreate={confirmCreate}
              onDismiss={dismissSuggestion}
              onRefine={refineDraft}
              onRouteToExisting={routeToExisting}
            />
          </ErrorBoundary>
        )}
      </div>

      <ChatInput onSend={sendMessage} placeholder={t("conversation.placeholder")} />
    </div>
  );
}
