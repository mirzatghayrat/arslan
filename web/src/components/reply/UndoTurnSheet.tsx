import { useState } from "react";
import { useTranslation } from "react-i18next";
import { ApiError, api } from "../../api/client";
import type { ArslanServerMessage, RunCheckpoint, TurnUndone } from "../../api/client.types";
import { useArslanStore } from "../../stores/arslanStore";
import { Button, Dialog, toast } from "../kit";

/** S3b: a conversation was taken back; `detail` is the undo's result with the conversation's history now
 * (App replaces the open conversation's messages with it). */
export const TURN_UNDONE_EVENT = "arslan:turn-undone";
export type TurnUndoneDetail = NonNullable<TurnUndone["conversation"]>;

/** App: the open conversation shows what the server now has (the store's own history handling). */
export function showUndone(detail: TurnUndoneDetail | undefined, openConversationId: string): boolean {
  if (!detail || detail.conversation_id !== openConversationId) return false;
  useArslanStore.getState().handleFrame({ type: "history", messages: detail.history } as ArslanServerMessage);
  return true;
}

const KNOWN = new Set(["none", "job", "not_own_turn", "already", "summarised", "running", "finishing",
  "not_finished", "changed"]);
type Failed = { failed?: string[]; git?: string | null };

/** What could not be put back, from a files result ("both" refused with files_failed). */
function failedPaths(files: { runs?: Failed[] } | undefined): string[] {
  return (files?.runs ?? []).flatMap((r) => [...(r.failed ?? []), ...(r.git === "failed" ? [".git"] : [])]);
}

/**
 * 0.1.63 S3b: what undoing a turn covers, before anything changes. Only the choices that can happen are
 * offered: its files (S3a), its conversation (this turn, every later one, the facts they taught), or both.
 * The later turns that go too are said first and plainly (⓪Plan's Q2). When its files can be undone, the
 * conversation goes only with them: afterwards the reply, and with it this menu, is gone (review 🟡11).
 * The undo is held to the messages this box counted (`last_message_id`, review 🟠1).
 */
export default function UndoTurnSheet({ runId, info, onClose }: {
  runId: number; info: RunCheckpoint; onClose: () => void;
}) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [notBack, setNotBack] = useState<string[] | null>(null);
  const files = info.exists && !info.restored_at && !info.running;
  const conversation = info.conversation;
  const why = (code: string | null | undefined) => (code && KNOWN.has(code) ? t(`process.undoWhy_${code}`) : null);
  const undo = async (what: "files" | "conversation" | "both") => {
    setBusy(true);
    try {
      const out = await api.undoTurn(runId, what, info.last_message_id);
      if (out.conversation) {
        window.dispatchEvent(new CustomEvent<TurnUndoneDetail>(TURN_UNDONE_EVENT, { detail: out.conversation }));
      }
      toast(t("process.undoDone"));
      onClose();
    } catch (err) {
      const detail = err instanceof ApiError ? err.detail as { code?: string; reason?: string; files?: { runs?: Failed[] } }
        | undefined : undefined;
      if (detail?.code === "files_failed") {
        setNotBack(failedPaths(detail.files));             // the conversation stayed: files can be tried again
      } else if (detail?.code === "conversation_failed") {
        toast(t("process.undoConversationFailed"));
        onClose();
      } else {
        toast(why(detail?.code) ?? t("process.undoFailed"));
      }
    } finally {
      setBusy(false);
    }
  };
  const line = "text-[13.5px] leading-normal text-muted-foreground";
  return (
    <Dialog open onClose={onClose} busy={busy} width={460} testId="undo-turn" title={t("process.undoTitle")}>
      <div className="flex flex-col gap-2.5 px-5 pb-4 pt-2">
        {conversation && (info.later_turns ?? 0) > 0 && (
          <p className="text-[14px] font-semibold text-warning" data-testid="undo-later-turns">
            {t("process.undoLater", { count: info.later_turns })}</p>
        )}
        {conversation ? <>
          <p className={line}>{t("process.undoMessages", { count: info.messages_after ?? 0 })}</p>
          {(info.facts ?? 0) > 0 && <p className={line} data-testid="undo-facts">{t("process.undoFacts", { count: info.facts })}</p>}
          <p className={line} data-testid="undo-phone">{t("process.undoPhone")}</p>
        </> : <p className={line} data-testid="undo-why">{why(info.reason)}</p>}
        {files ? <>
          <p className={line}>{t("process.undoFiles", { changed: info.changed ?? 0, created: info.created ?? 0 })}</p>
          {(info.later?.length ?? 0) > 0 && <p className={line}>{t("process.undoLaterRuns", { count: info.later!.length })}</p>}
          {(info.excluded?.length ?? 0) > 0 && <p className={line}>{t("process.undoExcluded", { names: info.excluded!.join(", ") })}</p>}
          {(info.skipped?.length ?? 0) > 0 && (
            <p className={line}>{t("process.undoSkipped", { names: info.skipped!.map((s) => s.path).join(", ") })}</p>
          )}
        </> : <p className={line}>{info.running ? why("running") : info.restored_at ? why("already") : t("process.undoNoFiles")}</p>}
        {notBack && <p className="text-[13.5px] font-semibold text-warning" data-testid="undo-not-back">
          {t("process.undoFilesFailed", { paths: notBack.join(", ") })}</p>}
        <div className="mt-1.5 flex flex-wrap gap-2">
          <Button tone="secondary" grow={1} onClick={onClose} disabled={busy} data-testid="undo-cancel">{t("kit.cancel")}</Button>
          {files && <Button tone="destructive" grow={1} disabled={busy} onClick={() => undo("files")}
            data-testid="undo-files">{t("process.undoFilesBtn")}</Button>}
          {conversation && !files && <Button tone="destructive" grow={1} disabled={busy} onClick={() => undo("conversation")}
            data-testid="undo-conversation">{t("process.undoConvBtn")}</Button>}
          {files && conversation && <Button tone="destructive" grow={1} disabled={busy} onClick={() => undo("both")}
            data-testid="undo-both">{t("process.undoBothBtn")}</Button>}
        </div>
      </div>
    </Dialog>
  );
}
