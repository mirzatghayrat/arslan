/**
 * SMART-8 (the card mock the user OK'd, 2026-11-02): what a command is for and what it touches, read from the
 * command itself. Read by code, never by the model: the card's 「涉及」 (touches) row always comes from here, and its
 * purpose line too unless Arslan said why. server/services/card_purpose.py reads commands the same way (the server's
 * title, which the iPhone shows); both are held to tests/fixtures/card_purpose_vectors.json.
 *
 * A shell line splits into steps (`;`, `&&`, `||`, `|`, `&`, new lines), quotes kept. What a step runs inside it
 * (`$(…)`, backticks, `<(…)`, `>(…)`, `sh -c '…'`, `watch '…'`) is read as steps of its own, before it. Steps that
 * only print, wait or change folder say nothing about what the line does (unless they write a file), so the step
 * with the most at stake names the purpose, and the rest are counted (`more`). A download piped into a shell, or run
 * through `$(…)` or `<(…)`, is one step: "download code and run it". A path after `cd` is shown from that folder.
 * The 「涉及」 row lists other machines and web addresses first, then paths outside the work folder, then the rest,
 * so its cap never hides the one target that matters (#688 review 6). A line the reader cannot split (an open quote)
 * gets the plain "run <program>" purpose.
 */

export interface Purpose { key: string; params: Record<string, string | number>; inner?: Purpose }
export interface CommandSummary { purpose: Purpose; touches: string[]; more: number }

/** At most this many hosts, paths or addresses in the 「涉及」 row; the rest are counted. */
export const TOUCHES_MAX = 6;
const QUIET = new Set(["echo", "printf", "true", "false", ":", "cd", "pushd", "popd", "sleep", "set", "export",
  "unset", "test", "[", "read", "wait", "clear"]);
/** Programs that run the rest of their words as another program, each with its options that take a value. */
const WRAPPERS: Record<string, string> = { sudo: "CDghpRrTUu", env: "CSu", command: "", exec: "a", nohup: "",
  time: "", nice: "n", timeout: "ks", xargs: "adEILnPs", caffeinate: "tw", stdbuf: "" };
const ASSIGNMENT = /^[A-Za-z_][A-Za-z0-9_]*=/;
const FD_DUP = /^\d*[<>]&(?:\d+|-)$/;
const OUT = /^(?:\d*|&)>>?\|?$/;
const OUT_ATTACHED = /^(?:\d*|&)>>?\|?([^>&|].*)$/;
const IN = /^\d*<(?:<<?|>)?-?$/;
const IN_ATTACHED = /^\d*<{1,3}-?\S/;
const NOT_A_FILE = new Set(["/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty"]);
/** ssh options that take a value (OpenSSH's own list). */
const SSH_VALUE = new Set("BbcDEeFIiJLlmOoPpQRSWw".split(""));
const COPY_VALUE: Record<string, string> = { scp: "cFiJlOoPS", sftp: "BbcDFiJlOoPRS", rsync: "e" };
const INSTALLERS = new Set(["brew", "pip", "pip3", "npm", "pnpm", "yarn", "uv", "cargo", "gem", "pipx"]);
const SCRIPT_RUNNERS = new Set(["python", "python3", "node", "ruby", "bash", "sh", "zsh", "perl", "deno", "bun"]);
const SHELLS = new Set(["sh", "bash", "zsh", "dash", "ksh", "fish"]);
/** Programs that run code they are given: piped in, or from `$(…)` / `<(…)`. */
const RUNS_CODE = new Set([...SHELLS, "python", "python2", "python3", "node", "perl", "ruby", "php", "deno", "bun",
  "source", ".", "eval"]);
const FETCHERS = new Set(["curl", "wget", "http", "https", "xh"]);
const DELETERS = new Set(["rm", "rmdir", "unlink", "trash", "srm"]);
const PATH_LIKE = /^(?:\/|~|\.{1,2}\/|\$HOME\b|\$\{HOME\})/;
const URL_LIKE = /^[a-z][a-z0-9+.-]*:\/\//i;
/** A path on another machine, as the 「涉及」 row writes it (`box:~/notes`). */
const REMOTE_PATH = /^[^/:\s]+:/;
/** What is most at stake in a step, by its purpose: the step with the most names the line (ties: the first). */
const STAKES: Record<string, number> = { fetchRun: 10, delete: 9, deleteSome: 9, findDelete: 9, mailTo: 8, mail: 8,
  upload: 8, onHost: 7, gitPush: 7, kill: 6, copyRemote: 6, ssh: 5, sshTimeout: 5, appleScript: 5, shortcut: 5,
  install: 5, write: 4, move: 4, open: 3, copyLocal: 3, gitClone: 3, fetch: 2, gitFetch: 2, script: 2 };

