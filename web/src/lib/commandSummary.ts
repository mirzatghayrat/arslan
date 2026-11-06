/**
 * SMART-8 (the card mock the user OK'd, 2026-11-02): what a command is for and what it touches, read from the
 * command itself. Read by code, never by the model: the card's 「涉及」 (touches) row always comes from here, and its
 * purpose line too unless Arslan said why. server/services/card_purpose.py reads commands the same way (the server's
 * title, which the iPhone shows); both are held to tests/fixtures/card_purpose_vectors.json.
 *
 * A shell line splits into steps (`;`, `&&`, `||`, `|`, `&`, new lines), quotes kept. What a step runs inside it
 * (`$(…)`, backticks, `<(…)`, `>(…)`, `sh -c '…'`, `watch '…'`) is read as steps of its own, before it. Steps that
 * only print, wait or change folder say nothing about what the line does (unless they write a file), so the step
 * with the most at stake names the purpose, and the rest are counted (`more`). A path after `cd` is shown from that
 * folder. The 「涉及」 row lists other machines and web addresses first, then paths outside the work folder, then the
 * rest, so its cap never hides the one that matters (#688 review 6).
 *
 * A step that reaches another machine (curl, ssh, scp, rsync, nc, the mail programs, a cloud CLI, an interpreter
 * running inline code) is read only as a fixed "uses the network" line, with no host and no file: what it sends
 * cannot be told from the command (#688/#689 reviews, Astra's two rounds; the user, 「简化吧」). `unsure` is set, so
 * the risk row says so and the Mac card shows the whole command. A line the reader cannot split (an open quote) gets
 * the plain "run <program>" purpose.
 */

export interface Purpose { key: string; params: Record<string, string | number>; inner?: Purpose }
export interface CommandSummary { purpose: Purpose; touches: string[]; more: number; unsure: boolean }

/** At most this many hosts, paths or addresses in the 「涉及」 row; the rest are counted. */
export const TOUCHES_MAX = 6;
const QUIET = new Set(["echo", "printf", "true", "false", ":", "cd", "pushd", "popd", "sleep", "set", "export",
  "unset", "test", "[", "read", "wait", "clear"]);
/** Programs that run the rest of their words as another program, each with its options that take a value. */
const WRAPPERS: Record<string, string> = { sudo: "CDghpRrTUu", env: "CSu", command: "", exec: "a", nohup: "",
  time: "", nice: "n", timeout: "ks", xargs: "adEILnPs", caffeinate: "tw", stdbuf: "", builtin: "" };
const ASSIGNMENT = /^[A-Za-z_][A-Za-z0-9_]*=/;
const FD_DUP = /^\d*[<>]&(?:\d+|-)$/;
const OUT = /^(?:\d*|&)>>?\|?$/;
const OUT_ATTACHED = /^(?:\d*|&)>>?\|?([^>&|].*)$/;
const IN = /^\d*<(?:<<?|>)?-?$/;
const IN_ATTACHED = /^\d*<{1,3}-?\S/;
const NOT_A_FILE = new Set(["/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty"]);
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
const STAKES: Record<string, number> = { overNetwork: 9, delete: 9, deleteSome: 9, findDelete: 9, gitPush: 7,
  kill: 6, appleScript: 5, shortcut: 5, install: 5, write: 4, move: 4, open: 3, copyLocal: 3, gitClone: 3,
  gitFetch: 2, script: 2 };

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
      const opens = text[i + 1] === "(" && text[i + 2] !== "("
        && (ch === "$" || (!quote && (ch === "<" || ch === ">" || (ch === "=" && !inToken))));
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
/** Re-quote a token so a token slice can be read as a command line again (for `find -exec`): a word with a space or
 *  a shell metacharacter is wrapped in single quotes, so `sh -c "cmd"` survives the round trip. */
const requote = (tok: string) => (/^[A-Za-z0-9_@%^:=+,./~-]+$/.test(tok) ? tok : `'${tok.replace(/'/g, "'\\''")}'`);

interface Words { program: string; args: string[]; writes: string[]; inputs: string[]; assigns: string[]; raw: string; listed: boolean }

/** A step's program and arguments with the noise taken off: redirects (an output one's file is kept as a write),
 *  assignments and wrappers (sudo, env, timeout, xargs…) with their options. `listed`: xargs gives it its operands. */
