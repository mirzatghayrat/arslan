import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronRight, FolderOpen, Plug, ScrollText, Smartphone } from "lucide-react";
import type { ConversationChangeTurn, ConversationFile, RepoChanges as Repo } from "../../api/files";
import { filesApi } from "../../api/files";
import { ApiError, api } from "../../api/client";
import type { RunCheckpoint } from "../../api/client.types";
import UndoTurnSheet from "../reply/UndoTurnSheet";
import { toast } from "../kit";
import { listMcpServers, reconnectMcpServer } from "../../api/mcp";
import { lessonsApi } from "../../api/lessons";
import type { McpServer, ProviderConfig, ProviderOption } from "../../api/client.types";
import { formatUiDateTime } from "../../lib/localeFormatting";
import { baseName } from "../../lib/fileKinds";
import { useSettingsStore } from "../../stores/settingsStore";
import { useWorkbench } from "../../stores/workbenchStore";
import { useArslanStore } from "../../stores/arslanStore";
import { isolate } from "../CapabilitySwitches";
import ConversationModelChip, { PART_LABEL, ringRows } from "../models/ConversationModelChip";
import { useConversationModel } from "../models/useConversationModel";
import { opensDiff } from "./DiffReader";
import FileIcon from "./FileIcon";
import RepoChanges, { gitError } from "./RepoChanges";
import { HEADING } from "./FilesTab";

/** What the workbench needs from App to show and change this conversation's model (the chip's own props). */
export type OverviewModels = {
  configs: ProviderConfig[]; llmProviders: ProviderOption[];
  onSetDefault: (configId: number) => Promise<void> | void; onManage?: () => void;
};

/** The ring's parts, coloured in the bar (the breakdown's order). */
const PART_COLOR: Record<keyof typeof PART_LABEL, string> = {
  system: "bg-subtle-foreground", tools: "bg-info", context: "bg-success", history: "bg-primary", turn: "bg-muted-foreground",
};
const row = "flex min-w-0 items-center gap-2 py-1 text-[12.5px]";
const KIND_COLOR = { made: "text-success", edited: "text-muted-foreground", deleted: "text-danger" } as const;
/** A turn's paths shown before "N more" (④参谋's review of #545: a run can list thousands). */
export const PATHS_SHOWN = 6;
/** Changes reloads this often while shown, as the panel's file poll: a turn's checkpoint is written after the turn
 * ends (host_run's finally), so the reload at its end can come before it (④参谋's recheck of PR 545). */
export const CHANGES_MS = 10_000;
/** "a/b/c.txt" as its name and the folder before it: a long path keeps its name in view. */
function splitPath(path: string): [string, string] {
  const i = path.lastIndexOf("/");
  return i < 0 ? [path, ""] : [path.slice(i + 1), path.slice(0, i + 1)];
}
const link = "shrink-0 rounded-md px-1.5 py-0.5 text-[11.5px] text-muted-foreground hover:bg-foreground/5 hover:text-foreground";

/** Newest first: by creation time when the server sent one, else the server's order reversed. */
export function newestFirst(files: ConversationFile[]): ConversationFile[] {
  return files.map((f, i) => ({ f, i }))
    .sort((a, b) => (b.f.created_at ?? "").localeCompare(a.f.created_at ?? "") || b.i - a.i)
    .map(({ f }) => f);
}

/** Connectors that need something, and how many others are ready. A switched-off or starting server is neither. */
export function connectorSummary(servers: McpServer[]) {
  const needs = servers.filter((s) => s.shown === "needs_auth" || s.shown === "failed" || s.shown === "parked");
  return { needs, readyCount: servers.filter((s) => s.shown === "ready").length };
}

/**
 * Overview (WB1-2, v0.1.64): the workbench's default tab, after Claude desktop's side rail (user,
 * 2026-10-30). Environment (the conversation's model, its folder, the iPhone remote), Deliverables
 * (every file this conversation made, newest first: the one place they are listed), Context (the
 * K4b breakdown as rows) and Connectors (only the MCP servers that need something). Background jobs
 * are Progress, not repeated here. All of it reads data the app already has.
 */
