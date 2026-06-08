import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import StepIndicator from "../components/build/StepIndicator";
import QuestionView from "../components/build/QuestionView";
import { useWebSocket } from "../hooks/useWebSocket";
import type { ServerMessage } from "../types";

function newSessionId(): string {
  return `build-${Date.now()}-${Math.floor(Math.random() * 1e6)}`;
}

export default function Build() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const sessionId = useMemo(newSessionId, []);
  const [question, setQuestion] = useState<Extract<ServerMessage, { type: "question" }> | null>(
    null,
  );
  const [creating, setCreating] = useState(false);

  const onMessage = useCallback(
    (raw: unknown) => {
      const msg = raw as ServerMessage;
      if (msg.type === "question") {
        setQuestion(msg);
      } else if (msg.type === "progress") {
        // Step indicator updates from the next question's node_id.
      } else if (msg.type === "build_complete") {
        setCreating(true);
        navigate(`/chat/${msg.spawn_id}`);
      }
    },
    [navigate],
  );

  const { send, reconnecting } = useWebSocket(`/ws/build/${sessionId}`, onMessage);

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="mb-2 text-2xl font-semibold">{t("build.title")}</h1>
      {reconnecting && <p className="mb-2 text-sm text-amber">{t("build.reconnecting")}</p>}
      {question && <StepIndicator activeNode={question.node_id} />}

      {creating ? (
        <p className="text-white/60">{t("build.creating")}</p>
      ) : question ? (
        <QuestionView
          key={question.node_id}
          text={question.text}
          options={question.options}
          multiSelect={question.multi_select}
          hint={question.hint}
          onSubmit={(answer) => send({ type: "user_message", content: answer })}
        />
      ) : (
        <p className="text-white/50">…</p>
      )}
    </div>
  );
}
