import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Globe2, ShieldAlert, Terminal } from "lucide-react";
import { AskCard, CodeBox } from "./kit";
import { DeclineNote, Fingerprints, RED_KINDS, ScopeChoice, lineIcon, offeredScopes, scopeToSend } from "./kit/askParts";

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
  /** 0.1.42: a background job is asking. */
  background?: boolean;
  /** 0.1.51 P3: "outside" — leave the sandbox; "retry" — the sandbox stopped it. */
  sandbox?: "outside" | "retry";
  /** With "outside": Arslan's one-line reason (the model's words). */
  why?: string;
  expiresAt?: number | null;
  /** 0.1.61 §A4: the choices a card from the permission layer offers. Every command card carries them
   *  (S4a); a frame without them answers with its first, narrowest choice. */
  options?: string[];
  /** The literal scope "Always" stores (the frame's `always_label`). */
  alwaysLabel?: string;
  /** The frame's permission kind (`perm_kind`). A red kind (money, app_risky, destructive) draws Run red,
   *  as the action card does; a once-only kind offers only the frame's first choice. Absent on an old frame. */
  permKind?: string;
  /** An answer is on its way: the card is inert (its buttons, its keys and its note). */
  busy?: boolean;
  queue?: import("./kit").AskQueuePosition;
  onOpenContext?: () => void;
  /** A yes, with the choice ticked (none on a frame without choices). */
  onConfirm: (callId: string, scope?: string) => void;
  /** A v2 card's No may carry the user's note. */
  onCancel: (callId: string, note?: string) => void;
}

/**
 * Per-command confirmation (a `propose_run_command` frame), in the 0.1.55 AskCard.
 * The FULL command is shown; only the user's click (or ⌘⏎) runs it.
 *
 * Remote: the machine leads, its fingerprint is shown to compare, and it is answered this time only.
 * Sandbox: the question is about leaving the sandbox, and "In this conversation" lets every command
 * of the conversation out, background tasks' too (S4a). 0.1.61: the card shows the frame's choices
 * and takes a note on No. (S4a deleted the old "remember" tick: every command card carries choices.)
 */
export default function RunCommandCard({ callId, pretty, reason, remoteHost, fingerprints, background,
                                         sandbox, why, expiresAt, options, alwaysLabel, permKind, busy, queue,
                                         onOpenContext, onConfirm, onCancel }: Props) {
  const { t } = useTranslation();
  // 0.1.61 §A4: a card with options offers them (a job's too: the same choices as the window).
  const offered = offeredScopes(options, permKind);
  const v2 = Boolean(offered?.length);
  // Starts on the narrowest choice the card shows: Always is never the default, whatever its place.
  const [scope, setScope] = useState(() => scopeToSend(offered, undefined, alwaysLabel) ?? "");
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
      // A command card's "In this conversation" is a grant for its kind of command (the rules it matched: every `rm`, every
      // `git push`), not for this one text — the same set "Always" names (approvals._command_request). It says so.
      // S4a: on the card to leave the sandbox it lets every command of this conversation out, a background task's too.
      options={v2 ? <ScopeChoice options={offered} value={scope} onChange={setScope} alwaysLabel={alwaysLabel}
        conversationLabel={permKind === "command" ? alwaysLabel
          : permKind === "outside" ? t("runcmd.sandboxConversation") : undefined} testId="runcmd-scope" />
        : null}
      extra={v2 ? <DeclineNote testId="runcmd-note" disabled={busy}
        onDeclineWithNote={(note) => (note ? onCancel(callId, note) : onCancel(callId))} /> : undefined}
      destructive={RED_KINDS.has(permKind ?? "")}
      expiresAt={expiresAt} queue={queue} busy={busy} onOpenContext={onOpenContext}
      allowDisabled={v2 && scopeToSend(offered, scope, alwaysLabel) === undefined}
      allowLabel={isRemote ? t("runcmd.runRemote") : sandbox ? t("runcmd.runOutside") : t("runcmd.run")}
      declineLabel={t("runcmd.cancel")}
      allowTestId="runcmd-run" declineTestId="runcmd-cancel"
      onAllow={() => onConfirm(callId, v2 ? scopeToSend(offered, scope, alwaysLabel) : undefined)}
      onDecline={() => onCancel(callId)} />
  );
}
