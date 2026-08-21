/**
 * EnrollNodeCard — Arslan asks to remember a machine (P3c).
 *
 * The button here calls REST, not the socket. That division is the safety
 * argument, not an implementation detail: the tool that proposed this wrote
 * nothing, so a machine can only become enrolled by a person clicking in this
 * card. Same shape as ConnectMcpCard.
 *
 * Two things the copy has to be honest about, because both are easy to assume
 * wrongly: the fingerprint is something only the user can verify (against the
 * machine itself — we can only show it again, which proves nothing), and
 * enrolling does NOT make future commands run without asking.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { ServerCog } from "lucide-react";
import { api } from "../api/client";

interface Props {
  callId: string;
  name: string;
  host: string;
  user: string;
  fingerprints: string[];
  onDone: () => void;
}

export default function EnrollNodeCard({ name, host, user, fingerprints, onDone }: Props) {
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
    <div className="runcmd-card runcmd-card--remote" data-testid="enroll-node-card">
      <div className="runcmd-card__label">
        <ServerCog className="w-3.5 h-3.5 inline mr-1.5" />
        {t("enroll.label", { name, host })}
      </div>
      <div className="runcmd-card__remote-note">{t("enroll.stillAsks")}</div>
      <pre className="runcmd-card__cmd">{user}@{host}</pre>
      {fingerprints.length > 0 ? (
        <div className="runcmd-card__fingerprints" data-testid="enroll-fingerprints">
          <div className="runcmd-card__fingerprints-label">{t("enroll.checkFingerprint")}</div>
          {fingerprints.map((fp) => (
            <code key={fp} className="runcmd-card__fingerprint">{fp}</code>
          ))}
        </div>
      ) : null}
      <div className="runcmd-card__actions">
        <button
          type="button"
          className="runcmd-card__btn runcmd-card__btn--primary"
          data-testid="enroll-confirm"
          disabled={busy}
          onClick={enroll}
        >
          {t("enroll.confirm")}
        </button>
        <button
          type="button"
          className="runcmd-card__btn runcmd-card__btn--ghost"
          data-testid="enroll-cancel"
          disabled={busy}
          onClick={onDone}
        >
          {t("enroll.cancel")}
        </button>
      </div>
      {error ? <div className="runcmd-card__reason" data-testid="enroll-error">{error}</div> : null}
    </div>
  );
}