interface Step { tokens: string[]; piped: boolean; subs: Step[] }

/** The index of the `)` that closes the `(` at `open`, quotes skipped, or -1. */
function closing(text: string, open: number): number {
  let depth = 1, quote: string | null = null;
  for (let j = open + 1; j < text.length; j++) {
    const c = text[j];
    if (quote) {
      if (c === quote) quote = null;
      else if (c === "\\" && quote === '"') j++;
      continue;
    }
    if (c === "'" || c === '"') quote = c;
    else if (c === "\\") j++;
    else if (c === "(") depth++;
    else if (c === ")" && --depth === 0) return j;
  }
  return -1;
}

/** The line's steps (each with the steps it runs inside it), or null when a quote or a `$(` is never closed. */
function parse(text: string): Step[] | null {
  const steps: Step[] = [];
  let step: Step = { tokens: [], piped: false, subs: [] }, token = "", inToken = false;
  let quote: "'" | '"' | null = null;
  const endToken = () => { if (inToken) step.tokens.push(token); token = ""; inToken = false; };
  const endStep = (piped: boolean) => {
    endToken();
    if (step.tokens.length || step.subs.length) steps.push(step);
    step = { tokens: [], piped, subs: [] };
  };
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quote !== "'") {
      const opens = text[i + 1] === "(" && text[i + 2] !== "(" && (ch === "$" || (!quote && (ch === "<" || ch === ">")));
      if (opens || ch === "`") {
        const end = ch === "`" ? text.indexOf("`", i + 1) : closing(text, i + 1);
        if (end < 0) return null;
        const inner = parse(text.slice(ch === "`" ? i + 1 : i + 2, end));
        if (inner === null) return null;
        step.subs.push(...inner);
        token += text.slice(i, end + 1); inToken = true; i = end;
        continue;
      }
    }
    if (quote) {
      if (ch === quote) quote = null;
      else if (ch === "\\" && quote === '"' && i + 1 < text.length) token += text[++i];
      else token += ch;
      continue;
    }
    if (ch === "'" || ch === '"') { quote = ch; inToken = true; continue; }
    if (ch === "\\" && i + 1 < text.length) { token += text[++i]; inToken = true; continue; }
    if (ch === "&" && (/\d?>$/.test(token) || (!inToken && text[i + 1] === ">"))) { token += ch; inToken = true; continue; }
    if (ch === ";" || ch === "\n" || ch === "|" || ch === "&") {
      const pipe = ch === "|" && text[i + 1] !== "|";
      endStep(pipe);
      if ((ch === "|" || ch === "&") && (text[i + 1] === ch || (ch === "|" && text[i + 1] === "&"))) i++;
      continue;
    }
    if (ch === " " || ch === "\t") { endToken(); continue; }
    token += ch; inToken = true;
  }
  if (quote) return null;
  endStep(false);
  return steps;
}

/** The line's steps as words, the steps run inside a step before it; null when a quote is never closed. */
export function splitShell(text: string): string[][] | null {
  const steps = parse(text);
  if (!steps) return null;
  const out: string[][] = [];
  const walk = (list: Step[]) => list.forEach(s => { walk(s.subs); out.push(s.tokens); });
  walk(steps);
  return out;
}

