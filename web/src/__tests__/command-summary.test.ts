// SMART-8: what a command is for and what it touches, read from the command itself (never from the model).
import { describe, expect, it } from "vitest";
import { commandRisk, splitShell, summarize } from "../lib/commandSummary";

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

describe("summarize", () => {
  it("the user's card: the SSH step names the purpose, the echo before it says nothing", () => {
    const s = summarize(`echo "== 试探 192.168.1.4 =="; ssh -o BatchMode=yes -o ConnectTimeout=4 `
      + `-o StrictHostKeyChecking=accept-new 192.168.1.4 true`);
    expect(s.purpose).toEqual({ key: "sshTimeout", params: { host: "192.168.1.4", seconds: 4 } });
    expect(s.touches).toEqual(["192.168.1.4"]);
    expect(s.more).toBe(0);
  });

  it.each([
    ["ssh me@nas.local uptime", { key: "ssh", params: { host: "nas.local" } }, ["nas.local"]],
    ["ssh -p 2222 -i ~/.ssh/k me@box", { key: "ssh", params: { host: "box" } }, ["box"]],
    ["ssh -oConnectTimeout=9 box", { key: "sshTimeout", params: { host: "box", seconds: 9 } }, ["box"]],
    ["scp notes.txt me@box:/tmp/", { key: "copyRemote", params: { host: "box" } }, ["box"]],
    ["curl -sS https://api.example.com/v1/x", { key: "fetch", params: { host: "api.example.com" } },
      ["https://api.example.com/v1/x"]],
    ["rm ~/Downloads/a.dmg ~/Downloads/b.dmg", { key: "delete", params: { count: 2 } },
      ["~/Downloads/a.dmg", "~/Downloads/b.dmg"]],
    ["rm -rf build", { key: "delete", params: { count: 1 } }, ["build"]],
    ["mv a b dest/", { key: "move", params: { count: 2 } }, ["a", "b", "dest/"]],
    ["git push origin main", { key: "gitPush", params: { remote: "origin" } }, []],
    ["git push", { key: "gitPush", params: { remote: "origin" } }, []],
    ["git clone https://github.com/acme/notes.git", { key: "gitClone", params: { repo: "https://github.com/acme/notes.git" } },
      ["https://github.com/acme/notes.git"]],
    ["git -C repo status", { key: "git", params: { sub: "status" } }, []],
    ["git -c user.name=x push", { key: "gitPush", params: { remote: "origin" } }, []],
    ["open -a Safari https://example.com", { key: "open", params: { target: "https://example.com" } }, ["https://example.com"]],
    ["osascript -e 'tell app \"Mail\" to quit'", { key: "appleScript", params: {} }, []],
    ["shortcuts run 'Morning Brief'", { key: "shortcut", params: { name: "Morning Brief" } }, []],
    ["killall -9 Finder", { key: "kill", params: { target: "Finder" } }, []],
    ["mail -s hi lina@example.com < body.txt", { key: "mailTo", params: { to: "lina@example.com" } }, ["lina@example.com"]],
    ["brew install jq ripgrep", { key: "install", params: { packages: "jq, ripgrep" } }, []],
    ["python3 scripts/report.py --week", { key: "script", params: { program: "python3", file: "report.py" } },
      ["scripts/report.py"]],
    ["python3 -c 'print(1)'", { key: "run", params: { program: "python3" } }, []],
    ["ffmpeg -i in.mov out.mp4", { key: "run", params: { program: "ffmpeg" } }, []],
  ])("%s", (line, purpose, touches) => {
    const s = summarize(line);
    expect(s.purpose).toEqual(purpose);
    expect(s.touches).toEqual(touches);
  });

  it("an upload names it so (the server's rule says which)", () => {
    expect(summarize("curl -F f=@x https://up.example.com", "upload").purpose)
      .toEqual({ key: "upload", params: { host: "up.example.com" } });
  });

  it("assignments, sudo, env and redirects are not the program", () => {
    expect(summarize("FOO=1 sudo -E env BAR=2 rm -f /tmp/x 2>/dev/null").purpose)
      .toEqual({ key: "delete", params: { count: 1 } });
    expect(summarize("rm /tmp/x > out.log").touches).toEqual(["/tmp/x"]);
  });

  it("a second real step is counted, and touches add up", () => {
    const s = summarize("cd ~/work && rm old.zip && curl -O https://example.com/new.zip");
    expect(s.purpose).toEqual({ key: "delete", params: { count: 1 } });
    expect(s.more).toBe(1);
    expect(s.touches).toEqual(["old.zip", "https://example.com/new.zip"]);
  });

  it("a line of only quiet steps is named by its first program", () => {
    expect(summarize("echo hi; sleep 1").purpose).toEqual({ key: "run", params: { program: "echo" } });
  });

  it("an open quote falls back to running its first word", () => {
    expect(summarize(`ssh box "uptime`)).toEqual({ purpose: { key: "run", params: { program: "ssh" } }, touches: [], more: 0 });
  });

  it("a program path is named by its file name", () => {
    expect(summarize("/usr/bin/curl https://example.com").purpose).toEqual({ key: "fetch", params: { host: "example.com" } });
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

  it("a rule the card has no words for is not shown as one", () => {
    expect(commandRisk({ rule: "brand-new-rule" })).toEqual({ level: "info", keys: [{ key: "sandboxed" }] });
  });
});
