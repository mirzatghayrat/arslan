/** The 0.1.6 silent lie, pinned from the frontend side.
 *
 * Server answers 200 with chunks_added: 0 for a file it could not read; every
 * caller used to count "did not throw" as success and the UI said "Fed 1".
 * These tests drive the REAL feedFile against a mocked api layer only — the
 * decision logic under test is not stubbed. */
import { describe, expect, it, vi, beforeEach } from "vitest";

vi.mock("../api/client", () => ({
  api: {
    listCollections: vi.fn(async () => [{ id: 7, name: "Images" }]),
    createCollection: vi.fn(async () => ({ id: 7, name: "Images" })),
    ingestCollectionFile: vi.fn(),
    ingestCollection: vi.fn(),
  },
}));

import { api } from "../api/client";
import { feedFile, feedTextOrUrl, NothingIngestedError } from "../lib/feed";

const t = ((k: string) => k) as never;
const file = (name: string) => new File(["x"], name);

beforeEach(() => vi.clearAllMocks());

describe("feed honesty — an accepted-but-empty ingest is a failure", () => {
  it("throws NothingIngestedError when the server stored zero chunks", async () => {
    vi.mocked(api.ingestCollectionFile).mockResolvedValue({ source: "shot.png", chunks_added: 0 });
    await expect(feedFile(file("shot.png"), t)).rejects.toBeInstanceOf(NothingIngestedError);
  });

  it("images get the specific reason, not a generic one", async () => {
    vi.mocked(api.ingestCollectionFile).mockResolvedValue({ source: "shot.png", chunks_added: 0 });
    await expect(feedFile(file("shot.png"), t)).rejects.toThrow("feed.image_not_readable");
    // …and a non-image zero-chunk file must NOT claim to be an image problem.
    vi.mocked(api.ingestCollectionFile).mockResolvedValue({ source: "empty.md", chunks_added: 0 });
    await expect(feedFile(file("empty.md"), t)).rejects.toThrow("feed.nothing_read");
  });

  it("a real ingest still resolves (the throw is caused by ZERO, not by images)", async () => {
    vi.mocked(api.ingestCollectionFile).mockResolvedValue({ source: "shot.png", chunks_added: 3 });
    await expect(feedFile(file("shot.png"), t)).resolves.toMatchObject({ chunks_added: 3 });
  });

  it("pasted text/URL is held to the same contract", async () => {
    vi.mocked(api.ingestCollection).mockResolvedValue({ source: "paste", chunks_added: 0 });
    await expect(feedTextOrUrl("some text", t)).rejects.toBeInstanceOf(NothingIngestedError);
    vi.mocked(api.ingestCollection).mockResolvedValue({ source: "paste", chunks_added: 2 });
    await expect(feedTextOrUrl("some text", t)).resolves.toMatchObject({ chunks_added: 2 });
  });
});

describe("feed entry point discloses where images go", () => {
  it("the locale string names the configured model, not just 'the cloud'", async () => {
    // Spec requirement: the user must know the picture reaches THEIR configured
    // model. A vague "sent for processing" would satisfy a naive check while
    // leaving the privacy question unanswered.
    const en = ((await import("../locales/en.json")).default as unknown) as Record<string, Record<string, string>>;
    expect(en.feed.image_goes_to_model.toLowerCase()).toContain("model");
    expect(en.feed.image_goes_to_model.toLowerCase()).toContain("configured");
  });

  it("no longer claims this build cannot read images", async () => {
    // The hotfix copy was true then and false now — vision reads them.
    const en = ((await import("../locales/en.json")).default as unknown) as Record<string, Record<string, string>>;
    expect(en.feed.image_not_readable.toLowerCase()).not.toContain("can't read images yet");
    expect(en.feed.image_not_readable.toLowerCase()).toContain("supports images");
  });
});
