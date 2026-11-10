import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { capabilitiesApi } from "../../api/capabilities";
import type { ImportPluginRow, ImportResult, ImportRow, ImportScan, ImportSkillRow, ImportTick } from "../../api/client.types";
import { isolate } from "../../lib/outsideText";
import { Button, Dialog, Notice, Tag } from "../kit";
import ImportPluginCard from "./ImportPluginCard";

const TOOL = { claude_code: "Claude Code", codex: "Codex" } as const;
const REGISTRY: Record<string, string> = { npx: "npm", uvx: "PyPI" };
/** The codes `connection_import` and (CAP8-2) `tool_import` can refuse with. The key is chosen from this list, never
 *  built from what the server sent. */
const REFUSED = new Set(["unreadable", "cannot_pin", "unsafe_setting", "runs_a_helper", "transport", "blocked", "too_large"]);
const refusedKey = (code: string) => `capabilityList.import_refused_${REFUSED.has(code) ? code : "other"}`;
/** A plugin's own parts Arslan doesn't take (plugin_package's codes). With the part named, the line says which. */
const PARTS = new Set(["commands", "agents", "lsp", "other", "entry_adds_parts"]);
type Waiting = ImportResult & { card: NonNullable<ImportResult["card"]>; card_digest: string };
/** Parts of a line as they run: one holding a space or a quote, or an empty one, is quoted, so it can't read as two or none. */
const asLine = (parts: string[]) => parts.map(part => (/^$|[\s"]/.test(part) ? JSON.stringify(part) : part)).join(" ");
/** The state of one password input. An id can't hold a line break next to a name, and a Map has no `__proto__`. */
const keySlot = (row: ImportRow, name: string) => `${row.id}\n${name}`;

const Code = ({ children }: { children: ReactNode }) => <span className="block font-mono text-[11.5px] break-all"><bdi>{children}</bdi></span>;
const Small = ({ children, testId }: { children: ReactNode; testId?: string }) =>
  <span data-testid={testId} className="text-[12px] text-muted-foreground [overflow-wrap:anywhere]">{children}</span>;

/**
 * "Import connections" (v0.1.64 CAP8-1, the mock the user approved): what Claude Code and Codex have configured, one
 * row and one tick per server. Reached only by the button in Capabilities, which is when the files are read. A row
 * says what `server/services/connection_import.py` read, and a tick sends back that row's `id` and `digest`, so what
 * it adds is what it showed or nothing. Keys typed here live in this component and go only in their own row's `keys`.
 *
 * CAP8-2: Claude Code's skills are rows too, with the same parts. One is copied into Arslan's skills folder switched
 * off, and goes on through CAP6a's card in Capabilities. Its plugins are a group of their own (board 7): each starts
 * unticked, and with one ticked, Add adds the other picks first, then shows each plugin's card in turn
 * (`ImportPluginCard`). Only its "Add plugin" sends that plugin back, with the card's digest. One the server refused is
 * a red line with no tick.
 */
export default function ImportConnections({ onClose, onChanged }: { onClose: () => void; onChanged: () => void }) {
  const { t } = useTranslation();
  const [scan, setScan] = useState<ImportScan | null>(null);
  const [scanFailed, setScanFailed] = useState(false);
  // Ticks are held by `digest`, which differs per entry. A scan's ids are unique too (`_unique_ids` in the server), so a
  // key slot and a result line go by `id`, which is what the POST and its results carry.
  const [ticked, setTicked] = useState<Set<string>>(new Set());
  const [keys, setKeys] = useState<Map<string, string>>(new Map());
  const [busy, setBusy] = useState(false);
  const [addFailed, setAddFailed] = useState(false);
  const [results, setResults] = useState<ImportResult[] | null>(null);
  const [scanNumber, setScanNumber] = useState(0);
  // The plugins' cards still to answer, the results so far, and how many cards there were.
  const [waiting, setWaiting] = useState<Waiting[]>([]);
  const [sofar, setSofar] = useState<ImportResult[]>([]);
  const [cards, setCards] = useState(0);

  useEffect(() => {
    let live = true;
    capabilitiesApi.importScan().then(next => {
      if (!live) return;
      setScan(next);
      // The server decides, except that a refused row has nothing to tick and a program is only ever ticked by hand.
      setTicked(new Set([...next.servers.filter(r => r.tick && !r.refused && r.kind !== "program").map(r => r.digest),
        ...(next.skills ?? []).filter(r => r.tick && !r.refused).map(r => r.digest)]));
    }).catch(() => { if (live) setScanFailed(true); });
    return () => { live = false; };
  }, [scanNumber]);

  function scanAgain() {
    setScan(null); setScanFailed(false); setResults(null); setAddFailed(false); setWaiting([]); setSofar([]);
    setScanNumber(n => n + 1);
  }

  const rows = scan?.servers ?? [];
  const listed = rows.filter(r => !r.here);
  const here = rows.filter(r => r.here);
  const chosen = listed.filter(r => ticked.has(r.digest));
  const programTicked = chosen.some(r => r.kind === "program");
  const skills = scan?.skills ?? [];
  const listedSkills = skills.filter(r => !r.here);
  const chosenSkills = listedSkills.filter(r => !r.refused && ticked.has(r.digest));
  const plugins = scan?.plugins ?? [];
  const listedPlugins = plugins.filter(r => !r.here && !r.refused);
  const refusedPlugins = plugins.filter(r => !r.here && r.refused);
  const chosenPlugins = listedPlugins.filter(r => ticked.has(r.digest));
  const count = chosen.length + chosenSkills.length + chosenPlugins.length;
  const hereNames = [...here, ...skills.filter(r => r.here), ...plugins.filter(r => r.here)].map(r => isolate(r.name));

  /** Each card in turn; the results once none is left. */
  function next(left: Waiting[], done: ImportResult[]) {
    setWaiting(left); setSofar(done);
    if (!left.length) setResults(done);
  }

  async function add() {
    setBusy(true); setAddFailed(false);
    try {
      const { results: done } = await capabilitiesApi.importAdd(chosen.map(r => ({ id: r.id, digest: r.digest,
        keys: Object.fromEntries(r.asks.flatMap(name => {
          const value = keys.get(keySlot(r, name))?.trim();
          return value ? [[name, value]] : [];
        })) })), chosenSkills.map(r => ({ id: r.id, digest: r.digest, keys: {} })),
        chosenPlugins.map(r => ({ id: r.id, digest: r.digest, keys: {} })));
      setKeys(new Map());
      const cardsNow = done.filter((r): r is Waiting => r.state === "card" && !!r.card && !!r.card_digest);
      setCards(cardsNow.length);
      next(cardsNow, done.filter(r => r.state !== "card"));
    } catch { setAddFailed(true); }
    finally { setBusy(false); onChanged(); }     // also after a failure: some may have gone in before it
  }

  /** The card's answer: a yes sends this plugin back with the card's digest; a skip sends nothing. A card that comes
   *  back (what it showed changed, a lock moved) is shown again in its place. */
  async function answer(yes: boolean, cardKeys: Record<string, string> = {}) {
    const [current, ...rest] = waiting;
    const row = plugins.find(r => r.id === current.id);
    if (!yes || !row) return next(rest, [...sofar, { id: current.id, state: "skipped" }]);
    setBusy(true);
    let result: ImportResult;
    try {
      const tick: ImportTick = { id: row.id, digest: row.digest, keys: cardKeys, card: current.card_digest };
      result = (await capabilitiesApi.importAdd([], [], [tick])).results[0] ?? { id: row.id, state: "failed" };
    } catch { result = { id: row.id, state: "failed", stage: "install" }; }
    finally { setBusy(false); onChanged(); }
    if (result.state === "card" && result.card && result.card_digest) next([result as Waiting, ...rest], sofar);
    else next(rest, [...sofar, result]);
  }

  function runs(r: ImportRow) {
    if (r.refused) return <>
      <Small testId="import-refused">{t(refusedKey(r.refused))}</Small>
      {r.refused_part && r.refused_part !== r.name && <Code>{r.refused_part}</Code>}
      {r.command && <Code>{asLine([r.command, ...r.arguments])}</Code>}
      {r.address && <Code>{r.address}</Code>}
    </>;
    if (r.kind === "program") return <>
      <span data-testid="import-program" className="text-[12px] text-warning">{t("capabilityList.import_program")}</span>
      <Code>{asLine([r.command ?? "", ...r.arguments])}</Code>
    </>;
    if (r.kind === "remote") return <Small testId="import-runs">{t("capabilityList.import_remote", { address: isolate(r.address ?? "") })}</Small>;
    const start = r.arguments.findIndex(part => part !== "-y" && part !== "--yes");
    const rest = r.arguments.slice(start + 1);
    return <>
      <Small testId="import-runs">{t(r.network ? "capabilityList.import_packageNetwork" : "capabilityList.import_packageLocal",
        { registry: REGISTRY[r.command ?? ""] ?? r.command, package: isolate(r.arguments[start] ?? "") })}</Small>
      {rest.length > 0 && <Small>{t("capabilityList.import_arguments")} <Code>{asLine(rest)}</Code></Small>}
    </>;
  }

  const toggle = (digest: string) => setTicked(old => {
    const next = new Set(old);
    if (next.has(digest)) next.delete(digest); else next.add(digest);
    return next;
  });

  /** Why one was refused. A hook (the user's hook rule) or a part Arslan doesn't take names its event or part. */
  const why = (code: string, part: string | null) => code === "hooks" && part ? t("capabilityList.import_refused_hooks", { part })
    : PARTS.has(code) && part ? t("capabilityList.import_refused_parts", { part }) : t(refusedKey(code));
  const named = (code: string) => code === "hooks" || PARTS.has(code);
  const hookCount = (n: number) => t("capabilityList.import_pluginHooks", { count: n });

  /** CAP8-2: a skill, with a server row's parts. A refused one can't be ticked, whatever the server's tick said. */
  const skillRow = (r: ImportSkillRow) => {
    const first = r.same_as ? skills.find(other => other.id === r.same_as) : undefined;
    return <div key={r.digest} data-testid="import-row" data-name={r.name} className="flex flex-col gap-1.5 border-t border-border py-2.5 text-[13px] leading-snug">
      <label className="grid cursor-pointer grid-cols-[18px_minmax(0,1fr)] items-start gap-2.5 has-[:disabled]:cursor-default">
        <input type="checkbox" checked={!r.refused && ticked.has(r.digest)} disabled={!!r.refused} className="mt-0.5 h-[15px] w-[15px] accent-foreground"
          onChange={() => { if (!r.refused) toggle(r.digest); }} />
        <span className="flex min-w-0 flex-col gap-0.5">
          <span className="flex flex-wrap items-center gap-2"><bdi className="font-semibold [overflow-wrap:anywhere]">{r.name}</bdi><Tag>{TOOL[r.tool]}</Tag></span>
          {r.refused ? <>
            <Small testId="import-refused">{why(r.refused, r.refused_part)}</Small>
            {r.refused_part && r.refused_part !== r.name && !named(r.refused) && <Code>{r.refused_part}</Code>}
          </> : <>
            <Small testId="import-skill">{t("capabilityList.import_skill")}</Small>
            {r.scripts.length > 0 && <Small>{t("capabilityList.import_skillScripts")} <Code>{r.scripts.join(", ")}</Code></Small>}
            {r.scan === "warn" && <Small>{t("capabilityList.import_skillWarn")}</Small>}
            {(r.hooks?.length ?? 0) > 0 && <Small>{hookCount(r.hooks!.length)}</Small>}
          </>}
          {r.left > 0 && <Small>{t("capabilityList.import_skillLeft", { count: r.left })}</Small>}
          {first && <Small>{t("capabilityList.import_sameSkill", { name: isolate(first.name) })}</Small>}
        </span>
      </label>
    </div>;
  };

  /** Board 7: a plugin, with the same parts, always unticked until the user ticks it: its card comes before it's added. */
  const pluginRow = (r: ImportPluginRow) => {
    const first = r.same_as ? plugins.find(other => other.id === r.same_as) : undefined;
    const parts = [r.skills.length > 0 && t("capabilityList.import_pluginSkills", { count: r.skills.length }),
      r.connections.length > 0 && t("capabilityList.import_pluginConnections", { count: r.connections.length }),
      r.hooks.length > 0 && hookCount(r.hooks.length)].filter(Boolean).join(t("capabilityList.listJoin"));
    return <div key={r.digest} data-testid="import-row" data-name={r.name} className="flex flex-col gap-1.5 border-t border-border py-2.5 text-[13px] leading-snug">
      <label className="grid cursor-pointer grid-cols-[18px_minmax(0,1fr)] items-start gap-2.5">
        <input type="checkbox" checked={ticked.has(r.digest)} className="mt-0.5 h-[15px] w-[15px] accent-foreground"
          onChange={() => toggle(r.digest)} />
        <span className="flex min-w-0 flex-col gap-0.5">
          <span className="flex flex-wrap items-center gap-2"><bdi className="font-semibold [overflow-wrap:anywhere]">{r.name}</bdi><Tag>{TOOL[r.tool]}</Tag></span>
          <Small testId="import-plugin">{parts ? t("capabilityList.import_plugin", { parts }) : t("capabilityList.import_pluginCard")}</Small>
          {first && <Small>{t("capabilityList.import_samePlugin", { name: isolate(first.name) })}</Small>}
        </span>
      </label>
    </div>;
  };
  const group = (key: "connections" | "skills" | "plugins") => <p data-testid={`import-group-${key}`}
    className="pb-1.5 pt-3.5 text-[12px] font-semibold text-muted-foreground first:pt-1.5">{t(`capabilityList.section_${key}`)}</p>;

  const row = (r: ImportRow) => {
    const first = r.same_as ? rows.find(other => other.id === r.same_as) : undefined;
    return <div key={r.digest} data-testid="import-row" data-name={r.name} className="flex flex-col gap-1.5 border-t border-border py-2.5 text-[13px] leading-snug">
      <label className="grid cursor-pointer grid-cols-[18px_minmax(0,1fr)] items-start gap-2.5 has-[:disabled]:cursor-default">
        <input type="checkbox" checked={ticked.has(r.digest)} disabled={!!r.refused} className="mt-0.5 h-[15px] w-[15px] accent-foreground"
          onChange={() => { if (!r.refused) toggle(r.digest); }} />
        <span className="flex min-w-0 flex-col gap-0.5">
          <span className="flex flex-wrap items-center gap-2"><bdi className="font-semibold [overflow-wrap:anywhere]">{r.name}</bdi><Tag>{TOOL[r.tool]}</Tag></span>
          {runs(r)}
          {!r.on_there && <Small>{t("capabilityList.import_off", { tool: TOOL[r.tool] })}</Small>}
          {r.tool_limits && <Small>{t("capabilityList.import_limits")}</Small>}
          {first && <Small>{t("capabilityList.import_same", { name: isolate(first.name), tool: TOOL[first.tool] })}</Small>}
          {r.env.length > 0 && <Small testId="import-env">{t(r.kind === "remote" ? "capabilityList.import_headers" : "capabilityList.import_env",
            { names: r.env.join(", ") })}</Small>}
          {r.keys > 0 && <Small>{t("capabilityList.import_keys", { count: r.keys })}</Small>}
        </span>
      </label>
      {!r.refused && r.asks.map(name => <label key={name} className="ml-[28px] flex flex-col gap-0.5">
        <span className="font-mono text-[11.5px] break-all">{name}</span>
        <input type="password" autoComplete="off" disabled={!ticked.has(r.digest)} value={keys.get(keySlot(r, name)) ?? ""}
          onChange={event => { const { value } = event.target; setKeys(old => new Map(old).set(keySlot(r, name), value)); }}
          className="rounded-lg border border-border bg-background px-2 py-1 text-[12.5px] disabled:opacity-50" />
      </label>)}
    </div>;
  };

  const resultLine = (result: ImportResult) => {
    const server = rows.find(r => r.id === result.id) ?? skills.find(r => r.id === result.id)
      ?? plugins.find(r => r.id === result.id);
    if (!server) return null;
    const name = isolate(server.name);
    const part = "refused_part" in server && server.refused === result.code ? server.refused_part : null;
    const words = server.kind === "skill" && result.state === "added" ? t("capabilityList.import_result_copied", { name })
      : result.state === "on" ? t("discover.result_on", { name, count: result.tools ?? 0 })
      : result.state === "needs_sign_in" ? t("discover.result_signIn", { name })
      : result.state === "blocked" ? t("discover.result_blocked", { name })
      : result.state === "failed" ? t("discover.result_failed", { name, stage: result.stage ?? "", detail: result.detail ?? result.code ?? "" })
      : result.state === "refused" ? `${t("capabilityList.import_result_refused", { name })} ${why(result.code ?? "", part)}`
      : result.state === "needs_keys" ? t("capabilityList.import_result_needs_keys", { name, keys: (result.keys ?? []).join(", ") })
      : t(`capabilityList.import_result_${result.state}`, { name });
    const tone = result.state === "on" ? "text-success" : result.state === "failed" || result.state === "blocked" || result.state === "refused"
      ? "text-danger-strong" : result.state === "added" && server.kind !== "skill" ? "text-warning" : "text-muted-foreground";
    return <p key={result.id} data-testid={`import-result-${result.state}`} data-state={result.state}
      className={`border-t border-border py-2.5 text-[13px] leading-snug [overflow-wrap:anywhere] ${tone}`}>{words}</p>;
  };

  const rescanOffered = results?.some(r => r.state === "gone" || r.state === "changed" || r.state === "needs_keys");
  const card = waiting[0];
  const footer = results ? <>
    {rescanOffered && <Button data-testid="import-rescan" onClick={scanAgain}>{t("capabilityList.import_rescan")}</Button>}
    <Button tone="primary" data-testid="import-done" onClick={onClose}>{t("capabilityList.import_done")}</Button>
  </> : card ? null : scan ? <div className="flex w-full flex-col gap-2">
    {addFailed && <Notice tone="error" role="alert" testId="import-add-failed">{t("capabilityList.import_addFailed")}</Notice>}
    <div className="flex flex-wrap items-center gap-2.5">
      <Button tone="primary" data-testid="import-add" disabled={busy || count === 0} onClick={() => void add()}>
        {busy ? t("capabilityList.import_adding")
          : chosenPlugins.length > 0 ? t(chosenPlugins.length === 1 ? "capabilityList.import_addThenPlugin"
            : "capabilityList.import_addThenPlugins", { count })
          : chosenSkills.length > 0 ? t("capabilityList.import_addMixed", { count })
          : t("capabilityList.import_add", { count })}</Button>
      <Button data-testid="import-not-now" disabled={busy} onClick={onClose}>{t("capabilityList.import_notNow")}</Button>
    </div>
    {/* A custom program isn't tested (`added`), so "each one" is said only while none is ticked; and a skill isn't
        tested at all, so the connections' line goes while only skills are ticked. */}
    <span data-testid="import-foot" className="text-[11px] text-subtle-foreground">{t("capabilityList.import_keysFoot")}{" "}
      {t("capabilityList.import_shownFoot")}
      {(chosen.length > 0 || chosenSkills.length === 0) && <>{" "}
        {t(programTicked ? "capabilityList.import_programFoot" : "capabilityList.import_testedFoot")}</>}
      {chosenSkills.length > 0 && <>{" "}{t("capabilityList.import_skillFoot")}</>}</span>
  </div> : null;

  return <Dialog open onClose={onClose} busy={busy} width={600} padded testId="cap-import-sheet" title={t("capabilityList.import_open")} footer={footer}>
    {results ? <div data-testid="import-results" className="flex flex-col">{results.map(resultLine)}</div>
      : card ? <ImportPluginCard key={`${card.id}\n${card.card_digest}`} card={card.card} n={cards - waiting.length + 1}
        total={cards} others={sofar.some(r => !plugins.some(p => p.id === r.id))} busy={busy}
        onAdd={cardKeys => void answer(true, cardKeys)} onSkip={() => void answer(false)} />
      : <div className="flex flex-col gap-3">
      <p className="text-[13px] text-muted-foreground">{t("capabilityList.import_intro")}</p>
      {scanFailed ? <div className="flex flex-col items-start gap-2">
        <Notice tone="error" role="alert" testId="import-scan-failed">{t("capabilityList.import_scanFailed")}</Notice>
        <Button data-testid="import-rescan" onClick={scanAgain}>{t("capabilityList.import_rescan")}</Button>
      </div> : !scan ? <p className="text-[13px] text-subtle-foreground">{t("capabilityList.import_scanning")}</p> : <>
        {scan.tools.filter(tool => tool.state === "malformed").map(tool => <Notice key={tool.tool} tone="warn" testId="import-malformed">
          {t("capabilityList.import_malformed", { tool: TOOL[tool.tool] })}</Notice>)}
        {rows.length + skills.length + plugins.length === 0 && <p data-testid="import-nothing" className="text-[13px] text-subtle-foreground">{t("capabilityList.import_nothing")}</p>}
        {rows.length + skills.length + plugins.length > 0 && <div className="flex flex-col">
          {listed.length > 0 && group("connections")}
          {listed.map(row)}
          {listedSkills.length > 0 && group("skills")}
          {listedSkills.map(skillRow)}
          {listedPlugins.length > 0 && group("plugins")}
          {listedPlugins.map(pluginRow)}
          {/* Board 7: a plugin that can't come in is one red line naming why, with no tick; then what is already here. */}
          {refusedPlugins.length + hereNames.length > 0 && <div className="flex flex-col gap-0.5 border-t border-border py-2.5 pl-[28px] text-[12px] [overflow-wrap:anywhere]">
            {refusedPlugins.map(r => <span key={r.digest} data-testid="import-plugin-refused" className="text-danger-strong">
              {t("capabilityList.import_pluginRefused", { name: isolate(r.name) })} {why(r.refused!, r.refused_part)}</span>)}
            {hereNames.length > 0 && <span data-testid="import-here" className="text-muted-foreground">
              {t("capabilityList.import_here", { names: hereNames.join(", ") })}</span>}
          </div>}
        </div>}
      </>}
    </div>}
  </Dialog>;
}
