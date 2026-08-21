import { useState } from "react";
import { useTranslation } from "react-i18next";

interface Props {
  callId: string;
  /** Full command as one string, e.g. "git status". */
  pretty: string;
  reason?: string;
  /** Non-empty when the command runs on ANOTHER machine (P3b), as "user@ip". */
  remoteHost?: string;
  /** That machine's host key fingerprints, for the user to compare. */
  fingerprints?: string[];
  onConfirm: (callId: string, remember: boolean) => void;
  onCancel: (callId: string) => void;
}

/**
 * Per-command confirmation card for a backend `propose_run_command` frame.
 * Shows the FULL command verbatim; the user must click Run for it to execute.
 * "Remember this session" auto-approves same-shape commands for the rest of the chat.
 *
 * When `remoteHost` is set the card changes shape rather than adding a footnote:
 * the machine goes first, the fingerprint is shown so a person can compare it
 * against the machine itself, and "remember this session" is GONE — the backend
 * refuses to honour it for a remote command, and offering a checkbox that does
 * nothing would be a lie told in a safety dialog.
 */
export default function RunCommandCard({ callId, pretty, reason, remoteHost, fingerprints,
                                         onConfirm, onCancel }: Props) {
  const { t } = useTranslation();
  const [remember, setRemember] = useState(false);
  const isRemote = Boolean(remoteHost);
  return (
    <div className={isRemote ? "runcmd-card runcmd-card--remote" : "runcmd-card"} data-testid="runcmd-card">
      <div className="runcmd-card__label">
        {isRemote ? t("runcmd.remoteLabel", { host: remoteHost }) : t("runcmd.label")}
      </div>
      {isRemote ? (
        <div className="runcmd-card__remote-note" data-testid="runcmd-remote-note">
          {t("runcmd.remoteWarning")}
        </div>
      ) : null}
      <pre className="runcmd-card__cmd">{pretty}</pre>
      {isRemote && (fingerprints?.length ?? 0) > 0 ? (
        <div className="runcmd-card__fingerprints" data-testid="runcmd-fingerprints">
          <div className="runcmd-card__fingerprints-label">{t("runcmd.fingerprint")}</div>
          {fingerprints!.map((fp) => (
            <code key={fp} className="runcmd-card__fingerprint">{fp}</code>
          ))}
        </div>
      ) : null}
      {reason ? <div className="runcmd-card__reason">{reason}</div> : null}
      {isRemote ? null : (
      <label className="runcmd-card__remember">
        <input
          type="checkbox"
          data-testid="runcmd-remember"
          checked={remember}
          onChange={(e) => setRemember(e.target.checked)}
        />
        {t("runcmd.remember")}
      </label>
      )}
      <div className="runcmd-card__actions">
        <button
          type="button"
          className="runcmd-card__btn runcmd-card__btn--primary"
          data-testid="runcmd-run"
          onClick={() => onConfirm(callId, remember)}
        >
          {isRemote ? t("runcmd.runRemote") : t("runcmd.run")}
        </button>
        <button
          type="button"
          className="runcmd-card__btn runcmd-card__btn--ghost"
          data-testid="runcmd-cancel"
          onClick={() => onCancel(callId)}
        >
          {t("runcmd.cancel")}
        </button>
      </div>
    </div>
  );
}
