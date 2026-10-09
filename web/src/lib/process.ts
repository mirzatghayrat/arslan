/**
 * What a reply did, as one list (0.1.58 §1). Live turns build it from the store's steps
 * (tool calls and Arslan's narration); a finished reply fetches the same list from
 * GET /runs/{id}/process, so the live view and a reloaded one read the same.
 * Words come from i18n (process.*), keyed by lib/toolWords.json — never the tool's key.
 */
import type { ProcessSummary, StreamUsage, ToolStep } from "../api/client.types";
import toolWords from "./toolWords.json";
import { humanizeStep } from "./toolHumanize";

export type Family = "read" | "search" | "web" | "write" | "command" | "code" | "memory" | "hands" | "plan"
  | "capability" | "mcp" | "other";

/** A step's own view, as the server built it (server/services/run_process.py `plain`). */
export interface StepDetail {
  view: string;
  error?: string | null;
  [key: string]: unknown;
}

export interface ProcessEntry {
  kind: "note" | "tool";
  text?: string;
  tool?: string;
  status: "running" | "ok" | "error";
  ms?: number | null;
  argsSummary?: string;
  summary?: string;
  detail?: StepDetail;
  raw?: { args: string; result: string };
}

export type ProcessItem = ProcessEntry | { kind: "group"; family: Family; entries: ProcessEntry[] };

type Word = { family?: Family; arg?: string; host?: boolean };
const WORDS = toolWords as unknown as Record<string, Word>;

/** Families whose consecutive steps fold into one line ("看了 4 项"). */
const MERGED: Family[] = ["read", "search", "web"];

export function familyOf(tool: string | undefined): Family {
  if (!tool) return "other";
  if (tool.startsWith("mcp_")) return "mcp";
  return WORDS[tool]?.family ?? "other";
}

function argValue(argsSummary: string | undefined, key: string): string {
  if (!argsSummary) return "";
  try {
    const v = JSON.parse(argsSummary)?.[key];
    if (typeof v === "string") return v;
  } catch {
    // args_summary is cut at 200 characters: read the one value straight from the text.
    const m = new RegExp(`"${key}"\\s*:\\s*"((?:[^"\\\\]|\\\\.)*)`).exec(argsSummary);
    if (m) return m[1].replace(/\\"/g, '"');
  }
  return "";
}

function hostOf(url: string): string {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return url; }
}

/** The capability's own name from an MCP tool key (mcp_<server>_<tool>). */
export function mcpName(tool: string): string {
  return tool.replace(/^mcp_\d*_*/, "") || tool;
}

type T = (k: string, o?: Record<string, unknown>) => string;

/** One step in words: "读了 notes.md", "搜了「tide tables」", "用了外部能力 read_data". */
export function stepWords(entry: Pick<ProcessEntry, "tool" | "argsSummary" | "status" | "summary">, t: T): string {
  const tool = entry.tool ?? "";
  // A failed search or page read keeps its calm, specific line (rate-limited, quota, a page
  // that would not open) rather than a past tense that did not happen.
  if (entry.status === "error" && (tool === "web_search" || tool === "web_extract")) {
    return humanizeStep({ tool, argsSummary: entry.argsSummary ?? "", resultSummary: entry.summary, status: "error" }, t);
  }
  if (tool.startsWith("mcp_")) return t("process.mcp", { x: mcpName(tool) });
  const word = WORDS[tool];
  if (!word) return tool.replace(/_/g, " ");
  let x = word.arg ? argValue(entry.argsSummary, word.arg) : "";
  if (x && word.host) x = hostOf(x);
  if (x.length > 60) x = `${x.slice(0, 57)}…`;
  return x ? t(`process.t_${tool}_x`, { x }) : t(`process.t_${tool}`);
}

/** Live steps (store) → entries. */
export function fromSteps(steps: ToolStep[] | undefined): ProcessEntry[] {
  return (steps ?? []).map((s) => s.kind === "note"
    ? { kind: "note", text: s.text ?? "", status: "ok" }
    : { kind: "tool", tool: s.tool, status: s.status, ms: s.ms ?? null, argsSummary: s.argsSummary, summary: s.resultSummary });
}

/** The footer row from entries (live) — the same count the server gives a reloaded reply. */
export function summarize(entries: ProcessEntry[], ms: number | null, usage?: StreamUsage | null): ProcessSummary {
  const tools = entries.filter((e) => e.kind === "tool");
  return { steps: tools.length, failed: tools.filter((e) => e.status === "error").length, ms, usage: usage ?? null };
}

/** Consecutive finished steps of a reading/searching family fold into one expandable line. */
export function group(entries: ProcessEntry[]): ProcessItem[] {
  const out: ProcessItem[] = [];
  let run: ProcessEntry[] = [];
  const flush = () => {
    if (run.length >= 2) out.push({ kind: "group", family: familyOf(run[0].tool), entries: run });
    else out.push(...run);
    run = [];
  };
  for (const e of entries) {
    const fam = e.kind === "tool" && e.status !== "running" ? familyOf(e.tool) : null;
    if (fam && MERGED.includes(fam) && (run.length === 0 || familyOf(run[0].tool) === fam)) { run.push(e); continue; }
    flush();
    if (fam && MERGED.includes(fam)) { run.push(e); continue; }
    out.push(e);
  }
  flush();
  return out;
}

/** "48 秒" / "2 分 05 秒" — the chip's time, from the shared formatter. */
export { fmtMs as fmtDuration } from "./usageFormat";
