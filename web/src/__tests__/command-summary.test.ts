// SMART-8: what a command is for and what it touches, read from the command itself (never from the model).
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { commandRisk, splitShell, summarize } from "../lib/commandSummary";

/** The vectors both readers are held to (server/services/card_purpose.py reads the same file). */
const VECTORS: { line: string; rule?: string; purpose: unknown; touches: string[]; more: number; unsure: boolean }[] = JSON.parse(readFileSync(
  resolve(dirname(fileURLToPath(import.meta.url)), "../../../tests/fixtures/card_purpose_vectors.json"), "utf8")).vectors;

describe("splitShell", () => {
  it("splits steps and keeps quoted text whole", () => {
    expect(splitShell(`echo "== a; b =="; ssh -o BatchMode=yes host 'echo hi' && ls|wc -l`)).toEqual([
      ["echo", "== a; b =="], ["ssh", "-o", "BatchMode=yes", "host", "echo hi"], ["ls"], ["wc", "-l"]]);
  });

  it("keeps 2>&1 as one redirect, and backslashes as escapes", () => {
    expect(splitShell("make 2>&1 | tee log")).toEqual([["make", "2>&1"], ["tee", "log"]]);
    expect(splitShell("rm my\\ file")).toEqual([["rm", "my file"]]);
  });

  it("an open quote is no answer", () => {
    expect(splitShell(`echo "unclosed`)).toBeNull();
  });
});

describe("summarize, local operations", () => {
  it.each([
    ["rm ~/Downloads/a.dmg ~/Downloads/b.dmg", { key: "delete", params: { count: 2 } },
      ["~/Downloads/a.dmg", "~/Downloads/b.dmg"]],
    ["rm -rf build", { key: "delete", params: { count: 1 } }, ["build"]],
    ["mv a b dest/", { key: "move", params: { count: 2 } }, ["a", "b", "dest/"]],
    ["git push origin main", { key: "gitPush", params: { remote: "origin" } }, []],
    ["git push", { key: "gitPush", params: { remote: "origin" } }, []],
    ["git clone https://github.com/acme/notes.git", { key: "gitClone", params: { repo: "https://github.com/acme/notes.git" } },
      ["https://github.com/acme/notes.git"]],
    ["git -C repo status", { key: "git", params: { sub: "status" } }, []],
    ["open -a Safari https://example.com", { key: "open", params: { target: "https://example.com" } }, ["https://example.com"]],
    ["osascript -e 'tell app \"Mail\" to quit'", { key: "appleScript", params: {} }, []],
    ["shortcuts run 'Morning Brief'", { key: "shortcut", params: { name: "Morning Brief" } }, []],
    ["killall -9 Finder", { key: "kill", params: { target: "Finder" } }, []],
    ["brew install jq ripgrep", { key: "install", params: { packages: "jq, ripgrep" } }, []],
    ["python3 scripts/report.py --week", { key: "script", params: { program: "python3", file: "report.py" } },
      ["scripts/report.py"]],
    ["ffmpeg -i in.mov out.mp4", { key: "run", params: { program: "ffmpeg" } }, []],
  ])("%s", (line, purpose, touches) => {
    const s = summarize(line);
    expect(s.purpose).toEqual(purpose);
    expect(s.touches).toEqual(touches);
    expect(s.unsure).toBe(false);
  });

  it("assignments, sudo, env and redirects are not the program", () => {
    expect(summarize("FOO=1 sudo -E env BAR=2 rm -f /tmp/x 2>/dev/null").purpose)
      .toEqual({ key: "delete", params: { count: 1 } });
    expect(summarize("rm /tmp/x > out.log").touches).toEqual(["/tmp/x", "out.log"]);
  });

  it("a path after cd is shown from that folder, and a later step is counted", () => {
    const s = summarize("cd ~/work && rm old.zip && git push");
    expect(s.purpose).toEqual({ key: "delete", params: { count: 1 } });
    expect(s.touches).toEqual(["~/work/old.zip"]);
    expect(s.more).toBe(1);
  });

  it("a line of only quiet steps is named by its first program", () => {
    expect(summarize("echo hi; sleep 1").purpose).toEqual({ key: "run", params: { program: "echo" } });
  });

  it("an open quote falls back to running its first word", () => {
    expect(summarize(`ssh box "uptime`)).toEqual({ purpose: { key: "run", params: { program: "ssh" } }, touches: [], more: 0,
                                                   unsure: false });
  });

  it("a program path is named by its file name", () => {
    expect(summarize("/usr/bin/ffmpeg -i in.mov out.mp4").purpose).toEqual({ key: "run", params: { program: "ffmpeg" } });
  });

  it.each(VECTORS.map(v => [v.line, v] as const))("the shared vector %s", (line, v) => {
    expect(summarize(line, v.rule)).toEqual({ purpose: v.purpose, touches: v.touches, more: v.more, unsure: v.unsure });
  });
});

