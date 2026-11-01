/**
 * IMG1 (0.1.64): an image from the web never loads by itself.
 * A: a Markdown image whose URL is not data:image/ or blob: shows as a chip; a web one opens in the
 *    browser on click (the link path). Checked through every user of Markdown: chat replies, the
 *    reader and release notes.
 * C: every srcDoc frame starts with a CSP that loads nothing from the web.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k),
    i18n: { resolvedLanguage: "en", language: "en" } }),
}));
const { files, request } = vi.hoisted(() => ({
  files: { list: vi.fn(), read: vi.fn(), stat: vi.fn(), table: vi.fn(), html: vi.fn(), pdfPage: vi.fn(), open: vi.fn(),
    reveal: vi.fn(), home: vi.fn(), conversationFiles: vi.fn() },
  request: vi.fn(),
}));
vi.mock("../api/files", () => ({ filesApi: files }));
vi.mock("../api/client", async (orig) => ({ ...(await orig<object>()), request }));

import Markdown from "../components/Markdown";
import MessageBody, { HtmlDocCard } from "../components/MessageBody";
import Reader from "../components/workbench/Reader";
import AboutSection from "../components/settings/AboutSection";
import { FRAME_CSP, withFrameCsp } from "../lib/frameCsp";

type ShellWindow = Window & { __TAURI_INTERNALS__?: { invoke: ReturnType<typeof vi.fn> } };
const win = window as ShellWindow;
afterEach(() => { cleanup(); delete win.__TAURI_INTERNALS__; vi.clearAllMocks(); });

const PNG = "data:image/png;base64,iVBORw0KGgo=";
const WEB = [
  ["https", "https://h.example/p?d=1", "h.example"],
  ["http", "http://h.example/p?d=1", "h.example"],
  ["protocol-relative", "//h.example/p?d=1", "h.example"],
  ["upper-case scheme", "HTTPS://h.example/p", "h.example"],
] as const;
const NOT_WEB = [
  ["relative", "./diagram.png"],
  ["root-relative", "/api/files/x.png"],
  ["a scheme react-markdown drops", "javascript:alert(1)"],
  ["file:", "file:///etc/hosts"],
] as const;

/** No <img> at all, and one chip, inside `root`. */
function expectChipNoImage(root: ParentNode = document) {
  expect(root.querySelector("img")).toBeNull();
  expect(root.querySelectorAll("[data-testid=md-image-chip]")).toHaveLength(1);
}

describe("A: Markdown images", () => {
  it.each(WEB)("a %s image renders no <img> and a chip naming the host", (_, url, host) => {
    render(<Markdown>{`See ![chart](${url}) here`}</Markdown>);
    expectChipNoImage();
    const chip = screen.getByTestId("md-image-chip");
    expect(chip).toHaveTextContent("chart");
    expect(chip).toHaveTextContent(`workbench.imageFrom:{"host":"${host}"}`);
    expect(chip.closest("a")?.getAttribute("href")).toBe(url);
  });

  it.each(NOT_WEB)("a %s image renders no <img> and a chip that isn't a link", (_, url) => {
    render(<Markdown>{`![local](${url})`}</Markdown>);
    expectChipNoImage();
    expect(screen.getByTestId("md-image-chip")).toHaveTextContent("workbench.imageNotShown");
    expect(screen.getByTestId("md-image-chip").closest("a")).toBeNull();
  });

  it("a reference-style web image is a chip too", () => {
    render(<Markdown>{"![ref][r]\n\n[r]: https://h.example/r.png"}</Markdown>);
    expectChipNoImage();
  });

  it.each([["data:image/", PNG], ["blob:", "blob:http://127.0.0.1:8765/0b6f2c1e"]])("a %s image still renders inline", (_, url) => {
    render(<Markdown>{`![inline](${url})`}</Markdown>);
    expect(document.querySelector("img")?.getAttribute("src")).toBe(url);
    expect(screen.queryByTestId("md-image-chip")).toBeNull();
  });

  it("a data: URL that isn't an image is not loaded", () => {
    render(<Markdown>{"![x](data:text/html;base64,PGI+eDwvYj4=)"}</Markdown>);
    expectChipNoImage();
  });

  it("clicking a web chip opens the URL through the native gate", () => {
    const invoke = vi.fn(async () => undefined);
    win.__TAURI_INTERNALS__ = { invoke };
    render(<Markdown>{"![chart](https://h.example/p?d=1)"}</Markdown>);
    fireEvent.click(screen.getByTestId("md-image-chip"));
    expect(invoke).toHaveBeenCalledExactlyOnceWith("open_external", { url: "https://h.example/p?d=1" });
  });

  it("links are untouched", () => {
    render(<Markdown>{"[docs](https://h.example/docs)"}</Markdown>);
    expect(screen.getByRole("link").getAttribute("href")).toBe("https://h.example/docs");
    expect(screen.queryByTestId("md-image-chip")).toBeNull();
  });
});

