import { useState } from "react";
import { useTranslation } from "react-i18next";

interface Props {
  callId: string;
  /** Full command as one string, e.g. "git status". */
  pretty: string;
  reason?: string;
  onConfirm: (callId: string, remember: boolean) => void;
  onCancel: (callId: string) => void;
}

/**
 * Per-command confirmation card for a backend `propose_run_command` frame.
 * Shows the FULL command verbatim; the user must click Run for it to execute.
 * "Remember this session" auto-approves same-shape commands for the rest of the chat.
 */
export default function RunCommandCard({ callId, pretty, reason, onConfirm, onCancel }: Props) {
  const { t } = useTranslation();
  const [remember, setRemember] = useState(false);
  return (
    <div className="runcmd-card" data-testid="runcmd-card">
      <div className="runcmd-card__label">{t("runcmd.label")}</div>
      <pre className="runcmd-card__cmd">{pretty}</pre>
      {reason ? <div className="runcmd-card__reason">{reason}</div> : null}
      <label className="runcmd-card__remember">
        <input
          type="checkbox"
          data-testid="runcmd-remember"
          checked={remember}
          onChange={(e) => setRemember(e.target.checked)}
        />
        {t("runcmd.remember")}
      </label>
      <div className="runcmd-card__actions">
        <button
          type="button"
          className="runcmd-card__btn runcmd-card__btn--primary"
          data-testid="runcmd-run"
          onClick={() => onConfirm(callId, remember)}
        >
          {t("runcmd.run")}
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
