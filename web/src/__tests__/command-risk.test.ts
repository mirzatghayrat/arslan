// SMART-8: a command card's 「风险」 row, from what the server decided about the command (never from the model). What the
// command is for and touches is the server's reading (card_purpose.summarize, tests/server/test_smart8_plain_title.py).
import { describe, expect, it } from "vitest";
import { commandRisk, summaryOf, unread } from "../lib/commandRisk";

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

  it("the outside and remote cards keep the rule's line after their own (#688 review 1)", () => {
    expect(commandRisk({ sandbox: "outside", rules: ["delete-outside"] })).toEqual({
      level: "irreversible", keys: [{ key: "outside" }, { key: "rule.delete-outside" }] });
    expect(commandRisk({ remoteHost: "me@box", rules: ["delete-outside"] }).keys).toEqual([
      { key: "remote", params: { host: "me@box" } }, { key: "rule.delete-outside" }]);
  });
});

describe("the frame's summary (LOOP1 d1)", () => {
  const read = { purpose: { key: "delete", params: { count: 1 } }, touches: ["build"], more: 0, unsure: false };

  it("is taken as the server sent it", () => {
    expect(summaryOf(read)).toEqual(read);
    expect(summaryOf({ ...read, purpose: { key: "overNetwork", params: { program: "ssh" },
                                           inner: { key: "run", params: { program: "ls" } } } })?.purpose.inner?.key).toBe("run");
  });

  it("is none when the frame has none, or not in that shape", () => {
    for (const raw of [undefined, null, "rm", { ...read, purpose: { params: {} } }, { ...read, more: "1" },
                       { ...read, unsure: undefined }, { ...read, touches: "build" }]) {
      expect(summaryOf(raw)).toBeUndefined();
    }
  });

  it("a frame without one names the command's first word by its file name, and nothing else", () => {
    expect(unread("/usr/bin/ffmpeg -i in.mov out.mp4")).toEqual({ purpose: { key: "run", params: { program: "ffmpeg" } },
                                                                 touches: [], more: 0, unsure: false });
  });
});
