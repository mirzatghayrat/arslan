// SMART-8 (the card mock the user OK'd, 2026-11-02, with 「去掉小标题」): a confirm card leads with what the step is
// for, in the user's language; then what it touches and the risk, read by code; the command folded, whole when opened;
// the action named first, then other choices, then No. Real strings (en, zh), not keys.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import i18n from "../i18n";
import RunCommandCard from "../components/RunCommandCard";
import { AskCard } from "../components/kit";

afterEach(async () => { cleanup(); await i18n.changeLanguage("en"); });

const SSH = `echo "== 试探 192.168.1.4 =="; ssh -o BatchMode=yes -o ConnectTimeout=4 -o StrictHostKeyChecking=accept-new `
  + `192.168.1.4 true`;

const card = (extra: Record<string, unknown> = {}) => render(<RunCommandCard callId="c1" pretty={SSH} rule="remote-shell"
  network onConfirm={vi.fn()} onCancel={vi.fn()} {...extra} />);

describe("the user's card, as the mock draws it", () => {
  it("leads with the purpose read from the command, then what it touches and the risk", () => {
    card();
    expect(screen.getByTestId("runcmd-purpose")).toHaveTextContent(
      "Check whether 192.168.1.4 can be reached over SSH (one try, at most 4 seconds)");
    expect(screen.getByTestId("ask-purpose-from")).toHaveTextContent("Read from the command");
    expect(screen.getByTestId("ask-touches")).toHaveTextContent("192.168.1.4");
    expect(screen.getByTestId("ask-risk-row")).toHaveTextContent("Connects to another machine, Uses the network, this time");
    expect(screen.getByTestId("ask-risk-row")).toHaveAttribute("data-level", "warn");
  });

  it("in Chinese too", async () => {
    await i18n.changeLanguage("zh");
    card();
    expect(screen.getByTestId("runcmd-purpose")).toHaveTextContent("看看能不能用 SSH 连上 192.168.1.4（试连一次，最多 4 秒）");
    expect(screen.getByTestId("ask-purpose-from")).toHaveTextContent("按命令推出");
    expect(screen.getByTestId("ask-risk-row")).toHaveTextContent("连到另一台机器、会联网，仅这一次");
    expect(screen.getByText("涉及")).toBeInTheDocument();
    expect(screen.getByText("风险")).toBeInTheDocument();
  });

  it("the command is folded, never cut: 'Show command' shows it whole", () => {
    card();
    const body = screen.getByTestId("ask-folded-body");
    expect(body).not.toBeVisible();
    expect(body).toHaveTextContent(SSH);                         // the whole command, not 80 characters
    fireEvent.click(screen.getByTestId("runcmd-show-command"));
    expect(screen.getByTestId("ask-folded-body")).toBeVisible();
    expect(screen.getByTestId("runcmd-show-command")).toHaveTextContent("Hide command");
    expect(screen.getByTestId("runcmd-show-command")).toHaveAttribute("aria-expanded", "true");
  });

  it("no 'Arslan is asking' heading (the user: 「去掉小标题」)", () => {
    card();
    expect(screen.queryByText("Arslan is asking")).toBeNull();
  });
});

