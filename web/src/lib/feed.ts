import { api } from "../api/client";

/** Caller-provided translate function (react-i18next `t`). This module must not
 * import the i18n singleton (it would crash every test that mocks react-i18next),
 * so the rendering components pass their own `t` in. */
export type TranslateFn = (key: string, opts?: Record<string, unknown>) => string;

/** Bucket → locale key of its display/collection name (feed.bucket.*).
 *
 * KNOWN LIMIT (S4.2-d, deliberate): the translated name doubles as the
 * backend COLLECTION name (find-or-create at ingest). zh values equal the
 * pre-i18n originals, so existing zh users keep matching their collections —
 * but a user who switches UI language will find-or-create new locale-named
 * buckets from then on (old ones keep their data, nothing is lost or merged).
 * The full fix is a stable backend collection key with display-only
 * translation; registered as follow-up, out of this round's scope. */
export const BUCKET = {
  text: "feed.bucket.text",
  web: "feed.bucket.web",
  pdf: "feed.bucket.pdf",
  image: "feed.bucket.image",
  word: "feed.bucket.word",
} as const;
export type BucketKey = keyof typeof BUCKET;

/** File name → bucket key, or null if unsupported. */
export function bucketForFile(name: string): BucketKey | null {
  const n = name.toLowerCase();
  if (/\.pdf$/.test(n)) return "pdf";
  if (/\.docx?$/.test(n)) return "word";
  if (/\.html?$/.test(n)) return "web";
  if (/\.(png|jpe?g|gif|webp|bmp)$/.test(n)) return "image";
  if (/\.(txt|md|markdown)$/.test(n)) return "text";
  return null;
}

/** Pasted input → bucket key (url → web, else text). */
export function bucketForText(input: string): BucketKey {
  return /^https?:\/\//.test(input.trim()) ? "web" : "text";
}

/** Find-or-create the collection named `bucketName`, return its id. */
async function bucketCollectionId(bucketName: string): Promise<number> {
  const cols = await api.listCollections();
  const found = cols.find((c) => c.name === bucketName);
  return found ? found.id : (await api.createCollection(bucketName)).id;
}

/** Raised when the server accepted the upload but stored NOTHING.
 *
 * The 0.1.6 silent lie lived exactly here: `ingest` answers 200 with
 * `chunks_added: 0` for a file it could not read (an image, with no OCR stack
 * in the packaged app), and every caller counted "did not throw" as success.
 * Failing loud by default means a future call site cannot re-introduce the lie
 * by forgetting to inspect the result. */
export class NothingIngestedError extends Error {
  constructor(readonly fileName: string, message: string) {
    super(message);
    this.name = "NothingIngestedError";
  }
}

/** Feed a file into its type bucket.
 * Throws on unsupported type, and on an accepted-but-empty ingest. */
export async function feedFile(file: File, t: TranslateFn) {
  const b = bucketForFile(file.name);
  if (!b) throw new Error(t("feed.unsupported_format", { name: file.name }));
  const result = await api.ingestCollectionFile(await bucketCollectionId(t(BUCKET[b])), file);
  if (!result.chunks_added) {
    // Images get the specific reason, which the S4.3-a spec already required
    // ("must not silently return empty") and which nothing implemented.
    throw new NothingIngestedError(
      file.name,
      t(b === "image" ? "feed.image_not_readable" : "feed.nothing_read", { name: file.name }),
    );
  }
  return result;
}

/** Feed pasted text or a URL into its bucket (文本 / 网页). */
export async function feedTextOrUrl(input: string, t: TranslateFn) {
  const trimmed = input.trim();
  const web = /^https?:\/\//.test(trimmed);
  const id = await bucketCollectionId(t(web ? BUCKET.web : BUCKET.text));
  const result = await api.ingestCollection(
    id, web ? { url: trimmed } : { source: t("feed.paste_source"), text: trimmed });
  if (!result.chunks_added) {
    throw new NothingIngestedError(trimmed, t("feed.nothing_read", { name: trimmed.slice(0, 40) }));
  }
  return result;
}
