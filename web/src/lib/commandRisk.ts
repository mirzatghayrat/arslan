/**
 * SMART-8 (the card mock the user OK'd, 2026-11-02): a command card's reading and its 「风险」 row.
 *
 * What a command is for and what it touches is read by code on the server (server/services/card_purpose.py
 * `summarize`, held to tests/fixtures/card_purpose_vectors.json), the same reading the iPhone's heading is made from,
 * and comes on the `propose_run_command` frame as `summary` (LOOP1 d1). The card turns it into words here, and builds
 * its risk row from what the server decided about the command (the frame's rules and flags, never the model's words).
 */

export interface Purpose { key: string; params: Record<string, string | number>; inner?: Purpose }
export interface CommandSummary { purpose: Purpose; touches: string[]; more: number; unsure: boolean }

/** At most this many hosts, paths or addresses in the 「涉及」 row; the rest are counted. */
export const TOUCHES_MAX = 6;

const isPurpose = (p: unknown): p is Purpose => {
  const v = p as Purpose | null;
  return Boolean(v) && typeof v!.key === "string" && typeof v!.params === "object" && v!.params !== null
    && (v!.inner === undefined || isPurpose(v!.inner));
};

/** The frame's `summary`, or none when the frame has none (or not in that shape). */
export function summaryOf(raw: unknown): CommandSummary | undefined {
  const s = raw as CommandSummary | null;
  if (!s || typeof s !== "object" || !isPurpose(s.purpose) || typeof s.more !== "number" || typeof s.unsure !== "boolean"
      || !Array.isArray(s.touches)) return undefined;
  return { purpose: s.purpose, touches: s.touches.filter((x): x is string => typeof x === "string"), more: s.more,
           unsure: s.unsure };
}

/** A card whose frame has no `summary` names the command's first word and reads nothing else from it; the card then
 *  shows the whole command unfolded. DELETE-BY: v0.1.65, when no caller or test builds a command card without the
 *  server's `summary` (the prop is then required). */
export function unread(text: string): CommandSummary {
  const first = text.trim().split(/\s+/)[0] ?? "";
  return { purpose: { key: "run", params: { program: first.slice(first.lastIndexOf("/") + 1) } }, touches: [], more: 0,
           unsure: false };
}

export type RiskLevel = "info" | "warn" | "irreversible";
export interface CommandRisk { level: RiskLevel; keys: { key: string; params?: Record<string, string> }[] }

/** Rules whose step cannot be taken back: a delete outside the work folder, or sending in the user's name. */
const IRREVERSIBLE = new Set(["delete-outside", "send-mail", "send-message", "publish"]);
/** Every rule the server's terminal policy names (server/services/terminal_policy.py `_ASK`, delete-outside,
 *  protected-write and unreadable), each with its line; tests/server/test_smart8_card_purpose.py holds the two
 *  lists together. */
export const RULES = new Set(["delete-outside", "send-mail", "send-message", "upload", "publish", "git-push",
  "remote-shell", "apple-events", "shortcuts", "force-kill", "login-items", "keychain-write", "system-settings",
  "open-app", "screen-clipboard", "protected-write", "unreadable"]);
/** Why the server could not read a command (server/services/command_confirm.py `UNREADABLE`), each with its line. */
export const UNREADABLE_KINDS = new Set(["fetched-code", "script-reach", "quoting", "complex"]);
/** The delete modes with a line of their own; "permanent" is the rule's plain line. */
const DELETE_MODE_LINES = new Set(["trash", "protected", "sandboxed"]);

/**
 * The card's 「风险」 row, from what the server decided about the command (never the model's words): every terminal
 * rule it matched (`rules`; an older frame's one `rule`), why it could not read it, whether it also asks for the
 * network, whether it runs outside the sandbox or on another machine. The row takes the worst level of them; a rule
 * the card has no line for still asks, in amber, never as "sandboxed" (#688 review 3, 4).
 */
export function commandRisk(f: { rule?: string; rules?: string[]; unreadable?: string; network?: boolean;
                                 sandbox?: "outside"; remoteHost?: string; unsandboxed?: boolean;
                                 unsure?: boolean; deleteMode?: string }): CommandRisk {
  const keys: CommandRisk["keys"] = [];
  let level: RiskLevel = "info";
  const raise = (to: RiskLevel) => { if (to === "irreversible" || (to === "warn" && level === "info")) level = to; };
  // Leaving the sandbox is said first on the card (S4a), so it leads the row.
  if (f.sandbox === "outside") { keys.push({ key: "outside" }); raise("warn"); }
  if (f.remoteHost) { keys.push({ key: "remote", params: { host: f.remoteHost } }); raise("warn"); }
  const rules = f.rules?.length ? f.rules : f.rule ? [f.rule] : [];
  const ordered = [...rules.filter(r => IRREVERSIBLE.has(r)), ...rules.filter(r => !IRREVERSIBLE.has(r))];
  let unknown = false;
  for (const rule of ordered) {
    // SMART-8: how Allow deletes, from the server (`delete_to_trash.card_mode`). What goes to the Trash can come back.
    if (rule === "delete-outside" && f.deleteMode && DELETE_MODE_LINES.has(f.deleteMode)) {
      keys.push({ key: `rule.delete-outside-${f.deleteMode}` });
      raise(f.deleteMode === "sandboxed" ? "irreversible" : "warn");
      continue;
    }
    if (rule === "unreadable" && f.unreadable && UNREADABLE_KINDS.has(f.unreadable)) keys.push({ key: `rule.unreadable-${f.unreadable}` });
    else if (RULES.has(rule)) keys.push({ key: `rule.${rule}` });
    else if (!unknown) { keys.push({ key: "rule.unknown" }); unknown = true; }
    raise(IRREVERSIBLE.has(rule) ? "irreversible" : "warn");
  }
  // #688 review, Astra: a transfer the reader could not fully read may send local data, whatever the rules say.
  if (f.unsure) { keys.push({ key: "rule.unreadable-send" }); raise("warn"); }
  if (!f.sandbox && f.unsandboxed) { keys.push({ key: "unsandboxed" }); raise("warn"); }
  if (f.network) { keys.push({ key: "network" }); raise("warn"); }
  if (!keys.length) keys.push({ key: f.remoteHost ? "remote" : "sandboxed" });
  return { level, keys };
}

/** A delete that moves its targets to the Trash says so: word for word with server/services/card_purpose.py. */
export function deletePurpose(p: Purpose, deleteMode?: string): Purpose {
  return p.key === "delete" && (deleteMode === "trash" || deleteMode === "protected") ? { ...p, key: "toTrash" } : p;
}

/** A purpose in the user's words: a step run on another machine says that step inside its own sentence. */
export function purposeText(t: (key: string, params?: Record<string, unknown>) => string, p: Purpose): string {
  return t(`runcmd.purpose.${p.key}`, { ...p.params, ...(p.inner ? { what: purposeText(t, p.inner) } : {}) });
}
