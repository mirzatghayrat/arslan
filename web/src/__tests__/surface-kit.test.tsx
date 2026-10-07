/** 0.1.55 S1: the surface kit — keys (⌘⏎ allows, esc declines, plain ⏎ never),
 *  only the top surface answers, the queue, the confirm promise, the undo toast. */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, act } from "@testing-library/react";
import { useState } from "react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, o?: Record<string, unknown>) => (o ? `${key}:${JSON.stringify(o)}` : key) }),
}));

import { AskCard, AskQueue, ConfirmHost, Dialog, Notice, ToastHost, confirmSheet, toast } from "../components/kit";

afterEach(() => { cleanup(); vi.useRealTimers(); });

const key = (k: string, extra: Partial<KeyboardEventInit> = {}) =>
  fireEvent.keyDown(window, { key: k, ...extra });

function card(over: Partial<Parameters<typeof AskCard>[0]> = {}) {
  const onAllow = vi.fn(), onDecline = vi.fn();
  render(<AskCard who="Arslan 在问你" title="运行一段 AppleScript" said="只读，数笔记" risk="这段脚本会删除东西（第 2 行：delete）"
    onAllow={onAllow} onDecline={onDecline} {...over} />);
  return { onAllow, onDecline };
}

describe("AskCard", () => {
  it("shows who asks, the plain sentence, the model's words as Arslan's, and the code-derived risk", () => {
    card();
    expect(screen.getByRole("alertdialog", { name: "Arslan 在问你" })).toBeInTheDocument();
    expect(screen.getByTestId("ask-said")).toHaveTextContent("kit.arslanSays只读，数笔记");
    expect(screen.getByTestId("ask-risk")).toHaveTextContent("delete");
  });

  it("⌘⏎ allows, Ctrl+⏎ too, esc declines", () => {
    const { onAllow, onDecline } = card();
    key("Enter", { metaKey: true });
    key("Enter", { ctrlKey: true });
    key("Escape");
    expect(onAllow).toHaveBeenCalledTimes(2);
    expect(onDecline).toHaveBeenCalledTimes(1);
  });

  it("plain ⏎, ⇧⌘⏎ and an input-method ⌘⏎ never answer", () => {
    const { onAllow, onDecline } = card();
    key("Enter");
    key("Enter", { metaKey: true, shiftKey: true });
    key("Enter", { metaKey: true, isComposing: true } as never);
    expect(onAllow).not.toHaveBeenCalled();
    expect(onDecline).not.toHaveBeenCalled();
  });

  it("no keys while busy, or when shown as a preview", () => {
    const busy = card({ busy: true });
    key("Enter", { metaKey: true });
    expect(busy.onAllow).not.toHaveBeenCalled();
    cleanup();
    const preview = card({ keys: false });
    key("Escape");
    expect(preview.onDecline).not.toHaveBeenCalled();
  });

  it("a dialog opened over a waiting card takes esc; the card keeps waiting", () => {
    const onClose = vi.fn();
    const { onDecline } = card();
    render(<Dialog open title="项目和记忆" onClose={onClose}><p>body</p></Dialog>);
    key("Escape");
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onDecline).not.toHaveBeenCalled();
  });
});

describe("AskQueue", () => {
  function Host() {
    const [keys, setKeys] = useState(["a", "b", "c"]);
    return <AskQueue items={keys.map((k) => ({ key: k, render: (q) => (
      <AskCard who="w" title={`card ${k}`} queue={q} onAllow={() => setKeys((all) => all.filter((x) => x !== k))}
        onDecline={() => {}} />) }))} />;
  }
  it("shows one card with 1 / 3, moves with the arrows, and the next moves up when one is answered", () => {
    render(<Host />);
    expect(screen.getAllByRole("alertdialog")).toHaveLength(1);
    expect(screen.getByTestId("ask-queue")).toHaveTextContent('kit.queueOf:{"index":1,"total":3}');
    fireEvent.click(screen.getByLabelText("kit.next"));
    expect(screen.getByText("card b")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("ask-allow"));
    expect(screen.queryByText("card b")).toBeNull();
    expect(screen.getAllByRole("alertdialog")).toHaveLength(1);
    expect(screen.getByTestId("ask-queue")).toHaveTextContent('"total":2');
  });
});

describe("confirmSheet", () => {
  it("resolves true on ⌘⏎ and false on esc", async () => {
    render(<ConfirmHost />);
    let first: Promise<boolean>;
    act(() => { first = confirmSheet({ title: "删除这个模型配置？", body: "不能撤销", action: "删除" }); });
    expect(screen.getByTestId("confirm-sheet")).toBeInTheDocument();
    act(() => { key("Enter", { metaKey: true }); });
    await expect(first!).resolves.toBe(true);
    let second: Promise<boolean>;
    act(() => { second = confirmSheet({ title: "x", action: "删除" }); });
    act(() => { key("Escape"); });
    await expect(second!).resolves.toBe(false);
    expect(screen.queryByTestId("confirm-sheet")).toBeNull();
  });
});

describe("toast and notice", () => {
  it("an undo toast calls back and goes away", () => {
    const undo = vi.fn();
    render(<ToastHost />);
    act(() => { toast("已删除这条做法", { action: { label: "撤销", onClick: undo } }); });
    fireEvent.click(screen.getByTestId("kit-toast-action"));
    expect(undo).toHaveBeenCalled();
    expect(screen.queryByTestId("kit-toast")).toBeNull();
  });
  it("a toast leaves by itself", () => {
    vi.useFakeTimers();
    render(<ToastHost />);
    act(() => { toast("已保存", { ms: 1000 }); });
    expect(screen.getByTestId("kit-toast")).toBeInTheDocument();
    act(() => { vi.advanceTimersByTime(1100); });
    expect(screen.queryByTestId("kit-toast")).toBeNull();
  });
  it("an error notice is an alert, the others are status", () => {
    render(<><Notice tone="error" title="模型出错了">402</Notice><Notice tone="info" title="提示" /></>);
    expect(screen.getByRole("alert")).toHaveTextContent("模型出错了");
    expect(screen.getByRole("status")).toHaveTextContent("提示");
  });
});
