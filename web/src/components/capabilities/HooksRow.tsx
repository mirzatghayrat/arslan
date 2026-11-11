import { Fragment } from "react";
import { useTranslation } from "react-i18next";
import type { HookRow } from "../../api/client.types";
import { commandParts } from "../../lib/commandText";
import { Escaped } from "../../lib/outsideText";
import { Row } from "./CapabilityProposeCard";
import { Tag } from "./PluginContains";

/** The events a hook may fire on and still come in (server/services/plugin_package.py, QUIET_HOOK_EVENTS). A key is
 *  built only from this list, never from what the server sent. */
const QUIET = new Set(["SessionStart", "Setup", "PermissionDenied", "PostToolUse", "PostToolUseFailure", "Notification",
  "MessageDisplay", "SubagentStart", "StopFailure", "InstructionsLoaded", "CwdChanged", "DirectoryAdded", "FileChanged",
  "PostCompact", "PostModelSwitch", "SessionEnd"]);
/** The five events Arslan runs (docs/plans/0164/HOOK-plugin-hooks.md); their keys are built only from this list. Each
 *  has its own capability line (`hookCan_<event>`), as the card's table says what it can do. */
const RUN = new Set(["PreToolUse", "UserPromptSubmit", "Stop", "PostToolUse", "SessionStart"]);
const ON_A_TOOL = new Set(["PreToolUse", "PostToolUse"]);
/** Stands for the tools in "on {{tools}}", so each language keeps its own word order around them. */
const MARK = "\u0001";

type T = (key: string, options?: Record<string, unknown>) => string;

/** A hook Arslan runs (HOOK-3 marks it supported): only these get an entry of their own and a switch. */
export const runs = (hook: HookRow) => hook.kind === "supported" && RUN.has(hook.event);
/** When it runs, as the chip says it ("Before a tool runs"). */
export const hookWhen = (t: T, event: string) => RUN.has(event) ? t(`capabilityList.hookChip_${event}`) : event;
/** The exact command line: its command, then its arguments. */
export const commandLine = (hook: HookRow) => [hook.command ?? "", ...(hook.args ?? [])].join(" ").trim();

/** A command line as the shell reads it (`commandParts`): kept on its lines (pre-wrap), each line break a muted `⏎`
 *  before the real one, every other control character an escape, and what shows nothing `Escaped`'s marker. */
export function CommandText({ text }: { text: string }) {
  return <bdi data-testid="command-text" className="whitespace-pre-wrap">
    {commandParts(text).map((part, i) => part.kind === "text" ? <Escaped key={i} text={part.text} block />
      : part.kind === "break" ? <Fragment key={i}><span data-testid="command-break" className="text-muted-foreground">
        {"⏎"}</span>{"\n"}</Fragment>
      : <span key={i} data-testid="command-escape"
        className="mx-px rounded bg-fill px-1 font-mono text-[10px] text-muted-foreground">{part.text}</span>)}
  </bdi>;
}

/** What a tool hook matches, in Arslan's tool names; null for an event that isn't about a tool. */
function tools(t: T, hook: HookRow): { text: string; unsure: boolean } | null {
  if (!ON_A_TOOL.has(hook.event)) return null;
  if (hook.matches_note) return { text: t("capabilityList.hookUnsure"), unsure: true };
  return { text: hook.matches.includes("*") ? t("capabilityList.hookEveryTool") : hook.matches.join(", "), unsure: false };
}

/** The short form beside a hook's switch: its tools, "can't tell; every tool", or every conversation, message or answer. */
export function hookMatch(t: T, hook: HookRow): string {
  const on = tools(t, hook);
  if (!on) return t(`capabilityList.hookEvery_${hook.event}`);
  return on.unsure ? t("capabilityList.hookMatchUnsure") : on.text;
}

/** One hook Arslan runs, on its card (board 8, A): when, on what, the exact command line, and what it can do. */
function HookEntry({ hook }: { hook: HookRow }) {
  const { t } = useTranslation();
  const on = tools(t, hook);
  const [before, after = ""] = t("capabilityList.hookOn", { tools: MARK }).split(MARK);
  return <span data-testid="hook-entry" data-event={hook.event} className="flex flex-col gap-0.5">
    <span><Tag>{hookWhen(t, hook.event)}</Tag>{on && <> {before}
      <bdi data-testid="hook-entry-on" className={on.unsure ? "text-ask" : undefined}>{on.text}</bdi>{after}</>}</span>
    <code className="rounded-md bg-fill px-1.5 py-1 font-mono text-[12px] [overflow-wrap:anywhere]">
      <CommandText text={commandLine(hook)} /></code>
    <span data-testid="hook-entry-can" className="text-[12px] text-muted-foreground">
      {t(`capabilityList.hookCan_${hook.event}`)}</span>
  </span>;
}

/**
 * The Hooks row (CAP8-2's board 7; HOOK-4's board 8). Each hook Arslan runs gets an entry of its own, then one sentence
 * on how every hook runs. The hooks that don't run keep CAP8-2's words, by the user's hook rule: how many, when each
 * fires, and that what depends on them may not work. `rows` (HOOK-1) when the server sends them, else `hooks` (one
 * event per hook); nothing when there are none. The plugin card, CAP4's skill card and CAP6a's folder card show it.
 */
export function HooksRow({ hooks, rows, kind }: { hooks?: string[]; rows?: HookRow[]; kind: "plugin" | "skill" }) {
  const { t } = useTranslation();
  const running = (rows ?? []).filter(runs);
  const quiet = rows?.length ? rows.filter(hook => !runs(hook)).map(hook => hook.event) : hooks ?? [];
  if (!running.length && !quiet.length) return null;
  const events = [...new Set(quiet)].map(event => QUIET.has(event)
    ? t("capabilityList.hookEvent", { event, when: t(`capabilityList.hookWhen_${event}`) }) : event)
    .join(t("capabilityList.hookJoin"));
  return <Row label={t("capabilityList.hooksRow")}>
    <span data-testid="import-card-hooks" className="flex flex-col gap-2.5">
      {running.length > 0 && <>
        {running.map(hook => <HookEntry key={hook.id} hook={hook} />)}
        <span data-testid="hook-runs-note" className="text-[12px] text-muted-foreground">{t("capabilityList.hookRuns")}</span>
      </>}
      {quiet.length > 0 && <span className="flex flex-col gap-0.5">
        <span>{t("capabilityList.import_cardHooks", { count: quiet.length, events })}</span>
        <span className="text-[12px] text-warning">
          {t(kind === "skill" ? "capabilityList.hooksWarnSkill" : "capabilityList.import_cardHooksWarn")}</span>
      </span>}
    </span>
  </Row>;
}
