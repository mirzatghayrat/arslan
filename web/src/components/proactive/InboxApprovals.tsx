import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { request } from "../../api/client";
import AskForFrame, { ANSWERABLE, type AnswerExtra, type PendingAsk } from "../AskForFrame";
import { AnswerGuardScope, AskQueue, Notice, useAnswerGuardState } from "../kit";
import { announceProactiveChange } from "../../api/proactive";

const POLL_MS = 5_000;

/** A call id is one entry in the queue (it keys the card and what has been typed or picked on it): the first of a card listed twice stays. */
function onePerCallId(rows: PendingAsk[]): PendingAsk[] {
  const seen = new Set<string>();
  return rows.filter((r) => {
    if (typeof r.call_id !== "string" || !r.call_id || seen.has(r.call_id)) return false;
    seen.add(r.call_id);
    return true;
  });
}

/**
 * "现在就要你批准" (0.1.55 §12): every card waiting for the user, from any conversation
 * or background job, answerable right here — with the same choices as in the chat (0.1.61 §A4).
 * Polls while visible; fails quietly (a broken list must not hide the rest of the Inbox).
 * Returns null when nothing waits. A call id is one entry: a card listed twice is one card.
 */
export default function InboxApprovals({ onOpenConversation, onCount }: {
  onOpenConversation: (conversationId: string) => void;
  onCount?: (n: number) => void;
}) {
  const { t } = useTranslation();
  const [asks, setAsks] = useState<PendingAsk[]>([]);
  const [error, setError] = useState(false);
  // The guard is kept here, above the queue, which is not on screen while nothing waits: the next command of the turn can come up
  // a moment after the last card was answered, and the second click of a double-click must not answer it (kit/guard.ts).
  const guard = useAnswerGuardState();
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

  const load = useCallback(async () => {
    try {
      const rows = await request<PendingAsk[]>("/approvals/pending");
      if (!alive.current) return;
      const shown = Array.isArray(rows) ? onePerCallId(rows.filter((r) => ANSWERABLE.has(r.frame?.type))) : [];
      setAsks(shown);
      onCount?.(shown.length);
    } catch { /* the rest of the Inbox still works */ }
  }, [onCount]);
  useEffect(() => {
    void load();
    const timer = setInterval(() => { if (document.visibilityState !== "hidden") void load(); }, POLL_MS);
    return () => clearInterval(timer);
  }, [load]);

  async function answer(ask: PendingAsk, approve: boolean, extra?: AnswerExtra) {
    setError(false);
    setAsks((all) => all.filter((a) => a.call_id !== ask.call_id));
    try {
      // 0.1.61 §A4: a v2 card's scope and note go with it; an old card's body is exactly as before.
      await request(`/approvals/${encodeURIComponent(ask.call_id)}/answer`,
        { method: "POST", body: JSON.stringify({ approve, source: "inbox",
          ...(extra?.scope ? { scope: extra.scope } : {}), ...(extra?.note ? { note: extra.note } : {}) }) });
    } catch {
      setError(true);         // expired or answered elsewhere meanwhile
    }
    announceProactiveChange();
    await load();
  }

  if (!asks.length && !error) return null;
  return (
    <section data-testid="inbox-approvals" aria-label={t("inbox.approveNow")} className="flex flex-col gap-2">
      <h2 className="flex items-center gap-2 text-[13px] font-semibold">
        <span aria-hidden="true" className="h-[7px] w-[7px] rounded-full bg-ask" />{t("inbox.approveNow")}
        <span className="font-mono text-[12px] text-subtle-foreground">{asks.length}</span>
      </h2>
      {error && <Notice tone="warn">{t("inbox.answerFailed")}</Notice>}
      <AnswerGuardScope value={guard}>
        <AskQueue items={asks.map((ask) => ({ key: ask.call_id, render: (queue) => (
          <AskForFrame ask={ask} queue={queue} onAnswer={(approve, extra) => void answer(ask, approve, extra)}
            onOpenContext={() => onOpenConversation(ask.conversation_id)} />) }))} />
      </AnswerGuardScope>
    </section>
  );
}
