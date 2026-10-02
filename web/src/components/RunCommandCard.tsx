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
  /** 0.1.42: a background job is asking. The backend never honours "remember"
   *  for a job, so the checkbox is not offered — same reasoning as remote. */
  background?: boolean;
  /** 0.1.51 P3: "outside" — Arslan asks to run this outside the sandbox; "retry" —
   *  the sandbox stopped it and it would run again outside, from the start. */
  sandbox?: "outside" | "retry";
  /** With "outside": Arslan's one-line reason. */
  why?: string;
  onConfirm: (callId: string, remember: boolean) => void;
  onCancel: (callId: string) => void;
}

/**
 * Per-command confirmation card for a backend `propose_run_command` frame.
 * Shows the FULL command verbatim; the user must click Run for it to execute.
 * "Don't ask again" (0.1.48) remembers the KIND of command — the rule the backend
 * matched — until the user takes it back in Settings › Advanced.
 *
 * When `remoteHost` is set the card changes shape rather than adding a footnote:
 * the machine goes first, the fingerprint is shown so a person can compare it
 * against the machine itself, and "remember this session" is GONE — the backend
 * refuses to honour it for a remote command, and offering a checkbox that does
 * nothing would be a lie told in a safety dialog.
 *
 * When `sandbox` is set (0.1.51 P3) the question is about leaving the sandbox, so the
 * card says that first, and its checkbox means "for the rest of this conversation"
 * (the backend keeps it in memory only), not "don't ask again for this kind".
 */
export default function RunCommandCard({ callId, pretty, reason, remoteHost, fingerprints, background,
                                         sandbox, why, onConfirm, onCancel }: Props) {
  const { t } = useTranslation();
  const [remember, setRemember] = useState(false);
  const isRemote = Boolean(remoteHost);
  const label = isRemote ? t("runcmd.remoteLabel", { host: remoteHost })
    : sandbox === "outside" ? t("runcmd.sandboxOutsideLabel")
    : sandbox === "retry" ? t("runcmd.sandboxRetryLabel")
    : t("runcmd.label");
  return (
    <div className={isRemote ? "runcmd-card runcmd-card--remote" : "runcmd-card"} data-testid="runcmd-card">
      {background ? <div className="runcmd-card__reason" data-testid="runcmd-background">{t("jobs.askingBadge")}</div> : null}
      <div className="runcmd-card__label">{label}</div>
      {sandbox ? (
        <div className="runcmd-card__remote-note" data-testid="runcmd-sandbox-note">
          {t(sandbox === "outside" ? "runcmd.sandboxOutsideNote" : "runcmd.sandboxRetryNote")}
        </div>
      ) : null}
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
      {sandbox === "outside" && why ? <div className="runcmd-card__reason" data-testid="runcmd-why">{why}</div> : null}
      {reason ? <div className="runcmd-card__reason">{reason}</div> : null}
      {isRemote || background ? null : (
      <label className="runcmd-card__remember">
        <input
          type="checkbox"
          data-testid="runcmd-remember"
          checked={remember}
          onChange={(e) => setRemember(e.target.checked)}
        />
        {t(sandbox ? "runcmd.sandboxRemember" : "runcmd.remember")}
      </label>
      )}
      <div className="runcmd-card__actions">
        <button
          type="button"
          className="runcmd-card__btn runcmd-card__btn--primary"
          data-testid="runcmd-run"
          onClick={() => onConfirm(callId, remember && !background)}
        >
          {isRemote ? t("runcmd.runRemote") : sandbox ? t("runcmd.runOutside") : t("runcmd.run")}
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
