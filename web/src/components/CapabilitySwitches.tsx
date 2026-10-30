import { useCallback, useEffect, useState } from "react";
import { ChevronRight, KeyRound, MessageSquare, Sparkles, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { capabilitiesApi, type CapabilityRow } from "../api/capabilities";
import { ApiError } from "../api/client";
import { matches } from "../lib/capabilitySearch";
import { formatUiDate } from "../lib/localeFormatting";
import { openSection } from "../lib/sections";
import CapabilityFilter from "./CapabilityFilter";
import CapabilitySheet from "./CapabilitySheet";
import McpServers from "./McpServers";
import SkillImportPanel from "./SkillImportPanel";
import { Button, Dialog, Notice, confirmSheet, toast } from "./kit";

const SECTIONS = ["builtin", "skills", "connections"] as const;
type Filter = "all" | "on" | "canTurnOn";
type Sheet = { kind: "row"; key: string } | { kind: "link" } | { kind: "manual" } | null;
/** Built-in details that are a note to show (others, like a runtime name, feed the reason). */
const NOTES = new Set(["own_folder_only", "first_use_setup"]);
const FOLD_AFTER = 6;
const DOT = { on: "bg-[#34C759]", off: "bg-subtle-foreground", setup: "bg-ask", na: "bg-subtle-foreground" } as const;
const DAY = 86_400_000;
/** What a delete loses, by what the row is (#500 review): said plainly, never "switched off". */
const DELETE_BODY: Record<string, string> = {
  "skills:authored": "capabilityList.deleteBodyAuthored", "skills:installed": "capabilityList.deleteBodyInstalledSkill",
  "connections:manual": "capabilityList.deleteBodyManual", "connections:installed": "capabilityList.deleteBodyInstalledConnection",
};
/** A name from outside (a SKILL.md, a server label) inside one of Arslan's sentences: isolated, so bidi controls
 *  in it cannot reorder the sentence around it (#500 review). */
export const isolate = (text: string) => `\u2068${text.replace(BIDI_CONTROLS, "")}\u2069`;
/** Marks and controls that could close the isolate early or reorder what follows it (#500 recheck). */
const BIDI_CONTROLS = /[\u061C\u200E\u200F\u202A-\u202E\u2066-\u2069]/g;

type Translate = (key: string, options?: Record<string, unknown>) => string;

/** When a row was last used, in days from today (v0.1.64 CAP3a); "not used yet" when the records have nothing. */
export function usedLabel(t: Translate, iso: string | null, language?: string, now: number = Date.now()): string {
  if (!iso) return t("capabilityList.usedNever");
  const then = new Date(iso);
  const midnight = (ms: number) => new Date(ms).setHours(0, 0, 0, 0);
  const days = Math.round((midnight(now) - midnight(then.getTime())) / DAY);
  if (days <= 0) return t("capabilityList.usedToday");
  if (days === 1) return t("capabilityList.usedYesterday");
  if (days < 30) return t("capabilityList.usedDaysAgo", { count: days });
  return t("capabilityList.usedOn", { date: formatUiDate(then, language) });
}

/**
 * What Arslan can do (0.1.55 §14). v0.1.64 CAP3a: one list in three sections, built in, skills and
 * connections (the mock the user approved). Every row comes from GET /capabilities, which reads the same
 * gates the model's tool list is built from: a switch here is the switch, not a second opinion about it.
 * Each row says where it came from and when it was last used; only what is not built in can be deleted,
 * and the server refuses the rest too. A row opens its details sheet.
 */
export default function CapabilitySwitches() {
  const { t, i18n } = useTranslation();
  const [rows, setRows] = useState<CapabilityRow[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [openSections, setOpenSections] = useState<Set<string>>(new Set());
  const [sheet, setSheet] = useState<Sheet>(null);
  const load = useCallback(async () => {
    try { setRows(await capabilitiesApi.list()); setFailed(false); }
    catch { setFailed(true); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  async function flip(row: CapabilityRow, on: boolean) {
    setBusy(row.key); setError(null);
    try {
      const next = await capabilitiesApi.switch(row.key, on);
      setRows(old => old?.map(r => (r.key === row.key ? { ...r, ...next } : r)) ?? old);
    } catch { setError(t("capabilityList.failed")); }
    finally { setBusy(null); }
  }
  function fix(row: CapabilityRow) {
    const [what, where] = (row.fix ?? "").split(":");
    if (what === "open_settings") openSection("settings", where);
    else open({ kind: "row", key: row.key });              // a connection's card (connect, sign in) is in its sheet
  }
  async function remove(row: CapabilityRow) {
    const label = isolate(name(row));
    // By origin alone: a Discover skill reads "authored" since migration 0080 and SKF1 (no key rule, #519 review).
    const body = DELETE_BODY[`${row.section}:${row.origin}`];
    const ok = await confirmSheet({ title: t("capabilityList.deleteTitle", { name: label }), action: t("capabilityList.delete"),
      body: body ? t(body) : undefined });
    if (!ok) return;
    setBusy(row.key); setError(null);
    try {
      await capabilitiesApi.deleteRow(row.key);
      setSheet(null);
      toast(t("capabilityList.deleted", { name: label }));
      await load();
    } catch (failure) {
      // Already gone (404) or not deletable (409): the list was out of date, so it is read again and says which.
      // Anything else may pass on a second try.
      const status = failure instanceof ApiError ? failure.status : 0;
      setError(t(status === 404 ? "capabilityList.deleteGone" : status === 409 ? "capabilityList.deleteRefused"
        : "capabilityList.deleteFailed", { name: label }));
      if (status === 404 || status === 409) await load();
    }
    finally { setBusy(null); }
  }
  function open(next: Sheet) { setError(null); setSheet(next); }

  const isMethod = (row: CapabilityRow) => row.key.startsWith("method:");
  const name = (row: CapabilityRow) => row.name
    ?? (isMethod(row) ? t(`methods.${row.key.slice(7)}`) : t(`capabilityList.${row.key}_name`));
  const what = (row: CapabilityRow) => row.section === "builtin" ? t(`capabilityList.${row.key}_what`)
    : isMethod(row) ? t("capabilityList.methodWhat") : row.section === "skills" ? row.detail ?? "" : "";
  const used = (row: CapabilityRow) => usedLabel(t, row.last_used, i18n?.resolvedLanguage);
  const reason = (row: CapabilityRow) => row.reason
    ? t(`capabilityList.reason_${row.reason}`, { detail: row.detail ?? "Node.js", defaultValue: row.reason }) : "";
  const all = rows ?? [];
  const counts = { on: all.filter(r => r.state === "on").length, canTurnOn: all.filter(r => r.state === "off" || r.state === "setup").length };
  const inFilter = all.filter(r => filter === "all" || (filter === "on" ? r.state === "on" : r.state === "off" || r.state === "setup"));
  // A connection is also found by how it is reached ("the one I pointed at playwright").
  const shown = inFilter.filter(r => matches({ key: r.key, name: name(r), description: [what(r), r.reach ?? ""].join(" ") }, query));
  const searching = query.trim() !== "";
  const opened = sheet?.kind === "row" ? all.find(r => r.key === sheet.key) : undefined;

  const row = (r: CapabilityRow) => {
    const switchable = r.switch !== null && (r.state === "on" || r.state === "off");
    return <div key={r.key} data-testid={`cap-${r.key}`} data-state={r.state}
      className={`flex items-center gap-3 border-t border-border px-4 py-2.5 first:border-t-0 ${r.state === "na" ? "opacity-55" : ""}`}>
      <button type="button" data-testid={`cap-open-${r.key}`} onClick={() => open({ kind: "row", key: r.key })}
        className="flex min-w-0 flex-1 flex-col gap-0.5 text-left">
        <span className="flex flex-wrap items-center gap-2 text-[14px]"><bdi>{name(r)}</bdi>
          <span className="inline-flex items-center gap-1 text-[11px] text-subtle-foreground">
            <span aria-hidden="true" className={`h-1.5 w-1.5 rounded-full ${DOT[r.state]}`} />{t(`capabilityList.state_${r.state}`)}</span></span>
        <span className="text-[12px] text-subtle-foreground">
          {/* What it does can be outside text: isolated, so it cannot pass for the origin beside it (#500 review). */}
          {what(r) && <><bdi>{what(r)}</bdi> · </>}{t(`capabilityList.origin_${r.origin}`)} · {used(r)}
          {r.section === "builtin" && r.detail && NOTES.has(r.detail) ? <> · {t(`capabilityList.detail_${r.detail}`)}</> : null}
          {r.state === "setup" && r.reason === "mcp_error" && r.detail ? <> · <span className="font-mono">{r.detail}</span></> : null}
        </span>
      </button>
      {switchable ? <input type="checkbox" role="switch" className="kit-switch" aria-label={name(r)} data-testid={`cap-switch-${r.key}`}
        checked={r.state === "on"} disabled={busy === r.key} onChange={event => void flip(r, event.target.checked)} />
        : r.state === "setup" ? <Button size="sm" data-testid={`cap-fix-${r.key}`} onClick={() => fix(r)}>{reason(r)}</Button>
        : r.state === "na" ? <span className="shrink-0 text-[12px] text-subtle-foreground">{reason(r)}</span> : null}
      {r.deletable
        ? <button type="button" data-testid={`cap-delete-${r.key}`} aria-label={t("capabilityList.deleteLabel", { name: name(r) })}
            disabled={busy === r.key} onClick={() => void remove(r)}
            className="shrink-0 rounded-md p-1 text-subtle-foreground hover:bg-danger/10 hover:text-danger disabled:opacity-50"><Trash2 size={14} /></button>
        : <span aria-hidden="true" className="w-[22px] shrink-0" />}
    </div>;
  };

  return <div className="flex flex-col gap-6 lg:flex-row lg:items-start">
    <div className="flex min-w-0 max-w-[720px] flex-1 flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h1 className="text-[20px] font-semibold">{t("capabilityList.tab")}</h1>
        <p className="max-w-xl text-[13px] text-muted-foreground">{t("capabilityList.intro")}</p>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div role="group" className="inline-flex rounded-lg bg-fill p-0.5">
          {(["all", "on", "canTurnOn"] as const).map(key => <button key={key} aria-pressed={filter === key} data-testid={`cap-filter-${key}`}
            className={`rounded-md px-2.5 py-1 text-[12px] ${filter === key ? "bg-background font-semibold text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
            onClick={() => setFilter(key)}>{key === "all" ? t("capabilityList.filterAll")
              : t(key === "on" ? "capabilityList.filterOn" : "capabilityList.filterCanTurnOn", { count: counts[key] })}</button>)}
        </div>
        {rows && <div className="min-w-[200px] flex-1"><CapabilityFilter testId="cap-search" value={query} onChange={setQuery}
          shown={shown.length} total={inFilter.length} /></div>}
      </div>
      {failed && <Notice tone="error" role="alert">{t("capabilityList.loadFailed")}</Notice>}
      {error && <Notice tone="error" role="alert">{error}</Notice>}
      {rows && searching && shown.length === 0 &&
        <p data-testid="cap-no-match" className="px-1 text-[13px] text-subtle-foreground">{t("capabilityList.noMatch", { query })}</p>}
      {rows && SECTIONS.map(section => {
        const inSection = shown.filter(r => r.section === section);
        if (!inSection.length && !(section === "connections" && !searching)) return null;
        // A long section opens with its first few; the rest one click away. A search shows everything it found.
        const folded = inSection.length > FOLD_AFTER && !openSections.has(section) && !searching;
        return <section key={section} data-testid={`cap-section-${section}`} className="flex flex-col gap-1.5">
          <h2 className="flex items-baseline gap-2 px-1 text-[12px] font-semibold text-muted-foreground">{t(`capabilityList.section_${section}`)}
            <span className="font-normal text-subtle-foreground">{inSection.length}</span>
            {section === "connections" && <button type="button" data-testid="cap-add-manual" className="ml-auto font-normal hover:text-foreground"
              onClick={() => open({ kind: "manual" })}>{t("capabilityList.addByHand")} ›</button>}</h2>
          {inSection.length > 0 && <div className="overflow-hidden rounded-xl border border-border bg-surface">
            {(folded ? inSection.slice(0, FOLD_AFTER) : inSection).map(row)}
            {inSection.length > FOLD_AFTER && !searching && <button type="button" data-testid={`cap-more-${section}`} aria-expanded={!folded}
              className="w-full border-t border-border px-4 py-2 text-left text-[12px] text-muted-foreground hover:text-foreground"
              onClick={() => setOpenSections(old => { const next = new Set(old); if (next.has(section)) next.delete(section); else next.add(section); return next; })}>
              {folded ? `${t("memoryPage.showAll", { count: inSection.length })} ›` : t("memoryPage.showFewer")}</button>}
          </div>}
        </section>;
      })}
    </div>
    <aside className="flex w-full shrink-0 flex-col gap-2 lg:w-[300px]">
      <h2 className="px-1 text-[12px] font-semibold text-muted-foreground">{t("capabilityList.addTitle")}</h2>
      <div className="overflow-hidden rounded-xl border border-border bg-surface">
        {/* Not buttons: there is nothing to open. A new capability is asked for in a conversation (v0.1.64 CAP1a),
            and Arslan writes a method there for the user to approve on a card (CAP2a). */}
        <div data-testid="cap-add-say" className="flex w-full items-center gap-2.5 px-3.5 py-2.5">
          <MessageSquare size={14} className="shrink-0 text-subtle-foreground" />
          <span className="flex min-w-0 flex-1 flex-col"><span className="text-[13px]">{t("capabilityList.addSay")}</span>
            <span className="text-[12px] text-subtle-foreground">{t("capabilityList.addSayWhat")}</span></span>
        </div>
        <button type="button" data-testid="cap-add-link" onClick={() => open({ kind: "link" })}
          className="flex w-full items-center gap-2.5 border-t border-border px-3.5 py-2.5 text-left hover:bg-fill">
          <KeyRound size={14} className="shrink-0 text-subtle-foreground" />
          <span className="flex min-w-0 flex-1 flex-col"><span className="text-[13px]">{t("capabilityList.addLink")}</span>
            <span className="text-[12px] text-subtle-foreground">{t("capabilityList.addLinkWhat")}</span></span>
          <ChevronRight size={14} className="text-subtle-foreground" />
        </button>
        <div data-testid="cap-add-method" className="flex w-full items-center gap-2.5 border-t border-border px-3.5 py-2.5">
          <Sparkles size={14} className="shrink-0 text-subtle-foreground" />
          <span className="flex min-w-0 flex-1 flex-col"><span className="text-[13px]">{t("capabilityList.addMethod")}</span>
            <span className="text-[12px] text-subtle-foreground">{t("capabilityList.addMethodSay")}</span></span>
        </div>
      </div>
      <p className="px-1 text-[12px] leading-relaxed text-subtle-foreground">{t("capabilityList.addFoot")}</p>
    </aside>
    {opened && <CapabilitySheet row={opened} name={name(opened)} what={what(opened)} used={used(opened)} error={error}
      onClose={() => setSheet(null)} onDelete={row => void remove(row)} onChanged={() => void load()} />}
    {sheet?.kind === "link" && <Dialog open onClose={() => setSheet(null)} width={640} testId="cap-link-sheet" padded title={t("capabilityList.addLink")}>
      <SkillImportPanel onImported={() => void load()} /></Dialog>}
    {sheet?.kind === "manual" && <Dialog open onClose={() => setSheet(null)} width={640} testId="cap-manual-sheet" padded title={t("capabilityList.addByHand")}>
      <div className="flex flex-col gap-3"><p className="text-[12px] text-subtle-foreground">{t("capabilityList.addByHandHint")}</p>
        <McpServers form onChanged={() => { void load(); setSheet(null); }} /></div></Dialog>}
  </div>;
}
