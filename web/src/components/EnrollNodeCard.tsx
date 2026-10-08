/**
 * EnrollNodeCard — Arslan asks to remember a machine (P3c), in the 0.1.55 AskCard.
 *
 * The button calls REST, not the socket: the tool that proposed this wrote nothing,
 * so a machine can only become enrolled by a person clicking here. The copy is
 * honest about two things: only the user can verify the fingerprint (against the
 * machine itself), and enrolling does NOT make future commands run without asking.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { ServerCog } from "lucide-react";
import { api } from "../api/client";
import { AskCard, CodeBox, Notice, type AskQueuePosition } from "./kit";
import { Fingerprints, lineIcon } from "./kit/askParts";

interface Props {
  callId: string;
  name: string;
  host: string;
  user: string;
  fingerprints: string[];
  expiresAt?: number | null;
  queue?: AskQueuePosition;
  onDone: () => void;
}

export default function EnrollNodeCard({ name, host, user, fingerprints, expiresAt, queue, onDone }: Props) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const enroll = async () => {
    setBusy(true);
    setError("");
    try {
      await api.enrollSshNode({ name, host, user, fingerprints });
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("enroll.failed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AskCard testId="enroll-node-card" who={t("kit.whoArslan")} title={t("enroll.label", { name, host })}
      detail={<><CodeBox code={`${user}@${host}`} numbered={false} />
        <Fingerprints label={t("enroll.checkFingerprint")} list={fingerprints} testId="enroll-fingerprints" /></>}
      context={[{ icon: lineIcon(ServerCog), text: t("enroll.stillAsks") }]}
      extra={error ? <Notice tone="error" testId="enroll-error">{error}</Notice> : null}
      expiresAt={expiresAt} queue={queue} busy={busy}
      allowLabel={t("enroll.confirm")} declineLabel={t("enroll.cancel")}
      allowTestId="enroll-confirm" declineTestId="enroll-cancel"
      onAllow={() => void enroll()} onDecline={onDone} />
  );
}
