/**
 * S6 (v0.1.64): Settings › What Arslan may do › "Remembered answers", in the words of the mock the user approved
 * (2026-11-11), read in Chinese through the real locale: each kind of remembered answer with its sentence, the
 * commander's block holding its sub-sessions', take-back without a confirm (the row fades and leaves; a failure keeps
 * it with a red line), and the empty and unlisted states. Plus S4a follow-up 1's words: an unanswered card expired.
 */
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import i18n from "../i18n";
import zh from "../locales/zh.json";

const request = vi.fn();
vi.mock("../api/client", () => ({
  ApiError: class ApiError extends Error {
    status: number;
    constructor(message: string, status: number) { super(message); this.status = status; }
  },
  request: (...args: unknown[]) => request(...args),
}));

import { ApiError } from "../api/client";
import RememberedAnswers, { FADE_MS, type RememberedGrant, type RememberedRule } from "../components/settings/RememberedAnswers";
import NotDoneList from "../components/proactive/NotDoneList";

const NOW = new Date();
const iso = (d: Date) => d.toISOString();

const rule = (over: Partial<RememberedRule> = {}): RememberedRule => ({
  id: 1, kind: "app", target: "com.apple.Notes", label: "备忘录", created_at: iso(NOW), last_used_at: null, use_count: 0,
  ...over,
});
let nextId = 100;
const grant = (what: string, over: Partial<RememberedGrant> = {}): RememberedGrant => ({
  id: nextId--, conversation_id: "c-top", title: "整理下载文件夹", kind: what, target: "*", created_at: iso(NOW), what,
  name: "", server: "", server_gone: false, sub_session: false, parent_id: "c-top", parent_title: "整理下载文件夹", ...over,
});

function serve(rules: unknown, grants: unknown) {
  request.mockImplementation(async (path: string, init?: { method?: string }) => {
    if (init?.method === "DELETE") return { ok: true };
    if (path === "/permissions/rules") { if (rules instanceof Error) throw rules; return rules; }
    if (path === "/permissions/grants") { if (grants instanceof Error) throw grants; return grants; }
    throw new Error(`unexpected ${path}`);
  });
}

const page = (props: Parameters<typeof RememberedAnswers>[0] = {}) =>
  render(<I18nextProvider i18n={i18n}><RememberedAnswers {...props} /></I18nextProvider>);
const rowOf = (what: string) => screen.getAllByTestId("remembered-row").filter((r) => r.dataset.what === what);
const sentence = (row: HTMLElement) => within(row).getByTestId("remembered-sentence").textContent;

beforeAll(async () => { await i18n.changeLanguage("zh"); });
beforeEach(() => { request.mockReset(); nextId = 100; });
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe("Remembered answers lists each kind in its own words", () => {
  const all = () => [
    grant("outside"), grant("unsandboxed", { kind: "command", target: "unsandboxed:*" }),
    grant("command", { kind: "command", target: "text:git status", name: "git status" }),
    grant("network", { target: "network:*" }),
    grant("workspace_write", { target: "/Users/someone/项目", name: "项目" }),
    grant("schedule"),
    grant("mcp_tool", { target: "mcp_7__create_issue", name: "create_issue", server: "GitHub" }),
    grant("mcp_tool", { target: "mcp_8__send", name: "send", server: "", server_gone: true }),
    grant("app", { target: "com.apple.Notes", name: "备忘录" }),
    grant("site", { target: "https://example.com", name: "https://example.com" }),
    grant("shortcut", { target: "每日记录", name: "每日记录" }),
  ];

  it("says what each answer allows, with the note where it applies", async () => {
    serve([rule({ last_used_at: iso(NOW), use_count: 12 })], all());
    page();
    await screen.findByTestId("remembered-block");
    const [app] = rowOf("app").filter((r) => within(r).queryByText("所有对话"));
    expect(sentence(app)).toBe("可以看、可以操作「备忘录」，以后不再问。删除、发送、付款仍每次问。");
    expect(app.textContent).toMatch(/上次用到：今天 \d\d:\d\d · 共 12 次/);
    expect(app.textContent).toMatch(/今天 \d\d:\d\d给的/);
    const words: Record<string, string> = {
      outside: "这段对话里的命令（包括后台任务）可以在沙盒外运行",
      unsandboxed: "这段对话里的命令可以不放进沙盒、不问就运行",
      command: "这段对话里，这条命令再运行时不再问：git status",
      network: "这段对话里，读过网页之后，沙盒里的命令也可以联网",
      workspace_write: "这段对话里可以写「项目」文件夹，不再问",
      schedule: "这段对话里可以新建定时任务，不再问",
      site: "这段对话里可以在 https://example.com 上点击、输入",
      shortcut: "这段对话里可以运行快捷指令「每日记录」",
    };
    for (const [what, text] of Object.entries(words)) expect(sentence(rowOf(what)[0]), what).toBe(text);
    expect(rowOf("mcp_tool").map(sentence)).toEqual([
      "这段对话里可以用「GitHub」的「create_issue」，参数不限", "这段对话里可以用「MCP」的「send」，参数不限"]);
    const [grantApp] = rowOf("app").filter((r) => !within(r).queryByText("所有对话"));
    expect(sentence(grantApp)).toBe("这段对话里可以看、可以操作「备忘录」");
    const note = (what: string, i = 0) => within(rowOf(what)[i]).queryByTestId("remembered-note")?.textContent;
    expect(note("unsandboxed")).toBe("只在沙盒关着或启动不了时用得上");
    expect(note("command")).toBe("只在「每条命令都先问」时用得上");
    expect(note("network")).toBe("在沙盒外运行的命令仍每次问");
    expect(note("mcp_tool", 1)).toBe("这个服务器已经删掉了");
    expect(note("outside")).toBeUndefined();
    expect(note("mcp_tool", 0)).toBeUndefined();
  });

  it("sets commands, folders and sites as code, the whole on hover", async () => {
    serve([], all());
    page();
    await screen.findByTestId("remembered-block");
    const code = (what: string) => within(rowOf(what)[0]).getByTestId("remembered-code");
    expect(code("command").textContent).toBe("git status");
    expect(code("workspace_write").textContent).toBe("项目");
    expect(code("workspace_write").getAttribute("title")).toContain("/Users/someone/项目");
    expect(code("site").textContent).toBe("https://example.com");
    expect(within(rowOf("schedule")[0]).queryByTestId("remembered-code")).toBeNull();
  });

  it("marks only the two answers that let commands out of the sandbox with an amber edge", async () => {
    serve([], all());
    page();
    await screen.findByTestId("remembered-block");
    const amber = screen.getAllByTestId("remembered-row").filter((r) => r.className.includes("border-warning"));
    expect(amber.map((r) => r.dataset.what).sort()).toEqual(["outside", "unsandboxed"]);
  });

  it("an app never used says so", async () => {
    serve([rule()], []);
    page();
    expect((await screen.findByTestId("remembered-always")).textContent).toContain("还没用到");
  });
});