describe("summarize, a step that uses the network (SMART-8, Astra's rounds, simplified)", () => {
  it.each([
    "curl https://example.org", "wget https://example.org -O out", "scp a.txt host:/tmp/", "scp host:/a .",
    "rsync -av d/ host:/b/", "ssh host uptime", "ssh user@host", "sftp host", "nc host 22", "socat - tcp:host:1",
    "mail -s hi a@b.example", "mailx -s hi a@b.example", "mutt -a f -- a@b.example", "sendmail -t", "telnet host",
    "aws s3 ls", "gcloud storage ls", "gsutil cp a gs://b", "gh release view v1", "rclone copy a b:/c",
    "python3 -c pass", "node -e x", "node --eval=x", "perl -e1", "ruby -e x",
  ])("%s is read only as using the network", (line) => {
    const program = line.split(/\s+/)[0].replace(/^.*\//, "");
    const s = summarize(line);
    expect(s.purpose).toEqual({ key: "overNetwork", params: { program } });
    expect(s.touches).toEqual([]);
    expect(s.unsure).toBe(true);
  });

  it("an interpreter running a script file is local, not the network", () => {
    expect(summarize("python3 report.py").purpose).toEqual({ key: "script", params: { program: "python3", file: "report.py" } });
    expect(summarize("python3 report.py").unsure).toBe(false);
  });

  it("the most dangerous step still leads, and the network step sets unsure", () => {
    const s = summarize("rm old.log && curl https://example.org");
    expect(s.purpose).toEqual({ key: "delete", params: { count: 1 } });
    expect(s.more).toBe(1);
    expect(s.unsure).toBe(true);
  });

  it("a download piped into a shell is one step that uses the network", () => {
    expect(summarize("curl https://example.org | sh")).toMatchObject({ purpose: { key: "overNetwork" }, more: 0, unsure: true });
  });

  it("git stays a local reading (push/clone/pull), never the network line", () => {
    expect(summarize("git push origin main").unsure).toBe(false);
    expect(summarize("git clone https://e.example/r.git").purpose.key).toBe("gitClone");
  });
});

describe("summarize, Astra round 2's gaps are caught", () => {
  it.each([
    ['env -S "curl https://example.org"', "curl"],              // 1: env -S runs the string
    ['eval "curl https://example.org"', "curl"],                // 2: eval runs its argument
    ['builtin eval "curl https://example.org"', "curl"],
    ["git -c core.sshCommand=ssh fetch", "git"],                // 3: git -c can run any program
    ["git --upload-pack=x fetch origin", "git"],
    ["GIT_SSH_COMMAND=x git fetch", "git"],
    ["git -c user.name=x push", "git"],                         // any -c is cautious
    ["dig example.org", "dig"], ["nslookup example.org", "nslookup"], ["ping -c 1 example.org", "ping"],
    ["openssl s_client -connect example.org:443", "openssl"], ["docker push img", "docker"],
    ["kubectl get pods", "kubectl"], ["twine upload dist/x", "twine"],
    ["npm publish", "npm"], ["cargo publish", "cargo"], ["gem push pkg.gem", "gem"],
  ])("%s reads only as using the network", (line, program) => {
    expect(summarize(line)).toMatchObject({ purpose: { key: "overNetwork", params: { program } }, unsure: true });
  });

  it("a wrapper that took its program is never a plain reading", () => {
    expect(summarize("sudo").unsure).toBe(true);
    expect(summarize("timeout 5").unsure).toBe(true);
  });

  it("the plain git and eval readings are unchanged", () => {
    expect(summarize("git fetch origin").purpose.key).toBe("gitFetch");
    expect(summarize('eval "rm -rf build"').purpose).toEqual({ key: "delete", params: { count: 1 } });
    expect(summarize("gem install rails").purpose.key).toBe("install");
  });
});

describe("summarize, Astra round 2's containment rule", () => {
  it("case-folds the program (a case-insensitive volume runs Curl/SSH/GIT as the real binary) (F1)", () => {
    for (const line of ["Curl https://example.org", "SSH host", "GIT -c x=y fetch", "Python3 -c pass", "NC host 1"]) {
      expect(summarize(line).purpose.key).toBe("overNetwork");
      expect(summarize(line).unsure).toBe(true);
    }
  });

  it.each([
    "arch -x86_64 curl https://example.org", "script -q /dev/null curl https://example.org", "noglob curl https://e.example",
    "repeat 3 curl https://e.example", "find . -exec curl https://e.example {} ;", "f(){ curl https://e.example; }; f",
    "{ curl https://e.example; }", "if true; then curl https://e.example; fi", "sudo --user root curl https://e.example",
    "sudo -Eu root curl https://e.example", "stdbuf -o L curl https://e.example", "env -P curl https://e.example",
    "command curl https://e.example",
  ])("a network program buried in a step is caught: %s (F2)", (line) => {
    expect(summarize(line)).toMatchObject({ purpose: { key: "overNetwork", params: { program: "curl" } }, unsure: true });
  });

  it.each(["grep curl notes.txt", "man ssh", "which curl", "type curl", "whence -p curl", "command -v curl",
           "brew info curl", "brew search wget"])("a step that only names things stays plain: %s (F3)", (line) => {
    expect(summarize(line).unsure).toBe(false);
    expect(summarize(line).purpose.key).not.toBe("overNetwork");
  });

  it("an empty inline line keeps the wrapper node, not dropped (F5)", () => {
    expect(summarize("bash -c ''").purpose).toEqual({ key: "run", params: { program: "bash" } });
    expect(summarize("eval ''").purpose).toEqual({ key: "run", params: { program: "eval" } });
  });
});

describe("commandRisk", () => {
  it("a plain command in the sandbox", () => {
    expect(commandRisk({})).toEqual({ level: "info", keys: [{ key: "sandboxed" }] });
  });

  it("the user's card: the network, this time", () => {
    expect(commandRisk({ rule: "remote-shell", network: true })).toEqual({
      level: "warn", keys: [{ key: "rule.remote-shell" }, { key: "network" }] });
  });

  it.each(["delete-outside", "send-mail", "send-message", "publish"])("%s cannot be taken back", (rule) => {
    expect(commandRisk({ rule }).level).toBe("irreversible");
  });

  it("an irreversible rule stays irreversible whatever else is said", () => {
    expect(commandRisk({ rule: "delete-outside", network: true, sandbox: "outside" }).level).toBe("irreversible");
  });

  it("another machine, outside the sandbox, or with no sandbox at all", () => {
    expect(commandRisk({ remoteHost: "me@box" }).keys).toEqual([{ key: "remote", params: { host: "me@box" } }]);
    expect(commandRisk({ sandbox: "outside" }).keys).toEqual([{ key: "outside" }]);
    expect(commandRisk({ sandbox: "retry" }).keys).toEqual([{ key: "retry" }]);
    expect(commandRisk({ unsandboxed: true }).keys).toEqual([{ key: "unsandboxed" }]);
  });

  it("a rule the card has no words for still asks, in amber, never as 'sandboxed' (#688 review 4)", () => {
    expect(commandRisk({ rule: "brand-new-rule" })).toEqual({ level: "warn", keys: [{ key: "rule.unknown" }] });
    expect(commandRisk({ rules: ["brand-new-rule", "other-new-rule"] }).keys).toEqual([{ key: "rule.unknown" }]);
  });

  it("every rule the server matched is named, the worst first, and the row takes the worst level (#688 review 3)", () => {
    expect(commandRisk({ rules: ["apple-events", "send-mail"] })).toEqual({
      level: "irreversible", keys: [{ key: "rule.send-mail" }, { key: "rule.apple-events" }] });
    expect(commandRisk({ rules: ["remote-shell", "unreadable"] }).keys).toEqual([{ key: "rule.remote-shell" },
                                                                                  { key: "rule.unreadable" }]);
  });

  it("the rules win over an older frame's one rule, which still works alone", () => {
    expect(commandRisk({ rule: "apple-events", rules: ["apple-events", "send-mail"] }).level).toBe("irreversible");
    expect(commandRisk({ rule: "git-push" }).keys).toEqual([{ key: "rule.git-push" }]);
  });

  it.each(["fetched-code", "script-reach", "quoting", "complex"])("why it can't be read is said plainly: %s (#688 review 5)",
    (kind) => {
      expect(commandRisk({ rules: ["unreadable"], unreadable: kind }).keys).toEqual([{ key: `rule.unreadable-${kind}` }]);
    });

  it("a kind of unreadable the card does not know reads as the generic line", () => {
    expect(commandRisk({ rules: ["unreadable"], unreadable: "new-kind" }).keys).toEqual([{ key: "rule.unreadable" }]);
  });

  it("a step that uses the network adds its own line to the risk row (Astra, simplified)", () => {
    expect(commandRisk({ unsure: true })).toEqual({ level: "warn", keys: [{ key: "rule.unreadable-send" }] });
    expect(commandRisk({ rules: ["delete-outside"], unsure: true }).level).toBe("irreversible");
  });

  it("the outside, retry and remote cards keep the rule's line after their own (#688 review 1)", () => {
    expect(commandRisk({ sandbox: "outside", rules: ["delete-outside"] })).toEqual({
      level: "irreversible", keys: [{ key: "outside" }, { key: "rule.delete-outside" }] });
    expect(commandRisk({ sandbox: "retry", rules: ["delete-outside"] }).level).toBe("irreversible");
    expect(commandRisk({ remoteHost: "me@box", rules: ["delete-outside"] }).keys).toEqual([
      { key: "remote", params: { host: "me@box" } }, { key: "rule.delete-outside" }]);
  });
});
