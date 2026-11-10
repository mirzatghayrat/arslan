import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { capabilitiesApi } from "../../api/capabilities";
import type { ImportResult, ImportRow, ImportScan, ImportSkillRow } from "../../api/client.types";
import { isolate } from "../../lib/outsideText";
import { Button, Dialog, Notice, Tag } from "../kit";

const TOOL = { claude_code: "Claude Code", codex: "Codex" } as const;
const REGISTRY: Record<string, string> = { npx: "npm", uvx: "PyPI" };
/** The codes `connection_import` and (CAP8-2) `tool_import` can refuse with. The key is chosen from this list, never
 *  built from what the server sent. */
const REFUSED = new Set(["unreadable", "cannot_pin", "unsafe_setting", "runs_a_helper", "transport", "blocked", "too_large"]);
const refusedKey = (code: string) => `capabilityList.import_refused_${REFUSED.has(code) ? code : "other"}`;
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
 * off, and goes on through CAP6a's card in Capabilities. The scan also lists plugins, which aren't drawn here: a plugin's
 * card comes before its install, on this sheet, and that card needs its own board first.
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
    setScan(null); setScanFailed(false); setResults(null); setAddFailed(false);
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
  const count = chosen.length + chosenSkills.length;

  async function add() {
    setBusy(true); setAddFailed(false);
    try {
      const { results: done } = await capabilitiesApi.importAdd(chosen.map(r => ({ id: r.id, digest: r.digest,
        keys: Object.fromEntries(r.asks.flatMap(name => {
          const value = keys.get(keySlot(r, name))?.trim();
          return value ? [[name, value]] : [];
        })) })), chosenSkills.map(r => ({ id: r.id, digest: r.digest, keys: {} })));
      setResults(done);
      setKeys(new Map());
    } catch { setAddFailed(true); }
    finally { setBusy(false); onChanged(); }     // also after a failure: some may have gone in before it
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
            <Small testId="import-refused">{t(refusedKey(r.refused))}</Small>
            {r.refused_part && r.refused_part !== r.name && <Code>{r.refused_part}</Code>}
          </> : <>
            <Small testId="import-skill">{t("capabilityList.import_skill")}</Small>
            {r.scripts.length > 0 && <Small>{t("capabilityList.import_skillScripts")} <Code>{r.scripts.join(", ")}</Code></Small>}
            {r.scan === "warn" && <Small>{t("capabilityList.import_skillWarn")}</Small>}
          </>}
          {r.left > 0 && <Small>{t("capabilityList.import_skillLeft", { count: r.left })}</Small>}
          {first && <Small>{t("capabilityList.import_sameSkill", { name: isolate(first.name) })}</Small>}
        </span>
      </label>
    </div>;
  };

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
    const server = rows.find(r => r.id === result.id) ?? skills.find(r => r.id === result.id);
    if (!server) return null;
    const name = isolate(server.name);
    const words = server.kind === "skill" && result.state === "added" ? t("capabilityList.import_result_copied", { name })
      : result.state === "on" ? t("discover.result_on", { name, count: result.tools ?? 0 })
      : result.state === "needs_sign_in" ? t("discover.result_signIn", { name })
      : result.state === "blocked" ? t("discover.result_blocked", { name })
      : result.state === "failed" ? t("discover.result_failed", { name, stage: result.stage ?? "", detail: result.detail ?? result.code ?? "" })
      : result.state === "refused" ? `${t("capabilityList.import_result_refused", { name })} ${t(refusedKey(result.code ?? ""))}`
      : result.state === "needs_keys" ? t("capabilityList.import_result_needs_keys", { name, keys: (result.keys ?? []).join(", ") })
      : t(`capabilityList.import_result_${result.state}`, { name });
    const tone = result.state === "on" ? "text-success" : result.state === "failed" || result.state === "blocked" || result.state === "refused"
      ? "text-danger-strong" : result.state === "added" && server.kind !== "skill" ? "text-warning" : "text-muted-foreground";
    return <p key={result.id} data-testid={`import-result-${result.state}`} data-state={result.state}
      className={`border-t border-border py-2.5 text-[13px] leading-snug [overflow-wrap:anywhere] ${tone}`}>{words}</p>;
  };

  const rescanOffered = results?.some(r => r.state === "gone" || r.state === "changed" || r.state === "needs_keys");
  const footer = results ? <>
    {rescanOffered && <Button data-testid="import-rescan" onClick={scanAgain}>{t("capabilityList.import_rescan")}</Button>}
    <Button tone="primary" data-testid="import-done" onClick={onClose}>{t("capabilityList.import_done")}</Button>
  </> : scan ? <div className="flex w-full flex-col gap-2">
    {addFailed && <Notice tone="error" role="alert" testId="import-add-failed">{t("capabilityList.import_addFailed")}</Notice>}
    <div className="flex flex-wrap items-center gap-2.5">
      <Button tone="primary" data-testid="import-add" disabled={busy || count === 0} onClick={() => void add()}>
        {busy ? t("capabilityList.import_adding") : chosenSkills.length > 0 ? t("capabilityList.import_addMixed", { count })
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
    {results ? <div data-testid="import-results" className="flex flex-col">{results.map(resultLine)}</div> : <div className="flex flex-col gap-3">
      <p className="text-[13px] text-muted-foreground">{t("capabilityList.import_intro")}</p>
      {scanFailed ? <div className="flex flex-col items-start gap-2">
        <Notice tone="error" role="alert" testId="import-scan-failed">{t("capabilityList.import_scanFailed")}</Notice>
        <Button data-testid="import-rescan" onClick={scanAgain}>{t("capabilityList.import_rescan")}</Button>
      </div> : !scan ? <p className="text-[13px] text-subtle-foreground">{t("capabilityList.import_scanning")}</p> : <>
        {scan.tools.filter(tool => tool.state === "malformed").map(tool => <Notice key={tool.tool} tone="warn" testId="import-malformed">
          {t("capabilityList.import_malformed", { tool: TOOL[tool.tool] })}</Notice>)}
        {rows.length + skills.length === 0 && <p data-testid="import-nothing" className="text-[13px] text-subtle-foreground">{t("capabilityList.import_nothing")}</p>}
        {rows.length + skills.length > 0 && <div className="flex flex-col">
          {listed.map(row)}
          {listedSkills.map(skillRow)}
          {here.length + skills.length - listedSkills.length > 0 && <p data-testid="import-here" className="border-t border-border py-2.5 pl-[28px] text-[12px] text-muted-foreground">
            {t("capabilityList.import_here", { names: [...here, ...skills.filter(r => r.here)].map(r => isolate(r.name)).join(", ") })}</p>}
        </div>}
      </>}
    </div>}
  </Dialog>;
}