const base = (word: string) => word.slice(word.lastIndexOf("/") + 1);
/** A program word by its file name; one that is itself a substitution (`$(curl …)`) is kept whole. */
const programOf = (word: string) => (/^(?:\$\(|`)/.test(word) ? word : base(word));
const plain = (args: string[]) => args.filter(a => !a.startsWith("-"));
const unique = <T,>(list: T[]) => [...new Set(list)];

interface Words { program: string; args: string[]; writes: string[]; listed: boolean }

/** A step's program and arguments with the noise taken off: redirects (an output one's file is kept as a write),
 *  assignments and wrappers (sudo, env, timeout, xargs…) with their options. `listed`: xargs gives it its operands. */
function words(tokens: string[]): Words {
  const rest: string[] = [], writes: string[] = [];
  const write = (target: string | undefined) => { if (target && !NOT_A_FILE.has(target)) writes.push(target); };
  for (let i = 0; i < tokens.length; i++) {
    const tk = tokens[i];
    if (/^[<>]\(/.test(tk)) rest.push(tk);
    else if (FD_DUP.test(tk)) continue;
    else if (OUT.test(tk)) write(tokens[++i]);
    else if (IN.test(tk)) i++;
    else if (OUT_ATTACHED.test(tk)) write(OUT_ATTACHED.exec(tk)?.[1]);
    else if (!IN_ATTACHED.test(tk)) rest.push(tk);
  }
  let i = 0, listed = false;
  for (;;) {
    while (i < rest.length && ASSIGNMENT.test(rest[i])) i++;
    const name = base(rest[i] ?? "");
    if (!(name in WRAPPERS)) break;
    i++;
    listed = listed || name === "xargs";
    while (i < rest.length && rest[i].startsWith("-") && rest[i] !== "-") {
      const flag = rest[i++];
      if (flag === "--") break;
      if (!flag.startsWith("--") && flag.length === 2 && WRAPPERS[name].includes(flag[1])) i++;
    }
    if (name === "timeout" && i < rest.length) i++;                         // its duration
  }
  return { program: programOf(rest[i] ?? ""), args: rest.slice(i + 1), writes, listed };
}

/** The command line a shell's `-c` (or `watch`) runs, or null. */
function inlineLine(w: Words): string | null {
  if (SHELLS.has(w.program)) {
    const at = w.args.findIndex(a => /^-[a-z]*c[a-z]*$/i.test(a));
    return at >= 0 && at + 1 < w.args.length ? w.args[at + 1] : null;
  }
  if (w.program === "watch") {
    const args = [...w.args];
    while (args.length && args[0].startsWith("-")) { const flag = args.shift() ?? ""; if (/^-[ndq]$/.test(flag)) args.shift(); }
    return args.length ? args.join(" ") : null;
  }
  return null;
}

/** Whether a program reads the code it runs from its input (`| sh`, `| python3 -`), not a file or `-c`. */
function readsCode(w: Words): boolean {
  if (!RUNS_CODE.has(w.program)) return false;
  for (let i = 0; i < w.args.length; i++) {
    const a = w.args[i];
    if (a === "--") return true;
    if (/^-[a-z]*[cme]$/i.test(a) && !SHELLS.has(w.program) || /^-[a-z]*c[a-z]*$/i.test(a)) return false;
    if (a === "-s" || a === "-") return true;
    if (!a.startsWith("-")) return false;                                     // a script file
  }
  return true;
}

function hostOfUrl(text: string): string | null {
  try {
    const url = new URL(URL_LIKE.test(text) ? text : `https://${text}`);
    return url.hostname || null;
  } catch {
    return null;
  }
}

interface Reading { purpose: Purpose; hosts: string[]; local: string[] }
const run = (program: string): Reading => ({ purpose: { key: "run", params: { program } }, hosts: [], local: [] });

/** Skips an option's value where the program takes one, so the operands are what is left. */
function operands(args: string[], valued: string): string[] {
  const out: string[] = [];
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (a.startsWith("-") && a.length > 1) { if (a.length === 2 && valued.includes(a[1])) i++; continue; }
    out.push(a);
  }
  return out;
}

function ssh(program: string, args: string[], rules: string[]): Reading {
  let timeout = 0;
  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg.startsWith("-") && arg.length > 1) {
      const flag = arg[1], inline = arg.slice(2);
      const value = SSH_VALUE.has(flag) ? (inline || args[++i] || "") : "";
      const m = flag === "o" ? /^ConnectTimeout=(\d+)$/i.exec(value) : null;
      if (m) timeout = Number(m[1]);
      continue;
    }
    const host = arg.slice(arg.lastIndexOf("@") + 1);
    const remote = args.slice(i + 1);
    if (remote[0] === "--") remote.shift();
    // #688 review 6d: words after the host are a command that runs there, read as its own line.
    const there = remote.length ? read(remote.join(" "), rules) : null;
    if (there && there.real) {
      return { purpose: { key: "onHost", params: { host }, inner: there.purpose }, hosts: [host, ...there.hosts],
               local: there.local.map(p => `${host}:${p}`) };
    }
    return { purpose: timeout ? { key: "sshTimeout", params: { host, seconds: timeout } } : { key: "ssh", params: { host } },
             hosts: [host], local: [] };
  }
  return run(program);
}