describe("Arslan's reason", () => {
  it("leads when Arslan gave one, marked as its words; what it touches is still read from the command", () => {
    card({ why: "See whether the NAS is up before backing up the photos" });
    expect(screen.getByTestId("runcmd-purpose")).toHaveTextContent("See whether the NAS is up before backing up the photos");
    expect(screen.getByTestId("ask-purpose-from")).toHaveTextContent("In Arslan's words");
    expect(screen.getByTestId("ask-touches")).toHaveTextContent("192.168.1.4");
  });

  it("cannot hide what it touches or soften the risk: those rows ignore its words", () => {
    render(<RunCommandCard callId="c2" pretty="rm -rf ~/Documents/taxes" rule="delete-outside"
      why="Just tidy up a temporary cache, nothing important" onConfirm={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByTestId("ask-touches")).toHaveTextContent("~/Documents/taxes");
    expect(screen.getByTestId("ask-risk-row")).toHaveTextContent(
      "Deletes files outside the work folder; they don't go to the Trash");
    expect(screen.getByTestId("ask-risk-row")).toHaveAttribute("data-level", "irreversible");
  });

  it("shows a reordering control in its words as a marker, not applied", () => {
    card({ why: "safe" + String.fromCodePoint(0x202e) + "txt.exe" });
    expect(within(screen.getByTestId("runcmd-purpose")).getByTestId("escaped-control")).toHaveTextContent("U+202E");
  });
});

describe("what it touches", () => {
  it("lists at most six, and counts the rest", () => {
    render(<RunCommandCard callId="c3" pretty={"rm " + Array.from({ length: 9 }, (_, i) => `f${i}`).join(" ")}
      onConfirm={vi.fn()} onCancel={vi.fn()} />);
    const touches = screen.getByTestId("ask-touches");
    expect(touches).toHaveTextContent("f5");
    expect(touches).not.toHaveTextContent("f6");
    expect(touches).toHaveTextContent("and 3 more");
  });

  it("a command it cannot place names its program and touches nothing it would make up", () => {
    render(<RunCommandCard callId="c4" pretty="ffmpeg -i in.mov out.mp4" onConfirm={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByTestId("runcmd-purpose")).toHaveTextContent("Run ffmpeg");
    expect(screen.queryByTestId("ask-touches")).toBeNull();
    expect(screen.getByTestId("ask-risk-row")).toHaveTextContent("Runs in the sandbox: it can change files only in the work folder");
  });

  it("a second step is counted in the purpose", () => {
    render(<RunCommandCard callId="c5" pretty="rm old.zip && curl -O https://example.com/new.zip"
      onConfirm={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByTestId("runcmd-purpose")).toHaveTextContent("Delete 1 file or folder (and 1 more step)");
  });
});

describe("the shared card (AskCard), for every card", () => {
  const base = { who: "Arslan is asking", title: "Do the thing", onAllow: vi.fn(), onDecline: vi.fn() };

  it("draws the action first, then other choices, then No", () => {
    const onRetry = vi.fn();
    render(<AskCard {...base} allowLabel="Trust nas.local and run again" declineLabel="Not now"
      actions={[{ label: "Run once outside the sandbox", onClick: onRetry, testId: "extra-once" }]} />);
    const labels = screen.getAllByRole("button").map(b => b.textContent?.replace(/⌘⏎|esc/, "").trim());
    expect(labels).toEqual(["Trust nas.local and run again", "Run once outside the sandbox", "Not now"]);
    fireEvent.click(screen.getByTestId("extra-once"));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("says who is asking only when it is not Arslan itself (a background job)", () => {
    render(<AskCard {...base} who="A background task is asking" />);
    expect(screen.getByTestId("ask-who")).toHaveTextContent("A background task is asking");
    cleanup();
    render(<AskCard {...base} />);
    expect(screen.queryByTestId("ask-who")).toBeNull();
  });

  it("a card with a countdown keeps its header, still without 'Arslan is asking'", () => {
    render(<AskCard {...base} expiresAt={Date.now() + 60_000} />);
    expect(screen.getByTestId("ask-who")).toBeEmptyDOMElement();
    expect(screen.queryByText("Arslan is asking")).toBeNull();
  });

  it("an irreversible risk is red and a warning amber", () => {
    render(<AskCard {...base} riskRow={{ level: "irreversible", text: "can't be undone" }} />);
    expect(screen.getByTestId("ask-risk-row").className).toContain("text-danger");
    cleanup();
    render(<AskCard {...base} riskRow={{ level: "warn", text: "uses the network" }} />);
    expect(screen.getByTestId("ask-risk-row").className).toContain("text-ask");
  });

  it("a card not yet in the new shape keeps its amber risk line", () => {
    render(<AskCard {...base} risk="sends email" />);
    expect(screen.getByTestId("ask-risk")).toHaveTextContent("sends email");
    expect(screen.queryByTestId("ask-rows")).toBeNull();
  });
});
