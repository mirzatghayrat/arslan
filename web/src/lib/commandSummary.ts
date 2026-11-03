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
export interface CommandSummary { purpose: Purpose; touches: string[]; more: number; unsure: boolean }

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
const STAKES: Record<string, number> = { fetchRun: 10, delete: 9, deleteSome: 9, findDelete: 9, unreadableSend: 9,
  mailTo: 8, mail: 8, mailFile: 8, mailFileMore: 8, upload: 8, uploadFile: 8, uploadFileMore: 8, onHost: 7, gitPush: 7, kill: 6, copyRemote: 6, ssh: 5, sshTimeout: 5, appleScript: 5, shortcut: 5,
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

interface Words { program: string; args: string[]; writes: string[]; inputs: string[]; listed: boolean }

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
  for (;;) {
    while (i < rest.length && ASSIGNMENT.test(rest[i])) i++;
    const name = base(rest[i] ?? "");
    if (!Object.prototype.hasOwnProperty.call(WRAPPERS, name)) break;      // never `toString` and its kin
    i++;
    listed = listed || name === "xargs";
    while (i < rest.length && rest[i].startsWith("-") && rest[i] !== "-") {
      const flag = rest[i++];
      if (flag === "--") break;
      if (!flag.startsWith("--") && flag.length === 2 && WRAPPERS[name].includes(flag[1])) i++;
    }
    if (name === "timeout" && i < rest.length) i++;                         // its duration
  }
  return { program: programOf(rest[i] ?? ""), args: rest.slice(i + 1), writes, inputs, listed };
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

/** A web address's host, read the same way here and in server/services/card_purpose.py (#688 review, Astra 9): ASCII
 *  only, as written, lowercased; an IPv6 host keeps its brackets. No IDN, no `%` escape, no `_`, no IPv4 shorthand
 *  (`127.1`), no port that is not a number: such a host is not read at all, so its transfer is not read either. */
function hostOfUrl(text: string): string | null {
  const m = /^[a-z][a-z0-9+.-]*:\/\/([^/?#]*)/i.exec(text) ?? /^([^/?#]*)/.exec(text);
  let auth = m?.[1] ?? "";
  auth = auth.slice(auth.lastIndexOf("@") + 1);
  let host: string, port: string;
  if (auth.startsWith("[")) {
    const close = auth.indexOf("]");
    if (close < 0) return null;
    host = auth.slice(0, close + 1); port = auth.slice(close + 1);
    if (!/^\[[0-9a-fA-F:.]+\]$/.test(host)) return null;
  } else {
    const colon = auth.indexOf(":");
    host = colon < 0 ? auth : auth.slice(0, colon); port = colon < 0 ? "" : auth.slice(colon);
    if (!/^[A-Za-z0-9.-]+$/.test(host) || host.startsWith(".") || host.includes("..")) return null;
    if (/^[0-9.]+$/.test(host) && !(/^[0-9]{1,3}(?:\.[0-9]{1,3}){3}$/.test(host) && host.split(".").every(n => Number(n) <= 255))) return null;
  }
  if (port && !/^:[0-9]{0,5}$/.test(port)) return null;
  return host.toLowerCase();
}

/** `sent`: the files a step sends, named on it. `stdin`: it sends its input too (`@-`, a mail's body). `stdinUnsure`:
 *  given an input, what it sends is not read (ssh). `unsure`: the step was not fully read (#688 review, Astra). */
interface Reading { purpose: Purpose; hosts: string[]; local: string[]; sent?: string[]; stdin?: boolean;
                    stdinUnsure?: boolean; unsure?: boolean }
const run = (program: string): Reading => ({ purpose: { key: "run", params: { program } }, hosts: [], local: [] });
/** A transfer the reader cannot fully read: said so, never read as a download or a plain run (#688 review, Astra). */
const unsure = (program: string, hosts: string[] = [], local: string[] = []): Reading =>
  ({ purpose: { key: "unreadableSend", params: { program } }, hosts, local, unsure: true });

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

interface Spec { valued: string; flags: string; long: Map<string, boolean>; multi?: RegExp; stop?: boolean }
const longs = (valued: string, flags: string) =>
  new Map<string, boolean>([...valued.split(" ").map(n => [`--${n}`, true] as [string, boolean]),
                            ...flags.split(" ").map(n => [`--${n}`, false] as [string, boolean])]);

/** A command's options by its own table: `ok` is false when one is not in it (or lacks its value). Short options may
 *  be bundled (`-sd @f`); `stop`: options end at the first operand (BSD getopt, as ssh and scp parse them on a Mac). */
function parseOpts(args: string[], spec: Spec): { ok: boolean; opts: [string, string][]; operands: string[] } {
  const opts: [string, string][] = [], ops: string[] = [];
  let ok = true;
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (a === "--") { ops.push(...args.slice(i + 1)); break; }
    if (spec.multi?.test(a)) { opts.push([a, ""]); continue; }
    if (a.startsWith("--")) {
      const eq = a.indexOf("="), name = eq < 0 ? a : a.slice(0, eq);
      const valued = spec.long.get(name) ?? spec.long.get(name.replace(/^--no-/, "--"));
      if (valued === undefined || (valued === false && eq >= 0)) { ok = false; continue; }
      const value = !valued ? "" : eq >= 0 ? a.slice(eq + 1) : args[++i];
      if (value === undefined) ok = false;
      opts.push([name, value ?? ""]);
      continue;
    }
    if (a.startsWith("-") && a.length > 1) {
      for (let j = 1; j < a.length; j++) {
        const c = a[j];
        if (spec.valued.includes(c)) {
          const value = j + 1 < a.length ? a.slice(j + 1) : args[++i];
          if (value === undefined) ok = false;
          opts.push([`-${c}`, value ?? ""]);
          break;
        }
        if (!spec.flags.includes(c)) { ok = false; break; }
        opts.push([`-${c}`, ""]);
      }
      continue;
    }
    if (spec.stop) { ops.push(...args.slice(i)); break; }
    ops.push(a);
  }
  return { ok, opts, operands: ops };
}

const CURL: Spec = { valued: "AbcCdDeEFHKmoPQrtTuUwxXyYz", flags: "sSLfkviIOJGNq012346gjlnRZBaMVhp#",
  long: longs("data data-ascii data-binary data-raw data-urlencode json form form-string upload-file url header output "
    + "user request referer user-agent cookie cookie-jar proxy proxy-user max-time connect-timeout retry retry-delay "
    + "retry-max-time write-out cert key cacert capath cert-type key-type pass resolve connect-to limit-rate "
    + "max-filesize range output-dir interface dns-servers oauth2-bearer unix-socket abstract-unix-socket proto "
    + "proto-redir ciphers tls-max max-redirs continue-at dump-header time-cond keepalive-time expect100-timeout "
    + "local-port speed-limit speed-time url-query aws-sigv4 netrc-file config variable trace trace-ascii stderr "
    + "preproxy noproxy socks5 socks5-hostname socks4 socks4a parallel-max hsts alt-svc etag-save etag-compare",
    "silent show-error location location-trusted fail fail-with-body fail-early insecure verbose include head "
    + "remote-name remote-name-all remote-header-name get buffer compressed http0.9 http1.0 http1.1 http2 "
    + "http2-prior-knowledge http3 http3-only ipv4 ipv6 globoff progress-bar progress-meter create-dirs raw "
    + "tcp-nodelay anyauth basic digest ntlm negotiate netrc netrc-optional post301 post302 post303 list-only append "
    + "ssl ssl-reqd tlsv1 tlsv1.0 tlsv1.1 tlsv1.2 tlsv1.3 path-as-is parallel parallel-immediate retry-all-errors "
    + "retry-connrefused keepalive sessionid disable styled-output version help manual junk-session-cookies "
    + "remove-on-error skip-existing") };
const WGET: Spec = { valued: "OoaPUtTwQelABDXIiR", flags: "qvcNrkpmSbxH46LKEFdhV", multi: /^-n[vpcdH]$/,
  long: longs("output-document output-file append-output directory-prefix user-agent header post-data post-file "
    + "body-data body-file method tries timeout user password http-user http-password wait limit-rate quota execute "
    + "input-file config base referer load-cookies save-cookies ca-certificate certificate private-key level accept "
    + "reject domains exclude-directories include-directories restrict-file-names progress bind-address ftp-user "
    + "ftp-password read-timeout dns-timeout connect-timeout waitretry",
    "quiet verbose verbose continue timestamping recursive parent clobber convert-links page-requisites mirror "
    + "server-response spider check-certificate background show-progress inet4-only inet6-only span-hosts relative "
    + "backup-converted adjust-extension content-disposition trust-server-names cookies keep-session-cookies "
    + "ignore-length auth-no-challenge https-only directories host-directories force-directories debug help version "
    + "force-html random-wait cache proxy") };
const SSH: Spec = { valued: "BbcDEeFIiJLlmOoPpQRSWw", flags: "46AaCfGgKkMNnqsTtVvXxYy", long: new Map(), stop: true };
const SCP: Spec = { valued: "cDFiJlOoPSX", flags: "346ABCOpqRrTv", long: new Map(), stop: true };
const RSYNC: Spec = { valued: "eBfTM", flags: "avzrPhnucCdlLkKHpogDtSWxRqiIAXEbFm8O",
  long: longs("rsh exclude include exclude-from include-from files-from filter port bwlimit timeout contimeout info "
    + "debug chmod chown usermap groupmap backup-dir suffix temp-dir partial-dir compare-dest copy-dest link-dest "
    + "log-file log-file-format out-format max-size min-size max-delete modify-window block-size remote-option "
    + "rsync-path password-file iconv compress-level checksum-choice protocol sockopts address outbuf stop-after "
    + "stop-at write-batch read-batch only-write-batch",
    "archive verbose compress recursive partial progress human-readable dry-run update checksum delete delete-after "
    + "delete-before delete-during delete-delay delete-excluded stats itemize-changes links perms times group owner "
    + "devices specials hard-links acls xattrs sparse one-file-system whole-file relative copy-links safe-links "
    + "copy-dirlinks keep-dirlinks backup remove-source-files inplace append append-verify mkpath ignore-existing "
    + "existing size-only quiet ignore-times omit-dir-times omit-link-times numeric-ids prune-empty-dirs force "
    + "ignore-errors list-only motd 8-bit-output super fake-super executability crtimes atimes open-noatime "
    + "cvs-exclude from0 protect-args secluded-args trust-sender copy-unsafe-links munge-links implied-dirs "
    + "delay-updates fuzzy blocking-io") };
const MAILX: Spec = { valued: "scbaAqrSuf", flags: "nNvEdiIH", long: new Map() };
const SENDMAIL: Spec = { valued: "fFBNRVXaC", flags: "iv", multi: /^-o[A-Za-z]+$/, long: new Map() };
/** Programs that reach another machine; a step of one is read only when every option and source is known. */
const TALKERS = new Set(["nc", "ncat", "netcat", "socat", "telnet", "ftp", "tftp", "lftp", "smbclient", "sftp"]);
const CLOUD = new Set(["aws", "gcloud", "gsutil", "gh", "az", "rclone", "s3cmd"]);
const INLINE_CODE: Record<string, RegExp> = { python: /^-[a-zA-Z]*c$/, python2: /^-[a-zA-Z]*c$/, python3: /^-[a-zA-Z]*c$/,
  node: /^(?:-e|-p|--eval|--print)$/, perl: /^-[a-zA-Z]*[eE]$/, ruby: /^-[a-zA-Z]*e$/, php: /^-r$/,
  bun: /^(?:-e|--eval)$/, deno: /^eval$/ };
const NETWORK = new Set([...FETCHERS, ...TALKERS, ...CLOUD, "ssh", "mosh", "autossh", "scp", "rsync", "mail", "mailx",
  "sendmail", "msmtp", "mutt"]);

/** The file a `-F name=@file` / `name=<file` field sends, curl's own quoting read (`=@"a;b.txt"`); "" for a field
 *  with no file; null when its quoting does not close. */
function formFile(value: string): string | null {
  const m = /^[^=]*=[@<]/.exec(value);
  if (!m) return "";
  const rest = value.slice(m[0].length);
  if (!rest.startsWith('"')) return rest.split(";")[0];
  let out = "";
  for (let i = 1; i < rest.length; i++) {
    if (rest[i] === "\\" && i + 1 < rest.length) out += rest[++i];
    else if (rest[i] === '"') return out;
    else out += rest[i];
  }
  return null;
}

function curl(w: Words, rules: string[]): Reading {
  const { ok, opts, operands: ops } = parseOpts(w.args, CURL);
  const files: string[] = [];
  let sends = false, sure = ok, stdin = false;
  const file = (f: string) => { if (f === "-") stdin = true; else if (f) files.push(f); };
  const urls = [...opts.filter(([n]) => n === "--url").map(([, v]) => v), ...ops];
  for (const [name, value] of opts) {
    switch (name) {
      case "-K": case "--config": case "--variable": sure = false; break;
      case "-d": case "--data": case "--data-ascii": case "--data-binary": case "--json":
        sends = true; if (value.startsWith("@")) file(value.slice(1)); break;
      case "--data-raw": case "--form-string": sends = true; break;
      case "--data-urlencode": sends = true; file(/^[^=@]*@(.*)$/.exec(value)?.[1] ?? ""); break;
      case "-F": case "--form": { sends = true; const f = formFile(value); if (f === null) sure = false; else file(f); break; }
      case "-T": case "--upload-file": sends = true; if (/[[{]/.test(value)) sure = false; else file(value); break;
      case "-b": case "--cookie": if (!value.includes("=")) file(value); break;              // a cookie file is sent
      case "-H": case "--header": if (value.startsWith("@")) file(value.slice(1)); break;
    }
  }
  const hosts = urls.map(hostOfUrl);
  if (!urls.length && sure) return run(w.program);                                         // nothing goes out
  if (!sure || !urls.length || hosts.some(h => !h)) return { ...unsure(w.program, urls, files), stdin };
  return { purpose: { key: sends || rules.includes("upload") ? "upload" : "fetch", params: { host: hosts[0] as string } },
           hosts: urls, local: [], sent: files, stdin };
}

function wget(w: Words): Reading {
  const { ok, opts, operands: urls } = parseOpts(w.args, WGET);
  const files: string[] = [];
  let sends = false, sure = ok;
  for (const [name, value] of opts) {
    if (["-e", "--execute", "-i", "--input-file", "--config"].includes(name)) sure = false;
    else if (name === "--post-file" || name === "--body-file") { sends = true; files.push(value); }
    else if (name === "--post-data" || name === "--body-data") sends = true;
    else if (name === "--load-cookies") files.push(value);
  }
  const hosts = urls.map(hostOfUrl);
  if (!urls.length && sure) return run(w.program);
  if (!sure || !urls.length || hosts.some(h => !h)) return unsure(w.program, urls, files);
  return { purpose: { key: sends ? "upload" : "fetch", params: { host: hosts[0] as string } }, hosts: urls, local: [],
           sent: files };
}

/** HTTPie (http, https, xh): read only as `http [GET|HEAD] <url>`; items and anything else may send local data. */
function httpie(w: Words): Reading {
  const ops = w.args.filter(a => !/^-/.test(a));
  const flags = w.args.filter(a => /^-/.test(a));
  const url = ops.length === 1 ? ops[0] : ops.length === 2 && /^(?:GET|HEAD)$/.test(ops[0]) ? ops[1] : null;
  const host = url ? hostOfUrl(url) : null;
  if (!host || flags.some(f => !/^(?:-v|-h|-b|--verbose|--headers|--body|--follow|-F|--check-status|--pretty=\w+)$/.test(f))) {
    return unsure(w.program, ops.filter(a => hostOfUrl(a) !== null && /[./:]/.test(a)), ops.filter(a => PATH_LIKE.test(a)));
  }
  return { purpose: { key: "fetch", params: { host } }, hosts: [url as string], local: [], stdinUnsure: true };
}

function ssh(program: string, args: string[], rules: string[]): Reading {
  const { ok, opts, operands: ops } = parseOpts(args, program === "autossh" ? { ...SSH, valued: SSH.valued + "M" } : SSH);
  const risky = opts.some(([n, v]) => n === "-F" || n === "-W"
    || (n === "-o" && /^(?:ProxyCommand|LocalCommand|PermitLocalCommand|KnownHostsCommand)\b/i.test(v)));
  const target = ops[0];
  if (!target) return ok && !risky ? run(program) : unsure(program);
  const host = target.slice(target.lastIndexOf("@") + 1);
  if (!ok || risky || program === "mosh" && opts.length) return unsure(program, [host]);
  const timeout = Number(opts.map(([n, v]) => (n === "-o" ? /^ConnectTimeout=(\d+)$/i.exec(v)?.[1] : undefined)).find(Boolean) ?? 0);
  const remote = ops.slice(1);
  if (remote[0] === "--") remote.shift();
  // #688 review 6d: words after the host are a command that runs there, read as its own line.
  const there = remote.length ? read(remote.join(" "), rules) : null;
  if (there && there.real) {
    return { purpose: { key: "onHost", params: { host }, inner: there.purpose }, hosts: [host, ...there.hosts],
             local: there.local.map(p => `${host}:${p}`), stdinUnsure: true, unsure: there.unsure };
  }
  return { purpose: timeout ? { key: "sshTimeout", params: { host, seconds: timeout } } : { key: "ssh", params: { host } },
           hosts: [host], local: [], stdinUnsure: true };
}

/** scp and rsync: the last operand is where it copies to. Local files sent to another machine are named. */
function copy(w: Words): Reading {
  const rsync = w.program === "rsync";
  const { ok, opts, operands: ops } = parseOpts(w.args, rsync ? RSYNC : SCP);
  const shell = opts.find(([n]) => n === "-e" || n === "--rsh")?.[1];
  const risky = opts.some(([n]) => ["-F", "-S", "--files-from", "--read-batch"].includes(n))
    || (shell !== undefined && !/^ssh(?:\s|$)/.test(shell));
  const extra = opts.filter(([n]) => n === "--password-file").map(([, v]) => v);
  const remote = (a: string) => /^[a-z]+:\/\//i.test(a) ? hostOfUrl(a) ?? "" : /^(?:[^@/\s]+@)?([^:/\s]+):/.exec(a)?.[1];
  const hosts = unique(ops.map(remote).filter(h => h !== undefined) as string[]);
  if (!ok || risky || ops.length < 2 || hosts.includes("")) return unsure(w.program, hosts.filter(Boolean), [...ops.filter(a => remote(a) === undefined), ...extra]);
  const dest = ops[ops.length - 1], sources = ops.slice(0, -1);
  const local = sources.filter(a => remote(a) === undefined);
  if (remote(dest) !== undefined && local.length) {
    return { purpose: { key: "upload", params: { host: remote(dest) as string } }, hosts, local: [], sent: [...local, ...extra] };
  }
  if (hosts.length) return { purpose: { key: "copyRemote", params: { host: hosts[0] } }, hosts, local: [dest, ...extra] };
  return { purpose: { key: "copyLocal", params: { count: Math.max(sources.length, 1) } }, hosts: [], local: ops };
}

function mail(w: Words): Reading {
  const { program, args } = w;
  if (program === "mutt") {
    const sent: string[] = [], to: string[] = [];
    let sure = true;
    for (let i = 0; i < args.length; i++) {
      const a = args[i];
      if (a === "--") { to.push(...args.slice(i + 1)); break; }
      if (a === "-a") { while (i + 1 < args.length && !args[i + 1].startsWith("-")) sent.push(args[++i]); continue; }
      if (a === "-i") { if (args[i + 1] !== undefined) sent.push(args[++i]); continue; }
      if (["-s", "-c", "-b"].includes(a)) { i++; continue; }
      if (/^-[nxyNRpZz]+$/.test(a)) continue;
      if (a.startsWith("-")) { sure = false; continue; }
      to.push(a);
    }
    if (!sure || !to.length) return { ...unsure(program, to, sent), stdin: true };
    return { purpose: { key: "mailTo", params: { to: to[0] } }, hosts: to, local: [], sent, stdin: true };
  }
  const { ok, opts, operands: to } = parseOpts(args, program === "sendmail" || program === "msmtp" ? SENDMAIL : MAILX);
  const sent = opts.filter(([n]) => n === "-a" || n === "-A" || n === "-q").map(([, v]) => v);
  if (!ok || !to.length) return { ...unsure(program, to, sent), stdin: true };
  return { purpose: { key: "mailTo", params: { to: to[0] } }, hosts: to, local: [], sent, stdin: true };
}

/** One step's purpose and what it touches: `hosts` (other machines, web addresses, mail addresses) and `local`
 *  (paths on the machine it runs on). `rules` are the server's terminal rules for the line (upload, git-push…). */
function readStep(w: Words, rules: string[]): Reading {
  const { program, args } = w;
  switch (program) {
    case "ssh": case "mosh": case "autossh":
      return ssh(program, args, rules);
    case "scp": case "rsync":
      return copy(w);
    case "curl":
      return curl(w, rules);
    case "wget":
      return wget(w);
    case "http": case "https": case "xh":
      return httpie(w);
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
    case "mail": case "mailx": case "sendmail": case "msmtp": case "mutt":
      return mail(w);
    default: {
      if (TALKERS.has(program)) {
        const target = plain(args)[0];
        return unsure(program, target && hostOfUrl(target) ? [target] : [], plain(args).filter(a => PATH_LIKE.test(a)));
      }
      if (CLOUD.has(program)) {
        // Their options are not read: every operand that looks like a file may be what it sends.
        return unsure(program, plain(args).filter(a => /^[a-z0-9]+:\/\//i.test(a)),
                      plain(args).filter(a => PATH_LIKE.test(a) || /^[^/:]+\.[A-Za-z0-9]{1,8}$/.test(a)));
      }
      if (Object.prototype.hasOwnProperty.call(INLINE_CODE, program) && args.some(a => INLINE_CODE[program].test(a))) {
        return unsure(program);                                                  // its inline code may send anything
      }
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

/** A shell a step runs in: a `$(…)` or `sh -c '…'` starts its own, so a `cd` inside it stays there (Astra 8). */
interface Ctx { parent: Ctx | null }
interface Node { w: Words; from: Node | null; container: Node | null; merged: boolean; run: boolean; ctx: Ctx }

function flatten(steps: Step[], container: Node | null, out: Node[], ctx: Ctx) {
  let prev: Node | null = null;
  for (const step of steps) {
    const node: Node = { w: words(step.tokens), from: step.piped ? prev : null, container, merged: false, run: false, ctx };
    const line = inlineLine(node.w);
    const inner = line === null ? null : parse(line);
    if (inner) flatten(inner, container, out, { parent: ctx });            // `sh -c '…'`: its line, read once
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
  const seen = new Map<Node, string[]>();                                  // the files each step names or reads
  const inside = (node: Node) => unique(nodes.filter(n => n.container === node).flatMap(n => seen.get(n) ?? []));
  const piped = (node: Node) => {                                         // what steps piped into it read
    const out: string[] = [];
    for (let n = node.from; n; n = n.from) out.push(...(seen.get(n) ?? []));
    return unique(out);
  };
  for (const node of nodes) {
    const { program, args, writes } = node.w;
    const dir = dirOf(node.ctx);
    if (program === "cd" || program === "pushd") {
      const to = args.find(a => a === "-" || !a.startsWith("-")) ?? "~";         // `cd -`: a folder the line does not name
      dirs.set(node.ctx, to === "-" ? null : rebase(dir, to));
      continue;
    }
    if (program === "popd") { dirs.set(node.ctx, null); continue; }
    const inputs = node.w.inputs.map(p => rebase(dir, p));
    if (node.merged || ((QUIET.has(program) || !program) && !writes.length)) {
      seen.set(node, inputs);
      continue;
    }
    let r: Reading = QUIET.has(program) || !program ? { purpose: { key: "write", params: { target: writes[0] } }, hosts: [], local: [] }
      : readStep(node.w, rules);
    if (node.run && (r.purpose.key === "fetch" || r.purpose.key === "upload")) {
      r = { ...r, purpose: { key: "fetchRun", params: { host: r.purpose.params.host } } };
    }
    const local = [...r.local, ...writes].map(p => rebase(dir, p));
    if (r.purpose.key === "write") r = { ...r, purpose: { key: "write", params: { target: rebase(dir, String(r.purpose.params.target)) } } };
    // #688 review, the second round and Astra 6: what a step sends, every source together: the files named on it, its
    // input when it sends it (`@-`, a mail's body) and the steps piped into it, and what a step run inside a network
    // step reads (`-d "$(cat f)"`, a URL with `$(…)` in it). The model picks the host; the file is the one tell.
    const fedIn = [...inputs, ...piped(node)];
    let sent = unique([...(r.sent ?? []).map(p => rebase(dir, p)), ...(r.stdin ? fedIn : []),
                       ...(NETWORK.has(program) ? inside(node) : [])]);
    if (r.stdinUnsure && fedIn.length) {                                   // ssh given an input: not read
      r = unsure(program, r.hosts, r.local);
      sent = unique([...sent, ...fedIn]);
    }
    const key = r.purpose.key;
    if (sent.length && (key === "fetch" || key === "upload" || key === "mailTo")) {
      const file = sent.slice(0, 3).join(", "), more = sent.length - 3;
      const mailing = key === "mailTo";
      const params = mailing ? { file, to: r.purpose.params.to } : { file, host: r.purpose.params.host };
      r = { ...r, purpose: { key: `${mailing ? "mailFile" : "uploadFile"}${more > 0 ? "More" : ""}`,
                             params: more > 0 ? { ...params, count: more } : params } };
    } else if (sent.length && NETWORK.has(program) && !r.unsure && key !== "fetchRun") {
      r = unsure(program, r.hosts, r.local);                               // a transfer that sends more than it says
    }
    const all = unique([...local, ...sent]);
    seen.set(node, [...all, ...inputs]);
    real.push({ ...r, local: all });
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