/** One step's purpose and what it touches: `hosts` (other machines, web addresses, mail addresses) and `local`
 *  (paths on the machine it runs on). `rules` are the server's terminal rules for the line (upload, git-push…). */
function readStep(w: Words, rules: string[]): Reading {
  const { program, args } = w;
  switch (program) {
    case "ssh": case "mosh": case "autossh":
      return ssh(program, args, rules);
    case "scp": case "sftp": case "rsync": {
      const ops = operands(args, COPY_VALUE[program]);
      const remote = (a: string) => /^(?:[^@/\s]+@)?([^:/\s]+):/.exec(a)?.[1];
      const hosts = unique(ops.map(remote).filter(Boolean) as string[]);
      return hosts.length ? { purpose: { key: "copyRemote", params: { host: hosts[0] } }, hosts, local: ops.filter(a => !remote(a)) }
        : { purpose: { key: "copyLocal", params: { count: Math.max(ops.length - 1, 1) } }, hosts: [], local: ops };
    }
    case "curl": case "wget": case "http": case "https": case "xh": {
      const url = plain(args).find(a => /^https?:\/\//i.test(a)) ?? plain(args)[0];
      const host = url ? hostOfUrl(url) : null;
      if (!host) return run(program);
      return { purpose: { key: rules.includes("upload") ? "upload" : "fetch", params: { host } }, hosts: [url], local: [] };
    }
    case "rm": case "rmdir": case "unlink": case "trash": case "srm": {
      const targets = plain(args);
      return targets.length || !w.listed ? { purpose: { key: "delete", params: { count: targets.length } }, hosts: [], local: targets }
        : { purpose: { key: "deleteSome", params: {} }, hosts: [], local: [] };
    }
    case "find": {
      const end = args.findIndex(a => /^[-(!)]/.test(a));
      const roots = end < 0 ? args : args.slice(0, end);
      const exec = args.findIndex(a => /^-(?:exec|execdir|ok|okdir)$/.test(a));
      if (args.includes("-delete") || (exec >= 0 && DELETERS.has(base(args[exec + 1] ?? "")))) {
        return { purpose: { key: "findDelete", params: { where: roots.join(", ") || "." } }, hosts: [], local: roots };
      }
      return { purpose: { key: "run", params: { program } }, hosts: [], local: roots };
    }
    case "mv": {
      const targets = plain(args);
      return { purpose: { key: "move", params: { count: Math.max(targets.length - 1, 1) } }, hosts: [], local: targets };
    }
    case "cp": {
      const targets = plain(args);
      return { purpose: { key: "copyLocal", params: { count: Math.max(targets.length - 1, 1) } }, hosts: [], local: targets };
    }
    case "tee": {
      const targets = plain(args);
      return targets.length ? { purpose: { key: "write", params: { target: targets[0] } }, hosts: [], local: targets } : run(program);
    }
    case "git": {
      const own = args.filter((a, i) => !/^-[Cc]$/.test(a) && !/^-[Cc]$/.test(args[i - 1] ?? ""));   // -C dir, -c key=value
      const [sub, ...rest] = plain(own);
      if (sub === "push") return { purpose: { key: "gitPush", params: { remote: rest[0] ?? "origin" } }, hosts: [], local: [] };
      if (sub === "clone" && rest[0]) {
        return { purpose: { key: "gitClone", params: { repo: rest[0] } }, hosts: [rest[0]], local: [] };
      }
      if (sub === "pull" || sub === "fetch") {
        return { purpose: { key: "gitFetch", params: { remote: rest[0] ?? "origin" } }, hosts: [], local: [] };
      }
      return { purpose: { key: "git", params: { sub: sub ?? "" } }, hosts: [], local: [] };
    }
    case "open": {
      const target = plain(args).at(-1);
      if (!target) return run(program);
      return { purpose: { key: "open", params: { target } }, hosts: URL_LIKE.test(target) ? [target] : [],
               local: URL_LIKE.test(target) ? [] : [target] };
    }
    case "osascript":
      return { purpose: { key: "appleScript", params: {} }, hosts: [], local: [] };
    case "shortcuts": {
      const [sub, name] = plain(args);
      return sub === "run" && name ? { purpose: { key: "shortcut", params: { name } }, hosts: [], local: [] } : run(program);
    }
    case "kill": case "killall": case "pkill":
      return { purpose: { key: "kill", params: { target: plain(args).join(" ") } }, hosts: [], local: [] };
    case "mail": case "mailx": case "sendmail": case "msmtp": case "mutt": {
      const to = plain(args).find(a => a.includes("@"));
      return to ? { purpose: { key: "mailTo", params: { to } }, hosts: [to], local: [] }
        : { purpose: { key: "mail", params: {} }, hosts: [], local: [] };
    }
    default: {
      const [sub, ...pkgs] = plain(args);
      if (INSTALLERS.has(program) && (sub === "install" || sub === "add")) {
        const names = pkgs.filter(p => !p.includes("/") || p.startsWith("@"));
        return { purpose: { key: "install", params: { packages: names.slice(0, 3).join(", ") || program } }, hosts: [], local: [] };
      }
      if (SCRIPT_RUNNERS.has(program) && sub && !args.some(a => a === "-c" || a === "-e" || a === "-m") && !/^(?:[<>$]\(|`)/.test(sub)) {
        return { purpose: { key: "script", params: { program, file: base(sub) } }, hosts: [], local: [sub] };
      }
      // #688 review 6i: an unknown program's operands that look like paths are what it touches.
      return { purpose: { key: "run", params: { program } }, hosts: [], local: plain(args).filter(a => PATH_LIKE.test(a)) };
    }
  }
}

/** `path` as seen from the folder `dir` (a `cd` before it), unless it is absolute, from home, or a variable. */
function rebase(dir: string | null, path: string): string {
  if (!dir || /^(?:\/|~|\$)/.test(path) || URL_LIKE.test(path) || REMOTE_PATH.test(path)) return path;
  const parts = `${dir.replace(/\/+$/, "")}/${path}`.split("/");
  const out: string[] = [];
  for (const part of parts) {
    if (part === "." || (part === "" && out.length)) continue;
    if (part === ".." && out.length && out[out.length - 1] !== ".." && out[out.length - 1] !== "~" && out[out.length - 1] !== "") out.pop();
    else out.push(part);
  }
  return out.join("/") || "/";
}

interface Node { w: Words; from: Node | null; container: Node | null; merged: boolean; run: boolean }

function flatten(steps: Step[], container: Node | null, out: Node[]) {
  let prev: Node | null = null;
  for (const step of steps) {
    const node: Node = { w: words(step.tokens), from: step.piped ? prev : null, container, merged: false, run: false };
    const line = inlineLine(node.w);
    const inner = line === null ? null : parse(line);
    if (inner) flatten(inner, container, out);                             // `sh -c '…'`: its line, read once
    else {
      flatten(step.subs, node, out);                                       // what runs inside it runs first
      out.push(node);
    }
    prev = node;
  }
}

/** The line read: its purpose, what it touches, and how many real steps it has. */
function read(text: string, rules: string[]): { purpose: Purpose; hosts: string[]; local: string[]; real: number } | null {
  const steps = parse(text);
  if (!steps) return null;
  const nodes: Node[] = [];
  flatten(steps, null, nodes);
  // #688 review 6e: a download whose output a program runs as code is one step.
  for (const node of nodes) {
    const isFetch = FETCHERS.has(node.w.program);
    if (!isFetch) continue;
    for (let n: Node | null = node; n; ) {
      const next = nodes.find(m => m.from === n);
      if (!next) break;
      if (readsCode(next.w)) { node.run = true; next.merged = true; break; }
      n = next;
    }
    const host = node.container;
    if (host && (RUNS_CODE.has(host.w.program) || /^[$`]/.test(host.w.program) || host.w.program === "")) {
      node.run = true; host.merged = true;
    }
  }
  let dir: string | null = null;
  const real: Reading[] = [];
  for (const node of nodes) {
    const { program, args, writes } = node.w;
    if (program === "cd" || program === "pushd") {
      const to = plain(args)[0] ?? "~";
      dir = to === "-" ? null : rebase(dir, to);
      continue;
    }
    if (program === "popd") { dir = null; continue; }
    if (node.merged || ((QUIET.has(program) || !program) && !writes.length)) continue;
    let r: Reading = QUIET.has(program) || !program ? { purpose: { key: "write", params: { target: writes[0] } }, hosts: [], local: [] }
      : readStep(node.w, rules);
    if (node.run && (r.purpose.key === "fetch" || r.purpose.key === "upload")) {
      r = { ...r, purpose: { key: "fetchRun", params: { host: r.purpose.params.host } } };
    }
    const local = [...r.local, ...writes].map(p => rebase(dir, p));
    if (r.purpose.key === "write") r = { ...r, purpose: { key: "write", params: { target: rebase(dir, String(r.purpose.params.target)) } } };
    real.push({ ...r, local });
  }
  if (!real.length) return { purpose: { key: "run", params: { program: nodes.find(n => n.w.program)?.w.program ?? "" } },
                             hosts: [], local: [], real: 0 };
  const lead = real.reduce((best, r) => ((STAKES[r.purpose.key] ?? 1) > (STAKES[best.purpose.key] ?? 1) ? r : best));
  return { purpose: lead.purpose, hosts: unique(real.flatMap(r => r.hosts)), local: unique(real.flatMap(r => r.local)),
           real: real.length };
}

/** What a shell line is for and what it touches. `rules`: the server's terminal rules for it (one, or several). */
export function summarize(text: string, rules?: string | string[]): CommandSummary {
  const list = typeof rules === "string" ? [rules] : rules ?? [];
  const r = read(text, list);
  if (!r) return { purpose: { key: "run", params: { program: base(text.trim().split(/\s+/)[0] ?? "") } }, touches: [], more: 0 };
  const outside = r.local.filter(p => /^(?:\/|~|\$|\.\.(?:\/|$))/.test(p) || REMOTE_PATH.test(p));
  const touches = unique([...r.hosts, ...outside, ...r.local]);
  return { purpose: r.purpose, touches, more: Math.max(r.real - 1, 0) };
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

/**
 * The card's 「风险」 row, from what the server decided about the command (never the model's words): every terminal
 * rule it matched (`rules`; an older frame's one `rule`), why it could not read it, whether it also asks for the
 * network, whether it runs outside the sandbox or on another machine. The row takes the worst level of them; a rule
 * the card has no line for still asks, in amber, never as "sandboxed" (#688 review 3, 4).
 */
export function commandRisk(f: { rule?: string; rules?: string[]; unreadable?: string; network?: boolean;
                                 sandbox?: "outside" | "retry"; remoteHost?: string; unsandboxed?: boolean }): CommandRisk {
  const keys: CommandRisk["keys"] = [];
  let level: RiskLevel = "info";
  const raise = (to: RiskLevel) => { if (to === "irreversible" || (to === "warn" && level === "info")) level = to; };
  // Leaving the sandbox is said first on the card (S4a), so it leads the row.
  if (f.sandbox === "outside") { keys.push({ key: "outside" }); raise("warn"); }
  else if (f.sandbox === "retry") { keys.push({ key: "retry" }); raise("warn"); }
  if (f.remoteHost) { keys.push({ key: "remote", params: { host: f.remoteHost } }); raise("warn"); }
  const rules = f.rules?.length ? f.rules : f.rule ? [f.rule] : [];
  const ordered = [...rules.filter(r => IRREVERSIBLE.has(r)), ...rules.filter(r => !IRREVERSIBLE.has(r))];
  let unknown = false;
  for (const rule of ordered) {
    if (rule === "unreadable" && f.unreadable && UNREADABLE_KINDS.has(f.unreadable)) keys.push({ key: `rule.unreadable-${f.unreadable}` });
    else if (RULES.has(rule)) keys.push({ key: `rule.${rule}` });
    else if (!unknown) { keys.push({ key: "rule.unknown" }); unknown = true; }
    raise(IRREVERSIBLE.has(rule) ? "irreversible" : "warn");
  }
  if (!f.sandbox && f.unsandboxed) { keys.push({ key: "unsandboxed" }); raise("warn"); }
  if (f.network) { keys.push({ key: "network" }); raise("warn"); }
  if (!keys.length) keys.push({ key: f.remoteHost ? "remote" : "sandboxed" });
  return { level, keys };
}

/** A purpose in the user's words: a step run on another machine says that step inside its own sentence. */
export function purposeText(t: (key: string, params?: Record<string, unknown>) => string, p: Purpose): string {
  return t(`runcmd.purpose.${p.key}`, { ...p.params, ...(p.inner ? { what: purposeText(t, p.inner) } : {}) });
}