describe("A: every user of Markdown", () => {
  it("a chat reply", () => {
    render(<MessageBody text={"Here: ![x](https://h.example/p?d=secret) and ![y](" + PNG + ")"} />);
    expect(document.querySelectorAll("img")).toHaveLength(1);
    expect(document.querySelector("img")?.getAttribute("src")).toBe(PNG);
    expect(screen.getAllByTestId("md-image-chip")).toHaveLength(1);
  });

  it("the reader, for a Markdown file", async () => {
    render(<Reader source={{ kind: "text", name: "AGENTS.md", text: "# Rules\n\n![x](https://h.example/p?d=1)" }} onBack={() => {}} />);
    const body = await screen.findByTestId("reader-markdown");
    expectChipNoImage(body);
  });

  it("release notes in About", async () => {
    request.mockResolvedValue({ version: "0.1.64", releases: [{ version: "0.1.64", notes: "New ![x](https://h.example/p.png)" }] });
    render(<AboutSection />);
    await waitFor(() => expect(screen.getByTestId("md-image-chip")).toBeInTheDocument());
    expectChipNoImage(screen.getByTestId("settings-whats-new"));
  });
});

/** The CSP meta comes first, before even a doctype (a srcdoc document is never in quirks mode). */
function expectCspFirst(srcdoc: string | null) {
  expect(srcdoc?.startsWith(FRAME_CSP)).toBe(true);
}

describe("C: frames load nothing from the web", () => {
  it("the policy is the card's", () => {
    expect(FRAME_CSP).toBe(`<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'">`);
  });

  it("withFrameCsp puts the meta first and keeps the document", () => {
    expect(withFrameCsp("<!doctype html><p>x</p>")).toBe(`${FRAME_CSP}<!doctype html><p>x</p>`);
  });

  it("the reader's HTML frame", async () => {
    render(<Reader source={{ kind: "text", name: "page.html", text: "<!doctype html><img src=\"https://h.example/p\">" }} onBack={() => {}} />);
    expectCspFirst((await screen.findByTestId("reader-html")).getAttribute("srcdoc"));
  });

  it("the reader's Word frame", async () => {
    files.html.mockResolvedValue({ html: "<html><body><img src=\"https://h.example/p\"></body></html>" });
    render(<Reader source={{ kind: "path", path: "/tmp/letter.docx" }} onBack={() => {}} />);
    expectCspFirst((await screen.findByTestId("reader-doc")).getAttribute("srcdoc"));
  });

  it("a reply's HTML document preview", () => {
    render(<HtmlDocCard html={"<!DOCTYPE html><html><body><img src=\"https://h.example/p\"></body></html>"} />);
    fireEvent.click(screen.getByTitle("msg.preview"));
    expectCspFirst(screen.getByTitle("msg.html_preview").getAttribute("srcdoc"));
  });

  it("every srcDoc in the web app goes through withFrameCsp", () => {
    const sources = import.meta.glob(["../**/*.tsx", "!../**/*.test.tsx", "!../__tests__/**"], { query: "?raw", import: "default", eager: true }) as Record<string, string>;
    const uses = Object.entries(sources).flatMap(([file, text]) =>
      [...text.matchAll(/srcDoc=\{([^}]*)\}/g)].map((m) => [file, m[1].trim()]));
    expect(uses.length).toBeGreaterThanOrEqual(3);
    expect(uses.filter(([, expr]) => !expr.startsWith("withFrameCsp("))).toEqual([]);
  });
});