function words(tokens: string[]): Words {
  const rest: string[] = [], writes: string[] = [], inputs: string[] = [];
  const write = (target: string | undefined) => { if (target && !NOT_A_FILE.has(target)) writes.push(target); };
  const input = (source: string | undefined) => { if (source && !NOT_A_FILE.has(source) && source !== "/dev/stdin") inputs.push(source); };
  for (let i = 0; i < tokens.length; i++) {
    const tk = tokens[i];
    if (/^[<>]\(/.test(tk)) rest.push(tk);
    else if (FD_DUP.test(tk)) continue;
    else if (OUT.test(tk)) write(tokens[++i]);
    else if (IN.test(tk)) { if (/^\d*<$/.test(tk)) input(tokens[i + 1]); i++; }        // a heredoc's word is no file
    else if (OUT_ATTACHED.test(tk)) write(OUT_ATTACHED.exec(tk)?.[1]);
    else if (IN_ATTACHED.test(tk)) input(/^\d*<([^<].*)$/.exec(tk)?.[1]);
    else rest.push(tk);
  }
  let i = 0, listed = false;
  const assigns: string[] = [];
  const raw = programOf(rest.find(tk => !ASSIGNMENT.test(tk)) ?? "");
  for (;;) {
    while (i < rest.length && ASSIGNMENT.test(rest[i])) assigns.push(rest[i++].split("=")[0]);
    const name = base(rest[i] ?? "");
    if (!Object.prototype.hasOwnProperty.call(WRAPPERS, name)) break;      // never `toString` and its kin
    // `env -S "…"` runs the string as a command line; keep env so inlineLine reads it (Astra r2, 1). `command -v X`
    // only names X, so keep command for the names-only check (Astra r2, F3).
    if (name === "env" && (rest[i + 1] === "-S" || rest[i + 1] === "--split-string")) break;
    if (name === "command" && /^-[vV]$/.test(rest[i + 1] ?? "")) break;
    i++;
    listed = listed || name === "xargs";
    while (i < rest.length && rest[i].startsWith("-") && rest[i] !== "-") {
      const flag = rest[i++];
      if (flag === "--") break;
      if (!flag.startsWith("--") && flag.length === 2 && WRAPPERS[name].includes(flag[1])) i++;
    }
    if (name === "timeout" && i < rest.length) i++;                         // its duration
  }
  return { program: programOf(rest[i] ?? ""), args: rest.slice(i + 1), writes, inputs, assigns, raw, listed };
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
  if (w.program === "eval") return w.args.length ? w.args.join(" ") : null;
  if (w.program === "trap" && w.args[0] && w.args[0] !== "-") return w.args[0];
  if (w.program === "env") {
    const at = w.args.findIndex(a => a === "-S" || a === "--split-string");
    if (at >= 0) return at + 1 < w.args.length ? w.args[at + 1] : null;
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

/** `unsure`: the step reaches another machine and what it sends cannot be read from the command, so it is read only
 *  as "uses the network" (no host, no file). */
interface Reading { purpose: Purpose; hosts: string[]; local: string[]; unsure?: boolean }
const run = (program: string): Reading => ({ purpose: { key: "run", params: { program } }, hosts: [], local: [] });
/** SMART-8 (#688/#689 reviews, Astra's two rounds; the user: 「简化吧」): a step that reaches another machine is read
 *  only as a fixed line — no host, no file — because what it sends cannot be told from the command. `unsure` is set,
 *  so the risk row and the card say so, and the Mac card shows the whole command. */
const overNetwork = (program: string): Reading =>
  ({ purpose: { key: "overNetwork", params: { program } }, hosts: [], local: [], unsure: true });

/** Programs that reach another machine; a step of one is never read past "uses the network". */
const NETWORK = new Set(["curl", "wget", "http", "https", "xh", "nc", "ncat", "netcat", "socat", "telnet", "ftp",
  "tftp", "lftp", "smbclient", "sftp", "ssh", "mosh", "autossh", "scp", "rsync", "mail", "mailx", "sendmail",
  "msmtp", "mutt", "aws", "gcloud", "gsutil", "gh", "az", "rclone", "s3cmd", "dig", "nslookup", "host", "ping",
  "traceroute", "openssl", "ssh-copy-id", "docker", "podman", "kubectl", "twine", "azcopy"]);
/** Interpreters whose inline code (`-c`, `-e`, `--eval` in any attached form) could reach the network (Astra 7). */
const INLINE_CODE: Record<string, RegExp> = { python: /^-[A-Za-z]*c/, python2: /^-[A-Za-z]*c/, python3: /^-[A-Za-z]*c/,
  node: /^(?:-[A-Za-z]*[ep]|--eval|--print)/, perl: /^-[A-Za-z]*[eE]/, ruby: /^-[A-Za-z]*e/, php: /^-[A-Za-z]*r/,
  bun: /^(?:-e|--eval)/, deno: /^eval$/ };

/** One step's purpose and what it touches: `hosts` (other machines, web addresses, mail addresses) and `local`
 *  (paths on the machine it runs on). `rules` are the server's terminal rules for the line (upload, git-push…). */
/** A step whose own program only names things (`grep curl`, `man ssh`, `command -v curl`) does not run its
 *  arguments, so a network name among them is not reached (Astra r2, F3). */
const NAMES_ONLY = new Set(["echo", "printf", "grep", "egrep", "fgrep", "rg", "man", "which", "type", "whence", "apropos"]);
function namesOnly(w: Words): boolean {
  if (NAMES_ONLY.has(w.program)) return true;
  if (w.program === "command" && /^-[vV]$/.test(w.args[0] ?? "")) return true;
  if (w.program === "brew" && (w.args[0] === "info" || w.args[0] === "search")) return true;
  return false;
}

/** The network program a step runs, wherever it sits — the first token, or one buried by a wrapper option the reader
 *  does not model (`arch … curl`, `sudo --user root curl`), by `find -exec`, or in a compound (Astra r2, F2). Each
 *  token is matched by its basename, lower-cased (so `Curl`, run as the real binary on a case-insensitive volume, is
 *  caught too — F1); an INLINE_CODE interpreter counts only when its inline flag follows it. */
function buriedNetwork(w: Words): string | null {
  const toks = [w.program, ...w.args];
  for (let i = 0; i < toks.length; i++) {
    const tok = toks[i];
    if (i > 0 && (tok.includes("/") || URL_LIKE.test(tok))) continue;      // a path or URL operand is not a program (Astra r2)
    const name = base(tok).toLowerCase();
    if (NETWORK.has(name)) return name;
    if (Object.prototype.hasOwnProperty.call(INLINE_CODE, name) && i + 1 < toks.length && INLINE_CODE[name].test(toks[i + 1]))
      return name;
  }
  return null;
}
/** Common commands whose operands are files or data, never programs — their reading is kept, not scanned (Astra r2). */
const BENIGN_LOCAL = new Set(["ls", "touch", "chmod", "chown", "chgrp", "mkdir", "ln", "tar", "stat", "file", "head",
  "tail", "wc", "sort", "uniq", "cut", "du", "basename", "dirname", "realpath", "readlink", "cmp", "diff", "nl", "tac",
  "rev", "vim", "vi", "nano", "emacs", "code", "subl", "pico", "ed", "vimdiff", "mate"]);
/** A benign command's option that makes it run another program (tar's compressor, an editor's command): the step may
 *  run anything, so it reads overNetwork; the value is not parsed (Astra r2 delta). */
const BENIGN_EXEC: Record<string, RegExp> = {
  tar: /^(?:-I|(?:--use-compress-program|--to-command)(?:=|$))/,
  vim: /^(?:-c|--cmd|\+)/, vi: /^(?:-c|--cmd|\+)/, vimdiff: /^(?:-c|--cmd|\+)/,
  emacs: /^--eval(?:=|$)/, sort: /^--compress-program(?:=|$)/, ed: /^!/,
};

function readStep(w: Words): Reading {
  const program = w.program.toLowerCase();                                 // the binary a case-insensitive volume runs
  const { args } = w;
  if (!program) return overNetwork(w.raw || "command");                    // a wrapper took everything (Astra r2, 1)
  if (NETWORK.has(program)) return overNetwork(program);                   // the program itself reaches the network
  if (Object.prototype.hasOwnProperty.call(INLINE_CODE, program) && args.some(a => INLINE_CODE[program].test(a)))
    return overNetwork(program);
  switch (program) {
    case "cat":
      return { purpose: { key: "run", params: { program } }, hosts: [], local: plain(args) };
    case "rm": case "rmdir": case "unlink": case "trash": case "srm": {
      const targets = plain(args);
      return targets.length || !w.listed ? { purpose: { key: "delete", params: { count: targets.length } }, hosts: [], local: targets }
        : { purpose: { key: "deleteSome", params: {} }, hosts: [], local: [] };
    }
    case "find": {
      const end = args.findIndex(a => /^[-(!)]/.test(a));
      const roots = end < 0 ? args : args.slice(0, end);
      // Every -exec/-execdir/-ok/-okdir action (up to its `;`/`+`) is a command find runs; read each as its own line
      // so a wrapper, a shell, a second action or an interpreter flag anywhere in it is caught (Astra r2 delta³).
      let deletes = args.includes("-delete");
      for (let i = 0; i < args.length; i++) {
        if (!/^-(?:exec|execdir|ok|okdir)$/.test(args[i])) continue;
        const slice: string[] = [];
        for (let j = i + 1; j < args.length && args[j] !== ";" && args[j] !== "+"; j++) slice.push(args[j]);
        if (!slice.length) continue;
        const r = read(slice.map(requote).join(" "), []);
        if (r?.unsure) return overNetwork(String(r.purpose.params.program ?? program));
        if (r && ["delete", "deleteSome", "findDelete"].includes(r.purpose.key)) deletes = true;
      }
      if (deletes) return { purpose: { key: "findDelete", params: { where: roots.join(", ") || "." } }, hosts: [], local: roots };
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
      if (args.some(a => /^-c$/.test(a) || /^--(?:config|upload-pack|receive-pack)(?:=|$)/.test(a))
          || w.assigns.some(v => /^GIT_(?:SSH|SSH_COMMAND|PROXY_COMMAND)$/.test(v))) return overNetwork("git");
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
    default: {
      if (Object.prototype.hasOwnProperty.call(BENIGN_EXEC, program) && args.some(a => BENIGN_EXEC[program].test(a)))
        return overNetwork(program);                                       // an option that runs another program
      const [sub, ...pkgs] = plain(args);
      if ((["npm", "pnpm", "yarn", "cargo"].includes(program) && sub === "publish") || (program === "gem" && sub === "push")) {
        return overNetwork(program);                                       // uploads to a registry
      }
      if (INSTALLERS.has(program) && (sub === "install" || sub === "add")) {
        const names = pkgs.filter(p => !p.includes("/") || p.startsWith("@"));
        return { purpose: { key: "install", params: { packages: names.slice(0, 3).join(", ") || program } }, hosts: [], local: [] };
      }
      if (SCRIPT_RUNNERS.has(program) && sub && !args.some(a => a === "-c" || a === "-e" || a === "-m") && !/^(?:[<>$]\(|`)/.test(sub)) {
        return { purpose: { key: "script", params: { program, file: base(sub) } }, hosts: [], local: [sub] };
      }
      // Astra r2: scan only an unknown program — a launcher (arch, script…), a compound (`{ }`, if/for), a function
      // body, a shell keyword — for a network program it runs. A step that only names things, and the file-reading
      // commands in BENIGN_LOCAL, keep their reading; their operands are never read as programs.
      if (!namesOnly(w) && !BENIGN_LOCAL.has(program)) {
        const buried = buriedNetwork(w);
        if (buried) return overNetwork(buried);
      }
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

/** A shell a step runs in: a `$(…)` or `sh -c '…'` starts its own, so a `cd` inside it stays there (Astra 8). */
interface Ctx { parent: Ctx | null }
interface Node { w: Words; from: Node | null; container: Node | null; merged: boolean; run: boolean; ctx: Ctx }

function flatten(steps: Step[], container: Node | null, out: Node[], ctx: Ctx) {
  let prev: Node | null = null;
  for (const step of steps) {
    const node: Node = { w: words(step.tokens), from: step.piped ? prev : null, container, merged: false, run: false, ctx };
    const line = inlineLine(node.w);
    const inner = line === null ? null : parse(line);
    if (inner && inner.length) flatten(inner, container, out, { parent: ctx });   // `sh -c '…'`: its line, read once
    else {
      flatten(step.subs, node, out, { parent: ctx });                      // what runs inside it runs first
      out.push(node);
    }
    prev = node;
  }
}

/** The line read: its purpose, what it touches, how many real steps it has, and whether a transfer in it was not
 *  fully read (`unsure`). */
function read(text: string, rules: string[]): { purpose: Purpose; hosts: string[]; local: string[]; real: number;
                                                 unsure: boolean } | null {
  const steps = parse(text);
  if (!steps) return null;
  const nodes: Node[] = [];
  flatten(steps, null, nodes, { parent: null });
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
  const dirs = new Map<Ctx, string | null>();
  const dirOf = (ctx: Ctx | null): string | null => (!ctx ? null : dirs.has(ctx) ? dirs.get(ctx) ?? null : dirOf(ctx.parent));
  const real: Reading[] = [];
  for (const node of nodes) {
    const { program, args, writes } = node.w;
    const dir = dirOf(node.ctx);
    if (program === "cd" || program === "pushd") {
      const to = args.find(a => a === "-" || !a.startsWith("-")) ?? "~";         // `cd -`: a folder the line does not name
      dirs.set(node.ctx, to === "-" ? null : rebase(dir, to));
      continue;
    }
    if (program === "popd") { dirs.set(node.ctx, null); continue; }
    // A wrapper that took its program (`sudo`, `timeout 5` alone) is read by readStep, not skipped (Astra r2, 1).
    const wrapped = !program && Object.prototype.hasOwnProperty.call(WRAPPERS, node.w.raw);
    if (node.merged || ((QUIET.has(program) || (!program && !wrapped)) && !writes.length)) continue;
    let r: Reading = (QUIET.has(program) || (!program && !wrapped)) ? { purpose: { key: "write", params: { target: writes[0] } }, hosts: [], local: [] }
      : readStep(node.w);
    const local = unique([...r.local, ...writes].map(p => rebase(dir, p)));
    if (r.purpose.key === "write") r = { ...r, purpose: { key: "write", params: { target: rebase(dir, String(r.purpose.params.target)) } } };
    real.push({ ...r, local });
  }
  if (!real.length) return { purpose: { key: "run", params: { program: nodes.find(n => n.w.program)?.w.program ?? "" } },
                             hosts: [], local: [], real: 0, unsure: false };
  const lead = real.reduce((best, r) => ((STAKES[r.purpose.key] ?? 1) > (STAKES[best.purpose.key] ?? 1) ? r : best));
  return { purpose: lead.purpose, hosts: unique(real.flatMap(r => r.hosts)), local: unique(real.flatMap(r => r.local)),
           real: real.length, unsure: real.some(r => r.unsure) };
}

/** What a shell line is for and what it touches; `unsure`: a transfer in it was not fully read, so it may send local
 *  data. `rules`: the server's terminal rules for it (one, or several). */
export function summarize(text: string, rules?: string | string[]): CommandSummary {
  const list = typeof rules === "string" ? [rules] : rules ?? [];
  const r = read(text, list);
  if (!r) return { purpose: { key: "run", params: { program: base(text.trim().split(/\s+/)[0] ?? "") } }, touches: [], more: 0,
                   unsure: false };
  const outside = r.local.filter(p => /^(?:\/|~|\$|\.\.(?:\/|$))/.test(p) || REMOTE_PATH.test(p));
  const touches = unique([...r.hosts, ...outside, ...r.local]);
  return { purpose: r.purpose, touches, more: Math.max(r.real - 1, 0), unsure: r.unsure };
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
                                 sandbox?: "outside" | "retry"; remoteHost?: string; unsandboxed?: boolean;
                                 unsure?: boolean }): CommandRisk {
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
  // #688 review, Astra: a transfer the reader could not fully read may send local data, whatever the rules say.
  if (f.unsure) { keys.push({ key: "rule.unreadable-send" }); raise("warn"); }
  if (!f.sandbox && f.unsandboxed) { keys.push({ key: "unsandboxed" }); raise("warn"); }
  if (f.network) { keys.push({ key: "network" }); raise("warn"); }
  if (!keys.length) keys.push({ key: f.remoteHost ? "remote" : "sandboxed" });
  return { level, keys };
}

/** A purpose in the user's words: a step run on another machine says that step inside its own sentence. */
export function purposeText(t: (key: string, params?: Record<string, unknown>) => string, p: Purpose): string {
  return t(`runcmd.purpose.${p.key}`, { ...p.params, ...(p.inner ? { what: purposeText(t, p.inner) } : {}) });
}