describe("by conversation", () => {
  it("is newest first, titled by the sidebar first, a sub-session's under its commander", async () => {
    serve([], [
      grant("schedule", { conversation_id: "c-new", parent_id: "c-new", title: "服务器的标题", parent_title: "服务器的标题" }),
      grant("outside", { conversation_id: "c-sub", sub_session: true, title: "数照片" }),
      grant("network", { target: "network:*" }),
      grant("app", { conversation_id: "c-old", parent_id: "c-old", title: "", parent_title: "", name: "备忘录" }),
    ]);
    const open = vi.fn();
    page({ titles: { "c-new": "侧栏生成的标题" }, onOpenConversation: open });
    const blocks = await screen.findAllByTestId("remembered-block");
    expect(blocks.map((b) => within(b).getByTestId("remembered-block-title").textContent)).toEqual([
      "侧栏生成的标题", "整理下载文件夹", "未命名对话"]);
    const sub = within(blocks[1]).getByTestId("remembered-sub");
    expect(sub.textContent).toContain("子会话：数照片");
    expect(within(sub).getByTestId("remembered-row").textContent).toContain("只在这个子会话里");
    expect(within(blocks[1]).getAllByTestId("remembered-row").map((r) => r.dataset.what)).toEqual(["network", "outside"]);
    fireEvent.click(within(blocks[1]).getByTestId("remembered-open"));
    expect(open).toHaveBeenCalledWith("c-top");
  });

  it("「收回这段对话的全部」 takes back the block's own and its sub-sessions'", async () => {
    const own = grant("network"), sub = grant("outside", { conversation_id: "c-sub", sub_session: true });
    const other = grant("schedule", { conversation_id: "c-2", parent_id: "c-2" });
    serve([], [own, sub, other]);
    page();
    const [block] = await screen.findAllByTestId("remembered-block");
    fireEvent.click(within(block).getByTestId("remembered-revoke-all"));
    await waitFor(() => expect(screen.getAllByTestId("remembered-block")).toHaveLength(1));
    const deleted = request.mock.calls.filter(([, init]) => init?.method === "DELETE").map(([path]) => path).sort();
    expect(deleted).toEqual([`/permissions/grants/${own.id}`, `/permissions/grants/${sub.id}`].sort());
  });
});

