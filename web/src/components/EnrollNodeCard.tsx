/**
 * EnrollNodeCard — Arslan asks to remember a machine (P3c), in the 0.1.55 AskCard.
 *
 * The button calls REST, not the socket: the tool that proposed this wrote nothing,
 * so a machine can only become enrolled by a person clicking here. The copy is
 * honest about two things: only the user can verify the fingerprint (against the
 * machine itself), and enrolling does NOT make future commands run without asking.
 */
import { useTranslation } from "react-i18next";
import { ServerCog } from "lucide-react";
import { api } from "../api/client";
import { useArslanStore } from "../stores/arslanStore";
import { AskCard, CodeBox, Notice, type AskQueuePosition } from "./kit";
import { Fingerprints, HideWhileBusy, lineIcon } from "./kit/askParts";

interface Props {
  callId: string;
  name: string;
  host: string;
  user: string;
  fingerprints: string[];
  expiresAt?: number | null;
  queue?: AskQueuePosition;
  /** The enrolment is in flight and the person hides the card: it leaves, the enrolment goes on, the chat says how it ended (arslanStore `hideCard`). */
  onHide?: () => void;
  onDone: () => void;
}

export default function EnrollNodeCard({ callId, name, host, user, fingerprints, expiresAt, queue, onHide, onDone }: Props) {
  const { t } = useTranslation();
  // Whether the enrolment is in flight, and why it failed, are the store's, by call id: this card is remounted when the person pages away
  // and back. While it is in flight its buttons stay off (never a second enrolment) though paging and the other cards stay free.
  const apply = useArslanStore((s) => s.cardApply[callId]);
  const busy = apply?.busy === true;
  const error = apply?.error ?? "";

  const enroll = async () => {
    if (useArslanStore.getState().cardApply[callId]?.busy) return;         // the store's, not this render's: a second click may come first
    useArslanStore.getState().beginCardApply(callId);
    try {
      await api.enrollSshNode({ name, host, user, fingerprints });
    } catch (e) {
      const why = e instanceof Error ? e.message : t("enroll.failed");
      const store = useArslanStore.getState();
      // A card the person hid has nowhere to show the error: the chat says so, naming the machine.
      if (store.endCardApply(callId, { error: why })) store.addCardNote(t("kit.hiddenEnrollFailed", { name, why }));
      return;
    }
    const store = useArslanStore.getState();
    if (store.endCardApply(callId)) store.addCardNote(t("kit.hiddenEnrolled", { name }));
    onDone();
  };

  return (
    <AskCard testId="enroll-node-card" who={t("kit.whoArslan")} title={t("enroll.label", { name, host })}
      detail={<><CodeBox code={`${user}@${host}`} numbered={false} />
        <Fingerprints label={t("enroll.checkFingerprint")} list={fingerprints} testId="enroll-fingerprints" /></>}
      context={[{ icon: lineIcon(ServerCog), text: t("enroll.stillAsks") }]}
      extra={<>
        {error ? <Notice tone="error" testId="enroll-error">{error}</Notice> : null}
        {busy && onHide ? <HideWhileBusy testId="enroll-hide" onHide={onHide} /> : null}
      </>}
      expiresAt={expiresAt} queue={queue} busy={busy}
      allowLabel={t("enroll.confirm")} declineLabel={t("enroll.cancel")}
      allowTestId="enroll-confirm" declineTestId="enroll-cancel"
      onAllow={() => void enroll()} onDecline={onDone} />
  );
}
