/**
 * SMART-8 (the card mock the user OK'd, 2026-11-02): what a command is for and what it touches, read from the
 * command itself, for a card whose step came with no reason from Arslan. Read by code, never by the model: the card's
 * 「涉及」 (touches) row always comes from here, and its purpose line too unless Arslan said why.
 *
 * A shell line splits into steps (`;`, `&&`, `||`, `|`, `&`, new lines), quotes kept. Steps that only print, wait or
 * change folder say nothing about what the line does, so the first other step names the purpose, and the rest are
 * counted (`more`). A line the reader cannot split (an open quote) gets the plain "run <program>" purpose.
 */

export interface Purpose { key: string; params: Record<string, string | number> }
export interface CommandSummary { purpose: Purpose; touches: string[]; more: number }

/** At most this many hosts, paths or addresses in the 「涉及」 row; the rest are counted. */
export const TOUCHES_MAX = 6;
const QUIET = new Set(["echo", "printf", "true", "false", ":", "cd", "pushd", "popd", "sleep", "set", "export",
  "unset", "test", "[", "read", "wait", "clear"]);
const WRAPPERS = new Set(["sudo", "env", "command", "exec", "nohup", "time", "nice"]);
const ASSIGNMENT = /^[A-Za-z_][A-Za-z0-9_]*=/;
const REDIRECT = /^(?:\d*>>?|\d*>&\d*|&>>?|<{1,3}|\d*<&?\d*)$/;
/** ssh options that take a value (OpenSSH's own list). */
const SSH_VALUE = new Set("BbcDEeFIiJLlmOoPpQRSWw".split(""));
const INSTALLERS = new Set(["brew", "pip", "pip3", "npm", "pnpm", "yarn", "uv", "cargo", "gem", "pipx"]);
const SCRIPT_RUNNERS = new Set(["python", "python3", "node", "ruby", "bash", "sh", "zsh", "perl", "deno", "bun"]);

/** The line's steps, each its tokens, or null when a quote is never closed. */
export function splitShell(text: string): string[][] | null {
  const steps: string[][] = [];
  let step: string[] = [], token = "", inToken = false;
  let quote: "'" | '"' | null = null;
  const endToken = () => { if (inToken) step.push(token); token = ""; inToken = false; };
  const endStep = () => { endToken(); if (step.length) steps.push(step); step = []; };
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quote) {
      if (ch === quote) quote = null;
      else if (ch === "\\" && quote === '"' && i + 1 < text.length) token += text[++i];
      else token += ch;
      continue;
    }
    if (ch === "'" || ch === '"') { quote = ch; inToken = true; continue; }
    if (ch === "\\" && i + 1 < text.length) { token += text[++i]; inToken = true; continue; }
    if (ch === ";" || ch === "\n" || ch === "|" || ch === "&") {
      if (ch === "&" && /\d?>$/.test(token)) { token += ch; continue; }           // 2>&1 is one redirect
      endStep();
      if ((ch === "|" || ch === "&") && text[i + 1] === ch) i++;
      continue;
    }
    if (ch === " " || ch === "\t") { endToken(); continue; }
    token += ch; inToken = true;
  }
  if (quote) return null;
  endStep();
  return steps;
}

const base = (word: string) => word.slice(word.lastIndexOf("/") + 1);

/** A step's words with the noise taken off: assignments, wrappers (sudo, env…) and redirects with their targets. */
function words(step: string[]): string[] {
  const out: string[] = [];
  let i = 0;
  while (i < step.length && (ASSIGNMENT.test(step[i]) || WRAPPERS.has(base(step[i])))) {
    const wrapper = base(step[i]) === "sudo";
    i++;
    while (wrapper && i < step.length && step[i].startsWith("-")) i++;
  }
  for (; i < step.length; i++) {
    if (REDIRECT.test(step[i])) { i++; continue; }
    if (/^\d*>>?\S/.test(step[i]) || /^<\S/.test(step[i])) continue;                  // >file, 2>file, <file
    out.push(step[i]);
  }
  return out;
}

const plain = (args: string[]) => args.filter(a => !a.startsWith("-"));

