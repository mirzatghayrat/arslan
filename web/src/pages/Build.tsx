import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
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
  const location = useLocation();
  const draft = (location.state as { draft?: import("../types").SuggestDraft } | null)?.draft;
  const sessionId = useMemo(newSessionId, []);
  const [question, setQuestion] = useState<Extract<ServerMessage, { type: "question" }> | null>(
    null,
  );
  const [creating, setCreating] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

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
      } else if (msg.type === "error") {
        setErrorMsg(`${t("errors.server_error")}: ${msg.message}`);
      }
    },
    [navigate, t],
  );

  const handleAuthFail = useCallback(() => setErrorMsg(t("errors.auth_failed")), [t]);

  const { send, reconnecting } = useWebSocket(`/ws/build/${sessionId}`, onMessage, {
    onAuthFail: handleAuthFail,
  });

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="mb-2 text-2xl font-semibold">{t("build.title")}</h1>
      {draft && (
        <p className="mb-3 rounded-lg border border-amber/30 bg-amber/5 px-4 py-2 text-sm text-amber">
          {draft.name} · {draft.domain}
        </p>
      )}
      {errorMsg && (
        <div className="mb-3 flex items-center justify-between rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-2 text-sm text-red-300">
          <span>{errorMsg}</span>
          <button onClick={() => setErrorMsg(null)} className="text-red-300/70 hover:text-red-200">
            {t("errors.dismiss")}
          </button>
        </div>
      )}
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