export default function OverviewTab({ conversationId, files, home, models, onOpenCapabilities, onOpenSettings }: {
  conversationId: string; files: ConversationFile[]; home: string | null; models?: OverviewModels;
  onOpenCapabilities?: () => void; onOpenSettings?: (section: string) => void;
}) {
  const { t, i18n } = useTranslation();
  const openReader = useWorkbench((s) => s.openReader);
  const bridgeOn = useSettingsStore((s) => s.settings?.phone_bridge_enabled ?? false);
  const { pct, lastInput, parts, window: contextWindow } = useConversationModel(conversationId, models?.configs ?? []);
  const rows = ringRows(parts, lastInput);
  const fmt = (n: number) => n.toLocaleString(i18n.resolvedLanguage || undefined);
  const delivered = useMemo(() => newestFirst(files), [files]);

  const [servers, setServers] = useState<McpServer[] | null>(null);
  const loadServers = useCallback(async () => {
    try { setServers(await listMcpServers()); } catch { /* keep the last list */ }
  }, []);
  useEffect(() => { void loadServers(); }, [loadServers]);
  const { needs, readyCount } = connectorSummary(servers ?? []);

  // L11-0 (the user's pick): the rules files this conversation follows, as one row in Environment.
  type RuleFile = { file: string; text: string; added?: { lesson_id: number; line: string }[] };
  const [rules, setRules] = useState<{ id: string; enabled: boolean; files: RuleFile[] } | null>(null);
  const [rulesOpen, setRulesOpen] = useState(false);
  const [rulesTick, setRulesTick] = useState(0);
  useEffect(() => {
    let alive = true;
    Promise.resolve().then(() => lessonsApi.folderRules(conversationId))
      .then((r) => { if (alive) setRules({ id: conversationId, enabled: r.enabled, files: r.files }); })
      .catch(() => { /* no row: rules are context */ });
    return () => { alive = false; };
  }, [conversationId, files.length, home, rulesTick]);
  // L11-2 (#603 review, F3): a line the card added can be taken back out here, after a reload or a switch too.
  // L11-3a: from the rules record, so it still works once the lesson was deleted in Memory.
  const removeRule = async (file: string, added: { lesson_id: number; line: string }) => {
    try {
      const r = await lessonsApi.removeFolderRule(conversationId, file, added.lesson_id, added.line);
      if (!r.in_file) toast(t("workbench.ruleNotInFile"));             // #621 review, F3
    } catch { toast(t("workbench.ruleFailed")); }
    setRulesTick((n) => n + 1);
  };
  const shownRules = rules?.id === conversationId ? rules : null;

  // WB1-3: what each turn changed in the user's folders (the S3 checkpoints), and its undo.
  const [changes, setChanges] = useState<ConversationChangeTurn[]>([]);
  // DIFF2: the folder as a git repo, kept with the conversation it was asked for, so another conversation's answer
  // is never drawn, not even for the first render after a switch (#588 review).
  const [repoFor, setRepoFor] = useState<{ id: string; repo: Repo | null } | null>(null);
  const repo = repoFor?.id === conversationId ? repoFor.repo : null;
  const repoAsking = useRef<string | null>(null);
  const [undo, setUndo] = useState<{ runId: number; info: RunCheckpoint } | null>(null);
  const [opened, setOpened] = useState<number[]>([]);
  const heading = useRef<HTMLHeadingElement>(null);
  const opener = useRef<HTMLButtonElement | null>(null);
  const turns = useArslanStore((s) => s.items.length);          // a turn that changed files but delivered none
  // Another conversation's turns never show here, nor its undo (④参谋's review of #545): the list is emptied
  // when the conversation changes, an answer for one no longer shown is dropped, and "no such conversation"
  // (404, a new one) is an empty list; any other failure keeps this conversation's last list.
  const current = useRef(conversationId);
  current.current = conversationId;
  useEffect(() => { setChanges([]); setUndo(null); setOpened([]); }, [conversationId]);
  const loadChanges = useCallback(async () => {
    const asked = conversationId;
    try {
      // Deferred into the promise so an unavailable client (offline, or a test's partial mock) is a rejection.
      const found = await Promise.resolve().then(() => filesApi.changes(asked));
      if (current.current === asked) setChanges(found.turns);
    } catch (err) {
      if (current.current === asked && err instanceof ApiError && err.status === 404) setChanges([]);
    }
  }, [conversationId]);
  useEffect(() => { void loadChanges(); }, [loadChanges, files.length, turns]);
  useEffect(() => {
    const timer = setInterval(() => { if (document.visibilityState !== "hidden") void loadChanges(); }, CHANGES_MS);
    return () => clearInterval(timer);
  }, [loadChanges]);
  // DIFF2: the repo on its own timer, never per chat item, and one request at a time per conversation: a large repo's
  // first answer can take longer than the poll (#588 review, F4).
  const loadRepo = useCallback(async () => {
    const asked = conversationId;
    if (repoAsking.current === asked) return;
    repoAsking.current = asked;
    try {
      const found = await Promise.resolve().then(() => filesApi.repoChanges(asked));
      if (current.current === asked) setRepoFor({ id: asked, repo: found.repo });
    } catch { /* keep the last answer */ } finally {
      if (repoAsking.current === asked) repoAsking.current = null;
    }
  }, [conversationId]);
  useEffect(() => {
    void loadRepo();
    const timer = setInterval(() => { if (document.visibilityState !== "hidden") void loadRepo(); }, CHANGES_MS);
    return () => clearInterval(timer);
  }, [loadRepo]);
  // DIFF2 (#588 review, F7): in a repo folder the repo's list is the one place a change shows; a turn's paths there are
  // left out of the per-turn list (its undo stays in the reply), and paths in other folders keep DIFF1's rows.
  const repoShown = !!repo && !gitError(repo);
  // `home` comes home-relative ("~/Code/journal"), the turn's folder absolute: the same folder only when what comes before
  // is itself a home folder, so "/Users/u/Other/Code/journal" isn't taken for it (⓪Plan's re-check of #588).
  const inRepo = (folder: string) => {
    if (!repoShown || !home) return false;
    if (!home.startsWith("~/")) return folder === home;
    const rest = home.slice(1);
    return folder.endsWith(rest) && /^\/(Users|home)\/[^/]+$/.test(folder.slice(0, folder.length - rest.length));
  };
  const shownTurns = changes.map((turn) => ({ ...turn, paths: turn.paths.filter((p) => !inRepo(p.folder)) }))
    .filter((turn) => turn.paths.length > 0);
  const askUndo = async (runId: number, button: HTMLButtonElement) => {
    opener.current = button;
    try { setUndo({ runId, info: await api.runCheckpoint(runId) }); } catch { toast(t("process.undoFailed")); }
  };

  return (
    <div className="flex h-full min-h-0 flex-col gap-5 overflow-y-auto p-3" data-testid="overview-tab">
      <section data-testid="overview-environment">
        <h3 className={HEADING}>{t("workbench.envH")}</h3>
        <div className="mt-1.5 space-y-0.5">
          {models && <div className={row}>
            <ConversationModelChip conversationId={conversationId} configs={models.configs} llmProviders={models.llmProviders}
              onSetDefault={models.onSetDefault} onManage={models.onManage} below noRing /></div>}
          {home && <div className={row}>
            <FolderOpen size={14} className="shrink-0 text-muted-foreground" aria-hidden />
            <span className="min-w-0 flex-1 truncate font-mono text-[12px]" title={home}>{home}</span>
            <button type="button" className={link} onClick={() => void filesApi.reveal(home)} data-testid="overview-reveal">
              {t("workbench.reveal")}</button>
          </div>}
          {shownRules && (!shownRules.enabled || shownRules.files.length > 0) && <div data-testid="overview-rules">
            <div className={row}>
              <ScrollText size={14} className="shrink-0 text-muted-foreground" aria-hidden />
              <span className="min-w-0 flex-1 truncate">{shownRules.enabled
                ? t("workbench.rulesRow", { count: shownRules.files.length }) : t("workbench.rulesOff")}</span>
              {shownRules.enabled && <button type="button" className={link} aria-expanded={rulesOpen} data-testid="overview-rules-toggle"
                onClick={() => setRulesOpen(!rulesOpen)}>{t(rulesOpen ? "workbench.rulesHide" : "workbench.rulesShow")}</button>}
            </div>
            {shownRules.enabled && rulesOpen && <div className="mb-1 ml-[22px]">
              <ul className="space-y-0.5">{shownRules.files.map((f) => <li key={f.file} data-testid="overview-rules-file">
                <button type="button" className="max-w-full truncate text-left font-mono text-[11.5px] hover:underline"
                  onClick={() => openReader({ kind: "text", name: f.file, text: f.text })}>{isolate(f.file)}</button>
                {(f.added ?? []).map((a, i) => <div key={`${i}-${a.lesson_id}`} className="ml-3 flex min-w-0 items-center gap-2 text-[11.5px]"
                  data-testid="overview-rules-added">
                  <span className="min-w-0 flex-1 truncate text-muted-foreground">{isolate(a.line)}</span>
                  <button type="button" className={link} onClick={() => void removeRule(f.file, a)}>{t("workbench.ruleRemove")}</button>
                </div>)}</li>)}</ul>
              <p className="mt-0.5 text-[11px] leading-snug text-subtle-foreground">{t("workbench.rulesNote")}</p>
            </div>}
          </div>}
          <div className={row}>
            <Smartphone size={14} className="shrink-0 text-muted-foreground" aria-hidden />
            <span className="min-w-0 flex-1 truncate">{t("workbench.bridge")}</span>
            {/* State only: the switch stays in Settings, beside pairing (not a one-click toggle here). */}
            <button type="button" className={link} onClick={() => onOpenSettings?.("connections")} data-testid="overview-bridge">
              {t(bridgeOn ? "workbench.bridgeOn" : "workbench.bridgeOff")}</button>
          </div>
        </div>
      </section>

      <section data-testid="overview-deliverables">
        <h3 className={HEADING}>{t("validation.artifacts")}</h3>
        {delivered.length === 0 ? <p className="mt-1.5 text-[12.5px] text-muted-foreground">{t("workbench.noConvFiles")}</p>
          : <ul className="mt-1 space-y-0.5" data-testid="conv-files">{delivered.map((f) => (
            <li key={`${f.run_id}-${f.filename}`}>
              <button type="button" onClick={() => openReader({ kind: "artifact", file: f })}
                className="flex w-full items-center gap-2 rounded-lg px-1.5 py-1 text-left hover:bg-foreground/[0.04]">
                <FileIcon name={f.title} size={13} />
                <span className="min-w-0 flex-1 truncate text-[13px]">{baseName(f.title)}</span>
                <span className="shrink-0 text-[11px] text-subtle-foreground">
                  {f.created_at ? `${formatUiDateTime(f.created_at, i18n.language)} · ` : ""}{Math.max(1, Math.ceil(f.bytes / 1024))} KB</span>
              </button>
            </li>))}</ul>}
      </section>

      {(shownTurns.length > 0 || repo) && <section data-testid="overview-changes">
        <h3 ref={heading} tabIndex={-1} className={`${HEADING} outline-none`}>{t("workbench.chH")}</h3>
        {repo && <RepoChanges repo={repo} conversationId={conversationId} folder={home ?? ""} />}
        {shownTurns.length > 0 && <p className="mt-2 text-[11px] text-subtle-foreground">{t("workbench.chNote")}</p>}
        <ul className="mt-1.5 space-y-2">{shownTurns.map((turn) => {
          const all = opened.includes(turn.run_id);
          const shown = all ? turn.paths : turn.paths.slice(0, PATHS_SHOWN);
          return <li key={turn.run_id} data-testid={`overview-turn-${turn.run_id}`} data-undone={turn.undone || undefined}
            className={turn.undone ? "opacity-60" : ""}>
            <div className="flex items-center gap-2 text-[11.5px] text-muted-foreground">
              <span className="min-w-0 flex-1 truncate">{turn.at ? formatUiDateTime(turn.at, i18n.language) : ""}</span>
              {turn.undone ? <span className="shrink-0 rounded bg-fill px-1.5 text-[10.5px]" data-testid={`overview-undone-${turn.run_id}`}>
                {t("workbench.undone")}</span>
                : <button type="button" className={link} onClick={(e) => void askUndo(turn.run_id, e.currentTarget)}
                  data-testid={`overview-undo-${turn.run_id}`}>{t("process.undoTurn")}</button>}
            </div>
            <ul className="mt-0.5 space-y-0.5">{shown.map((p) => {
              const [name, dir] = splitPath(p.path);
              const parts = <>
                <span className={`min-w-12 shrink-0 text-[11px] ${KIND_COLOR[p.kind]}`}>{t(`workbench.${p.kind}`)}</span>
                <span className="min-w-0 max-w-[70%] truncate" data-testid="overview-change-name">{isolate(name)}</span>
                {dir && <span className="min-w-0 flex-1 truncate text-[11px] text-subtle-foreground" dir="rtl">{isolate(dir)}</span>}
              </>;
              const line = "flex w-full min-w-0 items-center gap-2 text-[12.5px]";
              // DIFF1: a text path of a turn that can still be undone opens its line diff (made and deleted too).
              return <li key={`${p.folder}/${p.path}`} title={isolate(`${p.folder}/${p.path}`)}>
                {!turn.undone && opensDiff(p.path)
                  ? <button type="button" data-testid="overview-change-open"
                    className={`${line} -mx-1 rounded-md px-1 text-left hover:bg-foreground/[0.04]`}
                    onClick={() => openReader({ kind: "diff", conversationId, runId: turn.run_id, folder: p.folder, path: p.path })}>
                    {parts}<ChevronRight size={13} className="ml-auto shrink-0 text-subtle-foreground" aria-hidden /></button>
                  : <div className={line}>{parts}</div>}
              </li>;
            })}</ul>
            {turn.paths.length > PATHS_SHOWN && !all && <button type="button" className={`${link} mt-0.5`}
              data-testid={`overview-more-${turn.run_id}`} onClick={() => setOpened([...opened, turn.run_id])}>
              {t("workbench.morePaths", { count: turn.paths.length - PATHS_SHOWN })}</button>}
          </li>;
        })}</ul>
        {undo && <UndoTurnSheet runId={undo.runId} info={undo.info} onClose={() => {
          setUndo(null);
          // Back to the Undo button that opened the sheet (Cancel); once the list shows the turn undone, that
          // button is gone, so the section's heading, not the page.
          void loadChanges().then(() => requestAnimationFrame(() =>
            (opener.current?.isConnected ? opener.current : heading.current)?.focus()));
        }} />}
      </section>}

      {pct != null && <section data-testid="overview-context">
        <h3 className={HEADING}>{t("workbench.ctxH")}</h3>
        <div className="mt-1.5 flex items-baseline justify-between text-[12.5px]">
          <span>{t("models.context", { pct })}</span>
          <span className="font-mono text-[11.5px] text-muted-foreground">{fmt(lastInput!)} / {fmt(contextWindow!)}</span>
        </div>
        <div className="mt-1.5 flex h-1.5 overflow-hidden rounded-full bg-fill" aria-hidden>
          {rows.map((r) => <span key={r.key} className={PART_COLOR[r.key]} style={{ width: `${(r.tokens / contextWindow!) * 100}%` }} />)}
        </div>
        {rows.length > 0 && <>
          <ul className="mt-2 space-y-1 text-[12px]">
            {rows.map((r) => <li key={r.key} data-testid={`overview-part-${r.key}`} className="flex items-center gap-2">
              <span className={`h-2 w-2 shrink-0 rounded-sm ${PART_COLOR[r.key]}`} aria-hidden />
              <span className="flex-1">{t(PART_LABEL[r.key])}</span>
              <span className="font-mono text-muted-foreground">{t("models.about", { value: fmt(r.tokens) })}</span>
              <span className="w-9 text-right font-mono text-subtle-foreground">{r.pct}%</span>
            </li>)}
          </ul>
          <p className="mt-1.5 text-[11px] text-subtle-foreground">{t("models.contextEstimated")}</p>
        </>}
      </section>}

      {(needs.length > 0 || readyCount > 0) && <section data-testid="overview-connectors">
        <h3 className={HEADING}>{t("workbench.conH")}</h3>
        <ul className="mt-1.5 space-y-0.5">
          {needs.map((s) => <li key={s.id} className={row} data-testid={`overview-connector-${s.id}`}>
            <Plug size={14} className="shrink-0 text-muted-foreground" aria-hidden />
            <span className="min-w-0 flex-1 truncate">{s.label}{" "}
              <span className="text-[11.5px] text-warning">{t(s.shown === "needs_auth" ? "workbench.needsSignIn" : "workbench.cantConnect")}</span></span>
            {s.shown === "needs_auth"
              // Sign-in runs where it always has (Capabilities' Authorize): its URL must come from the backend to the shell only.
              ? <button type="button" className={link} onClick={() => onOpenCapabilities?.()}>{t("workbench.signIn")}</button>
              : <button type="button" className={link} onClick={() => void reconnectMcpServer(s.id).then(loadServers, loadServers)}
                data-testid={`overview-retry-${s.id}`}>{t("workbench.retry")}</button>}
          </li>)}
          {readyCount > 0 && <li className={row} data-testid="overview-connectors-ok">
            <Plug size={14} className="shrink-0 text-muted-foreground" aria-hidden />
            <span className="min-w-0 flex-1 truncate text-muted-foreground">{t("workbench.othersOk", { count: readyCount })}</span>
            <button type="button" className={link} onClick={() => onOpenCapabilities?.()}>{t("workbench.manage")}</button>
          </li>}
        </ul>
      </section>}
    </div>
  );
}