function hostOfUrl(text: string): string | null {
  try {
    const url = new URL(/^[a-z][a-z0-9+.-]*:\/\//i.test(text) ? text : `https://${text}`);
    return url.hostname || null;
  } catch {
    return null;
  }
}

function ssh(args: string[]): { purpose: Purpose; touches: string[] } {
  let host = "", timeout = 0;
  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg.startsWith("-") && arg.length > 1) {
      const flag = arg[1], inline = arg.slice(2);
      const value = SSH_VALUE.has(flag) ? (inline || args[++i] || "") : "";
      const m = flag === "o" ? /^ConnectTimeout=(\d+)$/i.exec(value) : null;
      if (m) timeout = Number(m[1]);
      continue;
    }
    host = arg.slice(arg.lastIndexOf("@") + 1);
    break;
  }
  if (!host) return { purpose: { key: "run", params: { program: "ssh" } }, touches: [] };
  return { purpose: timeout ? { key: "sshTimeout", params: { host, seconds: timeout } } : { key: "ssh", params: { host } },
           touches: [host] };
}

/** One step's purpose and what it touches. `rule` is the server's terminal rule for the line (upload, git-push…). */
function summarizeStep(program: string, args: string[], rule?: string): { purpose: Purpose; touches: string[] } {
  switch (program) {
    case "ssh": case "mosh": case "autossh":
      return ssh(args);
    case "scp": case "sftp": case "rsync": {
      const hosts = [...new Set(plain(args).map(a => /^(?:[^@/\s]+@)?([^:/\s]+):/.exec(a)?.[1]).filter(Boolean) as string[])];
      return hosts.length ? { purpose: { key: "copyRemote", params: { host: hosts[0] } }, touches: hosts }
        : { purpose: { key: "copyLocal", params: { count: Math.max(plain(args).length - 1, 1) } }, touches: plain(args) };
    }
    case "curl": case "wget": case "http": case "https": case "xh": {
      const url = plain(args).find(a => /^https?:\/\//i.test(a)) ?? plain(args)[0];
      const host = url ? hostOfUrl(url) : null;
      if (!host) return { purpose: { key: "run", params: { program } }, touches: [] };
      return { purpose: { key: rule === "upload" ? "upload" : "fetch", params: { host } }, touches: [url] };
    }
    case "rm": case "rmdir": case "unlink": case "trash": case "srm": {
      const targets = plain(args);
      return { purpose: { key: "delete", params: { count: targets.length } }, touches: targets };
    }
    case "mv": {
      const targets = plain(args);
      return { purpose: { key: "move", params: { count: Math.max(targets.length - 1, 1) } }, touches: targets };
    }
    case "cp": {
      const targets = plain(args);
      return { purpose: { key: "copyLocal", params: { count: Math.max(targets.length - 1, 1) } }, touches: targets };
    }
    case "git": {
      const own = args.filter((a, i) => !/^-[Cc]$/.test(a) && !/^-[Cc]$/.test(args[i - 1] ?? ""));   // -C dir, -c key=value
      const [sub, ...rest] = plain(own);
      if (sub === "push") return { purpose: { key: "gitPush", params: { remote: rest[0] ?? "origin" } }, touches: [] };
      if (sub === "clone" && rest[0]) {
        return { purpose: { key: "gitClone", params: { repo: rest[0] } }, touches: [rest[0]] };
      }
      if (sub === "pull" || sub === "fetch") {
        return { purpose: { key: "gitFetch", params: { remote: rest[0] ?? "origin" } }, touches: [] };
      }
      return { purpose: { key: "git", params: { sub: sub ?? "" } }, touches: [] };
    }
    case "open": {
      const target = plain(args).at(-1);
      return target ? { purpose: { key: "open", params: { target } }, touches: [target] }
        : { purpose: { key: "run", params: { program } }, touches: [] };
    }
    case "osascript":
      return { purpose: { key: "appleScript", params: {} }, touches: [] };
    case "shortcuts": {
      const [sub, name] = plain(args);
      return sub === "run" && name ? { purpose: { key: "shortcut", params: { name } }, touches: [] }
        : { purpose: { key: "run", params: { program } }, touches: [] };
    }
    case "kill": case "killall": case "pkill": {
      const target = plain(args).join(" ");
      return { purpose: { key: "kill", params: { target } }, touches: [] };
    }
    case "mail": case "mailx": case "sendmail": case "msmtp": case "mutt": {
      const to = plain(args).find(a => a.includes("@"));
      return to ? { purpose: { key: "mailTo", params: { to } }, touches: [to] } : { purpose: { key: "mail", params: {} }, touches: [] };
    }
    default: {
      const [sub, ...pkgs] = plain(args);
      if (INSTALLERS.has(program) && (sub === "install" || sub === "add")) {
        const names = pkgs.filter(p => !p.includes("/") || p.startsWith("@"));
        return { purpose: { key: "install", params: { packages: names.slice(0, 3).join(", ") || program } }, touches: [] };
      }
      if (SCRIPT_RUNNERS.has(program) && sub && !args.includes("-c")) {
        return { purpose: { key: "script", params: { program, file: base(sub) } }, touches: [sub] };
      }
      return { purpose: { key: "run", params: { program } }, touches: [] };
    }
  }
}

/** What a shell line is for and what it touches. */
export function summarize(text: string, rule?: string): CommandSummary {
  const steps = splitShell(text);
  const first = (text.trim().split(/\s+/)[0] ?? "");
  if (!steps) return { purpose: { key: "run", params: { program: base(first) } }, touches: [], more: 0 };
  const real = steps.map(words).filter(w => w.length && !QUIET.has(base(w[0])));
  if (!real.length) {
    const any = steps.map(words).find(w => w.length);
    return { purpose: { key: "run", params: { program: base(any?.[0] ?? first) } }, touches: [], more: 0 };
  }
  const read = real.map(([program, ...args]) => summarizeStep(base(program), args, rule));
  const touches = [...new Set(read.flatMap(r => r.touches))];
  return { purpose: read[0].purpose, touches, more: real.length - 1 };
}

export type RiskLevel = "info" | "warn" | "irreversible";
export interface CommandRisk { level: RiskLevel; keys: { key: string; params?: Record<string, string> }[] }

/** Rules whose step cannot be taken back: a delete outside the work folder, or sending in the user's name. */
const IRREVERSIBLE = new Set(["delete-outside", "send-mail", "send-message", "publish"]);
/** Every rule the server's terminal policy names (server/services/terminal_policy.py `_ASK`), each with its line. */
export const RULES = new Set(["delete-outside", "send-mail", "send-message", "upload", "publish", "git-push",
  "remote-shell", "apple-events", "shortcuts", "force-kill", "login-items", "keychain-write", "system-settings",
  "open-app", "screen-clipboard", "protected-write", "unreadable"]);

/**
 * The card's 「风险」 row, from what the server decided about the command (never the model's words): the terminal rule
 * it matched, whether it also asks for the network, whether it runs outside the sandbox or on another machine.
 */
export function commandRisk(f: { rule?: string; network?: boolean; sandbox?: "outside" | "retry"; remoteHost?: string;
                                 unsandboxed?: boolean }): CommandRisk {
  const keys: CommandRisk["keys"] = [];
  let level: RiskLevel = "info";
  const raise = (to: RiskLevel) => { if (to === "irreversible" || (to === "warn" && level === "info")) level = to; };
  // Leaving the sandbox is said first on the card (S4a), so it leads the row.
  if (f.sandbox === "outside") { keys.push({ key: "outside" }); raise("warn"); }
  else if (f.sandbox === "retry") { keys.push({ key: "retry" }); raise("warn"); }
  if (f.remoteHost) { keys.push({ key: "remote", params: { host: f.remoteHost } }); raise("warn"); }
  if (f.rule && RULES.has(f.rule)) { keys.push({ key: `rule.${f.rule}` }); raise(IRREVERSIBLE.has(f.rule) ? "irreversible" : "warn"); }
  if (!f.sandbox && f.unsandboxed) { keys.push({ key: "unsandboxed" }); raise("warn"); }
  if (f.network) { keys.push({ key: "network" }); raise("warn"); }
  if (!keys.length) keys.push({ key: f.remoteHost ? "remote" : "sandboxed" });
  return { level, keys };
}