describe("taking one back", () => {
  it("needs no confirm: the button greys while it goes, then the row fades out and leaves", async () => {
    const out = grant("outside");
    let finish: (v: unknown) => void = () => {};
    serve([], [out]);
    const listed = request.getMockImplementation()!;
    request.mockImplementation((path: string, init?: { method?: string }) =>
      init?.method === "DELETE" ? new Promise((resolve) => { finish = resolve; }) : listed(path, init));
    page();
    const row = (await screen.findAllByTestId("remembered-row"))[0];
    const button = within(row).getByTestId("remembered-revoke");
    fireEvent.click(button);
    expect(button).toBeDisabled();
    expect(row.dataset.state).toBe("busy");
    expect(request).toHaveBeenCalledWith(`/permissions/grants/${out.id}`, { method: "DELETE" });
    await act(async () => { finish({ ok: true }); });
    expect(row.dataset.state).toBe("leaving");
    expect(row.className).toContain("opacity-0");
    await act(async () => { await new Promise((r) => setTimeout(r, FADE_MS + 20)); });
    expect(screen.queryAllByTestId("remembered-row")).toHaveLength(0);
    expect(screen.getByTestId("remembered-empty")).toBeInTheDocument();     // the last one gone: the group is empty
  });

  it("a failure keeps the row, with a red line to try again", async () => {
    serve([rule()], []);
    const listed = request.getMockImplementation()!;
    request.mockImplementation(async (path: string, init?: { method?: string }) => {
      if (init?.method === "DELETE") throw new ApiError("down", 500);
      return listed(path, init);
    });
    page();
    const row = (await screen.findAllByTestId("remembered-row"))[0];
    fireEvent.click(within(row).getByTestId("remembered-revoke"));
    expect(await within(row).findByTestId("remembered-failed")).toHaveTextContent("没收回成功，再试一次");
    await act(async () => { await new Promise((r) => setTimeout(r, FADE_MS + 20)); });
    expect(screen.getAllByTestId("remembered-row")).toHaveLength(1);
    expect(within(row).getByTestId("remembered-revoke")).not.toBeDisabled();
    expect(request).toHaveBeenCalledWith("/permissions/rules/1", { method: "DELETE" });
  });

  it("one already gone (404) leaves as taken back", async () => {
    serve([rule()], []);
    const listed = request.getMockImplementation()!;
    request.mockImplementation(async (path: string, init?: { method?: string }) => {
      if (init?.method === "DELETE") throw new ApiError("gone", 404);
      return listed(path, init);
    });
    page();
    fireEvent.click(within((await screen.findAllByTestId("remembered-row"))[0]).getByTestId("remembered-revoke"));
    await waitFor(() => expect(screen.queryAllByTestId("remembered-row")).toHaveLength(0));
  });
});

describe("states", () => {
  it("says what is never remembered, always", async () => {
    serve([rule()], []);
    page();
    expect((await screen.findByTestId("remembered-never")).textContent).toBe(zh.remembered.never);
  });

  it("all empty: the bar and one sentence, no sections", async () => {
    serve([], []);
    page();
    expect(await screen.findByTestId("remembered-empty")).toHaveTextContent(zh.remembered.empty);
    expect(screen.queryByTestId("remembered-always")).toBeNull();
    expect(screen.getByTestId("remembered-never")).toBeInTheDocument();
  });

  it("one section empty says 「没有」", async () => {
    serve([rule()], []);
    page();
    expect((await screen.findByTestId("remembered-conversation")).textContent).toBe("本对话内没有");
  });

  it("a list that can't be read says 「现在列不出来」, and the rest still shows", async () => {
    serve([rule()], new Error("old server"));
    page();
    expect((await screen.findByTestId("remembered-conversation")).textContent).toBe("本对话内现在列不出来");
    expect(screen.getAllByTestId("remembered-row")).toHaveLength(1);
  });

  it("neither readable: one line", async () => {
    serve(new Error("down"), new Error("down"));
    page();
    expect(await screen.findByTestId("remembered-unavailable")).toHaveTextContent("现在列不出来");
    expect(screen.queryByTestId("remembered-always")).toBeNull();
  });
});

describe("S4a follow-up 1: a card nobody answered expired", () => {
  it("names it so where it shows", () => {
    expect(zh.whileAway.title).toBe("过期了、没做的（这个对话）");
    expect(zh.scheduledPage.awayTitle).toBe("过期或没法问、没做的（只算这个任务的）");
    expect(zh.sidebar.glyph.waiting_away).toBe("有卡片过期了");
    expect(JSON.stringify(zh)).not.toContain("你不在时");
  });

  it("each row says which way it expired; a scheduled run's keeps its own words", async () => {
    const entry = (id: number, over: object) => ({ id, created_at: iso(NOW), first_at: iso(NOW), count: 1,
      conversation_id: "c1", kind: "schedule", target: `t${id}`, detail: `d${id}`, always_ok: false, always: [], ...over });
    request.mockResolvedValue([entry(1, { unopened: true }), entry(2, { unopened: false }),
      entry(3, { unattended: true, unopened: false }), entry(4, {})]);
    render(<I18nextProvider i18n={i18n}><NotDoneList conversationId="c1" /></I18nextProvider>);
    const rows = await screen.findAllByTestId("inbox-refused-row");
    const note = (i: number) => within(rows[i]).queryByTestId("inbox-refused-expired")?.textContent;
    expect(note(0)).toBe("前一张卡没人回应，这张没弹出来就过期了");
    expect(note(1)).toBe("30 分钟没人回应，过期了");
    expect(note(2)).toBeUndefined();
    expect(within(rows[2]).getByTestId("inbox-refused-each-time")).toHaveTextContent("定时任务不做需要你确认的事");
    expect(note(3)).toBeUndefined();                       // an older server says neither
    expect(screen.getByTestId("inbox-refused").getAttribute("aria-label")).toBe("过期了、没做的");
  });
});
