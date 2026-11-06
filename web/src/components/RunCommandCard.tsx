import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Globe2, ShieldAlert, Terminal } from "lucide-react";
import { AskCard, CodeBox } from "./kit";
import { DeclineNote, Fingerprints, RED_KINDS, ScopeChoice, lineIcon, offeredScopes, scopeToSend } from "./kit/askParts";
import { TOUCHES_MAX, commandRisk, deletePurpose, purposeText, summarize } from "../lib/commandSummary";
import { Escaped } from "../lib/outsideText";

interface Props {
  callId: string;
  /** Full command as one string, e.g. "git status". */
  pretty: string;
  /** Why it asks, as the server's English line (the terminal rule that matched). SMART-8: the 「风险」 row now says it in
   *  the user's language from `rule`, so the card no longer prints this; the phone still reads it. */
  reason?: string;
  /** Non-empty when the command runs on ANOTHER machine (P3b), as "user@ip". */
  remoteHost?: string;
  /** That machine's host key fingerprints, for the user to compare. */
  fingerprints?: string[];
  /** 0.1.42: a background job is asking. */
  background?: boolean;
  /** 0.1.51 P3: "outside" — leave the sandbox; "retry" — the sandbox stopped it. */
  sandbox?: "outside" | "retry";
  /** Arslan's one-line reason for the step (the model's words, cleaned by the server). SMART-8: when present it is
   *  the card's purpose, marked as Arslan's; else the purpose is read from the command. */
  why?: string;
  /** The terminal rule the server matched (`rule`), whether the card also asks for the network (`network`), and
   *  whether it would run with no sandbox around it (`unsandboxed`): the 「风险」 row, never the model's words. */
  rule?: string;
  /** Every terminal rule the server matched (#688 review 1, 3): on every command card, the outside, retry and remote
   *  ones too. An older frame has only `rule`. */
  rules?: string[];
  /** Why the server could not read it (fetched-code, script-reach, quoting, complex), when one of its rules is
   *  `unreadable` (#688 review 5). */
  unreadable?: string;
  /** SMART-8: how Allow deletes (trash, protected, permanent, sandboxed), and the targets as written ([] when the
   *  delete can't be read, and the card reads them itself). On the Mac's frame only. */
  deleteMode?: string;
  deleteTargets?: string[];
  network?: boolean;
  unsandboxed?: boolean;
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
export default function RunCommandCard({ callId, pretty, remoteHost, fingerprints, background,
                                         sandbox, why, rule, rules, unreadable, deleteMode, deleteTargets, network, unsandboxed, expiresAt, options, alwaysLabel,
                                         permKind, busy, queue, onOpenContext, onConfirm, onCancel }: Props) {
  const { t } = useTranslation();
  // 0.1.61 §A4: a card with options offers them (a job's too: the same choices as the window).
  const offered = offeredScopes(options, permKind);
  const v2 = Boolean(offered?.length);
  // Starts on the narrowest choice the card shows: Always is never the default, whatever its place.
  const [scope, setScope] = useState(() => scopeToSend(offered, undefined, alwaysLabel) ?? "");
  const isRemote = Boolean(remoteHost);
  // SMART-8 (the card mock the user OK'd): the purpose first, Arslan's own reason when it gave one, else read from
  // the command; then what it touches and the risk, read by code; the command itself folded, whole when opened.
  const matched = rules?.length ? rules : rule ? [rule] : [];
  const summary = summarize(pretty, matched);
  const said = (why ?? "").trim();
  const reading = purposeText(t, deletePurpose(summary.purpose, deleteMode)) + (summary.more ? t("runcmd.purpose.more", { count: summary.more }) : "");
  const purpose = said || reading;
  const touched = [...new Set([...(remoteHost ? [remoteHost] : []), ...(deleteTargets?.length ? deleteTargets : summary.touches)])];
  const risk = commandRisk({ rules: matched, unreadable, network, sandbox, remoteHost, unsandboxed, unsure: summary.unsure,
                             deleteMode });
  const riskText = risk.keys.map(k => t(`runcmd.risk.${k.key}`, k.params)).join(t("kit.riskJoin"));
  const context = [
    ...(background ? [{ icon: lineIcon(Terminal), text: <span data-testid="runcmd-background">{t("jobs.askingBadge")}</span> }] : []),
    ...(sandbox ? [{ icon: lineIcon(ShieldAlert), text: <span data-testid="runcmd-sandbox-note">
      {t(sandbox === "outside" ? "runcmd.sandboxOutsideNote" : "runcmd.sandboxRetryNote")}</span> }] : []),
    ...(isRemote ? [{ icon: lineIcon(Globe2), text: <span data-testid="runcmd-remote-note">{t("runcmd.remoteWarning")}</span> }] : []),
  ];
  return (
    <AskCard testId="runcmd-card" attrs={isRemote ? { "data-remote": "true" } : undefined}
      who={background ? t("jobs.askingBadge") : t("kit.whoArslan")}
      title={<span data-testid="runcmd-purpose"><Escaped text={purpose} /></span>}
      purposeFrom={said ? "arslan" : "command"}
      // #688 review 2: Arslan's words are never the only description. When they lead, the code's own reading of the
      // command starts the 「涉及」 row (the mock's three rows stay).
      touches={touched.length || said ? <span className="flex flex-col gap-0.5">
        {said ? <span data-testid="runcmd-reading"><Escaped text={reading} /></span> : null}
        {touched.slice(0, TOUCHES_MAX).map(item => <span key={item} className="font-mono text-[12px]"><Escaped text={item} /></span>)}
        {touched.length > TOUCHES_MAX ? <span className="text-muted-foreground">
          {t("kit.touchesMore", { count: touched.length - TOUCHES_MAX })}</span> : null}
      </span> : null}
      riskRow={{ level: risk.level, text: riskText }}
      // #688 review 7: opened, the command is whole (the box scrolls), so no line waits behind a second click. SMART-8
      // (Astra, simplified): a card that uses the network shows the whole command unfolded, since its reading cannot
      // say what it sends.
      folded={summary.unsure ? undefined
        : { testId: "runcmd-show-command", body: <CodeBox code={pretty} numbered={false} fold={Infinity} /> }}
      detail={(summary.unsure || isRemote) ? <span className="flex flex-col gap-2">
        {summary.unsure ? <span data-testid="runcmd-command"><CodeBox code={pretty} numbered={false} fold={Infinity} /></span> : null}
        {isRemote ? <Fingerprints label={t("runcmd.fingerprint")} list={fingerprints ?? []} testId="runcmd-fingerprints" /> : null}
      </span> : null}
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
