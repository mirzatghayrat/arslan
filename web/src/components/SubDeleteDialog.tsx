import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ApiError, deleteConversation } from "../api/client";
import { Button, Dialog, Notice } from "./kit";

export interface SubDeleteTarget {
  id: string;
  title: string;
  /** Its sub-sessions at every level. */
  count: number;
  /** One of them is running or waiting on you. */
  running: boolean;
}

/** SUB5d (the approved mock): deleting a conversation that started sub-sessions. "Also delete its N sub-sessions" is
 *  ticked by default: ticked, the whole tree goes; unticked, only this conversation goes and its sub-sessions become
 *  ordinary conversations with their settings as they are (SUB5a's `keep`). While one runs there is nothing to delete
 *  yet: the dialog says to stop it first. The server's 409 and 422 are shown, not dropped. */
export default function SubDeleteDialog({ target, onClose, onDeleted }: {
  target: SubDeleteTarget | null;
  onClose: () => void;
  onDeleted: (id: string, choice: "delete" | "keep") => void;
}) {
  const { t } = useTranslation();
  const [withSubs, setWithSubs] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  useEffect(() => { setWithSubs(true); setError(null); setRunning(Boolean(target?.running)); setBusy(false); }, [target]);
  if (!target) return null;
  const remove = async () => {
    const choice = withSubs ? "delete" : "keep";
    setBusy(true);
    setError(null);
    try {
      await deleteConversation(target.id, { subSessions: choice });
      onDeleted(target.id, choice);
    } catch (err) {
      const code = err instanceof ApiError ? (err.detail as { code?: string } | undefined)?.code ?? err.message : "";
      if (err instanceof ApiError && err.status === 409 && code === "sub_sessions_running") setRunning(true);
      else if (err instanceof ApiError && err.status === 422 && code === "sub_sessions_choice_required") {
        setError(t("subTree.delete.choiceRequired", { count: (err.detail as { sub_sessions?: number }).sub_sessions ?? target.count }));
      } else setError(t("subTree.delete.failed"));
    } finally {
      setBusy(false);
    }
  };
  return <Dialog open onClose={onClose} busy={busy} width={440} testId="sub-delete-dialog" title={t("subTree.delete.title", { name: target.title })}
    onSubmit={running ? undefined : () => void remove()}
    footer={<>
      <Button tone="secondary" onClick={onClose} disabled={busy} data-testid="sub-delete-cancel">{t(running ? "kit.close" : "kit.cancel")}</Button>
      {!running && <Button tone="destructive" onClick={() => void remove()} disabled={busy} data-testid="sub-delete-confirm">
        {t("confirm.delete")}</Button>}
    </>}>
    <div className="flex flex-col gap-3 px-5 pt-4 text-[14px]">
      {running
        ? <Notice tone="warn" testId="sub-delete-running">{t("subTree.delete.stopFirst")}</Notice>
        : <>
          <p className="text-muted-foreground">{t("confirm.conversationBody")}</p>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={withSubs} onChange={event => setWithSubs(event.target.checked)} data-testid="sub-delete-also" />
            <span>{t("subTree.delete.also", { count: target.count })}</span>
          </label>
          {!withSubs && <p className="text-[12.5px] text-subtle-foreground" data-testid="sub-delete-keep-note">{t("subTree.delete.keepNote")}</p>}
        </>}
      {error && <Notice tone="error" testId="sub-delete-error">{error}</Notice>}
    </div>
  </Dialog>;
}
