import { LockKeyhole } from "lucide-react";
import { useTranslation } from "react-i18next";
import { AskCard, type AskQueuePosition } from "./kit";
import { DeclineNote, lineIcon } from "./kit/askParts";

/**
 * 0.1.61 §A4 (PR 2b final review, M6): the Inbox's card for one that is answered only where its whole card is shown — a new capability
 * (kit/askParts.tsx `WINDOW_ONLY_KINDS`). The server refuses a yes from here (`open_in_arslan`), so no Allow is drawn: "Open in Arslan" stands
 * where it would, a line says why, and there is no choice of how long (nothing is allowed from here). Saying no stays, with the note. The words
 * are the island's own for a card it will not answer. What the card asks is the frame's own title and its literal subject — never the model's
 * line, which a prompt-injected model could word harmlessly.
 */
export default function WindowOnlyCard({ heading, subject, background, expiresAt, queue, onOpen, onNo, onOpenContext }: {
  heading: string; subject: string; background: boolean; expiresAt?: number | null; queue?: AskQueuePosition;
  /** Opens the conversation the card was asked in, where the whole card is shown. */
  onOpen: () => void; onNo: (note?: string) => void; onOpenContext?: () => void;
}) {
  const { t } = useTranslation();
  return (
    <AskCard testId="held-card" who={background ? t("jobs.askingBadge") : t("kit.whoArslan")}
      title={<span className="inline-flex max-w-full items-start gap-2">{lineIcon(LockKeyhole)}
        <span data-testid="held-title" className="min-w-0 [overflow-wrap:anywhere]">{heading}</span></span>}
      detail={subject ? <p data-testid="held-subject" className="break-words rounded-[10px] bg-surface-raised px-3 py-2.5 text-[15px] font-semibold leading-[1.4] text-foreground">{subject}</p> : null}
      context={[{ icon: lineIcon(LockKeyhole), text: <span data-testid="held-reason">{t("inbox.heldCapability")}</span> }]}
      extra={<DeclineNote testId="held-note" onDeclineWithNote={(note) => (note ? onNo(note) : onNo())} />}
      expiresAt={expiresAt} queue={queue} onOpenContext={onOpenContext}
      allowLabel={t("inbox.openInArslan")} declineLabel={t("kit.decline")}
      allowTestId="held-open" declineTestId="held-deny"
      onAllow={onOpen} onDecline={() => onNo()} />
  );
}
