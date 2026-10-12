import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Globe2, ShieldAlert, Terminal } from "lucide-react";
import { AskCard, CodeBox } from "./kit";
import { AskOption, DeclineNote, Fingerprints, ScopeChoice, lineIcon, scopeToSend } from "./kit/askParts";

interface Props {
  callId: string;
  /** Full command as one string, e.g. "git status". */
  pretty: string;
  /** Why it asks — the terminal rule that matched (host classification, never the model's words). */
  reason?: string;
  /** Non-empty when the command runs on ANOTHER machine (P3b), as "user@ip". */
  remoteHost?: string;
  /** That machine's host key fingerprints, for the user to compare. */
  fingerprints?: string[];
  /** 0.1.42: a background job is asking; "remember" is never honoured for a job. */
  background?: boolean;
  /** 0.1.51 P3: "outside" — leave the sandbox; "retry" — the sandbox stopped it. */
  sandbox?: "outside" | "retry";
  /** With "outside": Arslan's one-line reason (the model's words). */
  why?: string;
  expiresAt?: number | null;
  /** 0.1.61 §A4: the choices a card from the permission layer offers. Absent on an old frame
   *  (leaving the sandbox, another machine), which keeps its checkbox and its "remember". */
  options?: string[];
  /** The literal scope "Always" stores (the frame's `always_label`). */
  alwaysLabel?: string;
  /** The Inbox: the server never keeps "remember" from there, so the old checkbox is not shown. */
  noRemember?: boolean;
  /** An answer is on its way: the card is inert (its buttons, its keys and its note). */
  busy?: boolean;
  queue?: import("./kit").AskQueuePosition;
  onOpenContext?: () => void;
  /** An old card answers (callId, remember); a v2 card answers (callId, false, scope). */
  onConfirm: (callId: string, remember: boolean, scope?: string) => void;
  /** A v2 card's No may carry the user's note. */
  onCancel: (callId: string, note?: string) => void;
}

/**
 * Per-command confirmation (a `propose_run_command` frame), in the 0.1.55 AskCard.
 * The FULL command is shown; only the user's click (or ⌘⏎) runs it.
 *
 * Remote: the machine leads, its fingerprint is shown to compare, and there is NO
 * "remember" — the backend refuses it for a remote command, and a checkbox that does
 * nothing would be a lie in a safety dialog. Sandbox: the question is about leaving
 * the sandbox, and the checkbox means "for the rest of this conversation".
 * 0.1.61: a card from the permission layer (a frame with `options`) shows its choices in place
 * of the checkbox, and takes a note on No.
 */
export default function RunCommandCard({ callId, pretty, reason, remoteHost, fingerprints, background,
                                         sandbox, why, expiresAt, options, alwaysLabel, noRemember, busy, queue,
                                         onOpenContext, onConfirm, onCancel }: Props) {
  const { t } = useTranslation();
  const [remember, setRemember] = useState(false);
  // 0.1.61 §A4: a card with options offers them (a job's too: the same choices as the window).
  const v2 = Boolean(options?.length);
  // Starts on the narrowest choice the card shows: Always is never the default, whatever its place.
  const [scope, setScope] = useState(() => scopeToSend(options, undefined, alwaysLabel) ?? "");
  const isRemote = Boolean(remoteHost);
  const title = isRemote ? t("runcmd.remoteLabel", { host: remoteHost })
    : sandbox === "outside" ? t("runcmd.sandboxOutsideLabel")
    : sandbox === "retry" ? t("runcmd.sandboxRetryLabel")
    : t("runcmd.label");
  const context = [
    ...(background ? [{ icon: lineIcon(Terminal), text: <span data-testid="runcmd-background">{t("jobs.askingBadge")}</span> }] : []),
    ...(sandbox ? [{ icon: lineIcon(ShieldAlert), text: <span data-testid="runcmd-sandbox-note">
      {t(sandbox === "outside" ? "runcmd.sandboxOutsideNote" : "runcmd.sandboxRetryNote")}</span> }] : []),
    ...(isRemote ? [{ icon: lineIcon(Globe2), text: <span data-testid="runcmd-remote-note">{t("runcmd.remoteWarning")}</span> }] : []),
  ];
  return (
    <AskCard testId="runcmd-card" attrs={isRemote ? { "data-remote": "true" } : undefined}
      who={background ? t("jobs.askingBadge") : t("kit.whoArslan")}
      title={title}
      said={sandbox === "outside" && why ? why : null} saidTestId="runcmd-why"
      risk={reason || null}
      detail={<>
        <CodeBox code={pretty} numbered={false} fold={8} />
        {isRemote ? <Fingerprints label={t("runcmd.fingerprint")} list={fingerprints ?? []} testId="runcmd-fingerprints" /> : null}
      </>}
      context={context}
      options={v2 ? <ScopeChoice options={options} value={scope} onChange={setScope} alwaysLabel={alwaysLabel} testId="runcmd-scope" />
        : isRemote || background || noRemember ? null : (
        <AskOption checked={remember} onChange={setRemember} testId="runcmd-remember"
          label={t(sandbox ? "runcmd.sandboxRemember" : "runcmd.remember")} />
      )}
      extra={v2 ? <DeclineNote testId="runcmd-note" disabled={busy}
        onDeclineWithNote={(note) => (note ? onCancel(callId, note) : onCancel(callId))} /> : undefined}
      expiresAt={expiresAt} queue={queue} busy={busy} onOpenContext={onOpenContext}
      allowLabel={isRemote ? t("runcmd.runRemote") : sandbox ? t("runcmd.runOutside") : t("runcmd.run")}
      declineLabel={t("runcmd.cancel")}
      allowTestId="runcmd-run" declineTestId="runcmd-cancel"
      onAllow={() => (v2 ? onConfirm(callId, false, scopeToSend(options, scope, alwaysLabel))
        : onConfirm(callId, remember && !background && !isRemote && !noRemember))}
      onDecline={() => onCancel(callId)} />
  );
}
