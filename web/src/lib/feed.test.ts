import { describe, expect, it, vi } from "vitest";

vi.mock("../api/client", () => ({
  api: {
    listCollections: vi.fn(),
    createCollection: vi.fn(),
    ingestCollection: vi.fn(),
    ingestCollectionFile: vi.fn(),
  },
}));
import { api } from "../api/client";
import { bucketForFile, bucketForText, feedFile, feedTextOrUrl, BUCKET } from "./feed";

const f = (name: string) => new File(["x"], name, { type: "" });

describe("bucketForFile", () => {
  it("routes by extension", () => {
    expect(bucketForFile("a.pdf")).toBe("pdf");
    expect(bucketForFile("a.PDF")).toBe("pdf");
    expect(bucketForFile("a.docx")).toBe("word");
    expect(bucketForFile("a.doc")).toBe("word");
    expect(bucketForFile("a.html")).toBe("web");
    expect(bucketForFile("a.htm")).toBe("web");
    expect(bucketForFile("a.png")).toBe("image");
    expect(bucketForFile("a.jpeg")).toBe("image");
    expect(bucketForFile("a.txt")).toBe("text");
    expect(bucketForFile("a.md")).toBe("text");
    expect(bucketForFile("a.zip")).toBeNull();
  });
});

describe("bucketForText", () => {
  it("url → web, else text", () => {
    expect(bucketForText("https://x.com")).toBe("web");
    expect(bucketForText("  http://x ")).toBe("web");
    expect(bucketForText("hello world")).toBe("text");
  });
});

describe("feedFile", () => {
  it("find-or-create the type bucket then upload", async () => {
    (api.listCollections as any).mockResolvedValue([{ id: 3, name: "PDF" }]);
    (api.ingestCollectionFile as any).mockResolvedValue({ chunks_added: 2 });
    await feedFile(f("report.pdf"));
    expect(api.createCollection).not.toHaveBeenCalled();
    expect(api.ingestCollectionFile).toHaveBeenCalledWith(3, expect.any(File));
  });
  it("creates the bucket when missing", async () => {
    (api.listCollections as any).mockResolvedValue([]);
    (api.createCollection as any).mockResolvedValue({ id: 9, name: BUCKET.image });
    (api.ingestCollectionFile as any).mockResolvedValue({ chunks_added: 1 });
    await feedFile(f("shot.png"));
    expect(api.createCollection).toHaveBeenCalledWith("图片");
    expect(api.ingestCollectionFile).toHaveBeenCalledWith(9, expect.any(File));
  });
  it("throws on unsupported type", async () => {
    await expect(feedFile(f("a.zip"))).rejects.toThrow(/不支持/);
  });
});

describe("feedTextOrUrl", () => {
  it("url → 网页 bucket via ingestCollection url", async () => {
    (api.listCollections as any).mockResolvedValue([{ id: 5, name: "网页" }]);
    (api.ingestCollection as any).mockResolvedValue({ chunks_added: 1 });
    await feedTextOrUrl("https://example.com");
    expect(api.ingestCollection).toHaveBeenCalledWith(5, { url: "https://example.com" });
  });
  it("text → 文本 bucket via ingestCollection text", async () => {
    (api.listCollections as any).mockResolvedValue([]);
    (api.createCollection as any).mockResolvedValue({ id: 7, name: "文本" });
    (api.ingestCollection as any).mockResolvedValue({ chunks_added: 1 });
    await feedTextOrUrl("just a note");
    expect(api.createCollection).toHaveBeenCalledWith("文本");
    expect(api.ingestCollection).toHaveBeenCalledWith(7, { source: "粘贴", text: "just a note" });
  });
});
